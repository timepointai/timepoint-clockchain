import pytest


@pytest.mark.asyncio
async def test_cors_headers_present(client):
    """CORS headers should be present for cross-origin requests."""
    resp = await client.get(
        "/api/v1/stats",
        headers={"Origin": "https://example.com"},
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers


@pytest.mark.asyncio
async def test_cors_preflight(client):
    """OPTIONS preflight should return CORS headers."""
    resp = await client.options(
        "/api/v1/stats",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers


@pytest.mark.asyncio
async def test_rate_limiter_configured():
    """Rate limiter should be properly attached to the app."""
    from app.main import app
    from app.core.rate_limit import limiter

    assert app.state.limiter is limiter


@pytest.mark.asyncio
async def test_rate_limit_key_function():
    """Rate limit key function should hash service key or fall back to IP."""
    from app.core.rate_limit import _get_key
    from starlette.testclient import TestClient
    from starlette.requests import Request

    # Build a minimal request scope
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)
    key = _get_key(request)
    assert key == "127.0.0.1"

    # With service key
    scope_with_key = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-service-key", b"test-key")],
        "query_string": b"",
    }
    request_with_key = Request(scope_with_key)
    key_with_auth = _get_key(request_with_key)
    assert key_with_auth.startswith("auth:")
