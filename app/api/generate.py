from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.core.auth import verify_service_key, get_user_id
from app.core.config import get_settings
from app.core.graph import GraphManager, get_graph_manager
from app.core.jobs import JobManager
from app.models.schemas import (
    BulkGenerateRequest,
    GenerateRequest,
    JobResponse,
    PublishRequest,
)

router = APIRouter(dependencies=[Depends(verify_service_key)])


async def get_job_manager(request: Request) -> JobManager:
    jm = getattr(request.app.state, "job_manager", None)
    if jm is None:
        raise HTTPException(status_code=503, detail="Job manager not available")
    return jm


@router.post("/generate", response_model=JobResponse)
async def generate_moment(
    body: GenerateRequest,
    background_tasks: BackgroundTasks,
    jm: JobManager = Depends(get_job_manager),
    user_id: str | None = Depends(get_user_id),
):
    # Content judge (Phase 5) — if available
    try:
        from app.workers.judge import ContentJudge
        settings = get_settings()
        if settings.OPENROUTER_API_KEY:
            judge = ContentJudge(settings.OPENROUTER_API_KEY, model=settings.OPENROUTER_MODEL)
            verdict = await judge.screen(body.query)
            if verdict == "reject":
                raise HTTPException(status_code=400, detail="Query rejected by content judge")
    except ImportError:
        pass

    job = jm.create_job(
        query=body.query,
        preset=body.preset,
        user_id=user_id,
        visibility=body.visibility,
    )
    background_tasks.add_task(jm.process_job, job)
    return job.to_dict()


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    jm: JobManager = Depends(get_job_manager),
):
    job = jm.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.post("/moments/{path:path}/publish")
async def publish_moment(
    path: str,
    body: PublishRequest = PublishRequest(),
    gm: GraphManager = Depends(get_graph_manager),
    user_id: str | None = Depends(get_user_id),
):
    from datetime import datetime, timezone

    full_path = "/" + path.strip("/")
    node = await gm.get_node(full_path)
    if node is None:
        raise HTTPException(status_code=404, detail="Moment not found")

    update_fields = {"visibility": body.visibility}
    if body.visibility == "public":
        update_fields["published_at"] = datetime.now(timezone.utc)
    await gm.update_node(full_path, **update_fields)
    return {"path": full_path, "visibility": body.visibility}


@router.post("/bulk-generate", response_model=list[JobResponse])
async def bulk_generate(
    body: BulkGenerateRequest,
    background_tasks: BackgroundTasks,
    jm: JobManager = Depends(get_job_manager),
    x_admin_key: str | None = None,
):
    settings = get_settings()
    if not settings.ADMIN_KEY or x_admin_key != settings.ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Admin key required")

    results = []
    for req in body.queries:
        job = jm.create_job(query=req.query, preset=req.preset, visibility=req.visibility)
        background_tasks.add_task(jm.process_job, job)
        results.append(job.to_dict())
    return results


@router.post("/index")
async def index_moment(
    body: dict,
    gm: GraphManager = Depends(get_graph_manager),
):
    path = body.get("path")
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    metadata = body.get("metadata", {})
    flash_id = body.get("flash_timepoint_id")
    visibility = body.get("visibility", "private")
    created_by = body.get("created_by", "system")

    attrs = {
        "type": "event",
        "visibility": visibility,
        "created_by": created_by,
        **metadata,
    }
    if flash_id:
        attrs["flash_timepoint_id"] = flash_id
        attrs["layer"] = max(attrs.get("layer", 0), 2)

    await gm.add_node(path, **attrs)
    return {"path": path, "status": "indexed"}
