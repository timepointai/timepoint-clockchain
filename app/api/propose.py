"""Propose/challenge protocol endpoints.

Multi-agent debate protocol for historical moments. Agents propose moments,
challenge existing ones, and admins verify or reconcile disputes.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.auth import verify_service_key
from app.core.config import get_settings
from app.core.graph import GraphManager, get_graph_manager
from app.core.multi_writer import require_admin_auth, require_write_auth
from app.core.rate_limit import limiter
from app.models.schemas import (
    ChallengeRequest,
    ChallengeResponse,
    MomentHistoryEntry,
    MomentHistoryResponse,
    MomentResponse,
    ProposeRequest,
    ProposeResponse,
    ReconcileRequest,
    ReconcileResponse,
    VALID_MOMENT_STATUSES,
    VerifyResponse,
)

router = APIRouter(tags=["Propose/Challenge"], dependencies=[Depends(verify_service_key)])


@router.post("/moments/propose", response_model=ProposeResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_WRITE)
async def propose_moment(
    request: Request,
    body: ProposeRequest,
    gm: GraphManager = Depends(get_graph_manager),
    agent: dict = Depends(require_write_auth),
):
    """Propose a new moment. Sets status to 'proposed' and records proposer."""
    agent_name = agent.get("agent_name", "")

    # Check if moment already exists
    existing = await gm.get_node(body.id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Moment '{body.id}' already exists. Use challenge to dispute it.",
        )

    await gm.add_node(
        body.id,
        name=body.name,
        one_liner=body.one_liner,
        year=body.year,
        month=body.month,
        month_num=body.month_num,
        day=body.day,
        time=body.time,
        country=body.country,
        region=body.region,
        city=body.city,
        slug=body.slug,
        layer=body.layer,
        visibility=body.visibility,
        tags=body.tags,
        figures=body.figures,
        source_type=body.source_type,
        confidence=body.confidence,
        source_run_id=body.source_run_id,
        schema_version=body.schema_version,
        text_model=body.text_model,
        image_model=body.image_model,
        model_provider=body.model_provider,
        model_permissiveness=body.model_permissiveness,
        generation_id=body.generation_id,
        proposed_by=agent_name,
        status="proposed",
    )

    # Add edges if provided
    for edge in body.edges:
        try:
            await gm.add_edge(
                edge.source,
                edge.target,
                edge.type,
                weight=edge.weight,
                theme=edge.theme,
                description=edge.description,
                created_by=edge.created_by or agent_name,
            )
        except ValueError:
            pass  # skip invalid edge types

    return ProposeResponse(
        path=body.id,
        name=body.name,
        status="proposed",
        proposed_by=agent_name,
    )


@router.post("/moments/{moment_id:path}/challenge", response_model=ChallengeResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_WRITE)
async def challenge_moment(
    request: Request,
    moment_id: str,
    body: ChallengeRequest,
    gm: GraphManager = Depends(get_graph_manager),
    agent: dict = Depends(require_write_auth),
):
    """Challenge an existing moment with a competing version.

    - Sets the original moment's status to 'challenged'
    - Creates the competing moment with status 'proposed'
    - Links them with a 'challenges' edge
    - Records challenged_by on the original
    """
    full_path = "/" + moment_id.strip("/")
    agent_name = agent.get("agent_name", "")

    # Verify original moment exists
    original = await gm.get_node(full_path)
    if original is None:
        raise HTTPException(status_code=404, detail="Moment not found")

    # Cannot challenge an already-alternative moment
    original_status = original.get("status", "proposed")
    if original_status == "alternative":
        raise HTTPException(
            status_code=400,
            detail="Cannot challenge an alternative moment",
        )

    # Create the competing moment
    competing = body.competing_moment
    existing_competing = await gm.get_node(competing.id)
    if existing_competing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Competing moment '{competing.id}' already exists",
        )

    await gm.add_node(
        competing.id,
        name=competing.name,
        one_liner=competing.one_liner,
        year=competing.year,
        month=competing.month,
        month_num=competing.month_num,
        day=competing.day,
        time=competing.time,
        country=competing.country,
        region=competing.region,
        city=competing.city,
        slug=competing.slug,
        layer=competing.layer,
        visibility=competing.visibility,
        tags=competing.tags,
        figures=competing.figures,
        source_type=competing.source_type,
        confidence=competing.confidence,
        source_run_id=competing.source_run_id,
        schema_version=competing.schema_version,
        text_model=competing.text_model,
        image_model=competing.image_model,
        model_provider=competing.model_provider,
        model_permissiveness=competing.model_permissiveness,
        generation_id=competing.generation_id,
        proposed_by=agent_name,
        status="proposed",
    )

    # Add edges from the competing moment
    for edge in competing.edges:
        try:
            await gm.add_edge(
                edge.source,
                edge.target,
                edge.type,
                weight=edge.weight,
                theme=edge.theme,
                description=edge.description,
                created_by=edge.created_by or agent_name,
            )
        except ValueError:
            pass

    # Create 'challenges' edge: competing -> original
    await gm.add_edge(
        competing.id,
        full_path,
        "challenges",
        weight=1.0,
        description=body.reason,
        created_by=agent_name,
    )

    # Update original moment: set status to 'challenged', append to challenged_by
    challenged_by = list(original.get("challenged_by") or [])
    if agent_name and agent_name not in challenged_by:
        challenged_by.append(agent_name)

    await gm.update_node(
        full_path,
        status="challenged",
        challenged_by=challenged_by,
    )

    return ChallengeResponse(
        original_moment_id=full_path,
        original_status="challenged",
        competing_moment_id=competing.id,
        competing_status="proposed",
        challenged_by=agent_name,
    )


@router.post("/moments/{moment_id:path}/verify", response_model=VerifyResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_WRITE)
async def verify_moment(
    request: Request,
    moment_id: str,
    gm: GraphManager = Depends(get_graph_manager),
    admin: dict = Depends(require_admin_auth),
):
    """Mark a moment as verified. Admin or judge only."""
    full_path = "/" + moment_id.strip("/")
    agent_name = admin.get("agent_name", "")

    node = await gm.get_node(full_path)
    if node is None:
        raise HTTPException(status_code=404, detail="Moment not found")

    current_status = node.get("status", "proposed")
    if current_status == "verified":
        raise HTTPException(status_code=400, detail="Moment is already verified")
    if current_status == "alternative":
        raise HTTPException(
            status_code=400,
            detail="Cannot verify an alternative moment. Use reconcile instead.",
        )

    await gm.update_node(full_path, status="verified")

    return VerifyResponse(
        moment_id=full_path,
        status="verified",
        verified_by=agent_name,
    )


@router.post("/moments/{moment_id:path}/reconcile", response_model=ReconcileResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_WRITE)
async def reconcile_moments(
    request: Request,
    moment_id: str,
    body: ReconcileRequest,
    gm: GraphManager = Depends(get_graph_manager),
    admin: dict = Depends(require_admin_auth),
):
    """Reconcile two competing moments. Winner becomes verified, loser becomes alternative.

    The moment_id in the path is ignored in favor of the explicit winner/loser IDs
    in the request body, but must match one of them.
    """
    full_path = "/" + moment_id.strip("/")
    agent_name = admin.get("agent_name", "")

    # Verify the path matches either winner or loser
    if full_path not in (body.winner_id, body.loser_id):
        raise HTTPException(
            status_code=400,
            detail="Path moment_id must match either winner_id or loser_id",
        )

    # Verify both moments exist
    winner = await gm.get_node(body.winner_id)
    if winner is None:
        raise HTTPException(status_code=404, detail=f"Winner moment '{body.winner_id}' not found")

    loser = await gm.get_node(body.loser_id)
    if loser is None:
        raise HTTPException(status_code=404, detail=f"Loser moment '{body.loser_id}' not found")

    # Set winner to verified, loser to alternative
    await gm.update_node(body.winner_id, status="verified")
    await gm.update_node(body.loser_id, status="alternative")

    return ReconcileResponse(
        winner_id=body.winner_id,
        winner_status="verified",
        loser_id=body.loser_id,
        loser_status="alternative",
        reconciled_by=agent_name,
    )


@router.get("/moments/{moment_id:path}/challenges")
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_READ)
async def get_moment_challenges(
    request: Request,
    moment_id: str,
    gm: GraphManager = Depends(get_graph_manager),
):
    """Get all moments that challenge the given moment."""
    full_path = "/" + moment_id.strip("/")

    node = await gm.get_node(full_path)
    if node is None:
        raise HTTPException(status_code=404, detail="Moment not found")

    challenges = await gm.get_challenges(full_path)
    return {
        "moment_id": full_path,
        "challenges": challenges,
        "count": len(challenges),
    }


@router.get("/moments/{moment_id:path}/history", response_model=MomentHistoryResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_READ)
async def get_moment_history(
    request: Request,
    moment_id: str,
    gm: GraphManager = Depends(get_graph_manager),
):
    """Get the full propose/challenge/verify history for a moment."""
    full_path = "/" + moment_id.strip("/")

    node = await gm.get_node(full_path)
    if node is None:
        raise HTTPException(status_code=404, detail="Moment not found")

    entries = await gm.get_moment_history(full_path)
    return MomentHistoryResponse(
        moment_id=full_path,
        status=node.get("status", "proposed"),
        history=[MomentHistoryEntry(**e) for e in entries],
    )
