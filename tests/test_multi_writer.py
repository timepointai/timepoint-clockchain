"""Tests for multi-writer auth and agent identity tracking."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.multi_writer import hash_token, generate_token


# ---------- Unit tests for token utilities ----------


def test_hash_token_deterministic():
    assert hash_token("abc") == hash_token("abc")


def test_hash_token_different_inputs():
    assert hash_token("abc") != hash_token("xyz")


def test_generate_token_unique():
    t1 = generate_token()
    t2 = generate_token()
    assert t1 != t2
    assert len(t1) > 20


# ---------- Integration tests ----------


@pytest.fixture(autouse=True)
async def _init_agent_tokens_table():
    """Ensure agent_tokens table exists and is truncated."""
    import asyncpg
    from app.core.db import AGENT_TOKENS_DDL

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
    return "test-admin-token-secret"


@pytest.fixture()
def writer_token():
    return "test-writer-token-secret"


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
async def noauth_client():
    """Client with no multi-writer auth configured (legacy mode)."""
    os.environ.pop("ADMIN_TOKEN", None)
    os.environ.pop("WRITER_TOKENS", None)

    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import app

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Service-Key": "test-key"},
        ) as ac:
            yield ac

    get_settings.cache_clear()


class TestAgentRegistration:
    async def test_register_agent(self, admin_client, admin_token):
        resp = await admin_client.post(
            "/api/v1/agents/register",
            json={"agent_name": "test-agent", "permissions": "write"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "test-agent"
        assert data["permissions"] == "write"
        assert "token" in data
        assert data["agent_id"] > 0

    async def test_register_duplicate_agent(self, admin_client):
        await admin_client.post(
            "/api/v1/agents/register",
            json={"agent_name": "dup-agent"},
        )
        resp = await admin_client.post(
            "/api/v1/agents/register",
            json={"agent_name": "dup-agent"},
        )
        assert resp.status_code == 409

    async def test_list_agents(self, admin_client):
        await admin_client.post(
            "/api/v1/agents/register",
            json={"agent_name": "list-agent"},
        )
        resp = await admin_client.get("/api/v1/agents")
        assert resp.status_code == 200
        data = resp.json()
        # admin token bootstrapped + registered agent
        assert data["total"] >= 2
        names = [a["agent_name"] for a in data["agents"]]
        assert "list-agent" in names
        assert "admin" in names

    async def test_revoke_agent(self, admin_client):
        reg = await admin_client.post(
            "/api/v1/agents/register",
            json={"agent_name": "revoke-me"},
        )
        agent_id = reg.json()["agent_id"]
        resp = await admin_client.delete(f"/api/v1/agents/{agent_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

    async def test_revoke_nonexistent(self, admin_client):
        resp = await admin_client.delete("/api/v1/agents/99999")
        assert resp.status_code == 404


class TestWriteAuth:
    async def test_write_requires_token_when_enabled(self, admin_client, admin_token):
        """When auth is enabled, unauthenticated writes should fail."""
        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Service-Key": "test-key"},
        ) as unauth:
            resp = await unauth.post(
                "/api/v1/index",
                json={"path": "/2000/january/1/1200/us/ca/sf/test", "metadata": {}},
            )
            assert resp.status_code == 401

    async def test_write_with_valid_token(self, admin_client):
        # Register a writer
        reg = await admin_client.post(
            "/api/v1/agents/register",
            json={"agent_name": "writer-test"},
        )
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
        ) as writer:
            resp = await writer.post(
                "/api/v1/index",
                json={"path": "/2000/january/1/1200/us/ca/sf/test-moment", "metadata": {"name": "Test Moment"}},
            )
            assert resp.status_code == 200

    async def test_write_with_revoked_token(self, admin_client):
        reg = await admin_client.post(
            "/api/v1/agents/register",
            json={"agent_name": "revoked-writer"},
        )
        token = reg.json()["token"]
        agent_id = reg.json()["agent_id"]

        # Revoke the token
        await admin_client.delete(f"/api/v1/agents/{agent_id}")

        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={
                "X-Service-Key": "test-key",
                "Authorization": f"Bearer {token}",
            },
        ) as writer:
            resp = await writer.post(
                "/api/v1/index",
                json={"path": "/2000/january/1/1200/us/ca/sf/test", "metadata": {}},
            )
            assert resp.status_code == 403

    async def test_admin_endpoints_reject_writer_token(self, admin_client):
        reg = await admin_client.post(
            "/api/v1/agents/register",
            json={"agent_name": "just-a-writer"},
        )
        token = reg.json()["token"]

        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={
                "X-Service-Key": "test-key",
                "Authorization": f"Bearer {token}",
            },
        ) as writer:
            resp = await writer.get("/api/v1/agents")
            assert resp.status_code == 403


class TestLegacyMode:
    async def test_write_works_without_auth_config(self, noauth_client):
        """When no WRITER_TOKENS or ADMIN_TOKEN, auth is disabled (backward compat)."""
        resp = await noauth_client.post(
            "/api/v1/index",
            json={"path": "/2000/january/1/1200/us/ca/sf/legacy-test", "metadata": {"name": "Legacy"}},
        )
        assert resp.status_code == 200


class TestBootstrapTokens:
    async def test_bootstrap_writer_tokens(self):
        os.environ["WRITER_TOKENS"] = "tok1:agent-one,tok2:agent-two"
        os.environ["ADMIN_TOKEN"] = ""

        from app.core.config import get_settings
        get_settings.cache_clear()

        import asyncpg
        from app.core.multi_writer import bootstrap_tokens, get_agent_from_token

        url = os.environ["DATABASE_URL"]
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
        try:
            await bootstrap_tokens(pool)
            agent1 = await get_agent_from_token(pool, "tok1")
            agent2 = await get_agent_from_token(pool, "tok2")

            assert agent1 is not None
            assert agent1["agent_name"] == "agent-one"
            assert agent1["permissions"] == "write"

            assert agent2 is not None
            assert agent2["agent_name"] == "agent-two"
        finally:
            await pool.close()
            os.environ.pop("WRITER_TOKENS", None)
            get_settings.cache_clear()

    async def test_bootstrap_admin_token(self):
        os.environ["ADMIN_TOKEN"] = "admin-secret-123"
        os.environ["WRITER_TOKENS"] = ""

        from app.core.config import get_settings
        get_settings.cache_clear()

        import asyncpg
        from app.core.multi_writer import bootstrap_tokens, get_agent_from_token

        url = os.environ["DATABASE_URL"]
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
        try:
            await bootstrap_tokens(pool)
            agent = await get_agent_from_token(pool, "admin-secret-123")

            assert agent is not None
            assert agent["agent_name"] == "admin"
            assert agent["permissions"] == "admin"
        finally:
            await pool.close()
            os.environ.pop("ADMIN_TOKEN", None)
            get_settings.cache_clear()


class TestAgentIdentityOnMoments:
    async def test_proposed_by_set_on_index(self, admin_client):
        """proposed_by should be auto-set from agent identity."""
        resp = await admin_client.post(
            "/api/v1/index",
            json={
                "path": "/1945/august/6/1200/japan/hiroshima/hiroshima/atomic-bombing-test",
                "metadata": {"name": "Atomic Bombing Test", "year": 1945},
            },
        )
        assert resp.status_code == 200

        # Fetch the moment and verify proposed_by
        get_resp = await admin_client.get(
            "/api/v1/moments/1945/august/6/1200/japan/hiroshima/hiroshima/atomic-bombing-test"
        )
        if get_resp.status_code == 200:
            data = get_resp.json()
            assert data.get("proposed_by") == "admin"

    async def test_read_endpoints_remain_public(self, admin_client):
        """GET endpoints should not require Bearer auth."""
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as public:
            resp = await public.get("/api/v1/stats")
            assert resp.status_code == 200

            resp = await public.get("/health")
            assert resp.status_code == 200
