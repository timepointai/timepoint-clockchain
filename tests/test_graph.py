import os

import pytest

from app.core.db import create_pool, init_schema, seed_if_empty
from app.core.graph import GraphManager


@pytest.fixture()
async def graph_manager(tmp_path):
    seeds_src = os.path.join(os.path.dirname(__file__), "..", "data", "seeds.json")
    import shutil
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
async def test_load_seeds(graph_manager):
    assert await graph_manager.node_count() == 5
    assert await graph_manager.edge_count() == 3


@pytest.mark.asyncio
async def test_get_node(graph_manager):
    node = await graph_manager.get_node(
        "/-44/march/15/1030/italy/lazio/rome/assassination-of-julius-caesar"
    )
    assert node is not None
    assert node["name"] == "Assassination of Julius Caesar"
    assert node["year"] == -44


@pytest.mark.asyncio
async def test_get_node_not_found(graph_manager):
    assert await graph_manager.get_node("/nonexistent/path") is None


@pytest.mark.asyncio
async def test_browse_root(graph_manager):
    items = await graph_manager.browse("")
    segments = [i["segment"] for i in items]
    assert "-44" in segments
    assert "1945" in segments
    assert "1969" in segments
    assert "2016" in segments


@pytest.mark.asyncio
async def test_browse_year(graph_manager):
    items = await graph_manager.browse("1969")
    segments = [i["segment"] for i in items]
    assert "july" in segments
    assert "november" in segments


@pytest.mark.asyncio
async def test_today_in_history(graph_manager):
    # March 15 should return Caesar
    events = await graph_manager.today_in_history(3, 15)
    assert len(events) >= 1
    assert any("Caesar" in e.get("name", "") for e in events)


@pytest.mark.asyncio
async def test_search_caesar(graph_manager):
    results = await graph_manager.search("caesar")
    assert len(results) >= 1
    assert results[0]["name"] == "Assassination of Julius Caesar"


@pytest.mark.asyncio
async def test_search_apollo(graph_manager):
    results = await graph_manager.search("apollo")
    assert len(results) >= 2


@pytest.mark.asyncio
async def test_random_public(graph_manager):
    node = await graph_manager.random_public()
    assert node is not None
    assert node["visibility"] == "public"


@pytest.mark.asyncio
async def test_stats(graph_manager):
    s = await graph_manager.stats()
    assert s["total_nodes"] == 5
    assert s["total_edges"] == 3
    assert "layer_counts" in s
    assert "edge_type_counts" in s


@pytest.mark.asyncio
async def test_get_neighbors(graph_manager):
    neighbors = await graph_manager.get_neighbors(
        "/1969/july/20/2056/united-states/florida/cape-canaveral/apollo-11-moon-landing"
    )
    assert len(neighbors) >= 1
    types = [n["edge_type"] for n in neighbors]
    assert "contemporaneous" in types or "causes" in types


@pytest.mark.asyncio
async def test_get_frontier_nodes(graph_manager):
    frontier = await graph_manager.get_frontier_nodes(threshold=5)
    assert len(frontier) > 0
