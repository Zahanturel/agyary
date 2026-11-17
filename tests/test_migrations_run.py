"""The migrations themselves run, from nothing to head and back.

The rest of the suite builds its schema from the models (create_all), so a
migration that cannot run on a real database - a constraint dropped by the
wrong name, say - passes every other test and then fails the deploy's migrate
step. This runs the real chain on a scratch database: up to head, all the way
down to an empty database, up again, and checks the result matches the models.
(It used to stop at the revision before Phase 1, and the downgrade below that
had been broken since the bot tables were dropped; audit 30 Oct 2026, DB-01.)
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
        _ok(_alembic("downgrade", "base"))
        _ok(_alembic("upgrade", "head"))
        # And what the migrations built is what the models describe.
        _ok(_alembic("check"))
    finally:
        await _recreate(drop_only=True)


async def _scratch_execute(sql: str, params: dict | None = None):
    engine = create_async_engine(SCRATCH_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            return result.all() if result.returns_rows else None
    finally:
        await engine.dispose()


async def test_the_agyari_location_migration_holds_its_rules_and_comes_off_cleanly():
    """d0e1f2a3b4c6: a position is all three of latitude, longitude and source
    or none of them, on the globe, from "town" or "pin" - enforced by the
    database the migration builds, not only by the models - and the downgrade
    takes it all off again."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "head"))
        insert = ("INSERT INTO agyaries (name, city, latitude, longitude, location_source)"
                  " VALUES (:n, 'Mumbai', :lat, :lon, :src)")
        await _scratch_execute(insert, {"n": "Pinned", "lat": 18.95, "lon": 72.83, "src": "pin"})
        await _scratch_execute(insert, {"n": "Town", "lat": 18.95, "lon": 72.83, "src": "town"})
        await _scratch_execute(insert, {"n": "Nowhere yet", "lat": None, "lon": None, "src": None})
        refused = [
            {"n": "Half", "lat": 18.95, "lon": None, "src": "pin"},
            {"n": "No source", "lat": 18.95, "lon": 72.83, "src": None},
            {"n": "Source only", "lat": None, "lon": None, "src": "pin"},
            {"n": "Off the globe", "lat": 91.0, "lon": 72.83, "src": "pin"},
            {"n": "Round twice", "lat": 18.95, "lon": -180.5, "src": "pin"},
            {"n": "Guessed", "lat": 18.95, "lon": 72.83, "src": "gps"},
        ]
        for row in refused:
            try:
                await _scratch_execute(insert, row)
            except Exception as exc:  # noqa: BLE001 - the database's refusal, whatever its class
                assert "check constraint" in str(exc).lower(), (row, exc)
            else:
                raise AssertionError(f"accepted {row}")
        names = await _scratch_execute("SELECT conname FROM pg_constraint WHERE conrelid = 'agyaries'::regclass")
        assert {"ck_agyaries_location", "ck_agyaries_location_source",
                "fk_agyaries_location_set_by_user_id_users"} <= {n for (n,) in names}

        _ok(_alembic("downgrade", "c9d0e1f2a3b5"))
        cols = await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'agyaries'")
        assert not {"latitude", "longitude", "location_source", "location_set_by_user_id",
                    "location_set_at"} & {c for (c,) in cols}
        # The fire temples themselves are untouched by coming down.
        assert len(await _scratch_execute("SELECT id FROM agyaries")) == 3
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)
