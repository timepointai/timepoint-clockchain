from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import verify_service_key
from app.core.graph import GraphManager, get_graph_manager
from app.models.schemas import GraphStatsResponse

router = APIRouter(dependencies=[Depends(verify_service_key)])


@router.get("/graph/neighbors/{path:path}")
async def get_neighbors(
    path: str,
    gm: GraphManager = Depends(get_graph_manager),
):
    full_path = "/" + path.strip("/")
    if await gm.get_node(full_path) is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return await gm.get_neighbors(full_path)


@router.get("/stats", response_model=GraphStatsResponse)
async def graph_stats(gm: GraphManager = Depends(get_graph_manager)):
    return await gm.stats()
