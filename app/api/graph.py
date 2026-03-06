from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import verify_service_key
from app.core.config import get_settings
from app.core.graph import GraphManager, get_graph_manager
from app.core.rate_limit import limiter

router = APIRouter(dependencies=[Depends(verify_service_key)])


@router.get("/graph/neighbors/{path:path}")
@limiter.limit(lambda: get_settings().RATE_LIMIT_AUTH_READ)
async def get_neighbors(
    request: Request,
    path: str,
    gm: GraphManager = Depends(get_graph_manager),
):
    full_path = "/" + path.strip("/")
    if await gm.get_node(full_path) is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return await gm.get_neighbors(full_path)
