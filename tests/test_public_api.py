import pytest


@pytest.mark.asyncio
async def test_stats_no_auth(client):
    """Stats endpoint should work without auth."""
    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_nodes" in data
    assert "total_edges" in data
    assert "date_range" in data
    assert "avg_confidence" in data
    assert "last_updated" in data


@pytest.mark.asyncio
async def test_stats_with_auth(auth_client):
    """Stats endpoint should also work with auth."""
    resp = await auth_client.get("/api/v1/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_nodes"] == 5
    assert data["total_edges"] == 3


@pytest.mark.asyncio
async def test_list_moments_no_auth(client):
    """List moments should work without auth, returning public moments."""
    resp = await client.get("/api/v1/moments?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert data["limit"] == 5
    assert data["offset"] == 0
    assert len(data["items"]) <= 5


@pytest.mark.asyncio
async def test_list_moments_with_query(client):
    """List moments with q filter."""
    resp = await client.get("/api/v1/moments?q=caesar")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any("Caesar" in i["name"] for i in data["items"])


@pytest.mark.asyncio
async def test_list_moments_year_filter(client):
    """List moments with year range filter."""
    resp = await client.get("/api/v1/moments?year_from=1945&year_to=1970")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["items"]:
        assert 1945 <= item["year"] <= 1970


@pytest.mark.asyncio
async def test_get_moment_no_auth(client):
    """Get a public moment without auth."""
    resp = await client.get(
        "/api/v1/moments/-44/march/15/1030/italy/lazio/rome/assassination-of-julius-caesar"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Assassination of Julius Caesar"
    assert data["year"] == -44


@pytest.mark.asyncio
async def test_get_moment_with_auth(auth_client):
    """Get a moment with auth still works."""
    resp = await auth_client.get(
        "/api/v1/moments/-44/march/15/1030/italy/lazio/rome/assassination-of-julius-caesar"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Assassination of Julius Caesar"


@pytest.mark.asyncio
async def test_get_moment_not_found(client):
    """404 for non-existent moment."""
    resp = await client.get(
        "/api/v1/moments/9999/january/1/0000/x/x/x/nonexistent"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_moment_edges_included(client):
    """Moment detail should include edges."""
    resp = await client.get(
        "/api/v1/moments/1969/july/20/2056/united-states/florida/cape-canaveral/apollo-11-moon-landing"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "edges" in data


@pytest.mark.asyncio
async def test_auth_still_required_for_browse(client):
    """Browse should still require auth."""
    resp = await client.get("/api/v1/browse")
    assert resp.status_code in (403, 422)


@pytest.mark.asyncio
async def test_auth_still_required_for_search(client):
    """Search should still require auth."""
    resp = await client.get("/api/v1/search?q=test")
    assert resp.status_code in (403, 422)


@pytest.mark.asyncio
async def test_invalid_service_key_returns_403(client):
    """Providing a wrong service key returns 403."""
    resp = await client.get(
        "/api/v1/moments",
        headers={"X-Service-Key": "wrong-key"},
    )
    assert resp.status_code == 403
