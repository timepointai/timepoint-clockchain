from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import verify_service_key, get_user_id
from app.core.graph import GraphManager, get_graph_manager
from app.core.url import MONTH_TO_NUM
from app.models.schemas import (
    BrowseResponse,
    BrowseItem,
    MomentResponse,
    MomentSummary,
    SearchResult,
    TodayResponse,
)

router = APIRouter(dependencies=[Depends(verify_service_key)])


@router.get("/moments/{path:path}", response_model=MomentResponse)
async def get_moment(
    path: str,
    gm: GraphManager = Depends(get_graph_manager),
    user_id: str | None = Depends(get_user_id),
):
    full_path = "/" + path.strip("/")
    node = await gm.get_node(full_path)
    if node is None:
        raise HTTPException(status_code=404, detail="Moment not found")
    if node.get("visibility") != "public":
        if not user_id or node.get("created_by") != user_id:
            raise HTTPException(status_code=404, detail="Moment not found")
    raw_edges = await gm.get_neighbors(full_path)
    node["edges"] = [
        {
            "source": full_path,
            "target": e["path"],
            "edge_type": e.get("edge_type", ""),
            "weight": e.get("weight", 1.0),
            "theme": e.get("theme", ""),
        }
        for e in raw_edges
    ]
    return _normalize_node(node)


@router.get("/browse", response_model=BrowseResponse)
async def browse_root(gm: GraphManager = Depends(get_graph_manager)):
    items = await gm.browse("")
    return BrowseResponse(prefix="/", items=[BrowseItem(**i) for i in items])


@router.get("/browse/{path:path}", response_model=BrowseResponse)
async def browse_path(
    path: str,
    gm: GraphManager = Depends(get_graph_manager),
):
    prefix = path.strip("/")
    items = await gm.browse(prefix)
    return BrowseResponse(prefix=f"/{prefix}", items=[BrowseItem(**i) for i in items])


@router.get("/today", response_model=TodayResponse)
async def today_in_history(gm: GraphManager = Depends(get_graph_manager)):
    now = datetime.now(timezone.utc)
    events = await gm.today_in_history(now.month, now.day)
    return TodayResponse(
        month=now.month,
        day=now.day,
        events=[MomentSummary(**_summary(e)) for e in events],
    )


@router.get("/random", response_model=MomentSummary)
async def random_moment(gm: GraphManager = Depends(get_graph_manager)):
    node = await gm.random_public()
    if node is None:
        raise HTTPException(status_code=404, detail="No public moments available")
    return MomentSummary(**_summary(node))


@router.get("/search", response_model=list[SearchResult])
async def search_moments(
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


def _month_to_int(val) -> int:
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        return MONTH_TO_NUM.get(val.lower(), 0)
    return 0


def _normalize_node(node: dict) -> dict:
    node = dict(node)
    node["month"] = node.get("month_num", 0) or _month_to_int(node.get("month", 0))
    return node


def _summary(node: dict) -> dict:
    return {
        "path": node.get("path", ""),
        "name": node.get("name", ""),
        "one_liner": node.get("one_liner", ""),
        "year": node.get("year", 0),
        "month": node.get("month_num", node.get("month", 0)) if isinstance(node.get("month"), str) else node.get("month", 0),
        "day": node.get("day", 0),
        "layer": node.get("layer", 0),
        "visibility": node.get("visibility", "private"),
        "source_type": node.get("source_type", "historical"),
    }
