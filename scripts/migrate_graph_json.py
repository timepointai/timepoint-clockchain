#!/usr/bin/env python3
"""One-time migration: load an existing graph.json (NetworkX node_link format)
into PostgreSQL.

Usage:
    DATABASE_URL=postgresql://... python scripts/migrate_graph_json.py [path/to/graph.json]

If no path is given, defaults to data/graph.json.
"""
import asyncio
import json
import sys
import os

import asyncpg


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
    published_at TIMESTAMPTZ
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


async def migrate(graph_path: str, database_url: str):
    print(f"Reading {graph_path} ...")
    with open(graph_path) as f:
        data = json.load(f)

    # NetworkX node_link format has "nodes" and "links"
    nodes = data.get("nodes", [])
    links = data.get("links", [])
    print(f"Found {len(nodes)} nodes and {len(links)} edges")

    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(SCHEMA_DDL)

        # Insert nodes
        inserted_nodes = 0
        for node in nodes:
            node_id = node.get("id")
            if not node_id:
                continue

            tags = node.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            figures = node.get("figures", [])
            if not isinstance(figures, list):
                figures = []

            await conn.execute(
                """
                INSERT INTO nodes (
                    id, type, name, year, month, month_num, day, time,
                    country, region, city, slug, layer, visibility,
                    created_by, tags, one_liner, figures,
                    flash_timepoint_id, flash_slug, flash_share_url, era,
                    created_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8,
                    $9, $10, $11, $12, $13, $14,
                    $15, $16, $17, $18,
                    $19, $20, $21, $22, $23
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    visibility = EXCLUDED.visibility,
                    layer = EXCLUDED.layer,
                    tags = EXCLUDED.tags,
                    one_liner = EXCLUDED.one_liner,
                    figures = EXCLUDED.figures
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
                tags,
                node.get("one_liner", ""),
                figures,
                node.get("flash_timepoint_id"),
                node.get("flash_slug", ""),
                node.get("flash_share_url", ""),
                node.get("era", ""),
                node.get("created_at"),
            )
            inserted_nodes += 1

        # Insert edges
        inserted_edges = 0
        for link in links:
            source = link.get("source")
            target = link.get("target")
            edge_type = link.get("type", "thematic")
            if not source or not target:
                continue
            if edge_type not in ("causes", "contemporaneous", "same_location", "thematic"):
                print(f"  Skipping invalid edge type: {edge_type}")
                continue

            await conn.execute(
                """
                INSERT INTO edges (source, target, type, weight, theme)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (source, target, type) DO NOTHING
                """,
                source,
                target,
                edge_type,
                link.get("weight", 1.0),
                link.get("theme", ""),
            )
            inserted_edges += 1

        print(f"Migrated {inserted_nodes} nodes and {inserted_edges} edges")
    finally:
        await conn.close()


def main():
    graph_path = sys.argv[1] if len(sys.argv) > 1 else "data/graph.json"
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is required")
        sys.exit(1)
    if not os.path.exists(graph_path):
        print(f"ERROR: {graph_path} not found")
        sys.exit(1)

    asyncio.run(migrate(graph_path, database_url))


if __name__ == "__main__":
    main()
