"""MCP (Model Context Protocol) server for Clockchain.

Exposes the Clockchain temporal graph to MCP-compatible agents via
Streamable HTTP transport. Tools include propose_moment, challenge_moment,
query_moments, get_moment, and get_graph_stats.

Auth: Bearer tokens map to the multi-writer auth system. When multi-writer
auth is disabled, all requests are allowed (legacy single-writer mode).
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.core.config import get_settings
from app.core.graph import GraphManager
from app.core.multi_writer import get_agent_from_token

logger = logging.getLogger("clockchain.mcp")

# Module-level reference set during lifespan
_graph_manager: GraphManager | None = None
_db_pool: Any = None


@asynccontextmanager
async def mcp_lifespan(server: FastMCP):
    """MCP server lifespan — nothing to init, app state comes from FastAPI."""
    yield {}


mcp = FastMCP(
    name="Clockchain",
    instructions=(
        "Temporal causal graph for historical moments. Use propose_moment to "
        "submit new historical events, challenge_moment to dispute existing ones, "
        "query_moments to search the graph, get_moment for full details, and "
        "get_graph_stats for chain statistics."
    ),
    host="0.0.0.0",
    stateless_http=True,
    streamable_http_path="/",
)


async def _resolve_agent(token: str | None) -> dict:
    """Resolve a Bearer token to an agent identity.

    When multi-writer auth is disabled, returns a synthetic system agent.
    """
    settings = get_settings()
    auth_enabled = bool(settings.WRITER_TOKENS or settings.ADMIN_TOKEN)

    if not auth_enabled:
        return {
            "id": 0,
            "agent_name": "system",
            "permissions": "admin",
            "is_active": True,
        }

    if not token:
        raise ValueError("Bearer token required when multi-writer auth is enabled")

    if _db_pool is None:
        raise RuntimeError("Database pool not initialized")

    agent = await get_agent_from_token(_db_pool, token)
    if agent is None:
        raise ValueError("Invalid token")
    if not agent["is_active"]:
        raise ValueError("Token revoked")
    return agent


def _get_gm() -> GraphManager:
    """Get the graph manager, raising if not available."""
    if _graph_manager is None:
        raise RuntimeError("Graph manager not initialized — MCP server not ready")
    return _graph_manager


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def propose_moment(
    title: str,
    description: str,
    timestamp: str = "",
    location: str = "",
    sources: list[str] | None = None,
    causal_edges: list[dict] | None = None,
    year: int | None = None,
    month: str = "",
    month_num: int = 0,
    day: int = 0,
    country: str = "",
    region: str = "",
    city: str = "",
    slug: str = "",
    layer: int = 0,
    visibility: str = "public",
    tags: list[str] | None = None,
    figures: list[str] | None = None,
    agent_token: str = "",
) -> dict:
    """Submit a new historical moment with causal edges and sources.

    Args:
        title: Name/title of the moment
        description: One-liner description of the moment
        timestamp: Time string (e.g. "14:30")
        location: Free-text location (parsed into country/region/city if provided)
        sources: Evidence/source URLs supporting this moment
        causal_edges: List of edge dicts with keys: target, type, weight, description
        year: Year of the moment
        month: Month name (e.g. "january")
        month_num: Month number (1-12)
        day: Day of month
        country: Country name
        region: Region/state name
        city: City name
        slug: URL slug for the moment
        layer: Graph layer (0=seed, 1+=generated)
        visibility: "public" or "private"
        tags: Categorization tags
        figures: Historical figures involved
        agent_token: Bearer token for auth (required when multi-writer auth is enabled)
    """
    gm = _get_gm()
    agent = await _resolve_agent(agent_token or None)
    agent_name = agent.get("agent_name", "")

    if agent["permissions"] not in ("write", "admin"):
        return {"error": "Write permission required"}

    # Build the spatiotemporal path ID
    parts = []
    if year is not None:
        parts.append(str(year))
    if month:
        parts.append(month.lower())
    elif month_num:
        from app.core.url import NUM_TO_MONTH
        parts.append(NUM_TO_MONTH.get(month_num, str(month_num)))
    if day:
        parts.append(str(day))
    if country:
        parts.append(country.lower().replace(" ", "-"))
    if region:
        parts.append(region.lower().replace(" ", "-"))
    if city:
        parts.append(city.lower().replace(" ", "-"))
    s = slug or title.lower().replace(" ", "-")[:60]
    parts.append(s)
    moment_id = "/" + "/".join(parts) if parts else "/" + s

    # Check for existing moment
    existing = await gm.get_node(moment_id)
    if existing is not None:
        return {
            "error": f"Moment '{moment_id}' already exists. Use challenge_moment to dispute it.",
        }

    await gm.add_node(
        moment_id,
        name=title,
        one_liner=description,
        year=year,
        month=month,
        month_num=month_num,
        day=day,
        time=timestamp,
        country=country,
        region=region,
        city=city,
        slug=slug or s,
        layer=layer,
        visibility=visibility,
        tags=tags or [],
        figures=figures or [],
        source_type="historical",
        proposed_by=agent_name,
        status="proposed",
    )

    # Add causal edges
    edges_added = 0
    for edge in (causal_edges or []):
        target = edge.get("target", "")
        edge_type = edge.get("type", "thematic")
        if not target:
            continue
        try:
            await gm.add_edge(
                moment_id,
                target,
                edge_type,
                weight=edge.get("weight", 1.0),
                description=edge.get("description", ""),
                created_by=agent_name,
            )
            edges_added += 1
        except ValueError:
            pass  # skip invalid edge types

    return {
        "moment_id": moment_id,
        "status": "proposed",
        "proposed_by": agent_name,
        "edges_added": edges_added,
    }


@mcp.tool()
async def challenge_moment(
    moment_id: str,
    counter_description: str,
    counter_title: str = "",
    counter_sources: list[str] | None = None,
    counter_edges: list[dict] | None = None,
    year: int | None = None,
    month: str = "",
    month_num: int = 0,
    day: int = 0,
    country: str = "",
    region: str = "",
    city: str = "",
    agent_token: str = "",
) -> dict:
    """Dispute an existing moment with counter-evidence.

    Args:
        moment_id: Path ID of the moment to challenge (e.g. "/1969/july/20/us/moon-landing")
        counter_description: Description of the counter-claim
        counter_title: Title for the competing moment (auto-generated if empty)
        counter_sources: Evidence URLs supporting the challenge
        counter_edges: Causal edges for the competing moment
        year: Year override for competing moment
        month: Month override
        month_num: Month number override
        day: Day override
        country: Country override
        region: Region override
        city: City override
        agent_token: Bearer token for auth
    """
    gm = _get_gm()
    agent = await _resolve_agent(agent_token or None)
    agent_name = agent.get("agent_name", "")

    if agent["permissions"] not in ("write", "admin"):
        return {"error": "Write permission required"}

    # Normalize moment_id
    full_path = "/" + moment_id.strip("/")

    # Verify original exists
    original = await gm.get_node(full_path)
    if original is None:
        return {"error": f"Moment '{full_path}' not found"}

    original_status = original.get("status", "proposed")
    if original_status == "alternative":
        return {"error": "Cannot challenge an alternative moment"}

    # Build competing moment ID
    competing_title = counter_title or f"Challenge: {original.get('name', moment_id)}"
    competing_slug = competing_title.lower().replace(" ", "-").replace(":", "")[:60]
    competing_id = full_path.rsplit("/", 1)[0] + "/" + competing_slug

    # Use original's metadata as defaults for competing moment
    await gm.add_node(
        competing_id,
        name=competing_title,
        one_liner=counter_description,
        year=year or original.get("year"),
        month=month or original.get("month", ""),
        month_num=month_num or original.get("month_num", 0),
        day=day or original.get("day", 0),
        country=country or original.get("country", ""),
        region=region or original.get("region", ""),
        city=city or original.get("city", ""),
        slug=competing_slug,
        layer=original.get("layer", 0),
        visibility=original.get("visibility", "public"),
        proposed_by=agent_name,
        status="proposed",
    )

    # Add counter edges
    for edge in (counter_edges or []):
        target = edge.get("target", "")
        edge_type = edge.get("type", "thematic")
        if not target:
            continue
        try:
            await gm.add_edge(
                competing_id,
                target,
                edge_type,
                weight=edge.get("weight", 1.0),
                description=edge.get("description", ""),
                created_by=agent_name,
            )
        except ValueError:
            pass

    # Create 'challenges' edge: competing -> original
    await gm.add_edge(
        competing_id,
        full_path,
        "challenges",
        weight=1.0,
        description=counter_description,
        created_by=agent_name,
    )

    # Update original to 'challenged'
    challenged_by = list(original.get("challenged_by") or [])
    if agent_name and agent_name not in challenged_by:
        challenged_by.append(agent_name)

    await gm.update_node(
        full_path,
        status="challenged",
        challenged_by=challenged_by,
    )

    return {
        "challenge_moment_id": competing_id,
        "original_moment_id": full_path,
        "original_status": "challenged",
        "challenged_by": agent_name,
    }


@mcp.tool()
async def query_moments(
    query: str,
    time_range_start: int | None = None,
    time_range_end: int | None = None,
    status_filter: str | None = None,
    limit: int = 20,
) -> dict:
    """Search the temporal graph for moments matching a query.

    Args:
        query: Text search query (matches name, description, tags, figures)
        time_range_start: Start year filter (inclusive)
        time_range_end: End year filter (inclusive)
        status_filter: Filter by status: "proposed", "challenged", "verified", "alternative"
        limit: Maximum results to return (default 20, max 100)
    """
    gm = _get_gm()
    limit = min(limit, 100)

    # Use the list_moments method for filtering
    moments, total = await gm.list_moments(
        limit=limit,
        offset=0,
        year_from=time_range_start,
        year_to=time_range_end,
        query=query if query else None,
        status=status_filter,
    )

    results = []
    for m in moments:
        path = m.get("path") or m.get("id", "")
        neighbors = await gm.get_neighbors(path)
        results.append({
            "path": path,
            "name": m.get("name", ""),
            "one_liner": m.get("one_liner", ""),
            "year": m.get("year"),
            "status": m.get("status", "proposed"),
            "confidence": m.get("confidence"),
            "causal_neighbors": [
                {"path": n["path"], "name": n["name"], "edge_type": n["edge_type"]}
                for n in neighbors[:5]  # limit neighbor count for readability
            ],
        })

    return {
        "query": query,
        "total": total,
        "count": len(results),
        "moments": results,
    }


@mcp.tool()
async def get_moment(moment_id: str) -> dict:
    """Get a specific moment with full detail including edges, challenges, and status history.

    Args:
        moment_id: Path ID of the moment (e.g. "/1969/july/20/us/moon-landing")
    """
    gm = _get_gm()
    full_path = "/" + moment_id.strip("/")

    node = await gm.get_node(full_path)
    if node is None:
        return {"error": f"Moment '{full_path}' not found"}

    # Get edges (neighbors)
    neighbors = await gm.get_neighbors(full_path)

    # Get challenges
    challenges = await gm.get_challenges(full_path)

    # Get history
    history = await gm.get_moment_history(full_path)

    return {
        "moment": {
            "path": node.get("path", full_path),
            "name": node.get("name", ""),
            "one_liner": node.get("one_liner", ""),
            "year": node.get("year"),
            "month": node.get("month", ""),
            "day": node.get("day", 0),
            "time": node.get("time", ""),
            "country": node.get("country", ""),
            "region": node.get("region", ""),
            "city": node.get("city", ""),
            "status": node.get("status", "proposed"),
            "proposed_by": node.get("proposed_by", ""),
            "challenged_by": node.get("challenged_by", []),
            "confidence": node.get("confidence"),
            "tags": node.get("tags", []),
            "figures": node.get("figures", []),
            "visibility": node.get("visibility", "private"),
            "created_at": node.get("created_at", ""),
        },
        "causal_edges": [
            {
                "path": n["path"],
                "name": n["name"],
                "edge_type": n["edge_type"],
                "weight": n["weight"],
                "description": n.get("description", ""),
            }
            for n in neighbors
        ],
        "challenges": [
            {
                "path": c.get("path", ""),
                "name": c.get("name", ""),
                "status": c.get("status", "proposed"),
                "proposed_by": c.get("proposed_by", ""),
            }
            for c in challenges
        ],
        "status_history": history,
    }


@mcp.tool()
async def get_graph_stats() -> dict:
    """Get chain statistics: total moments, counts by status, edge types, and recent activity."""
    gm = _get_gm()
    stats = await gm.enhanced_stats()

    # Add status breakdown
    status_counts = {}
    for status in ("proposed", "challenged", "verified", "alternative"):
        moments, count = await gm.list_moments_by_status(status, limit=0, offset=0)
        status_counts[status] = count

    return {
        "total_moments": stats.get("total_nodes", 0),
        "total_edges": stats.get("total_edges", 0),
        "status_counts": status_counts,
        "layer_counts": stats.get("layer_counts", {}),
        "edge_type_counts": stats.get("edge_type_counts", {}),
        "source_type_counts": stats.get("source_type_counts", {}),
        "date_range": stats.get("date_range", {}),
        "avg_confidence": stats.get("avg_confidence"),
        "last_updated": stats.get("last_updated"),
        "nodes_with_images": stats.get("nodes_with_images", 0),
    }


# ---------------------------------------------------------------------------
# MCP Resources (optional — expose moments as browsable resources)
# ---------------------------------------------------------------------------


@mcp.resource("clockchain://stats")
async def stats_resource() -> str:
    """Current chain statistics."""
    import json
    stats = await get_graph_stats()
    return json.dumps(stats, indent=2, default=str)


@mcp.resource("clockchain://moments/recent")
async def recent_moments_resource() -> str:
    """Recently added moments."""
    import json
    gm = _get_gm()
    moments, _ = await gm.list_moments(limit=10, offset=0, sort="recent")
    return json.dumps(
        [{"path": m.get("path", m.get("id")), "name": m.get("name", "")} for m in moments],
        indent=2,
    )


def get_mcp_app():
    """Return the Starlette ASGI app for the MCP server.

    Mount this on the FastAPI app:
        app.mount("/mcp", get_mcp_app())
    """
    return mcp.streamable_http_app()


def init_mcp(graph_manager: GraphManager, pool) -> None:
    """Initialize the MCP server with shared app state.

    Called from the FastAPI lifespan after the graph manager is ready.
    """
    global _graph_manager, _db_pool
    _graph_manager = graph_manager
    _db_pool = pool
    logger.info("MCP server initialized with graph manager")
