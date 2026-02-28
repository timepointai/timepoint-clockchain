#!/usr/bin/env python3
"""Migration 002: Backfill tdf_hash on existing rows and enforce NOT NULL.

Usage:
    DATABASE_URL=postgresql://... python migrations/002_backfill_tdf_hash.py

Computes tdf_hash for every row where it is currently NULL, then adds
a NOT NULL constraint so all future inserts must include a hash.
"""
import asyncio
import hashlib
import json
import os
import sys

import asyncpg


_TDF_FIELDS = (
    "year", "month", "day", "time",
    "country", "region", "city", "slug",
    "name", "one_liner",
)


def compute_tdf_hash(row: dict) -> str:
    payload = {
        k: str(row.get(k) or "").lower().strip()
        for k in _TDF_FIELDS
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def migrate(database_url: str):
    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch("SELECT * FROM nodes WHERE tdf_hash IS NULL")
        print(f"Found {len(rows)} rows without tdf_hash")

        for row in rows:
            h = compute_tdf_hash(dict(row))
            await conn.execute(
                "UPDATE nodes SET tdf_hash = $1 WHERE id = $2",
                h, row["id"],
            )

        if rows:
            print(f"Backfilled {len(rows)} rows")

        await conn.execute(
            "ALTER TABLE nodes ALTER COLUMN tdf_hash SET NOT NULL"
        )
        print("Added NOT NULL constraint on tdf_hash")

    finally:
        await conn.close()


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is required")
        sys.exit(1)
    asyncio.run(migrate(database_url))


if __name__ == "__main__":
    main()
