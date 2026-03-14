"""Tests for the MCP server endpoint.

Verifies that the MCP server starts, responds to initialization,
and lists the expected tools.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
async def _init_and_truncate():
    """Override the conftest DB fixture — MCP tests use mocks, no DB needed."""
    yield


def _make_mock_gm():
    """Create a mock GraphManager for testing."""
    gm = AsyncMock()
    gm.pool = MagicMock()
    gm.get_node = AsyncMock(return_value=None)
    gm.add_node = AsyncMock()
    gm.add_edge = AsyncMock()
    gm.update_node = AsyncMock()
    gm.get_neighbors = AsyncMock(return_value=[])
    gm.get_challenges = AsyncMock(return_value=[])
    gm.get_moment_history = AsyncMock(return_value=[])
    gm.search = AsyncMock(return_value=[])
    gm.list_moments = AsyncMock(return_value=([], 0))
    gm.list_moments_by_status = AsyncMock(return_value=([], 0))
    gm.enhanced_stats = AsyncMock(return_value={
        "total_nodes": 5,
        "total_edges": 3,
        "layer_counts": {"0": 2, "1": 3},
        "edge_type_counts": {"causes": 2, "thematic": 1},
        "source_type_counts": {"historical": 5},
        "nodes_with_images": 1,
        "date_range": {"min_year": 1776, "max_year": 2024},
        "avg_confidence": 0.85,
        "last_updated": "2026-03-14T12:00:00",
        "schema_version_counts": {"0.2": 5},
        "text_model_counts": {},
    })
    return gm


def _make_fresh_mcp_app():
    """Create a fresh MCP app instance each time (session manager is single-use)."""
    from app.mcp_server import init_mcp, mcp

    gm = _make_mock_gm()
    init_mcp(gm, gm.pool)

    # Create a fresh session manager each time
    mcp._session_manager = None
    return mcp.streamable_http_app()


def test_mcp_app_creates():
    """MCP app should be a valid Starlette application."""
    app = _make_fresh_mcp_app()
    assert app is not None


def test_mcp_endpoint_accepts_post():
    """MCP endpoint should accept POST requests with JSON-RPC."""
    app = _make_fresh_mcp_app()

    with TestClient(app) as client:
        response = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "test-client",
                        "version": "1.0.0",
                    },
                },
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            data = response.json()
            assert data.get("jsonrpc") == "2.0"
            assert data.get("id") == 1
            result = data.get("result", {})
            assert "serverInfo" in result
            assert result["serverInfo"]["name"] == "Clockchain"
        elif "text/event-stream" in content_type:
            events = _parse_sse(response.text)
            assert len(events) > 0
            for event in events:
                if "result" in event:
                    data = json.loads(event)
                    assert data.get("result", {}).get("serverInfo", {}).get("name") == "Clockchain"
                    break


def test_mcp_lists_tools():
    """MCP server should list the expected tools."""
    app = _make_fresh_mcp_app()

    with TestClient(app) as client:
        # Initialize
        init_resp = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        assert init_resp.status_code == 200

        session_id = init_resp.headers.get("mcp-session-id", "")

        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if session_id:
            headers["mcp-session-id"] = session_id

        # Send initialized notification
        notif_resp = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
            headers=headers,
        )
        assert notif_resp.status_code in (200, 202)

        # List tools
        tools_resp = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            },
            headers=headers,
        )
        assert tools_resp.status_code == 200

        content_type = tools_resp.headers.get("content-type", "")

        tools = []
        if "application/json" in content_type:
            data = tools_resp.json()
            tools = data.get("result", {}).get("tools", [])
        elif "text/event-stream" in content_type:
            for event in _parse_sse(tools_resp.text):
                try:
                    data = json.loads(event)
                    if "result" in data:
                        tools = data["result"].get("tools", [])
                        break
                except json.JSONDecodeError:
                    continue

        tool_names = {t["name"] for t in tools}
        expected_tools = {
            "propose_moment",
            "challenge_moment",
            "query_moments",
            "get_moment",
            "get_graph_stats",
        }
        assert expected_tools.issubset(tool_names), (
            f"Missing tools: {expected_tools - tool_names}. Got: {tool_names}"
        )


def test_mcp_tool_registration():
    """Verify all 5 MCP tools are registered on the server."""
    from app.mcp_server import mcp

    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "propose_moment" in tool_names
    assert "challenge_moment" in tool_names
    assert "query_moments" in tool_names
    assert "get_moment" in tool_names
    assert "get_graph_stats" in tool_names


def _parse_sse(text: str) -> list[str]:
    """Parse SSE event stream into list of data payloads."""
    events = []
    current_data = []
    for line in text.split("\n"):
        if line.startswith("data:"):
            current_data.append(line[5:].strip())
        elif line == "" and current_data:
            events.append("\n".join(current_data))
            current_data = []
    if current_data:
        events.append("\n".join(current_data))
    return events
