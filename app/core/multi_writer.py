"""Multi-writer authentication for Clockchain.

Token-based write access control that allows multiple agents to propose
and challenge moments. Read operations remain public/unauthenticated.

When WRITER_TOKENS or ADMIN_TOKEN are not set, auth is disabled and the
system operates in legacy single-writer mode.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import Depends, Header, HTTPException, Request

from app.core.config import get_settings

logger = logging.getLogger("clockchain.multi_writer")


def hash_token(token: str) -> str:
    """SHA-256 hash a token for safe storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _auth_enabled() -> bool:
    """Check if multi-writer auth is enabled."""
    settings = get_settings()
    return bool(settings.WRITER_TOKENS or settings.ADMIN_TOKEN)


async def bootstrap_tokens(pool: asyncpg.Pool) -> None:
    """Bootstrap agent tokens from environment variables.

    WRITER_TOKENS is a comma-separated list of token:agent_name pairs.
    Example: WRITER_TOKENS="tok1:agent-alpha,tok2:agent-beta"

    If just a token is provided (no colon), agent_name defaults to "agent-N".

    ADMIN_TOKEN creates a single admin agent.
    """
    settings = get_settings()

    async with pool.acquire() as conn:
        # Bootstrap admin token
        if settings.ADMIN_TOKEN:
            token_hash = hash_token(settings.ADMIN_TOKEN)
            existing = await conn.fetchval(
                "SELECT id FROM agent_tokens WHERE token_hash = $1", token_hash
            )
            if not existing:
                await conn.execute(
                    """
                    INSERT INTO agent_tokens (token_hash, agent_name, permissions, is_active)
                    VALUES ($1, $2, $3, TRUE)
                    ON CONFLICT (token_hash) DO NOTHING
                    """,
                    token_hash,
                    "admin",
                    "admin",
                )
                logger.info("Bootstrapped admin token")

        # Bootstrap writer tokens
        if settings.WRITER_TOKENS:
            pairs = [t.strip() for t in settings.WRITER_TOKENS.split(",") if t.strip()]
            for i, pair in enumerate(pairs):
                if ":" in pair:
                    token, agent_name = pair.split(":", 1)
                else:
                    token = pair
                    agent_name = f"agent-{i}"

                token_hash = hash_token(token)
                existing = await conn.fetchval(
                    "SELECT id FROM agent_tokens WHERE token_hash = $1", token_hash
                )
                if not existing:
                    await conn.execute(
                        """
                        INSERT INTO agent_tokens (token_hash, agent_name, permissions, is_active)
                        VALUES ($1, $2, $3, TRUE)
                        ON CONFLICT (token_hash) DO NOTHING
                        """,
                        token_hash,
                        agent_name,
                        "write",
                    )
                    logger.info("Bootstrapped writer token for %s", agent_name)


async def get_agent_from_token(pool: asyncpg.Pool, token: str) -> Optional[dict]:
    """Look up an agent by their Bearer token. Returns agent record or None."""
    token_hash = hash_token(token)
    row = await pool.fetchrow(
        """
        SELECT id, agent_name, permissions, is_active, created_at
        FROM agent_tokens
        WHERE token_hash = $1
        """,
        token_hash,
    )
    if row is None:
        return None
    return dict(row)


async def _get_pool(request: Request) -> asyncpg.Pool:
    """Extract the database pool from the app state."""
    gm = getattr(request.app.state, "graph_manager", None)
    if gm is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    return gm.pool


async def require_write_auth(
    request: Request,
    authorization: str | None = Header(None),
) -> dict:
    """Dependency: require a valid write token (Bearer auth).

    If multi-writer auth is disabled (no WRITER_TOKENS or ADMIN_TOKEN),
    returns a synthetic agent identity for backward compatibility.
    """
    if not _auth_enabled():
        return {
            "id": 0,
            "agent_name": "system",
            "permissions": "admin",
            "is_active": True,
        }

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:]  # Strip "Bearer "
    pool = await _get_pool(request)
    agent = await get_agent_from_token(pool, token)

    if agent is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not agent["is_active"]:
        raise HTTPException(status_code=403, detail="Token revoked")
    if agent["permissions"] not in ("write", "admin"):
        raise HTTPException(status_code=403, detail="Write permission required")

    return agent


async def require_admin_auth(
    request: Request,
    authorization: str | None = Header(None),
) -> dict:
    """Dependency: require admin-level token."""
    if not _auth_enabled():
        return {
            "id": 0,
            "agent_name": "system",
            "permissions": "admin",
            "is_active": True,
        }

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:]
    pool = await _get_pool(request)
    agent = await get_agent_from_token(pool, token)

    if agent is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not agent["is_active"]:
        raise HTTPException(status_code=403, detail="Token revoked")
    if agent["permissions"] != "admin":
        raise HTTPException(status_code=403, detail="Admin permission required")

    return agent


def generate_token() -> str:
    """Generate a cryptographically secure token."""
    return secrets.token_urlsafe(32)
