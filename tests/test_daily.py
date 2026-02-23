import os
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.db import create_pool, init_schema, seed_if_empty
from app.core.graph import GraphManager
from app.core.jobs import JobManager
from app.workers.daily import DailyWorker
from app.workers.renderer import FlashClient


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


@pytest.fixture()
def job_manager(graph_manager):
    flash_client = MagicMock(spec=FlashClient)
    flash_client.generate_sync = AsyncMock(return_value={
        "id": "flash-daily-uuid",
        "name": "Test Event",
        "slug": "test-event",
        "year": 1969,
        "month": "july",
        "day": 20,
        "time": "2056",
        "country": "united-states",
        "region": "florida",
        "city": "cape-canaveral",
    })
    return JobManager(graph_manager=graph_manager, flash_client=flash_client)


@pytest.mark.asyncio
async def test_daily_finds_today_events(graph_manager):
    # March 15 matches Caesar
    events = await graph_manager.today_in_history(3, 15)
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_daily_identifies_sceneless(graph_manager):
    events = await graph_manager.today_in_history(3, 15)
    worker = DailyWorker(graph_manager, None)
    sceneless = worker.get_sceneless_events(events)
    # All seed events lack flash_timepoint_id
    assert len(sceneless) == len(events)


@pytest.mark.asyncio
async def test_daily_queues_generation(graph_manager, job_manager):
    worker = DailyWorker(graph_manager, job_manager)

    # Manually run for March 15 (Caesar's date)
    with patch("app.workers.daily.datetime") as mock_dt:
        mock_now = MagicMock()
        mock_now.month = 3
        mock_now.day = 15
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **kw: __import__("datetime").datetime(*a, **kw)
        await worker._run_daily()

    # Should have created at least one job
    assert len(job_manager.jobs) >= 1
