import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("SERVICE_API_KEY", "test-key")
os.environ.setdefault("FLASH_SERVICE_KEY", "flash-key")
os.environ.setdefault("ENVIRONMENT", "test")

# Default test database — override with DATABASE_URL env var
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://localhost:5432/clockchain_test",
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from app.core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _set_data_dir(tmp_path):
    """Point DATA_DIR at a temp dir containing seeds.json."""
    seeds_src = os.path.join(os.path.dirname(__file__), "..", "data", "seeds.json")
    if os.path.exists(seeds_src):
        import shutil
        shutil.copy(seeds_src, tmp_path / "seeds.json")
    os.environ["DATA_DIR"] = str(tmp_path)
    yield
    os.environ.pop("DATA_DIR", None)


@pytest.fixture(autouse=True)
async def _init_and_truncate():
    """Ensure schema exists and truncate tables before each test."""
    import asyncpg
    from app.core.db import SCHEMA_DDL
    url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(SCHEMA_DDL)
        await conn.execute("TRUNCATE edges, nodes CASCADE")
    finally:
        await conn.close()
    yield


@pytest.fixture()
def service_key():
    return "test-key"


@pytest.fixture()
async def client():
    from app.main import app
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture()
async def auth_client(service_key):
    from app.main import app
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Service-Key": service_key},
        ) as ac:
            yield ac
