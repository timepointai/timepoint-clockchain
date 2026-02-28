import json
import logging
from datetime import datetime
from pathlib import Path

import asyncpg

from app.core.tdf import compute_tdf_hash

logger = logging.getLogger("clockchain.db")

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT DEFAULT 'event',
    name TEXT DEFAULT '',
    year INTEGER,
    month TEXT DEFAULT '',
    month_num INTEGER DEFAULT 0,
    day INTEGER DEFAULT 0,
    time TEXT DEFAULT '',
    country TEXT DEFAULT '',
    region TEXT DEFAULT '',
    city TEXT DEFAULT '',
    slug TEXT DEFAULT '',
    layer INTEGER DEFAULT 0,
    visibility TEXT DEFAULT 'private',
    created_by TEXT DEFAULT 'system',
    tags TEXT[] DEFAULT '{}',
    one_liner TEXT DEFAULT '',
    figures TEXT[] DEFAULT '{}',
    flash_timepoint_id TEXT,
    flash_slug TEXT DEFAULT '',
    flash_share_url TEXT DEFAULT '',
    era TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now(),
    published_at TIMESTAMPTZ,
    source_type TEXT DEFAULT 'historical',
    confidence FLOAT,
    source_run_id TEXT,
    tdf_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    source TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('causes','contemporaneous','same_location','thematic')),
    weight FLOAT DEFAULT 1.0,
    theme TEXT DEFAULT '',
    PRIMARY KEY (source, target, type)
);
"""

INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_nodes_visibility ON nodes(visibility);
CREATE INDEX IF NOT EXISTS idx_nodes_month_day ON nodes(month, day);
CREATE INDEX IF NOT EXISTS idx_nodes_year ON nodes(year);
CREATE INDEX IF NOT EXISTS idx_nodes_location ON nodes(country, region, city);
CREATE INDEX IF NOT EXISTS idx_nodes_tags ON nodes USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_nodes_figures ON nodes USING GIN(figures);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS idx_nodes_source_type ON nodes(source_type);
"""

TRGM_DDL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_nodes_name_trgm ON nodes USING GIN(name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_nodes_one_liner_trgm ON nodes USING GIN(one_liner gin_trgm_ops);
"""


def _parse_dt(val) -> datetime | None:
    """Convert a datetime string or None to a proper datetime object."""
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


async def create_pool(database_url: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
    logger.info("Database pool created")
    return pool


async def init_schema(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_DDL)
        await conn.execute(INDEX_DDL)
        try:
            await conn.execute(TRGM_DDL)
        except asyncpg.UndefinedObjectError:
            logger.warning("pg_trgm extension not available, skipping trigram indexes")
    logger.info("Database schema initialized")


async def seed_if_empty(pool: asyncpg.Pool, data_dir: str):
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM nodes")
        if count > 0:
            logger.info("Database already has %d nodes, skipping seed", count)
            return

    seeds_path = Path(data_dir) / "seeds.json"
    bundled_path = Path("/app/seeds/seeds.json")

    path = None
    if seeds_path.exists():
        path = seeds_path
    elif bundled_path.exists():
        path = bundled_path

    if path is None:
        logger.warning("No seeds file found, starting empty")
        return

    logger.info("Seeding database from %s", path)
    with open(path) as f:
        seeds = json.load(f)

    async with pool.acquire() as conn:
        async with conn.transaction():
            for node in seeds.get("nodes", []):
                node_id = node.pop("id")
                tdf_hash = compute_tdf_hash(node)
                await conn.execute(
                    """
                    INSERT INTO nodes (
                        id, type, name, year, month, month_num, day, time,
                        country, region, city, slug, layer, visibility,
                        created_by, tags, one_liner, figures,
                        flash_timepoint_id, created_at, tdf_hash
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8,
                        $9, $10, $11, $12, $13, $14,
                        $15, $16, $17, $18, $19, $20, $21
                    )
                    ON CONFLICT (id) DO NOTHING
                    """,
                    node_id,
                    node.get("type", "event"),
                    node.get("name", ""),
                    node.get("year"),
                    node.get("month", ""),
                    node.get("month_num", 0),
                    node.get("day", 0),
                    node.get("time", ""),
                    node.get("country", ""),
                    node.get("region", ""),
                    node.get("city", ""),
                    node.get("slug", ""),
                    node.get("layer", 0),
                    node.get("visibility", "private"),
                    node.get("created_by", "system"),
                    node.get("tags", []),
                    node.get("one_liner", ""),
                    node.get("figures", []),
                    node.get("flash_timepoint_id"),
                    _parse_dt(node.get("created_at")),
                    tdf_hash,
                )

            for edge in seeds.get("edges", []):
                await conn.execute(
                    """
                    INSERT INTO edges (source, target, type, weight, theme)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (source, target, type) DO NOTHING
                    """,
                    edge["source"],
                    edge["target"],
                    edge.get("type", "thematic"),
                    edge.get("weight", 1.0),
                    edge.get("theme", ""),
                )

    async with pool.acquire() as conn:
        node_count = await conn.fetchval("SELECT count(*) FROM nodes")
        edge_count = await conn.fetchval("SELECT count(*) FROM edges")
    logger.info("Seeded %d nodes and %d edges", node_count, edge_count)
