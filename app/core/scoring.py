"""SNAG scoring integration for Clockchain.

Optionally scores proposed/challenged moments against the SNAG-Bench runner API.
Scoring is async/background — it never blocks API responses.

SNAG axes:
  GSR  — Grounded Source Reliability
  TCS  — Temporal Causal Specificity
  WMNED — World-Model Normative Empirical Density
  GCQ  — Graph Coherence Quality
  HTP  — Human-Testable Precision

Configuration:
  SNAG_RUNNER_URL — URL of the SNAG Bench runner service (empty = disabled)
  SNAG_AUTO_SCORE — Enable auto-scoring on propose/challenge (default: false)

When disabled, moments have null snag_scores. The system works fine without SNAG.
"""

import asyncio
import json
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("clockchain.scoring")

SNAG_AXES = ("GSR", "TCS", "WMNED", "GCQ", "HTP")


def scoring_enabled() -> bool:
    """Check if SNAG scoring is configured and enabled."""
    settings = get_settings()
    return bool(settings.SNAG_RUNNER_URL and settings.SNAG_AUTO_SCORE)


def aggregate_score(snag_scores: dict) -> float | None:
    """Compute aggregate SNAG score as mean of available axes.

    Returns None if snag_scores is None or empty.
    Returns float in [0.0, 1.0].
    """
    if not snag_scores:
        return None
    values = [v for k, v in snag_scores.items() if k in SNAG_AXES and isinstance(v, (int, float))]
    if not values:
        return None
    return sum(values) / len(values)


async def score_moment(moment_id: str, moment_data: dict) -> dict | None:
    """Call the SNAG runner /score endpoint and return the scores dict.

    Returns a dict with keys GSR, TCS, WMNED, GCQ, HTP (floats in [0.0, 1.0])
    or None if scoring fails or is disabled.
    """
    settings = get_settings()
    if not settings.SNAG_RUNNER_URL:
        return None

    url = settings.SNAG_RUNNER_URL.rstrip("/") + "/score"
    payload = {
        "moment_id": moment_id,
        "moment": {
            "name": moment_data.get("name", ""),
            "one_liner": moment_data.get("one_liner", ""),
            "year": moment_data.get("year"),
            "country": moment_data.get("country", ""),
            "source_type": moment_data.get("source_type", "historical"),
            "proposed_by": moment_data.get("proposed_by", ""),
            "tags": list(moment_data.get("tags") or []),
            "figures": list(moment_data.get("figures") or []),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            scores = data.get("scores", data)
            # Validate and clamp axes
            result = {}
            for axis in SNAG_AXES:
                val = scores.get(axis)
                if val is not None:
                    result[axis] = float(min(max(val, 0.0), 1.0))
            if result:
                logger.info("SNAG scored %s: %s", moment_id, result)
                return result
            logger.warning("SNAG runner returned no recognizable scores for %s: %s", moment_id, data)
            return None
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "SNAG runner returned %s for %s: %s",
            exc.response.status_code, moment_id, exc.response.text[:200],
        )
        return None
    except Exception as exc:
        logger.warning("SNAG scoring failed for %s: %s", moment_id, exc)
        return None


async def _score_and_store(pool, moment_id: str, moment_data: dict) -> None:
    """Score a moment and persist the results. Fire-and-forget coroutine."""
    scores = await score_moment(moment_id, moment_data)
    if scores is None:
        return
    try:
        async with pool.acquire() as conn:
            # asyncpg handles Python dicts as JSONB natively
            await conn.execute(
                "UPDATE nodes SET snag_scores = $1::jsonb WHERE id = $2",
                json.dumps(scores), moment_id,
            )
        logger.info("Stored SNAG scores for %s", moment_id)
    except Exception as exc:
        logger.warning("Failed to store SNAG scores for %s: %s", moment_id, exc)


def schedule_scoring(pool, moment_id: str, moment_data: dict) -> None:
    """Schedule background SNAG scoring for a moment.

    Creates an asyncio task — non-blocking. Safe to call from any async context.
    Does nothing if scoring is disabled.
    """
    if not scoring_enabled():
        return
    asyncio.create_task(_score_and_store(pool, moment_id, moment_data))
    logger.debug("Scheduled SNAG scoring for %s", moment_id)
