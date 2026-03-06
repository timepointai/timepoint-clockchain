from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.core.auth import optional_verify_service_key
from app.core.config import get_settings
from app.core.graph import GraphManager, get_graph_manager
from app.core.rate_limit import limiter
from app.core.tdf_bridge import export_node_as_tdf
from app.core.url import MONTH_TO_NUM
from app.models.schemas import (
    EnhancedStatsResponse,
    MomentListItem,
    PaginatedMomentsResponse,
)

router = APIRouter()


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


@router.get("/moments", response_model=PaginatedMomentsResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_PUBLIC)
async def list_moments(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    year_from: int | None = Query(default=None),
    year_to: int | None = Query(default=None),
    entity: str | None = Query(default=None),
    q: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None),
    sort: str = Query(default="year"),
    gm: GraphManager = Depends(get_graph_manager),
    service_key: str | None = Depends(optional_verify_service_key),
):
    items, total = await gm.list_moments(
        limit=limit,
        offset=offset,
        year_from=year_from,
        year_to=year_to,
        entity=entity,
        query=q,
        min_confidence=min_confidence,
        sort=sort,
    )
    return PaginatedMomentsResponse(
        items=[
            MomentListItem(
                path=i["path"],
                name=i.get("name", ""),
                one_liner=i.get("one_liner", ""),
                year=i.get("year"),
                month=i.get("month", ""),
                day=i.get("day", 0),
                country=i.get("country", ""),
                region=i.get("region", ""),
                city=i.get("city", ""),
                source_type=i.get("source_type", "historical"),
                confidence=i.get("confidence"),
            )
            for i in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/moments/{path:path}")
@limiter.limit(lambda: get_settings().RATE_LIMIT_PUBLIC)
async def get_moment_detail(
    request: Request,
    path: str,
    gm: GraphManager = Depends(get_graph_manager),
    service_key: str | None = Depends(optional_verify_service_key),
    format: str = Query(default="default"),
):
    full_path = "/" + path.strip("/")
    node = await gm.get_node(full_path)
    if node is None:
        raise HTTPException(status_code=404, detail="Moment not found")
    if node.get("visibility") != "public" and service_key is None:
        raise HTTPException(status_code=404, detail="Moment not found")

    if format == "tdf":
        record = export_node_as_tdf(node)
        return JSONResponse(record.model_dump(mode="json"))

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


@router.get("/stats", response_model=EnhancedStatsResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_PUBLIC)
async def public_stats(
    request: Request,
    gm: GraphManager = Depends(get_graph_manager),
    service_key: str | None = Depends(optional_verify_service_key),
):
    return await gm.enhanced_stats()
