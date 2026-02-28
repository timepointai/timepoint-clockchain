import logging
from datetime import datetime

import asyncpg
from fastapi import Request

from app.core.tdf import compute_tdf_hash

logger = logging.getLogger("clockchain.graph")

VALID_EDGE_TYPES = {"causes", "contemporaneous", "same_location", "thematic"}

NODE_COLUMNS = [
    "id", "type", "name", "year", "month", "month_num", "day", "time",
    "country", "region", "city", "slug", "layer", "visibility",
    "created_by", "tags", "one_liner", "figures",
    "flash_timepoint_id", "flash_slug", "flash_share_url", "era",
    "created_at", "published_at",
    "source_type", "confidence", "source_run_id", "tdf_hash",
]


def _parse_dt(val) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        val = val.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None
    return None


def _row_to_dict(row: asyncpg.Record) -> dict:
    d = dict(row)
    d["path"] = d.pop("id")
    # Convert list-like columns
    for col in ("tags", "figures"):
        if col in d and d[col] is not None:
            d[col] = list(d[col])
    # Stringify datetimes for JSON compat
    for col in ("created_at", "published_at"):
        if col in d:
            d[col] = d[col].isoformat() if d[col] is not None else ""
    return d


class GraphManager:
    def __init__(self, pool: asyncpg.Pool, **_kwargs):
        self.pool = pool

    async def load(self):
        nc = await self.node_count()
        ec = await self.edge_count()
        logger.info("Graph loaded: %d nodes, %d edges", nc, ec)

    async def close(self):
        await self.pool.close()
        logger.info("Database pool closed")

    async def node_count(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT count(*) FROM nodes")

    async def edge_count(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT count(*) FROM edges")

    async def add_node(self, node_id: str, **attrs) -> None:
        if not attrs.get("tdf_hash"):
            attrs["tdf_hash"] = compute_tdf_hash({"slug": node_id.split("/")[-1] if "/" in node_id else node_id, **attrs})

        async with self.pool.acquire() as conn:
            tags = attrs.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            figures = attrs.get("figures", [])
            if not isinstance(figures, list):
                figures = []

            await conn.execute(
                """
                INSERT INTO nodes (
                    id, type, name, year, month, month_num, day, time,
                    country, region, city, slug, layer, visibility,
                    created_by, tags, one_liner, figures,
                    flash_timepoint_id, flash_slug, flash_share_url, era,
                    created_at, source_type, confidence, source_run_id, tdf_hash
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8,
                    $9, $10, $11, $12, $13, $14,
                    $15, $16, $17, $18,
                    $19, $20, $21, $22, $23,
                    $24, $25, $26, $27
                )
                ON CONFLICT (id) DO UPDATE SET
                    type = EXCLUDED.type,
                    name = EXCLUDED.name,
                    year = EXCLUDED.year,
                    month = EXCLUDED.month,
                    month_num = EXCLUDED.month_num,
                    day = EXCLUDED.day,
                    time = EXCLUDED.time,
                    country = EXCLUDED.country,
                    region = EXCLUDED.region,
                    city = EXCLUDED.city,
                    slug = EXCLUDED.slug,
                    layer = EXCLUDED.layer,
                    visibility = EXCLUDED.visibility,
                    created_by = EXCLUDED.created_by,
                    tags = EXCLUDED.tags,
                    one_liner = EXCLUDED.one_liner,
                    figures = EXCLUDED.figures,
                    flash_timepoint_id = EXCLUDED.flash_timepoint_id,
                    flash_slug = EXCLUDED.flash_slug,
                    flash_share_url = EXCLUDED.flash_share_url,
                    era = EXCLUDED.era,
                    source_type = EXCLUDED.source_type,
                    confidence = EXCLUDED.confidence,
                    source_run_id = EXCLUDED.source_run_id,
                    tdf_hash = EXCLUDED.tdf_hash
                """,
                node_id,
                attrs.get("type", "event"),
                attrs.get("name", ""),
                attrs.get("year"),
                attrs.get("month", ""),
                attrs.get("month_num", 0),
                attrs.get("day", 0),
                attrs.get("time", ""),
                attrs.get("country", ""),
                attrs.get("region", ""),
                attrs.get("city", ""),
                attrs.get("slug", ""),
                attrs.get("layer", 0),
                attrs.get("visibility", "private"),
                attrs.get("created_by", "system"),
                tags,
                attrs.get("one_liner", ""),
                figures,
                attrs.get("flash_timepoint_id"),
                attrs.get("flash_slug", ""),
                attrs.get("flash_share_url", ""),
                attrs.get("era", ""),
                _parse_dt(attrs.get("created_at")),
                attrs.get("source_type", "historical"),
                attrs.get("confidence"),
                attrs.get("source_run_id"),
                attrs.get("tdf_hash"),
            )
        await self._auto_link(node_id)

    async def add_edge(self, src: str, tgt: str, edge_type: str, **attrs) -> None:
        if edge_type not in VALID_EDGE_TYPES:
            raise ValueError(f"Invalid edge type: {edge_type}. Must be one of {VALID_EDGE_TYPES}")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO edges (source, target, type, weight, theme)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (source, target, type) DO NOTHING
                """,
                src, tgt, edge_type,
                attrs.get("weight", 1.0),
                attrs.get("theme", ""),
            )

    async def get_node(self, node_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM nodes WHERE id = $1", node_id)
        if row is None:
            return None
        return _row_to_dict(row)

    async def update_node(self, node_id: str, **attrs) -> None:
        if not attrs:
            return
        set_clauses = []
        values = []
        idx = 1
        for key, val in attrs.items():
            set_clauses.append(f"{key} = ${idx}")
            values.append(val)
            idx += 1
        values.append(node_id)
        query = f"UPDATE nodes SET {', '.join(set_clauses)} WHERE id = ${idx}"
        async with self.pool.acquire() as conn:
            await conn.execute(query, *values)

    async def browse(self, prefix: str = "") -> list[dict]:
        prefix = prefix.strip("/")
        async with self.pool.acquire() as conn:
            if prefix:
                # Match nodes whose id (stripped of leading /) starts with prefix
                like_pattern = f"/{prefix}/%"
                rows = await conn.fetch(
                    "SELECT id FROM nodes WHERE visibility = 'public' AND id LIKE $1",
                    like_pattern,
                )
            else:
                rows = await conn.fetch(
                    "SELECT id FROM nodes WHERE visibility = 'public'"
                )

        results: dict[str, int] = {}
        for row in rows:
            node_path = row["id"].strip("/")
            if prefix:
                remainder = node_path[len(prefix):].strip("/")
            else:
                remainder = node_path
            if not remainder:
                continue
            next_segment = remainder.split("/")[0]
            results[next_segment] = results.get(next_segment, 0) + 1

        return [
            {"segment": seg, "count": count, "label": seg}
            for seg, count in sorted(results.items())
        ]

    async def today_in_history(self, month: int, day: int) -> list[dict]:
        from app.core.url import NUM_TO_MONTH
        month_name = NUM_TO_MONTH.get(month, "")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM nodes
                WHERE visibility = 'public'
                  AND day = $1
                  AND (lower(month) = $2 OR month_num = $3)
                """,
                day, month_name, month,
            )
        return [_row_to_dict(row) for row in rows]

    async def random_public(self) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM nodes
                WHERE visibility = 'public' AND layer >= 1
                ORDER BY random()
                LIMIT 1
                """
            )
        if row is None:
            return None
        return _row_to_dict(row)

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        pattern = f"%{query}%"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *,
                    CASE
                        WHEN name ILIKE $1 THEN 1.0
                        WHEN one_liner ILIKE $1 THEN 0.7
                        ELSE 0.4
                    END AS score
                FROM nodes
                WHERE visibility = 'public'
                  AND (
                    name ILIKE $1
                    OR one_liner ILIKE $1
                    OR EXISTS (SELECT 1 FROM unnest(tags) AS t WHERE t ILIKE $1)
                    OR EXISTS (SELECT 1 FROM unnest(figures) AS f WHERE f ILIKE $1)
                  )
                ORDER BY score DESC
                LIMIT $2
                """,
                pattern, limit,
            )
        results = []
        for row in rows:
            d = _row_to_dict(row)
            d["score"] = row["score"]
            results.append(d)
        return results

    async def get_neighbors(self, node_id: str) -> list[dict]:
        async with self.pool.acquire() as conn:
            # Check node exists
            exists = await conn.fetchval("SELECT 1 FROM nodes WHERE id = $1", node_id)
            if not exists:
                return []

            rows = await conn.fetch(
                """
                SELECT n.id, n.name, e.type AS edge_type, e.weight, e.theme, 'out' AS direction
                FROM edges e JOIN nodes n ON n.id = e.target
                WHERE e.source = $1
                UNION ALL
                SELECT n.id, n.name, e.type AS edge_type, e.weight, e.theme, 'in' AS direction
                FROM edges e JOIN nodes n ON n.id = e.source
                WHERE e.target = $1
                """,
                node_id,
            )
        return [
            {
                "path": row["id"],
                "name": row["name"],
                "edge_type": row["edge_type"],
                "weight": row["weight"],
                "theme": row["theme"],
            }
            for row in rows
        ]

    async def stats(self) -> dict:
        async with self.pool.acquire() as conn:
            total_nodes = await conn.fetchval("SELECT count(*) FROM nodes")
            total_edges = await conn.fetchval("SELECT count(*) FROM edges")
            layer_rows = await conn.fetch(
                "SELECT layer::text AS layer, count(*) AS cnt FROM nodes GROUP BY layer"
            )
            edge_type_rows = await conn.fetch(
                "SELECT type, count(*) AS cnt FROM edges GROUP BY type"
            )
            source_type_rows = await conn.fetch(
                "SELECT coalesce(source_type, 'historical') AS source_type, count(*) AS cnt FROM nodes GROUP BY source_type"
            )
        return {
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "layer_counts": {row["layer"]: row["cnt"] for row in layer_rows},
            "edge_type_counts": {row["type"]: row["cnt"] for row in edge_type_rows},
            "source_type_counts": {row["source_type"]: row["cnt"] for row in source_type_rows},
        }

    async def get_frontier_nodes(self, threshold: int = 3) -> list[str]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT n.id, coalesce(ec.cnt, 0) AS deg
                FROM nodes n
                LEFT JOIN (
                    SELECT id, count(*) AS cnt FROM (
                        SELECT source AS id FROM edges
                        UNION ALL
                        SELECT target AS id FROM edges
                    ) sub GROUP BY id
                ) ec ON ec.id = n.id
                WHERE coalesce(ec.cnt, 0) < $1
                """,
                threshold,
            )
        return [row["id"] for row in rows]

    async def degree(self, node_id: str) -> int:
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT count(*) FROM (
                    SELECT 1 FROM edges WHERE source = $1
                    UNION ALL
                    SELECT 1 FROM edges WHERE target = $1
                ) sub
                """,
                node_id,
            )
        return count or 0

    async def has_edge(self, src: str, tgt: str) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT 1 FROM edges WHERE source = $1 AND target = $2 LIMIT 1",
                src, tgt,
            )
        return row is not None

    async def _auto_link(self, node_id: str):
        async with self.pool.acquire() as conn:
            node = await conn.fetchrow("SELECT * FROM nodes WHERE id = $1", node_id)
            if node is None:
                return

            node_year = node["year"]
            node_country = node["country"] or ""
            node_region = node["region"] or ""
            node_city = node["city"] or ""
            node_tags = list(node["tags"]) if node["tags"] else []

            # Contemporaneous: same year +/- 1
            if node_year is not None:
                await conn.execute(
                    """
                    INSERT INTO edges (source, target, type, weight)
                    SELECT $1, id, 'contemporaneous', 0.5
                    FROM nodes
                    WHERE id != $1
                      AND year IS NOT NULL
                      AND abs(year - $2) <= 1
                      AND NOT EXISTS (
                          SELECT 1 FROM edges
                          WHERE source = $1 AND target = nodes.id AND type = 'contemporaneous'
                      )
                    """,
                    node_id, node_year,
                )
                await conn.execute(
                    """
                    INSERT INTO edges (source, target, type, weight)
                    SELECT id, $1, 'contemporaneous', 0.5
                    FROM nodes
                    WHERE id != $1
                      AND year IS NOT NULL
                      AND abs(year - $2) <= 1
                      AND NOT EXISTS (
                          SELECT 1 FROM edges
                          WHERE source = nodes.id AND target = $1 AND type = 'contemporaneous'
                      )
                    """,
                    node_id, node_year,
                )

            # Same location: matching country + region + city
            if node_country:
                await conn.execute(
                    """
                    INSERT INTO edges (source, target, type, weight)
                    SELECT $1, id, 'same_location', 0.5
                    FROM nodes
                    WHERE id != $1
                      AND country = $2 AND region = $3 AND city = $4
                      AND NOT EXISTS (
                          SELECT 1 FROM edges
                          WHERE source = $1 AND target = nodes.id AND type = 'same_location'
                      )
                    """,
                    node_id, node_country, node_region, node_city,
                )
                await conn.execute(
                    """
                    INSERT INTO edges (source, target, type, weight)
                    SELECT id, $1, 'same_location', 0.5
                    FROM nodes
                    WHERE id != $1
                      AND country = $2 AND region = $3 AND city = $4
                      AND NOT EXISTS (
                          SELECT 1 FROM edges
                          WHERE source = nodes.id AND target = $1 AND type = 'same_location'
                      )
                    """,
                    node_id, node_country, node_region, node_city,
                )

            # Thematic: overlapping tags
            if node_tags:
                await conn.execute(
                    """
                    INSERT INTO edges (source, target, type, weight, theme)
                    SELECT $1, n.id, 'thematic', 0.3,
                           array_to_string(ARRAY(
                               SELECT unnest($2::text[]) INTERSECT SELECT unnest(n.tags)
                               ORDER BY 1
                           ), ', ')
                    FROM nodes n
                    WHERE n.id != $1
                      AND n.tags && $2::text[]
                      AND NOT EXISTS (
                          SELECT 1 FROM edges
                          WHERE source = $1 AND target = n.id AND type = 'thematic'
                      )
                    """,
                    node_id, node_tags,
                )
                await conn.execute(
                    """
                    INSERT INTO edges (source, target, type, weight, theme)
                    SELECT n.id, $1, 'thematic', 0.3,
                           array_to_string(ARRAY(
                               SELECT unnest($2::text[]) INTERSECT SELECT unnest(n.tags)
                               ORDER BY 1
                           ), ', ')
                    FROM nodes n
                    WHERE n.id != $1
                      AND n.tags && $2::text[]
                      AND NOT EXISTS (
                          SELECT 1 FROM edges
                          WHERE source = n.id AND target = $1 AND type = 'thematic'
                      )
                    """,
                    node_id, node_tags,
                )


async def get_graph_manager(request: Request) -> GraphManager:
    return request.app.state.graph_manager
