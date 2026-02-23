import os
import shutil

import pytest

from app.core.db import create_pool, init_schema, seed_if_empty
from app.core.graph import GraphManager


@pytest.fixture()
async def graph_manager(tmp_path):
    seeds_src = os.path.join(os.path.dirname(__file__), "..", "data", "seeds.json")
    shutil.copy(seeds_src, tmp_path / "seeds.json")

    url = os.environ["DATABASE_URL"]
    pool = await create_pool(url)
    await init_schema(pool)
    await seed_if_empty(pool, str(tmp_path))

    gm = GraphManager(pool, data_dir=str(tmp_path))
    await gm.load()
    yield gm
    await pool.close()


@pytest.mark.asyncio
async def test_auto_link_contemporaneous(graph_manager):
    """Adding a 1969 event should auto-link to existing 1969 events."""
    await graph_manager.add_node(
        "/1969/july/16/0932/united-states/florida/cape-canaveral/apollo-11-launch",
        type="event",
        name="Apollo 11 Launch",
        year=1969,
        month="july",
        day=16,
        country="united-states",
        region="florida",
        city="cape-canaveral",
        tags=["space", "nasa", "apollo-program"],
        visibility="public",
    )

    # Should have edges to both Apollo 11 moon landing and Apollo 12
    neighbors = await graph_manager.get_neighbors(
        "/1969/july/16/0932/united-states/florida/cape-canaveral/apollo-11-launch"
    )
    neighbor_paths = [n["path"] for n in neighbors]
    assert "/1969/july/20/2056/united-states/florida/cape-canaveral/apollo-11-moon-landing" in neighbor_paths
    assert "/1969/november/14/1122/united-states/florida/cape-canaveral/apollo-12-lightning-launch" in neighbor_paths


@pytest.mark.asyncio
async def test_auto_link_same_location(graph_manager):
    """Adding an event in the same location should auto-link."""
    await graph_manager.add_node(
        "/2020/may/30/1522/united-states/florida/cape-canaveral/spacex-crew-dragon-demo-2",
        type="event",
        name="SpaceX Crew Dragon Demo-2",
        year=2020,
        month="may",
        day=30,
        country="united-states",
        region="florida",
        city="cape-canaveral",
        tags=["space", "spacex"],
        visibility="public",
    )

    neighbors = await graph_manager.get_neighbors(
        "/2020/may/30/1522/united-states/florida/cape-canaveral/spacex-crew-dragon-demo-2"
    )
    edge_types = [n["edge_type"] for n in neighbors]
    assert "same_location" in edge_types


@pytest.mark.asyncio
async def test_auto_link_thematic(graph_manager):
    """Adding an event with overlapping tags but different year/location should create thematic edges."""
    await graph_manager.add_node(
        "/1961/april/12/0907/russia/moscow-oblast/baikonur/vostok-1-launch",
        type="event",
        name="Vostok 1 Launch",
        year=1961,
        month="april",
        day=12,
        country="russia",
        region="moscow-oblast",
        city="baikonur",
        tags=["space", "nasa"],
        visibility="public",
    )

    neighbors = await graph_manager.get_neighbors(
        "/1961/april/12/0907/russia/moscow-oblast/baikonur/vostok-1-launch"
    )
    edge_types = [n["edge_type"] for n in neighbors]
    assert "thematic" in edge_types


@pytest.mark.asyncio
async def test_bidirectional_edges(graph_manager):
    """Auto-created edges should be bidirectional."""
    await graph_manager.add_node(
        "/1969/july/16/0932/united-states/florida/cape-canaveral/apollo-11-launch",
        type="event",
        name="Apollo 11 Launch",
        year=1969,
        month="july",
        day=16,
        country="united-states",
        region="florida",
        city="cape-canaveral",
        tags=["space"],
        visibility="public",
    )

    new_path = "/1969/july/16/0932/united-states/florida/cape-canaveral/apollo-11-launch"
    moon_path = "/1969/july/20/2056/united-states/florida/cape-canaveral/apollo-11-moon-landing"

    # Check edge exists both ways
    assert await graph_manager.has_edge(new_path, moon_path)
    assert await graph_manager.has_edge(moon_path, new_path)


@pytest.mark.asyncio
async def test_invalid_edge_type(graph_manager):
    """Adding an edge with invalid type should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid edge type"):
        await graph_manager.add_edge(
            "/-44/march/15/1030/italy/lazio/rome/assassination-of-julius-caesar",
            "/1945/july/16/0530/united-states/new-mexico/socorro/trinity-test",
            "invalid_type",
        )


@pytest.mark.asyncio
async def test_browse_only_public(graph_manager):
    """Browse should only return public nodes."""
    # Add a private node
    await graph_manager.add_node(
        "/2000/january/1/0000/united-states/new-york/new-york/y2k-non-event",
        type="event",
        name="Y2K Non-Event",
        year=2000,
        month="january",
        day=1,
        visibility="private",
    )

    items = await graph_manager.browse("2000")
    assert len(items) == 0


@pytest.mark.asyncio
async def test_search_only_public(graph_manager):
    """Search should only return public nodes."""
    await graph_manager.add_node(
        "/2000/january/1/0000/united-states/new-york/new-york/secret-event",
        type="event",
        name="Secret Event",
        year=2000,
        visibility="private",
    )

    results = await graph_manager.search("secret")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_today_only_public(graph_manager):
    """Today-in-history should only return public nodes."""
    await graph_manager.add_node(
        "/2000/march/15/0000/united-states/new-york/new-york/private-march-event",
        type="event",
        name="Private March Event",
        year=2000,
        month="march",
        month_num=3,
        day=15,
        visibility="private",
    )

    events = await graph_manager.today_in_history(3, 15)
    names = [e["name"] for e in events]
    assert "Private March Event" not in names
