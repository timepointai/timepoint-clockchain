import asyncio
import logging

from app.core.graph import GraphManager
from app.workers.renderer import FlashClient

logger = logging.getLogger("clockchain.image_backfill")

MAX_FAILURES = 3
BATCH_SIZE = 50
COOLDOWN_BETWEEN_NODES = 5  # seconds between image generations


class ImageBackfillWorker:
    def __init__(
        self,
        graph_manager: GraphManager,
        flash_client: FlashClient,
        interval_seconds: int = 600,
    ):
        self.gm = graph_manager
        self.flash = flash_client
        self.interval = interval_seconds
        self.fail_counts: dict[str, int] = {}

    async def start(self):
        logger.info("Image backfill worker starting (interval=%ds)", self.interval)
        while True:
            try:
                await self._run_batch()
            except asyncio.CancelledError:
                logger.info("Image backfill worker cancelled")
                break
            except Exception as e:
                logger.error("Image backfill worker error: %s", e, exc_info=True)
            await asyncio.sleep(self.interval)

    async def _run_batch(self):
        rows = await self._get_imageless_nodes()
        if not rows:
            logger.info("No imageless nodes to backfill")
            return

        total = len(rows)
        logger.info("Image backfill: %d nodes need images", total)

        processed = 0
        for node in rows:
            node_id = node["path"]

            if self.fail_counts.get(node_id, 0) >= MAX_FAILURES:
                logger.debug("Skipping %s (failed %d times)", node_id, self.fail_counts[node_id])
                continue

            success = await self._generate_image_for_node(node)
            processed += 1

            if success:
                logger.info(
                    "Image backfill [%d/%d]: %s - OK",
                    processed, total, node.get("name", node_id),
                )
            else:
                logger.warning(
                    "Image backfill [%d/%d]: %s - FAILED (attempt %d/%d)",
                    processed, total, node.get("name", node_id),
                    self.fail_counts.get(node_id, 0), MAX_FAILURES,
                )

            await asyncio.sleep(COOLDOWN_BETWEEN_NODES)

        remaining = await self._count_imageless()
        logger.info("Image backfill batch done: processed %d, remaining %d", processed, remaining)

    async def _get_imageless_nodes(self) -> list[dict]:
        async with self.gm.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM nodes
                WHERE (image_url IS NULL OR image_url = '')
                  AND flash_timepoint_id IS NOT NULL
                ORDER BY layer DESC, created_at DESC
                LIMIT $1
                """,
                BATCH_SIZE,
            )
        from app.core.graph import _row_to_dict
        return [_row_to_dict(row) for row in rows]

    async def _count_imageless(self) -> int:
        async with self.gm.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT count(*) FROM nodes WHERE (image_url IS NULL OR image_url = '')"
            )

    async def _generate_image_for_node(self, node: dict) -> bool:
        node_id = node["path"]
        name = node.get("name", "")
        year = node.get("year", "")
        country = node.get("country", "")
        city = node.get("city", "")

        query = f"{name}, {year}, {country}, {city}"

        try:
            result = await self.flash.generate_sync(
                query=query,
                preset="balanced",
                generate_image=True,
                request_context={
                    "source": "clockchain",
                    "worker": "image_backfill",
                    "original_node_id": node_id,
                },
            )

            image_url = result.get("image_url")
            if not image_url:
                logger.warning("Flash returned no image_url for %s", node_id)
                self.fail_counts[node_id] = self.fail_counts.get(node_id, 0) + 1
                return False

            new_flash_id = result.get("id") or result.get("timepoint_id")
            updates = {"image_url": image_url}
            if new_flash_id:
                updates["flash_timepoint_id"] = new_flash_id
            share_url = result.get("share_url")
            if share_url:
                updates["flash_share_url"] = share_url
            flash_slug = result.get("slug")
            if flash_slug:
                updates["flash_slug"] = flash_slug

            await self.gm.update_node(node_id, **updates)
            return True

        except Exception as e:
            self.fail_counts[node_id] = self.fail_counts.get(node_id, 0) + 1
            logger.error("Failed to generate image for %s: %s", node_id, e)
            return False
