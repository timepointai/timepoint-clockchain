import asyncio
import logging

from app.core.graph import GraphManager

logger = logging.getLogger("clockchain.iterator")

# Fields that are set once at creation and MUST NEVER be modified.
# These represent the provenance of the node — what created it, when, and how.
IMMUTABLE_FIELDS = frozenset({
    "schema_version",
    "text_model",
    "model_provider",
    "model_permissiveness",
    "generation_id",
    "graph_state_hash",
    "tdf_hash",
    "created_at",
    "source_type",
    "created_by",
    "flash_timepoint_id",
})

# Fields that are immutable once set, but can be backfilled when empty.
# This allows first-time population without permitting overwrites.
BACKFILLABLE_FIELDS = frozenset({
    "image_model",  # set when backfilling images, never changed after
})

# Fields the iterator may enhance (add to, improve, backfill).
MUTABLE_FIELDS = frozenset({
    "tags",          # can add, never remove
    "figures",       # can add, never remove
    "one_liner",     # can improve if empty or low quality
    "era",           # can backfill if missing
    "visibility",    # can promote private -> public after quality check
    "image_url",     # can backfill if missing (failed render, timeout)
})

BATCH_SIZE = 50
COOLDOWN_BETWEEN_NODES = 2  # seconds


class IteratorWorker:
    """Universal enhancement worker that scans nodes and applies improvement passes.

    The iterator can enrich mutable metadata but is firewalled from
    provenance fields — it cannot change what model generated a node,
    when it was created, or its content hash.
    """

    def __init__(
        self,
        graph_manager: GraphManager,
        interval_seconds: int = 600,
    ):
        self.gm = graph_manager
        self.interval = interval_seconds
        self._passes: list[callable] = []

    def register_pass(self, fn):
        """Register an enhancement pass function.

        Each pass receives (node_id: str, node: dict, gm: GraphManager)
        and returns a dict of field updates, or None to skip.
        """
        self._passes.append(fn)
        return fn

    async def start(self):
        logger.info(
            "Iterator worker starting (interval=%ds, passes=%d)",
            self.interval, len(self._passes),
        )
        while True:
            try:
                await self._iterate_cycle()
            except asyncio.CancelledError:
                logger.info("Iterator worker cancelled")
                break
            except Exception as e:
                logger.error("Iterator error: %s", e, exc_info=True)
            await asyncio.sleep(self.interval)

    async def _iterate_cycle(self):
        if not self._passes:
            return

        async with self.gm.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM nodes ORDER BY created_at ASC LIMIT $1",
                BATCH_SIZE,
            )

        if not rows:
            return

        from app.core.graph import _row_to_dict
        enhanced = 0
        for row in rows:
            node = _row_to_dict(row)
            node_id = node["path"]
            updates = {}

            for pass_fn in self._passes:
                try:
                    result = await pass_fn(node_id, node, self.gm)
                    if result:
                        # Enforce the provenance firewall
                        for key in result:
                            if key in IMMUTABLE_FIELDS:
                                logger.warning(
                                    "Pass %s tried to modify immutable field %s on %s — blocked",
                                    pass_fn.__name__, key, node_id,
                                )
                            elif key in BACKFILLABLE_FIELDS:
                                current_value = node.get(key)
                                if current_value:
                                    logger.warning(
                                        "Pass %s tried to overwrite backfillable field %s on %s — blocked",
                                        pass_fn.__name__, key, node_id,
                                    )
                                else:
                                    updates[key] = result[key]
                            elif key in MUTABLE_FIELDS:
                                updates[key] = result[key]
                except Exception as e:
                    logger.error(
                        "Pass %s failed on %s: %s",
                        pass_fn.__name__, node_id, e,
                    )

            if updates:
                # For list fields (tags, figures), merge rather than replace
                if "tags" in updates and isinstance(updates["tags"], list):
                    existing = node.get("tags", []) or []
                    updates["tags"] = list(set(existing) | set(updates["tags"]))
                if "figures" in updates and isinstance(updates["figures"], list):
                    existing = node.get("figures", []) or []
                    updates["figures"] = list(set(existing) | set(updates["figures"]))

                await self.gm.update_node(node_id, **updates)
                enhanced += 1

            await asyncio.sleep(COOLDOWN_BETWEEN_NODES)

        if enhanced:
            logger.info("Iterator cycle: enhanced %d/%d nodes", enhanced, len(rows))


# --- Built-in passes ---

async def backfill_era(node_id: str, node: dict, gm: GraphManager) -> dict | None:
    """Backfill missing era field based on year."""
    if node.get("era"):
        return None
    year = node.get("year")
    if year is None:
        return None
    if year < -500:
        era = "ancient"
    elif year < 500:
        era = "classical"
    elif year < 1500:
        era = "medieval"
    elif year < 1800:
        era = "early-modern"
    elif year < 1900:
        era = "industrial"
    elif year < 2000:
        era = "modern"
    else:
        era = "contemporary"
    return {"era": era}


def make_backfill_images_pass(flash_client):
    """Create an image backfill pass that uses the given FlashClient.

    Finds nodes with no image_url, calls Flash to generate an image,
    and returns the image_url and image_model for update.
    """

    async def backfill_images(node_id: str, node: dict, gm: GraphManager) -> dict | None:
        if node.get("image_url"):
            return None

        # Skip seed nodes (layer 0) — they don't need images
        if node.get("layer", 0) == 0:
            return None

        name = node.get("name", "")
        year = node.get("year", "")
        country = node.get("country", "")
        city = node.get("city", "")
        query = f"{name}, {year}, {country}, {city}".strip(", ")

        logger.info("Backfilling image for %s: %s", node_id, query)

        try:
            result = await flash_client.generate_sync(
                query=query,
                preset="balanced",
                request_context={
                    "source": "clockchain",
                    "worker": "iterator-backfill",
                    "node_id": node_id,
                },
                generate_image=True,
                model_policy="permissive",
            )

            image_url = result.get("image_url")
            if not image_url:
                logger.warning("Backfill for %s returned no image_url", node_id)
                return None

            image_model = result.get("image_model_used", "")
            logger.info("Backfill image for %s: %s (model=%s)", node_id, image_url, image_model)

            updates = {"image_url": image_url}
            if image_model:
                updates["image_model"] = image_model
            return updates

        except Exception as e:
            logger.error("Image backfill failed for %s: %s", node_id, e)
            return None

    return backfill_images
