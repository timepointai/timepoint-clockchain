import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("clockchain.jobs")

TIME_OF_DAY_MAP = {
    "dawn": "0600",
    "early morning": "0700",
    "morning": "0900",
    "late morning": "1100",
    "midday": "1200",
    "noon": "1200",
    "early afternoon": "1300",
    "afternoon": "1400",
    "late afternoon": "1600",
    "evening": "1800",
    "dusk": "1900",
    "night": "2100",
    "late night": "2300",
    "midnight": "0000",
}


def _parse_location(location_str: str) -> tuple[str, str, str]:
    """Parse Flash's location string into (country, region, city)."""
    if not location_str:
        return "unknown", "unknown", "unknown"
    parts = [p.strip() for p in location_str.split(",")]
    if len(parts) >= 3:
        city = parts[0].lower().replace(" ", "-")
        region = parts[-2].lower().replace(" ", "-")
        country = parts[-1].lower().replace(" ", "-")
    elif len(parts) == 2:
        city = parts[0].lower().replace(" ", "-")
        region = city
        country = parts[1].lower().replace(" ", "-")
    else:
        city = parts[0].lower().replace(" ", "-")
        region = city
        country = city
    return country, region, city


def _extract_name_from_query(query: str) -> str:
    """Clean up a query string into an event name."""
    # Remove trailing date/location hints like "March 15 44 BC Rome"
    name = query.strip()
    # Capitalize properly
    return name


def _time_of_day_to_time(tod: str | None) -> str:
    if not tod:
        return "1200"
    return TIME_OF_DAY_MAP.get(tod.lower(), "1200")


@dataclass
class Job:
    id: str
    query: str
    preset: str = "balanced"
    status: str = "pending"  # pending, processing, completed, failed
    path: str | None = None
    error: str | None = None
    created_at: str = ""
    completed_at: str | None = None
    flash_response: dict | None = None
    user_id: str | None = None
    visibility: str = "private"

    def to_dict(self) -> dict:
        return {
            "job_id": self.id,
            "status": self.status,
            "path": self.path,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class JobManager:
    def __init__(self, graph_manager, flash_client):
        self.graph_manager = graph_manager
        self.flash_client = flash_client
        self.jobs: dict[str, Job] = {}
        self.queue: asyncio.Queue = asyncio.Queue()

    def create_job(
        self,
        query: str,
        preset: str = "balanced",
        user_id: str | None = None,
        visibility: str = "private",
    ) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            query=query,
            preset=preset,
            user_id=user_id,
            visibility=visibility,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def process_job(self, job: Job):
        job.status = "processing"
        try:
            result = await self.flash_client.generate_sync(
                job.query,
                job.preset,
                request_context={
                    "source": "clockchain",
                    "worker": "renderer",
                    "job_id": job.id,
                },
            )

            flash_id = result.get("id") or result.get("timepoint_id")
            name = result.get("name") or _extract_name_from_query(job.query)
            slug = result.get("slug", "")

            # Flash returns year as positive int, month/day as ints
            year = result.get("year") or 0
            grounding = result.get("grounding", {}) or {}
            verified_year = grounding.get("verified_year")
            if verified_year and isinstance(verified_year, int):
                year = verified_year

            month = result.get("month") or 1
            day = result.get("day") or 1
            time_str = _time_of_day_to_time(result.get("time_of_day"))

            # Parse location from Flash's location string
            location_str = result.get("location", "")
            country, region, city = _parse_location(location_str)

            from app.core.url import build_path, slugify, NUM_TO_MONTH
            if isinstance(month, int):
                month_num = month
            else:
                from app.core.url import MONTH_TO_NUM
                month_num = MONTH_TO_NUM.get(str(month).lower(), 1)

            if not slug:
                slug = slugify(name)
            # Clean the slug — Flash appends random hex, keep it
            clean_slug = slugify(slug)

            path = build_path(year, month_num, day, time_str, country, region, city, clean_slug)

            # Extract figures from characters
            characters = result.get("characters", {}) or {}
            char_list = characters.get("characters", []) or []
            figures = [c.get("name", "") for c in char_list if c.get("name")]

            # Extract one-liner from moment
            moment = result.get("moment", {}) or {}
            one_liner = moment.get("plot_summary", "")
            if not one_liner:
                one_liner = result.get("query", job.query)

            # Tags from Flash (may be None)
            tags = result.get("tags") or []

            month_name = NUM_TO_MONTH.get(month_num, "")

            await self.graph_manager.add_node(
                path,
                type="event",
                name=name,
                year=year,
                month=month_name,
                month_num=month_num,
                day=day,
                time=time_str,
                country=country,
                region=region,
                city=city,
                slug=clean_slug,
                layer=2,
                visibility=job.visibility,
                created_by=job.user_id or "system",
                tags=tags,
                one_liner=one_liner[:200] if one_liner else "",
                figures=figures,
                flash_timepoint_id=flash_id,
                flash_slug=result.get("slug", ""),
                flash_share_url=result.get("share_url", ""),
                era=result.get("era", ""),
                created_at=datetime.now(timezone.utc).isoformat(),
            )

            # Save scene reference (not the full scene — that lives in Flash)
            self._save_scene(path, result)

            await self.graph_manager.save()

            job.path = path
            job.flash_response = result
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc).isoformat()
            logger.info("Job %s completed: %s", job.id, path)

        except Exception as e:
            job.status = "failed"
            error_msg = str(e)
            if hasattr(e, "response"):
                try:
                    error_msg = f"{error_msg} | response: {e.response.text[:500]}"
                except Exception:
                    logger.debug("Could not read error response body")
            job.error = error_msg or repr(e)
            job.completed_at = datetime.now(timezone.utc).isoformat()
            logger.error("Job %s failed: %s", job.id, job.error, exc_info=True)

    def _save_scene(self, path: str, scene_data: dict):
        data_dir = self.graph_manager.data_dir
        segments = path.strip("/").split("/")
        scene_dir = data_dir / "scenes" / "/".join(segments)
        scene_dir.mkdir(parents=True, exist_ok=True)
        scene_file = scene_dir / "scene.json"
        with open(scene_file, "w") as f:
            json.dump(scene_data, f, indent=2, default=str)
        logger.info("Scene saved to %s", scene_file)
