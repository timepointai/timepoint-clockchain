from fastapi import APIRouter

from app.api.public import router as public_router
from app.api.moments import router as moments_router
from app.api.graph import router as graph_router
from app.api.generate import router as generate_router
from app.api.ingest import router as ingest_router

api_router = APIRouter(prefix="/api/v1")
# Public router first so GET /moments list matches before auth catch-all paths
api_router.include_router(public_router)
api_router.include_router(moments_router)
api_router.include_router(graph_router)
api_router.include_router(generate_router)
api_router.include_router(ingest_router)
