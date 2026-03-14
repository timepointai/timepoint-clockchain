"""Tests for the propose/challenge protocol and moment status state machine."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import AGENT_TOKENS_DDL


# ---------- Fixtures ----------


@pytest.fixture(autouse=True)
async def _init_agent_tokens_table():
    """Ensure agent_tokens table exists and is truncated."""
    import asyncpg

    url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(AGENT_TOKENS_DDL)
        await conn.execute("TRUNCATE agent_tokens RESTART IDENTITY CASCADE")
    finally:
        await conn.close()
    yield


@pytest.fixture()
def admin_token():
    return "test-admin-token-propose"


@pytest.fixture()
async def admin_client(admin_token):
    """Client with admin token configured."""
    os.environ["ADMIN_TOKEN"] = admin_token
    os.environ["WRITER_TOKENS"] = ""

    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import app

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={
                "X-Service-Key": "test-key",
                "Authorization": f"Bearer {admin_token}",
            },
        ) as ac:
            yield ac

    os.environ.pop("ADMIN_TOKEN", None)
    os.environ.pop("WRITER_TOKENS", None)
    get_settings.cache_clear()


@pytest.fixture()
async def writer_client(admin_client):
    """Register a writer agent and return a client with its token."""
    reg = await admin_client.post(
        "/api/v1/agents/register",
        json={"agent_name": "test-writer", "permissions": "write"},
    )
    assert reg.status_code == 200
    writer_token = reg.json()["token"]

    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={
            "X-Service-Key": "test-key",
            "Authorization": f"Bearer {writer_token}",
        },
    ) as wc:
        yield wc


# ---------- Helper ----------


def _moment_payload(
    moment_id: str,
    name: str = "Test Moment",
    year: int = 1945,
    **kwargs,
) -> dict:
    return {
        "id": moment_id,
        "name": name,
        "one_liner": kwargs.get("one_liner", f"A test moment: {name}"),
        "year": year,
        "month": kwargs.get("month", "august"),
        "month_num": kwargs.get("month_num", 8),
        "day": kwargs.get("day", 6),
        "country": kwargs.get("country", "Japan"),
        "region": kwargs.get("region", "Hiroshima"),
        "city": kwargs.get("city", "Hiroshima"),
        "visibility": kwargs.get("visibility", "public"),
        "tags": kwargs.get("tags", ["test"]),
        "figures": kwargs.get("figures", []),
        "source_type": kwargs.get("source_type", "historical"),
    }


# ---------- Propose Tests ----------


class TestPropose:
    async def test_propose_creates_moment(self, writer_client):
        payload = _moment_payload("/test/propose/basic")
        resp = await writer_client.post("/api/v1/moments/propose", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "/test/propose/basic"
        assert data["status"] == "proposed"
        assert data["proposed_by"] == "test-writer"

    async def test_propose_sets_proposed_status(self, writer_client, admin_client):
        payload = _moment_payload("/test/propose/status-check")
        resp = await writer_client.post("/api/v1/moments/propose", json=payload)
        assert resp.status_code == 200

        # Fetch the moment and verify status
        get_resp = await admin_client.get("/api/v1/moments/test/propose/status-check")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data.get("status") == "proposed"
        assert data.get("proposed_by") == "test-writer"

    async def test_propose_duplicate_fails(self, writer_client):
        payload = _moment_payload("/test/propose/dup")
        resp1 = await writer_client.post("/api/v1/moments/propose", json=payload)
        assert resp1.status_code == 200

        resp2 = await writer_client.post("/api/v1/moments/propose", json=payload)
        assert resp2.status_code == 409

    async def test_propose_with_edges(self, writer_client, admin_client):
        # Create a target moment first
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/propose/target"),
        )

        # Propose with an edge
        payload = _moment_payload("/test/propose/with-edge")
        payload["edges"] = [
            {
                "source": "/test/propose/with-edge",
                "target": "/test/propose/target",
                "type": "causes",
                "weight": 0.9,
            }
        ]
        resp = await writer_client.post("/api/v1/moments/propose", json=payload)
        assert resp.status_code == 200

    async def test_propose_requires_auth(self, admin_client, admin_token):
        """Propose should require write auth when enabled."""
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Service-Key": "test-key"},
        ) as unauth:
            payload = _moment_payload("/test/propose/noauth")
            resp = await unauth.post("/api/v1/moments/propose", json=payload)
            assert resp.status_code == 401


# ---------- Challenge Tests ----------


class TestChallenge:
    async def test_challenge_moment(self, writer_client, admin_client):
        # First propose a moment
        original = _moment_payload("/test/challenge/original", name="Original Moment")
        await writer_client.post("/api/v1/moments/propose", json=original)

        # Challenge it
        competing = _moment_payload(
            "/test/challenge/competing",
            name="Competing Moment",
            one_liner="A better version",
        )
        resp = await writer_client.post(
            "/api/v1/moments/test/challenge/original/challenge",
            json={
                "competing_moment": competing,
                "reason": "This version has better sources",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["original_moment_id"] == "/test/challenge/original"
        assert data["original_status"] == "challenged"
        assert data["competing_moment_id"] == "/test/challenge/competing"
        assert data["competing_status"] == "proposed"

    async def test_challenge_updates_original_status(self, writer_client, admin_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/challenge/status-orig"),
        )

        competing = _moment_payload("/test/challenge/status-comp")
        await writer_client.post(
            "/api/v1/moments/test/challenge/status-orig/challenge",
            json={"competing_moment": competing, "reason": "test"},
        )

        # Original should now be 'challenged'
        get_resp = await admin_client.get("/api/v1/moments/test/challenge/status-orig")
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "challenged"

    async def test_challenge_records_challenged_by(self, writer_client, admin_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/challenge/cb-orig"),
        )

        competing = _moment_payload("/test/challenge/cb-comp")
        await writer_client.post(
            "/api/v1/moments/test/challenge/cb-orig/challenge",
            json={"competing_moment": competing, "reason": "test"},
        )

        get_resp = await admin_client.get("/api/v1/moments/test/challenge/cb-orig")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert "test-writer" in data.get("challenged_by", [])

    async def test_challenge_nonexistent_fails(self, writer_client):
        competing = _moment_payload("/test/challenge/ghost-comp")
        resp = await writer_client.post(
            "/api/v1/moments/test/challenge/nonexistent/challenge",
            json={"competing_moment": competing, "reason": "test"},
        )
        assert resp.status_code == 404

    async def test_challenge_alternative_fails(self, writer_client, admin_client):
        """Cannot challenge a moment that's already 'alternative'."""
        # Propose original + competing
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/challenge/alt-orig"),
        )
        competing = _moment_payload("/test/challenge/alt-comp")
        await writer_client.post(
            "/api/v1/moments/test/challenge/alt-orig/challenge",
            json={"competing_moment": competing, "reason": "test"},
        )

        # Reconcile: original wins, competing becomes alternative
        await admin_client.post(
            "/api/v1/moments/test/challenge/alt-orig/reconcile",
            json={
                "winner_id": "/test/challenge/alt-orig",
                "loser_id": "/test/challenge/alt-comp",
            },
        )

        # Try to challenge the alternative — should fail
        competing2 = _moment_payload("/test/challenge/alt-comp2")
        resp = await writer_client.post(
            "/api/v1/moments/test/challenge/alt-comp/challenge",
            json={"competing_moment": competing2, "reason": "test"},
        )
        assert resp.status_code == 400


# ---------- Verify Tests ----------


class TestVerify:
    async def test_verify_moment(self, writer_client, admin_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/verify/basic"),
        )

        resp = await admin_client.post("/api/v1/moments/test/verify/basic/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "verified"
        assert data["verified_by"] == "admin"

    async def test_verify_updates_status(self, writer_client, admin_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/verify/status"),
        )
        await admin_client.post("/api/v1/moments/test/verify/status/verify")

        get_resp = await admin_client.get("/api/v1/moments/test/verify/status")
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "verified"

    async def test_verify_already_verified_fails(self, writer_client, admin_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/verify/already"),
        )
        await admin_client.post("/api/v1/moments/test/verify/already/verify")

        resp = await admin_client.post("/api/v1/moments/test/verify/already/verify")
        assert resp.status_code == 400

    async def test_verify_nonexistent_fails(self, admin_client):
        resp = await admin_client.post("/api/v1/moments/test/verify/ghost/verify")
        assert resp.status_code == 404

    async def test_verify_requires_admin(self, writer_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/verify/admin-only"),
        )
        # Writer trying to verify — should be 403
        resp = await writer_client.post("/api/v1/moments/test/verify/admin-only/verify")
        assert resp.status_code == 403


# ---------- Reconcile Tests ----------


class TestReconcile:
    async def test_reconcile_moments(self, writer_client, admin_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/reconcile/orig"),
        )
        competing = _moment_payload("/test/reconcile/comp")
        await writer_client.post(
            "/api/v1/moments/test/reconcile/orig/challenge",
            json={"competing_moment": competing, "reason": "dispute"},
        )

        resp = await admin_client.post(
            "/api/v1/moments/test/reconcile/orig/reconcile",
            json={
                "winner_id": "/test/reconcile/orig",
                "loser_id": "/test/reconcile/comp",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["winner_status"] == "verified"
        assert data["loser_status"] == "alternative"

    async def test_reconcile_sets_correct_statuses(self, writer_client, admin_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/reconcile/s-orig"),
        )
        competing = _moment_payload("/test/reconcile/s-comp")
        await writer_client.post(
            "/api/v1/moments/test/reconcile/s-orig/challenge",
            json={"competing_moment": competing, "reason": "test"},
        )

        await admin_client.post(
            "/api/v1/moments/test/reconcile/s-comp/reconcile",
            json={
                "winner_id": "/test/reconcile/s-comp",
                "loser_id": "/test/reconcile/s-orig",
            },
        )

        # Winner should be verified
        winner = await admin_client.get("/api/v1/moments/test/reconcile/s-comp")
        assert winner.json()["status"] == "verified"

        # Loser should be alternative
        loser = await admin_client.get("/api/v1/moments/test/reconcile/s-orig")
        assert loser.json()["status"] == "alternative"

    async def test_reconcile_path_must_match(self, writer_client, admin_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/reconcile/m1"),
        )
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/reconcile/m2"),
        )

        resp = await admin_client.post(
            "/api/v1/moments/test/reconcile/unrelated/reconcile",
            json={
                "winner_id": "/test/reconcile/m1",
                "loser_id": "/test/reconcile/m2",
            },
        )
        assert resp.status_code == 400

    async def test_reconcile_requires_admin(self, writer_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/reconcile/admin-a"),
        )
        competing = _moment_payload("/test/reconcile/admin-b")
        await writer_client.post(
            "/api/v1/moments/test/reconcile/admin-a/challenge",
            json={"competing_moment": competing, "reason": "test"},
        )

        resp = await writer_client.post(
            "/api/v1/moments/test/reconcile/admin-a/reconcile",
            json={
                "winner_id": "/test/reconcile/admin-a",
                "loser_id": "/test/reconcile/admin-b",
            },
        )
        assert resp.status_code == 403


# ---------- Query Tests ----------


class TestQueryEnhancements:
    async def test_list_moments_filter_by_status(self, writer_client, admin_client):
        """GET /moments?status=proposed should filter by status."""
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/query/proposed-1", visibility="public"),
        )
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/query/proposed-2", visibility="public"),
        )
        # Verify one of them
        await admin_client.post("/api/v1/moments/test/query/proposed-2/verify")

        # Only proposed
        resp = await admin_client.get("/api/v1/moments?status=proposed")
        assert resp.status_code == 200
        data = resp.json()
        paths = [i["path"] for i in data["items"]]
        assert "/test/query/proposed-1" in paths
        assert "/test/query/proposed-2" not in paths

    async def test_get_challenges_endpoint(self, writer_client, admin_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/query/ch-orig"),
        )
        competing = _moment_payload("/test/query/ch-comp")
        await writer_client.post(
            "/api/v1/moments/test/query/ch-orig/challenge",
            json={"competing_moment": competing, "reason": "evidence"},
        )

        resp = await admin_client.get("/api/v1/moments/test/query/ch-orig/challenges")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["challenges"][0]["path"] == "/test/query/ch-comp"

    async def test_get_history_endpoint(self, writer_client, admin_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/query/hist"),
        )

        resp = await admin_client.get("/api/v1/moments/test/query/hist/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["moment_id"] == "/test/query/hist"
        assert data["status"] == "proposed"
        assert len(data["history"]) >= 1
        assert data["history"][0]["action"] == "proposed"

    async def test_history_shows_challenge(self, writer_client, admin_client):
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/query/hist-ch-orig"),
        )
        competing = _moment_payload("/test/query/hist-ch-comp")
        await writer_client.post(
            "/api/v1/moments/test/query/hist-ch-orig/challenge",
            json={"competing_moment": competing, "reason": "better data"},
        )

        resp = await admin_client.get("/api/v1/moments/test/query/hist-ch-orig/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "challenged"
        actions = [e["action"] for e in data["history"]]
        assert "proposed" in actions
        assert "challenged" in actions


# ---------- State Machine Tests ----------


class TestStateMachine:
    async def test_full_lifecycle_propose_verify(self, writer_client, admin_client):
        """proposed -> verified"""
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/sm/pv"),
        )
        # Status should be proposed
        node = await admin_client.get("/api/v1/moments/test/sm/pv")
        assert node.json()["status"] == "proposed"

        # Verify it
        await admin_client.post("/api/v1/moments/test/sm/pv/verify")
        node = await admin_client.get("/api/v1/moments/test/sm/pv")
        assert node.json()["status"] == "verified"

    async def test_full_lifecycle_propose_challenge_reconcile(
        self, writer_client, admin_client
    ):
        """proposed -> challenged -> reconciled (winner=verified, loser=alternative)"""
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/sm/pcr-orig"),
        )
        competing = _moment_payload("/test/sm/pcr-comp")
        await writer_client.post(
            "/api/v1/moments/test/sm/pcr-orig/challenge",
            json={"competing_moment": competing, "reason": "test"},
        )

        # Both exist; original is challenged
        orig = await admin_client.get("/api/v1/moments/test/sm/pcr-orig")
        assert orig.json()["status"] == "challenged"

        comp = await admin_client.get("/api/v1/moments/test/sm/pcr-comp")
        assert comp.json()["status"] == "proposed"

        # Reconcile: competing wins
        await admin_client.post(
            "/api/v1/moments/test/sm/pcr-comp/reconcile",
            json={
                "winner_id": "/test/sm/pcr-comp",
                "loser_id": "/test/sm/pcr-orig",
            },
        )

        orig = await admin_client.get("/api/v1/moments/test/sm/pcr-orig")
        assert orig.json()["status"] == "alternative"

        comp = await admin_client.get("/api/v1/moments/test/sm/pcr-comp")
        assert comp.json()["status"] == "verified"

    async def test_challenged_moment_can_be_verified(self, writer_client, admin_client):
        """A challenged moment can be directly verified (no reconcile needed)."""
        await writer_client.post(
            "/api/v1/moments/propose",
            json=_moment_payload("/test/sm/cv-orig"),
        )
        competing = _moment_payload("/test/sm/cv-comp")
        await writer_client.post(
            "/api/v1/moments/test/sm/cv-orig/challenge",
            json={"competing_moment": competing, "reason": "test"},
        )

        # Directly verify the challenged moment
        resp = await admin_client.post("/api/v1/moments/test/sm/cv-orig/verify")
        assert resp.status_code == 200

        node = await admin_client.get("/api/v1/moments/test/sm/cv-orig")
        assert node.json()["status"] == "verified"
