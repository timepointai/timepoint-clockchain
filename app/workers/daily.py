import asyncio
import logging
from datetime import datetime, timezone

from app.core.graph import GraphManager
from app.core.jobs import JobManager

logger = logging.getLogger("clockchain.daily")

DAILY_INTERVAL = 86400  # 24 hours
MAX_DAILY_GENERATIONS = 5


class DailyWorker:
    def __init__(
        self,
        graph_manager: GraphManager,
        job_manager: JobManager | None,
        interval_seconds: int = DAILY_INTERVAL,
    ):
        self.gm = graph_manager
        self.jm = job_manager
        self.interval = interval_seconds

    async def start(self):
        logger.info("Daily worker starting")
        while True:
            try:
                await self._run_daily()
            except asyncio.CancelledError:
                logger.info("Daily worker cancelled")
                break
            except Exception as e:
                logger.error("Daily worker error: %s", e)
            await asyncio.sleep(self.interval)

    async def _run_daily(self):
        now = datetime.now(timezone.utc)
        events = await self.gm.today_in_history(now.month, now.day)
        logger.info(
            "Today in history (%s/%s): %d events found",
            now.month, now.day, len(events),
        )

        if not events:
            return

        sceneless = self.get_sceneless_events(events)
        logger.info("Events without Flash scenes: %d", len(sceneless))

        to_generate = (await self._rank_events(sceneless))[:MAX_DAILY_GENERATIONS]

        if not to_generate or not self.jm:
            return

        for event in to_generate:
            name = event.get("name", "")
            year = event.get("year", "")
            query = f"{name} ({year})"
            job = self.jm.create_job(query=query, preset="balanced", visibility="public")
            await self.jm.process_job(job)
            logger.info("Daily generation queued: %s (job %s)", query, job.id)

    def get_sceneless_events(self, events: list[dict]) -> list[dict]:
        return [
            e for e in events
            if not e.get("flash_timepoint_id") and not e.get("flash_scene")
        ]

    async def _rank_events(self, events: list[dict]) -> list[dict]:
        scored = []
        for e in events:
            path = e.get("path", "")
            deg = await self.gm.degree(path) if path else 0
            layer = e.get("layer", 0)
            scored.append((e, deg + layer * 2))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored]
