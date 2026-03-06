from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.auth import verify_service_key
from app.core.config import get_settings
from app.core.graph import GraphManager, get_graph_manager
from app.core.rate_limit import limiter
from app.models.schemas import (
    BrowseResponse,
    BrowseItem,
    MomentSummary,
    SearchResult,
    TodayResponse,
)

router = APIRouter(dependencies=[Depends(verify_service_key)])


@router.get("/browse", response_model=BrowseResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_READ)
async def browse_root(request: Request, gm: GraphManager = Depends(get_graph_manager)):
    items = await gm.browse("")
    return BrowseResponse(prefix="/", items=[BrowseItem(**i) for i in items])


@router.get("/browse/{path:path}", response_model=BrowseResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_READ)
async def browse_path(
    request: Request,
    path: str,
    gm: GraphManager = Depends(get_graph_manager),
):
    prefix = path.strip("/")
    items = await gm.browse(prefix)
    return BrowseResponse(prefix=f"/{prefix}", items=[BrowseItem(**i) for i in items])


@router.get("/today", response_model=TodayResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_READ)
async def today_in_history(request: Request, gm: GraphManager = Depends(get_graph_manager)):
    now = datetime.now(timezone.utc)
    events = await gm.today_in_history(now.month, now.day)
    return TodayResponse(
        month=now.month,
        day=now.day,
        events=[MomentSummary(**_summary(e)) for e in events],
    )


@router.get("/random", response_model=MomentSummary)
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_READ)
async def random_moment(request: Request, gm: GraphManager = Depends(get_graph_manager)):
    node = await gm.random_public()
    if node is None:
        raise HTTPException(status_code=404, detail="No public moments available")
    return MomentSummary(**_summary(node))


@router.get("/search", response_model=list[SearchResult])
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_READ)
async def search_moments(
    request: Request,
    q: str = Query(..., min_length=1),
    gm: GraphManager = Depends(get_graph_manager),
):
    results = await gm.search(q)
    return [
        SearchResult(
            path=r["path"],
            name=r.get("name", ""),
            one_liner=r.get("one_liner", ""),
            score=r.get("score", 0.0),
        )
        for r in results
    ]


def _summary(node: dict) -> dict:
    return {
        "path": node.get("path", ""),
        "name": node.get("name", ""),
        "one_liner": node.get("one_liner", ""),
        "year": node.get("year", 0),
        "month": node.get("month_num", node.get("month", 0))
        if isinstance(node.get("month"), str)
        else node.get("month", 0),
        "day": node.get("day", 0),
        "layer": node.get("layer", 0),
        "visibility": node.get("visibility", "private"),
        "source_type": node.get("source_type", "historical"),
    }
