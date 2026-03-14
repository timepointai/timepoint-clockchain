"""Agent registration and management endpoints.

Admin-only endpoints for managing multi-writer agent tokens.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.config import get_settings
from app.core.multi_writer import (
    generate_token,
    hash_token,
    require_admin_auth,
)
from app.core.rate_limit import limiter
from app.models.schemas import (
    AgentRegisterRequest,
    AgentRegisterResponse,
    AgentListResponse,
    AgentInfo,
)

router = APIRouter(tags=["Agents"])


async def _get_pool(request: Request):
    gm = getattr(request.app.state, "graph_manager", None)
    if gm is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    return gm.pool


@router.post("/agents/register", response_model=AgentRegisterResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_WRITE)
async def register_agent(
    request: Request,
    body: AgentRegisterRequest,
    admin: dict = Depends(require_admin_auth),
):
    """Register a new agent and return its token. Admin-only."""
    pool = await _get_pool(request)

    # Check for duplicate agent name
    existing = await pool.fetchval(
        "SELECT id FROM agent_tokens WHERE agent_name = $1 AND is_active = TRUE",
        body.agent_name,
    )
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Agent '{body.agent_name}' already exists"
        )

    token = generate_token()
    token_hash = hash_token(token)
    permissions = body.permissions or "write"

    if permissions not in ("read", "write", "admin"):
        raise HTTPException(status_code=400, detail="Invalid permissions value")

    agent_id = await pool.fetchval(
        """
        INSERT INTO agent_tokens (token_hash, agent_name, permissions, is_active)
        VALUES ($1, $2, $3, TRUE)
        RETURNING id
        """,
        token_hash,
        body.agent_name,
        permissions,
    )

    return AgentRegisterResponse(
        agent_id=agent_id,
        agent_name=body.agent_name,
        token=token,
        permissions=permissions,
    )


@router.get("/agents", response_model=AgentListResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_READ)
async def list_agents(
    request: Request,
    admin: dict = Depends(require_admin_auth),
):
    """List all registered agents. Admin-only."""
    pool = await _get_pool(request)

    rows = await pool.fetch(
        """
        SELECT id, agent_name, permissions, is_active, created_at
        FROM agent_tokens
        ORDER BY created_at DESC
        """
    )

    agents = [
        AgentInfo(
            agent_id=row["id"],
            agent_name=row["agent_name"],
            permissions=row["permissions"],
            is_active=row["is_active"],
            created_at=row["created_at"].isoformat() if row["created_at"] else "",
        )
        for row in rows
    ]

    return AgentListResponse(agents=agents, total=len(agents))


@router.delete("/agents/{agent_id}")
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_WRITE)
async def revoke_agent(
    request: Request,
    agent_id: int,
    admin: dict = Depends(require_admin_auth),
):
    """Revoke an agent's access. Admin-only."""
    pool = await _get_pool(request)

    result = await pool.execute(
        "UPDATE agent_tokens SET is_active = FALSE WHERE id = $1",
        agent_id,
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Agent not found")

    return {"agent_id": agent_id, "status": "revoked"}
