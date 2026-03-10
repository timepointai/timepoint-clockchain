import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.core.config import get_settings
from app.core.db import create_pool, init_schema, run_migrations, seed_if_empty
from app.core.graph import GraphManager
from app.core.jobs import JobManager
from app.workers.renderer import FlashClient

logger = logging.getLogger("clockchain")


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Clockchain starting up (env=%s)", settings.ENVIRONMENT)

    # Database pool
    pool = await create_pool(settings.DATABASE_URL)
    await init_schema(pool)
    await run_migrations(pool)
    await seed_if_empty(pool, settings.DATA_DIR)

    # Graph manager
    gm = GraphManager(pool)
    await gm.load()
    application.state.graph_manager = gm

    # Job manager
    flash_client = FlashClient(settings.FLASH_URL, settings.FLASH_SERVICE_KEY)
    job_manager = JobManager(graph_manager=gm, flash_client=flash_client)
    application.state.job_manager = job_manager

    # Expander (gated by feature flag)
    expander_task = None
    if settings.EXPANSION_ENABLED and settings.OPENROUTER_API_KEY:
        try:
            from app.workers.expander import GraphExpander
            expander = GraphExpander(
                gm, settings.OPENROUTER_API_KEY, model=settings.OPENROUTER_MODEL
            )
            expander_task = asyncio.create_task(expander.start())
            logger.info("Graph expander started")
        except ImportError:
            pass

    # Daily worker (gated by feature flag)
    daily_task = None
    if settings.DAILY_CRON_ENABLED:
        try:
            from app.workers.daily import DailyWorker
            daily = DailyWorker(gm, job_manager)
            daily_task = asyncio.create_task(daily.start())
            logger.info("Daily worker started")
        except ImportError:
            pass

    # Image backfill worker (gated by feature flag)
    image_backfill_task = None
    if settings.IMAGE_BACKFILL_ENABLED:
        try:
            from app.workers.image_backfill import ImageBackfillWorker
            backfill = ImageBackfillWorker(
                gm, flash_client, interval_seconds=settings.IMAGE_BACKFILL_INTERVAL,
            )
            image_backfill_task = asyncio.create_task(backfill.start())
            logger.info("Image backfill worker started")
        except ImportError:
            pass

    yield

    # Shutdown
    if expander_task:
        expander_task.cancel()
    if daily_task:
        daily_task.cancel()
    if image_backfill_task:
        image_backfill_task.cancel()
    await gm.close()
    logger.info("Clockchain shutting down")


app = FastAPI(
    title="TIMEPOINT Clockchain",
    description=(
        "Temporal causal graph for AI agents. PostgreSQL-backed directed graph of "
        "historical moments with canonical spatiotemporal URLs, typed causal edges, "
        "autonomous expansion, and browse/search/discovery APIs.\n\n"
        "**Public endpoints** (`/api/v1/moments`, `/api/v1/stats`) require no auth. "
        "All other endpoints require an `X-Service-Key` header.\n\n"
        "Part of the [Timepoint AI](https://github.com/timepointai) suite."
    ),
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "Public", "description": "Unauthenticated read-only endpoints (rate limited)"},
        {"name": "Browse", "description": "Hierarchical path browsing and discovery"},
        {"name": "Graph", "description": "Graph structure queries (neighbors, stats)"},
        {"name": "Generate", "description": "Scene generation, job tracking, publishing"},
        {"name": "Ingest", "description": "Bulk data ingestion (subgraph, TDF)"},
        {"name": "System", "description": "Health checks and service info"},
    ],
    contact={"name": "Sean McDonald", "url": "https://x.com/seanmcdonaldxyz"},
    license_info={"name": "Apache 2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"},
)
app.include_router(api_router)


@app.get("/", tags=["System"])
async def root():
    return {"service": "timepoint-clockchain", "version": "0.2.0"}


@app.get("/health", tags=["System"])
async def health():
    gm = getattr(app.state, "graph_manager", None)
    nodes = await gm.node_count() if gm else 0
    edges = await gm.edge_count() if gm else 0
    return {
        "status": "healthy",
        "service": "timepoint-clockchain",
        "nodes": nodes,
        "edges": edges,
    }
