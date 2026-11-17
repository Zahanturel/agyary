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
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import TEST_DATABASE_URL

ROOT = Path(__file__).resolve().parent.parent
SCRATCH = "agyary_migrations"
SCRATCH_URL = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/" + SCRATCH
AT = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)


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


async def test_the_panthaky_claim_migration_holds_its_rules_and_comes_off_cleanly():
    """e1f2a3b4c5d7: a membership's claim is "mobed" or "panthaky" with its
    time, the owner's decision is one of three with its time, the deciding
    admin can go without taking the membership with them - all enforced by the
    database the migration builds - and the downgrade takes it off again
    without touching anyone's role."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "head"))
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Claimed', 'Mumbai')")
        for phone in ("+919000000001", "+919000000002", "+919000000003"):
            await _scratch_execute("INSERT INTO users (name, phone) VALUES ('Er. Test', :p)", {"p": phone})
        (aid,), = await _scratch_execute("SELECT id FROM agyaries")
        u1, u2, admin = [u for (u,) in await _scratch_execute("SELECT id FROM users ORDER BY id")]
        insert = ("INSERT INTO agyary_users (agyary_id, user_id, role, claimed_role, claimed_at,"
                  " claim_decision, claim_decided_at, claim_decided_by_user_id)"
                  " VALUES (:a, :u, :role, :claim, :at, :dec, :dec_at, :by)")
        base = {"a": aid, "role": "mobed", "claim": None, "at": None, "dec": None, "dec_at": None, "by": None}
        await _scratch_execute(insert, {**base, "u": u1, "claim": "panthaky", "at": AT,
                                        "role": "panthaky", "dec": "confirmed",
                                        "dec_at": AT, "by": admin})
        await _scratch_execute(insert, {**base, "u": u2})          # no claim at all, as before
        refused = [
            {"claim": "caretaker", "at": AT},
            {"claim": "panthaky", "at": None},
            {"claim": None, "at": AT},
            {"dec": "maybe", "dec_at": AT},
            {"dec": "declined", "dec_at": None},
            {"dec": None, "dec_at": AT},
        ]
        for change in refused:
            try:
                await _scratch_execute(insert, {**base, "u": admin, **change})
            except Exception as exc:  # noqa: BLE001 - the database's refusal, whatever its class
                assert "check constraint" in str(exc).lower(), (change, exc)
            else:
                raise AssertionError(f"accepted {change}")
        names = await _scratch_execute("SELECT conname FROM pg_constraint WHERE conrelid = 'agyary_users'::regclass")
        assert {"ck_agyary_users_claimed_role", "ck_agyary_users_claim_decision", "ck_agyary_users_claimed_at",
                "ck_agyary_users_claim_decided_at",
                "fk_agyary_users_claim_decided_by_user_id_users"} <= {n for (n,) in names}

        # The admin who decided goes; the membership and its decision stay.
        await _scratch_execute("DELETE FROM users WHERE id = :u", {"u": admin})
        assert await _scratch_execute(
            "SELECT role, claim_decision, claim_decided_by_user_id FROM agyary_users WHERE user_id = :u",
            {"u": u1}) == [("panthaky", "confirmed", None)]

        _ok(_alembic("downgrade", "d0e1f2a3b4c6"))
        cols = await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'agyary_users'")
        assert not {"claimed_role", "claimed_at", "claim_decision", "claim_decided_at",
                    "claim_decided_by_user_id"} & {c for (c,) in cols}
        # The memberships and their roles are untouched by coming down.
        assert sorted(await _scratch_execute("SELECT user_id, role FROM agyary_users")) == [
            (u1, "panthaky"), (u2, "mobed")]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_funeral_place_migration_holds_its_rules_and_comes_off_cleanly():
    """f1a2b3c4d5e7: every account already there stays a mobed's; an account is
    one of two kinds; a funeral place is one of three kinds, with both or
    neither of latitude and longitude and on the globe; a manager's link is a
    "manager"; the admin who added a place can go without taking it with them -
    all enforced by the database the migration builds - and the downgrade takes
    it off again without touching the accounts."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "e1f2a3b4c5d7"))
        await _scratch_execute("INSERT INTO users (name, phone) VALUES ('Er. Before', '+919000000001')")
        _ok(_alembic("upgrade", "head"))
        assert await _scratch_execute("SELECT account_kind FROM users") == [("mobed",)]
        await _scratch_execute("INSERT INTO users (name, phone, account_kind) VALUES"
                               " ('Manager', '+919000000002', 'funeral_manager')")
        try:
            await _scratch_execute("INSERT INTO users (name, phone, account_kind) VALUES ('X', '+919000000003', 'behdin')")
        except Exception as exc:  # noqa: BLE001 - the database's refusal, whatever its class
            assert "check constraint" in str(exc).lower(), exc
        else:
            raise AssertionError("accepted account_kind behdin")
        (admin,), (manager,) = await _scratch_execute("SELECT id FROM users ORDER BY id")

        insert = ("INSERT INTO funeral_places (name, kind, city, latitude, longitude, created_by_user_id)"
                  " VALUES (:n, :k, 'Mumbai', :lat, :lon, :by)")
        base = {"k": "doongerwadi", "lat": None, "lon": None, "by": admin}
        await _scratch_execute(insert, {**base, "n": "Doongerwadi (test)", "lat": 18.96, "lon": 72.80})
        await _scratch_execute(insert, {**base, "n": "Prayer hall (test)", "k": "prayer_hall"})
        await _scratch_execute(insert, {**base, "n": "Aramgah (test)", "k": "aramgah"})
        refused = [
            {"n": "Half", "lat": 18.96},
            {"n": "Other half", "lon": 72.80},
            {"n": "Off the globe", "lat": 91.0, "lon": 72.80},
            {"n": "Round twice", "lat": 18.96, "lon": 181.0},
            {"n": "Crematorium", "k": "crematorium"},
        ]
        for change in refused:
            try:
                await _scratch_execute(insert, {**base, **change})
            except Exception as exc:  # noqa: BLE001 - the database's refusal, whatever its class
                assert "check constraint" in str(exc).lower(), (change, exc)
            else:
                raise AssertionError(f"accepted {change}")
        (place,), *_ = await _scratch_execute("SELECT id FROM funeral_places ORDER BY id")
        link = "INSERT INTO funeral_place_managers (funeral_place_id, user_id, role) VALUES (:p, :u, :r)"
        await _scratch_execute(link, {"p": place, "u": manager, "r": "manager"})
        try:
            await _scratch_execute(link, {"p": place, "u": admin, "r": "owner"})
        except Exception as exc:  # noqa: BLE001
            assert "check constraint" in str(exc).lower(), exc
        else:
            raise AssertionError("accepted role owner")
        assert await _scratch_execute("SELECT is_active FROM funeral_places WHERE id = :p", {"p": place}) == [(True,)]
        names = await _scratch_execute(
            "SELECT conname FROM pg_constraint WHERE conrelid IN"
            " ('funeral_places'::regclass, 'funeral_place_managers'::regclass, 'users'::regclass)")
        assert {"ck_funeral_places_kind", "ck_funeral_places_location", "fk_funeral_places_created_by_user_id_users",
                "ck_funeral_place_managers_role", "ck_users_account_kind",
                "fk_funeral_place_managers_user_id_users"} <= {n for (n,) in names}

        # The admin who added the places goes; the places stay.
        await _scratch_execute("DELETE FROM users WHERE id = :u", {"u": admin})
        assert len(await _scratch_execute("SELECT id FROM funeral_places WHERE created_by_user_id IS NULL")) == 3

        _ok(_alembic("downgrade", "e1f2a3b4c5d7"))
        tables = await _scratch_execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        assert not {"funeral_places", "funeral_place_managers"} & {t for (t,) in tables}
        cols = await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")
        assert "account_kind" not in {c for (c,) in cols}
        assert await _scratch_execute("SELECT name FROM users") == [("Manager",)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)
