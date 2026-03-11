import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import httpx

from app.core.graph import GraphManager

logger = logging.getLogger("clockchain.expander")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

EXPANSION_PROMPT = """You are a historian. Given this historical event, suggest 3-5 closely related historical events.

Event: {name}
Date: {year}/{month}/{day}
Location: {country}, {region}, {city}
Description: {one_liner}

Return a JSON array of objects, each with:
- "name": clean human-readable event name (e.g. "Apollo 1 Fire", NOT slugified)
- "year": integer (negative for BCE)
- "month": lowercase month name (e.g. "march")
- "day": integer
- "time": 4-digit 24hr string (e.g. "1400")
- "country": lowercase, hyphenated
- "region": lowercase, hyphenated
- "city": lowercase, hyphenated
- "one_liner": one sentence description
- "tags": list of lowercase hyphenated tags
- "figures": list of historical figure names
- "edge_type": one of "causes", "caused_by", "influences", "contemporaneous", "same_era", "same_location", "same_conflict", "same_figure", "thematic", "precedes", "follows"
- "description": 1-2 sentence explanation of WHY this event is related to the source event

Edge type guide:
- causes/caused_by: direct causal link
- influences: indirect influence, softer than causes
- contemporaneous: EXACT same date (year+month+day)
- same_era: same decade, no direct causal link
- same_location: same country+region+city
- same_conflict: events in the same war/revolution/movement
- same_figure: shared historical figure
- thematic: shared themes or tags
- precedes/follows: temporal ordering within the same era

Return ONLY the JSON array, no other text."""


class BudgetTracker:
    """Track OpenRouter spend within a rolling 24h window."""

    def __init__(self, daily_limit: float):
        self.daily_limit = daily_limit
        self._spend: list[tuple[float, float]] = []  # (timestamp, cost)
        self._lock = asyncio.Lock()

    async def record(self, cost: float):
        async with self._lock:
            self._spend.append((time.monotonic(), cost))

    async def remaining(self) -> float:
        async with self._lock:
            cutoff = time.monotonic() - 86400
            self._spend = [(t, c) for t, c in self._spend if t > cutoff]
            spent = sum(c for _, c in self._spend)
            return max(0.0, self.daily_limit - spent)

    async def can_spend(self) -> bool:
        return (await self.remaining()) > 0

    async def total_spent(self) -> float:
        async with self._lock:
            cutoff = time.monotonic() - 86400
            self._spend = [(t, c) for t, c in self._spend if t > cutoff]
            return sum(c for _, c in self._spend)


class GraphExpander:
    def __init__(
        self,
        graph_manager: GraphManager,
        api_key: str,
        model: str = "deepseek/deepseek-chat-v3-0324",
        interval_seconds: int = 300,
        concurrency: int = 1,
        target: int = 0,
        daily_budget: float = 5.0,
        job_manager=None,
    ):
        self.gm = graph_manager
        self.api_key = api_key
        self.model = model
        self.interval = interval_seconds
        self.concurrency = max(1, concurrency)
        self.target = target
        self.jm = job_manager
        self.budget = BudgetTracker(daily_budget)
        self._paused_until: float = 0

    async def start(self):
        logger.info(
            "Graph expander starting (interval=%ds, concurrency=%d, target=%s, budget=$%.2f/day)",
            self.interval, self.concurrency,
            self.target or "unlimited", self.budget.daily_limit,
        )
        while True:
            try:
                await self._expand_cycle()
            except asyncio.CancelledError:
                logger.info("Graph expander cancelled")
                break
            except Exception as e:
                logger.error("Expander error: %s", e)
            await asyncio.sleep(self.interval)

    async def _expand_cycle(self):
        # Check target cap
        if self.target > 0:
            count = await self.gm.node_count()
            if count >= self.target:
                logger.info(
                    "Target reached (%d/%d nodes), expander paused",
                    count, self.target,
                )
                return

        # Check budget
        if not await self.budget.can_spend():
            spent = await self.budget.total_spent()
            logger.info(
                "Daily budget exhausted ($%.4f/$%.2f), expander paused",
                spent, self.budget.daily_limit,
            )
            return

        # Get frontier nodes for concurrent expansion
        frontier = await self.gm.get_frontier_nodes(
            threshold=3, limit=self.concurrency
        )
        if not frontier:
            logger.info("No frontier nodes to expand")
            return

        if self.concurrency == 1:
            await self._expand_node(frontier[0])
        else:
            tasks = [self._expand_node(nid) for nid in frontier]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _expand_node(self, node_id: str):
        # Pre-check budget before each node
        if not await self.budget.can_spend():
            return

        node = await self.gm.get_node(node_id)
        if not node:
            return

        logger.info("Expanding from node: %s", node_id)
        related, cost = await self._generate_related(node)
        await self.budget.record(cost)

        remaining = await self.budget.remaining()
        logger.info(
            "OpenRouter cost: $%.6f (remaining today: $%.4f)",
            cost, remaining,
        )

        added = 0
        for event in related:
            ok = await self._add_event(event, source_node_id=node_id)
            if ok:
                added += 1

        logger.info(
            "Expansion complete: added %d events from %s", added, node_id
        )

    async def _generate_related(self, node: dict) -> tuple[list[dict], float]:
        prompt = EXPANSION_PROMPT.format(
            name=node.get("name", ""),
            year=node.get("year", ""),
            month=node.get("month", ""),
            day=node.get("day", ""),
            country=node.get("country", ""),
            region=node.get("region", ""),
            city=node.get("city", ""),
            one_liner=node.get("one_liner", ""),
        )

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract cost from OpenRouter response
        cost = 0.0
        usage = data.get("usage", {})
        if usage:
            # OpenRouter includes cost in the response body
            cost = float(usage.get("total_cost", 0) or 0)
        if cost == 0:
            # Fallback: estimate from token counts (rough, for cheap models)
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            # Assume ~$0.10/M tokens as conservative upper bound for distillable models
            cost = (prompt_tokens + completion_tokens) * 0.0000001

        text = data["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        return json.loads(text), cost

    async def _add_event(self, event: dict, source_node_id: str) -> bool:
        if self.jm:
            return await self._add_via_flash(event, source_node_id)
        return await self._add_direct(event, source_node_id)

    async def _add_via_flash(self, event: dict, source_node_id: str) -> bool:
        name = event.get("name", "")
        year = event.get("year", "")
        country = event.get("country", "")
        city = event.get("city", "")

        query = f"{name}, {year}, {country}, {city}".strip(", ")
        logger.info("Rendering via Flash: %s", query)

        try:
            job = self.jm.create_job(
                query=query, preset="balanced", visibility="public",
                override_name=name,
            )
            await self.jm.process_job(job)

            if job.status == "completed" and job.path:
                edge_type = event.get("edge_type", "thematic")
                from app.core.graph import VALID_EDGE_TYPES
                if edge_type in VALID_EDGE_TYPES:
                    try:
                        description = event.get("description", "")
                        await self.gm.add_edge(
                            source_node_id, job.path, edge_type,
                            weight=0.5, description=description,
                            created_by="expander",
                        )
                    except ValueError:
                        pass
                logger.info("Flash render complete: %s -> %s", query, job.path)
                return True
            else:
                logger.warning(
                    "Flash render failed for %s: %s", query, job.error
                )
                return False
        except Exception as e:
            logger.error("Flash render error for %s: %s", query, e)
            return False

    async def _add_direct(self, event: dict, source_node_id: str) -> bool:
        """Fallback: add node directly without Flash (layer 1)."""
        from app.core.url import build_path, MONTH_TO_NUM

        month_str = str(event.get("month", "january")).lower()
        month_num = MONTH_TO_NUM.get(month_str, 1)

        path = build_path(
            year=event.get("year", 0),
            month=month_num,
            day=event.get("day", 1),
            time=event.get("time", "1200"),
            country=event.get("country", "unknown"),
            region=event.get("region", "unknown"),
            city=event.get("city", "unknown"),
            slug=event.get("name", "unknown"),
        )

        if await self.gm.get_node(path):
            return False

        # Derive provider from model ID (e.g. "deepseek/deepseek-chat-v3-0324" -> "deepseek")
        model_provider = self.model.split("/")[0] if "/" in self.model else "openrouter"

        await self.gm.add_node(
            path,
            type="event",
            name=event.get("name", ""),
            year=event.get("year", 0),
            month=month_str,
            month_num=month_num,
            day=event.get("day", 1),
            time=event.get("time", "1200"),
            country=event.get("country", "unknown"),
            region=event.get("region", "unknown"),
            city=event.get("city", "unknown"),
            slug=path.split("/")[-1],
            layer=1,
            visibility="public",
            created_by="expander",
            source_type="expander",
            tags=event.get("tags", []),
            one_liner=event.get("one_liner", ""),
            figures=event.get("figures", []),
            flash_timepoint_id=None,
            created_at=datetime.now(timezone.utc).isoformat(),
            text_model=self.model,
            image_model="",
            model_provider=model_provider,
            model_permissiveness="permissive",
            generation_id=f"expander-{source_node_id}",
        )

        edge_type = event.get("edge_type", "thematic")
        from app.core.graph import VALID_EDGE_TYPES
        if edge_type in VALID_EDGE_TYPES:
            try:
                description = event.get("description", "")
                await self.gm.add_edge(
                    source_node_id, path, edge_type,
                    weight=0.5, description=description,
                    created_by="expander",
                )
            except ValueError:
                pass
        return True
