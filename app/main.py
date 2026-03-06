import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api import api_router
from app.core.config import get_settings
from app.core.db import create_pool, init_schema, seed_if_empty
from app.core.graph import GraphManager
from app.core.jobs import JobManager
from app.core.rate_limit import limiter
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
                gm, settings.OPENROUTER_API_KEY, model=settings.OPENROUTER_MODEL,
                job_manager=job_manager,
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

    yield

    # Shutdown
    if expander_task:
        expander_task.cancel()
    if daily_task:
        daily_task.cancel()
    await gm.close()
    logger.info("Clockchain shutting down")


app = FastAPI(
    title="TIMEPOINT Clockchain",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS
settings = get_settings()
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "Retry-After",
    ],
)

app.include_router(api_router)


@app.get("/")
async def root():
    return {"service": "timepoint-clockchain", "version": "0.1.0"}


@app.get("/health")
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
