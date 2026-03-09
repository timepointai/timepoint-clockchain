"""Add image_url column to nodes table."""

import asyncio
import os

import asyncpg


async def migrate(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        col_exists = await conn.fetchval(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'nodes' AND column_name = 'image_url'
            """
        )
        if col_exists:
            return
        await conn.execute("ALTER TABLE nodes ADD COLUMN image_url TEXT")


async def main():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    await migrate(pool)
    await pool.close()
    print("Migration 003 complete: added image_url column")


if __name__ == "__main__":
    asyncio.run(main())
