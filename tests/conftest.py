"""Integration-test fixtures: real Postgres (agyary_test database).

Each test gets a clean schema (truncate-all) and a seeded demo agyary.
"""

from __future__ import annotations

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
