"""The migrations themselves run, from nothing to head and back.

The rest of the suite builds its schema from the models (create_all), so a
migration that cannot run on a real database - a constraint dropped by the
wrong name, say - passes every other test and then fails the deploy's migrate
step. This runs the real chain on a scratch database: up to head, down to the
revision before Phase 1, up again, and checks the result matches the models.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import TEST_DATABASE_URL

ROOT = Path(__file__).resolve().parent.parent
SCRATCH = "agyary_migrations"
SCRATCH_URL = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/" + SCRATCH
# The last revision production ran before the Phase 1 migrations.
BEFORE_PHASE_1 = "d1e2f3a4b5c6"


async def _recreate(drop_only: bool = False) -> None:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)"))
        if not drop_only:
            await conn.execute(text(f"CREATE DATABASE {SCRATCH}"))
    await engine.dispose()


def _alembic(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": SCRATCH_URL}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )


def _ok(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]


async def test_the_migration_chain_runs_up_down_and_up_again():
    await _recreate()
    try:
        _ok(_alembic("upgrade", "head"))
        _ok(_alembic("downgrade", BEFORE_PHASE_1))
        _ok(_alembic("upgrade", "head"))
        # And what the migrations built is what the models describe.
        _ok(_alembic("check"))
    finally:
        await _recreate(drop_only=True)
