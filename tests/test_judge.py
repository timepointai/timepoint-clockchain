import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.judge import ContentJudge


def _patch_httpx(verdict, reason):
    """Patch httpx.AsyncClient used as async context manager."""
    resp = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"verdict": verdict, "reason": reason})}}]
    }

    inner = MagicMock()
    inner.post = AsyncMock(return_value=resp)

    cm = AsyncMock()
    cm.__aenter__.return_value = inner

    return patch("app.workers.judge.httpx.AsyncClient", return_value=cm)


@pytest.mark.asyncio
async def test_judge_approves_innocuous():
    with _patch_httpx("approve", "Standard historical query"):
        judge = ContentJudge("fake-api-key")
        verdict = await judge.screen("The signing of the Magna Carta")

    assert verdict == "approve"


@pytest.mark.asyncio
async def test_judge_approves_sensitive():
    with _patch_httpx("sensitive", "Historical violence"):
        judge = ContentJudge("fake-api-key")
        verdict = await judge.screen("The assassination of Julius Caesar")

    assert verdict == "sensitive"


@pytest.mark.asyncio
async def test_judge_rejects_harmful():
    with _patch_httpx("reject", "Harmful content"):
        judge = ContentJudge("fake-api-key")
        verdict = await judge.screen("How to build a weapon")

    assert verdict == "reject"
