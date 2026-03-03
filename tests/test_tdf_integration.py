import os

import pytest

from app.core.db import create_pool, init_schema, seed_if_empty
from app.core.graph import GraphManager
from app.core.tdf_bridge import make_tdf_record, tdf_to_node_attrs, export_node_as_tdf


@pytest.fixture()
async def graph_manager(tmp_path):
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    import shutil

    seeds_jsonl = os.path.join(data_dir, "seeds.jsonl")
    if os.path.exists(seeds_jsonl):
        shutil.copy(seeds_jsonl, tmp_path / "seeds.jsonl")
    seeds_json = os.path.join(data_dir, "seeds.json")
    if os.path.exists(seeds_json):
        shutil.copy(seeds_json, tmp_path / "seeds.json")

    url = os.environ["DATABASE_URL"]
    pool = await create_pool(url)
    await init_schema(pool)
    await seed_if_empty(pool, str(tmp_path))

    gm = GraphManager(pool, data_dir=str(tmp_path))
    await gm.load()
    yield gm
    await pool.close()


# --- make_tdf_record tests ---


def test_make_tdf_record_produces_valid_record():
    attrs = {
        "type": "event",
        "name": "Test Event",
        "year": 2020,
        "month": "january",
        "month_num": 1,
        "day": 1,
        "time": "1200",
        "country": "united-states",
        "region": "california",
        "city": "san-francisco",
        "tags": ["test"],
        "one_liner": "A test event",
    }
    record = make_tdf_record(
        "/2020/january/1/1200/united-states/california/san-francisco/test-event", attrs
    )
    assert record.tdf_hash
    assert len(record.tdf_hash) == 64  # SHA-256 hex
    assert record.source == "clockchain"
    assert record.provenance.generator == "timepoint-clockchain"


def test_identical_payloads_produce_identical_hashes():
    attrs = {
        "type": "event",
        "name": "Test Event",
        "year": 2020,
        "tags": ["test"],
        "one_liner": "A test event",
    }
    r1 = make_tdf_record("/test/1", attrs.copy())
    r2 = make_tdf_record("/test/2", attrs.copy())
    # Same payload content -> same hash (hash is payload-only, not id-dependent)
    assert r1.tdf_hash == r2.tdf_hash


def test_different_payloads_produce_different_hashes():
    attrs_a = {
        "type": "event",
        "name": "Event A",
        "year": 2020,
        "one_liner": "First event",
    }
    attrs_b = {
        "type": "event",
        "name": "Event B",
        "year": 2021,
        "one_liner": "Second event",
    }
    r1 = make_tdf_record("/test/a", attrs_a)
    r2 = make_tdf_record("/test/b", attrs_b)
    assert r1.tdf_hash != r2.tdf_hash


def test_provenance_keys_excluded_from_payload():
    attrs = {
        "type": "event",
        "name": "Test",
        "confidence": 0.9,
        "source_run_id": "run-123",
        "tdf_hash": "old-hash",
        "flash_timepoint_id": "flash-456",
        "created_at": "2026-01-01T00:00:00Z",
    }
    record = make_tdf_record("/test/prov", attrs)
    assert "confidence" not in record.payload
    assert "source_run_id" not in record.payload
    assert "tdf_hash" not in record.payload
    assert "flash_timepoint_id" not in record.payload
    assert "created_at" not in record.payload
    assert record.provenance.confidence == 0.9
    assert record.provenance.run_id == "run-123"
    assert record.provenance.flash_id == "flash-456"


def test_custom_generator():
    attrs = {"type": "event", "name": "Test"}
    record = make_tdf_record(
        "/test/gen", attrs, generator="timepoint-clockchain:expander"
    )
    assert record.provenance.generator == "timepoint-clockchain:expander"


# --- tdf_to_node_attrs tests ---


def test_tdf_to_node_attrs_roundtrip():
    attrs = {
        "type": "event",
        "name": "Roundtrip Test",
        "year": 2020,
        "tags": ["test"],
        "one_liner": "Testing roundtrip",
    }
    node_id = "/test/roundtrip"
    record = make_tdf_record(node_id, attrs)
    out_id, out_attrs = tdf_to_node_attrs(record)
    assert out_id == node_id
    assert out_attrs["name"] == "Roundtrip Test"
    assert out_attrs["year"] == 2020
    assert out_attrs["tdf_hash"] == record.tdf_hash


# --- export_node_as_tdf tests ---


def test_export_node_as_tdf():
    node_dict = {
        "path": "/test/export",
        "type": "event",
        "name": "Export Test",
        "year": 2020,
        "month": "march",
        "month_num": 3,
        "day": 15,
        "time": "1030",
        "country": "italy",
        "region": "lazio",
        "city": "rome",
        "slug": "export-test",
        "layer": 1,
        "visibility": "public",
        "created_by": "system",
        "tags": ["test"],
        "one_liner": "An export test",
        "figures": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "published_at": "",
        "source_type": "historical",
        "confidence": 0.95,
        "source_run_id": "run-abc",
        "tdf_hash": "existing-hash",
        "flash_timepoint_id": None,
        "flash_slug": "",
        "flash_share_url": "",
        "era": "",
    }
    record = export_node_as_tdf(node_dict)
    assert record.id == "/test/export"
    assert record.source == "clockchain"
    assert record.provenance.confidence == 0.95
    assert record.provenance.run_id == "run-abc"
    # Provenance keys should not be in payload
    assert "confidence" not in record.payload
    assert "source_run_id" not in record.payload
    assert "tdf_hash" not in record.payload


# --- Database integration tests ---


@pytest.mark.asyncio
async def test_add_node_populates_tdf_hash(graph_manager):
    await graph_manager.add_node(
        "/test/tdf-hash",
        type="event",
        name="TDF Hash Test",
        year=2020,
        visibility="public",
        layer=1,
    )
    node = await graph_manager.get_node("/test/tdf-hash")
    assert node is not None
    assert node["tdf_hash"] is not None
    assert len(node["tdf_hash"]) == 64


@pytest.mark.asyncio
async def test_seed_nodes_have_tdf_hash(graph_manager):
    node = await graph_manager.get_node(
        "/-44/march/15/1030/italy/lazio/rome/assassination-of-julius-caesar"
    )
    assert node is not None
    assert node["tdf_hash"] is not None
    assert len(node["tdf_hash"]) == 64


@pytest.mark.asyncio
async def test_seed_from_jsonl_loads_edges(graph_manager):
    assert await graph_manager.edge_count() == 3


# --- API tests ---


@pytest.mark.asyncio
async def test_format_tdf_returns_tdf_record(auth_client):
    resp = await auth_client.get(
        "/api/v1/moments/-44/march/15/1030/italy/lazio/rome/assassination-of-julius-caesar?format=tdf"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tdf_hash" in data
    assert data["tdf_hash"]
    assert data["source"] == "clockchain"
    assert "provenance" in data
    assert "payload" in data
    assert (
        data["id"]
        == "/-44/march/15/1030/italy/lazio/rome/assassination-of-julius-caesar"
    )


@pytest.mark.asyncio
async def test_format_default_returns_moment_response(auth_client):
    resp = await auth_client.get(
        "/api/v1/moments/-44/march/15/1030/italy/lazio/rome/assassination-of-julius-caesar"
    )
    assert resp.status_code == 200
    data = resp.json()
    # Default format has flat fields, not nested TDF structure
    assert "path" in data
    assert "edges" in data
    assert "provenance" not in data


@pytest.mark.asyncio
async def test_ingest_tdf_endpoint(auth_client):
    tdf_records = [
        {
            "id": "/2000/january/1/0000/test/region/city/ingest-test",
            "source": "clockchain",
            "timestamp": "2026-01-01T00:00:00Z",
            "provenance": {
                "generator": "test-ingest",
                "confidence": 0.8,
            },
            "payload": {
                "type": "event",
                "name": "Ingest Test",
                "year": 2000,
                "month": "january",
                "month_num": 1,
                "day": 1,
                "time": "0000",
                "country": "test",
                "region": "region",
                "city": "city",
                "slug": "ingest-test",
                "layer": 1,
                "visibility": "public",
                "tags": ["test"],
                "one_liner": "A test node ingested via TDF",
            },
        }
    ]
    resp = await auth_client.post("/api/v1/ingest/tdf", json=tdf_records)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ingested_nodes"] == 1

    # Verify the node was created with a tdf_hash
    resp2 = await auth_client.get(
        "/api/v1/moments/2000/january/1/0000/test/region/city/ingest-test?format=tdf"
    )
    assert resp2.status_code == 200
    tdf = resp2.json()
    assert tdf["tdf_hash"]
    assert len(tdf["tdf_hash"]) == 64
