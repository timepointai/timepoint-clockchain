import json
import os
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.db import create_pool, init_schema, seed_if_empty
from app.core.graph import GraphManager
from app.workers.expander import GraphExpander


MOCK_RESPONSE = [
    {
        "name": "Roman Civil War",
        "year": -49,
        "month": "january",
        "day": 10,
        "time": "0800",
        "country": "italy",
        "region": "lazio",
        "city": "rome",
        "one_liner": "Caesar crosses the Rubicon, triggering civil war",
        "tags": ["politics", "ancient-rome", "civil-war"],
        "figures": ["Julius Caesar", "Pompey"],
        "edge_type": "causes",
    },
    {
        "name": "Death of Cleopatra",
        "year": -30,
        "month": "august",
        "day": 12,
        "time": "1400",
        "country": "egypt",
        "region": "alexandria",
        "city": "alexandria",
        "one_liner": "Cleopatra VII takes her own life after Octavian's conquest of Egypt",
        "tags": ["politics", "ancient-rome", "ancient-egypt"],
        "figures": ["Cleopatra VII", "Octavian"],
        "edge_type": "thematic",
    },
]

OPENROUTER_RESPONSE = {
    "choices": [{"message": {"content": json.dumps(MOCK_RESPONSE)}}]
}


def _patch_httpx():
    """Patch httpx.AsyncClient used as async context manager."""
    resp = MagicMock()
    resp.json.return_value = OPENROUTER_RESPONSE

    inner = MagicMock()
    inner.post = AsyncMock(return_value=resp)

    cm = AsyncMock()
    cm.__aenter__.return_value = inner

    return patch("app.workers.expander.httpx.AsyncClient", return_value=cm)


@pytest.fixture()
async def graph_manager(tmp_path):
    seeds_src = os.path.join(os.path.dirname(__file__), "..", "data", "seeds.json")
    shutil.copy(seeds_src, tmp_path / "seeds.json")

    url = os.environ["DATABASE_URL"]
    pool = await create_pool(url)
    await init_schema(pool)
    await seed_if_empty(pool, str(tmp_path))

    gm = GraphManager(pool)
    await gm.load()
    yield gm
    await pool.close()


@pytest.mark.asyncio
async def test_expander_generates_related_events(graph_manager):
    initial_count = await graph_manager.node_count()

    with _patch_httpx():
        expander = GraphExpander(graph_manager, "fake-api-key")
        await expander._expand_once()

    new_count = await graph_manager.node_count()
    assert new_count > initial_count
    assert new_count == initial_count + 2


@pytest.mark.asyncio
async def test_expander_creates_edges(graph_manager):
    initial_edges = await graph_manager.edge_count()

    with _patch_httpx():
        expander = GraphExpander(graph_manager, "fake-api-key")
        await expander._expand_once()

    assert await graph_manager.edge_count() > initial_edges


@pytest.mark.asyncio
async def test_expander_sets_correct_attributes(graph_manager):
    with _patch_httpx():
        expander = GraphExpander(graph_manager, "fake-api-key")
        await expander._expand_once()

    # Find the "Roman Civil War" node by searching
    results = await graph_manager.search("roman civil war")
    assert len(results) >= 1
    found = results[0]
    assert found["visibility"] == "public"
    assert found["layer"] == 1
