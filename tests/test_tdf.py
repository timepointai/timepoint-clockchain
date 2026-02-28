"""Verify TDF hashing is pervasive across all node-creation paths."""

import os

import pytest

from app.core.tdf import compute_tdf_hash


def test_compute_tdf_hash_deterministic():
    attrs = {
        "year": 1969, "month": "july", "day": 20, "time": "2056",
        "country": "united-states", "region": "florida",
        "city": "cape-canaveral", "slug": "apollo-11-moon-landing",
        "name": "Apollo 11 Moon Landing",
        "one_liner": "First humans on the Moon",
    }
    h1 = compute_tdf_hash(attrs)
    h2 = compute_tdf_hash(attrs)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_compute_tdf_hash_differs_on_content_change():
    base = {
        "year": 1969, "month": "july", "day": 20, "time": "2056",
        "country": "united-states", "region": "florida",
        "city": "cape-canaveral", "slug": "apollo-11-moon-landing",
        "name": "Apollo 11 Moon Landing",
        "one_liner": "First humans on the Moon",
    }
    modified = {**base, "name": "Apollo 11 Lunar Landing"}
    assert compute_tdf_hash(base) != compute_tdf_hash(modified)


def test_compute_tdf_hash_handles_missing_fields():
    h = compute_tdf_hash({"name": "Minimal"})
    assert isinstance(h, str) and len(h) == 64


# -- Graph-layer tests: every add_node path should stamp tdf_hash --

@pytest.fixture()
async def _seed(auth_client):
    """Seed via the app lifespan so GraphManager is available."""
    yield


async def test_add_node_stamps_tdf_hash(auth_client):
    """GraphManager.add_node auto-computes tdf_hash."""
    import asyncpg
    url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(url)

    # Seed via API so the lifespan (and graph manager) has run
    resp = await auth_client.post("/api/v1/index", json={
        "path": "/1776/july/4/1200/united-states/pennsylvania/philadelphia/declaration-of-independence",
        "name": "Declaration of Independence",
        "one_liner": "Continental Congress adopts the Declaration",
        "tags": ["independence"],
        "visibility": "public",
        "layer": 1,
    })
    assert resp.status_code == 200

    row = await conn.fetchrow(
        "SELECT tdf_hash FROM nodes WHERE id = $1",
        "/1776/july/4/1200/united-states/pennsylvania/philadelphia/declaration-of-independence",
    )
    await conn.close()
    assert row is not None
    assert row["tdf_hash"] is not None
    assert len(row["tdf_hash"]) == 64


async def test_seed_nodes_have_tdf_hash(auth_client):
    """Seed data inserted by seed_if_empty() should carry tdf_hash."""
    import asyncpg
    url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(url)
    rows = await conn.fetch("SELECT id, tdf_hash FROM nodes WHERE tdf_hash IS NOT NULL")
    await conn.close()
    # Seeds are loaded via lifespan; every node should have a hash
    assert len(rows) >= 5, f"Expected ≥5 nodes with tdf_hash, got {len(rows)}"
    for row in rows:
        assert len(row["tdf_hash"]) == 64, f"Bad hash on {row['id']}"


async def test_ingest_subgraph_stamps_tdf_hash(auth_client):
    """POST /ingest/subgraph auto-computes tdf_hash when not provided."""
    import asyncpg
    resp = await auth_client.post("/api/v1/ingest/subgraph", json={
        "nodes": [{
            "id": "/2000/january/1/0000/world/world/world/y2k-arrives",
            "name": "Y2K Arrives",
            "year": 2000,
            "month": "january",
            "month_num": 1,
            "day": 1,
            "time": "0000",
            "country": "world",
            "region": "world",
            "city": "world",
            "slug": "y2k-arrives",
            "layer": 1,
            "visibility": "public",
            "one_liner": "The new millennium begins without catastrophic computer failures",
        }],
        "edges": [],
    })
    assert resp.status_code == 200

    url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(url)
    row = await conn.fetchrow(
        "SELECT tdf_hash FROM nodes WHERE id = $1",
        "/2000/january/1/0000/world/world/world/y2k-arrives",
    )
    await conn.close()
    assert row is not None
    assert row["tdf_hash"] is not None
    assert len(row["tdf_hash"]) == 64


async def test_ingest_subgraph_preserves_explicit_tdf_hash(auth_client):
    """When caller provides tdf_hash, the system should keep it."""
    import asyncpg
    explicit = "a" * 64
    resp = await auth_client.post("/api/v1/ingest/subgraph", json={
        "nodes": [{
            "id": "/2001/september/11/0846/united-states/new-york/new-york/sept-11",
            "name": "September 11",
            "year": 2001, "month": "september", "month_num": 9,
            "day": 11, "time": "0846",
            "country": "united-states", "region": "new-york", "city": "new-york",
            "slug": "sept-11", "layer": 1, "visibility": "public",
            "one_liner": "Terrorist attacks",
            "tdf_hash": explicit,
        }],
        "edges": [],
    })
    assert resp.status_code == 200

    url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(url)
    row = await conn.fetchrow(
        "SELECT tdf_hash FROM nodes WHERE id = $1",
        "/2001/september/11/0846/united-states/new-york/new-york/sept-11",
    )
    await conn.close()
    assert row["tdf_hash"] == explicit
