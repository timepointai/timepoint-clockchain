import pytest


@pytest.mark.asyncio
async def test_browse_root(auth_client):
    resp = await auth_client.get("/api/v1/browse")
    assert resp.status_code == 200
    data = resp.json()
    segments = [i["segment"] for i in data["items"]]
    assert "-44" in segments
    assert "1969" in segments


@pytest.mark.asyncio
async def test_browse_year(auth_client):
    resp = await auth_client.get("/api/v1/browse/1969")
    assert resp.status_code == 200
    data = resp.json()
    segments = [i["segment"] for i in data["items"]]
    assert "july" in segments
    assert "november" in segments


@pytest.mark.asyncio
async def test_get_moment_caesar(auth_client):
    resp = await auth_client.get(
        "/api/v1/moments/-44/march/15/1030/italy/lazio/rome/assassination-of-julius-caesar"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Assassination of Julius Caesar"
    assert data["year"] == -44


@pytest.mark.asyncio
async def test_get_moment_not_found(auth_client):
    resp = await auth_client.get(
        "/api/v1/moments/9999/january/1/0000/x/x/x/nonexistent"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_403_without_service_key(client):
    resp = await client.get("/api/v1/browse")
    assert resp.status_code in (403, 422)


@pytest.mark.asyncio
async def test_search_caesar(auth_client):
    resp = await auth_client.get("/api/v1/search?q=caesar")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1
    assert "Caesar" in results[0]["name"]


@pytest.mark.asyncio
async def test_search_trinity(auth_client):
    resp = await auth_client.get("/api/v1/search?q=trinity")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_random(auth_client):
    resp = await auth_client.get("/api/v1/random")
    assert resp.status_code == 200
    data = resp.json()
    assert "name" in data
    assert data["visibility"] == "public"


@pytest.mark.asyncio
async def test_today(auth_client):
    resp = await auth_client.get("/api/v1/today")
    assert resp.status_code == 200
    data = resp.json()
    assert "month" in data
    assert "day" in data
    assert "events" in data


@pytest.mark.asyncio
async def test_stats(auth_client):
    resp = await auth_client.get("/api/v1/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_nodes"] == 5
    assert data["total_edges"] == 3


@pytest.mark.asyncio
async def test_neighbors(auth_client):
    resp = await auth_client.get(
        "/api/v1/graph/neighbors/1969/july/20/2056/united-states/florida/cape-canaveral/apollo-11-moon-landing"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
