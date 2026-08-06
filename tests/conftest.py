"""Integration-test fixtures: real Postgres (agyary_test database).

Each test gets a clean schema (truncate-all) and a seeded demo agyary.
"""

from __future__ import annotations

import os

# The mobed auth layer signs JWTs with jwt_secret_key; the repo ships it empty.
# Set a test value before any get_settings() call so the suite runs green under
# a plain `uv run pytest` (an OS env var overrides the empty .env entry).
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import agyary.models  # noqa: F401 - register models on Base.metadata
from agyary.core.database import Base

TEST_DATABASE_URL = "postgresql+asyncpg://agyary:agyary@localhost:5432/agyary_test"

_schema_ready = False


@pytest.fixture
async def db():
    """A session on the test database with a clean, seeded schema."""
    global _schema_ready
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        if not _schema_ready:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            _schema_ready = True
        else:
            table_list = ", ".join(t.name for t in Base.metadata.sorted_tables)
            await conn.execute(text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"))

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seeded(db):
    """Demo agyary + panthaky + mobed + services; returns ids/phones."""
    from agyary.scripts.seed_demo import seed

    await seed(db)
    return {
        "agyary_id": 1,
        "panthaky_phone": "+919800000001",
        "mobed_phone": "+919800000002",
    }


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """The login rate limiter (api/rate_limit.py) keeps its counters in a
    module-level dict, keyed by client IP - every test hits it from the
    same in-process ASGI transport, so without a reset here, the third or
    fourth test to log in would 429 the rest of the suite. Real deployments
    have real distinct client IPs; this is purely a test-isolation fix."""
    from agyary.api import rate_limit

    rate_limit._hits.clear()
    yield
    rate_limit._hits.clear()


@pytest.fixture
async def client(db):
    """httpx client hitting the FastAPI app in-process (no real server, no
    lifespan - bare ASGITransport never fires startup/shutdown, so the send
    worker's background tasks never start here). get_db is overridden to
    the same test-database session used by other fixtures, so route
    handlers and test assertions share one transaction."""
    from httpx import ASGITransport, AsyncClient

    from agyary.api.main import app
    from agyary.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
