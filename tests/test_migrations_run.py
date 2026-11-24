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
from datetime import date, datetime, time, timezone
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
            await _scratch_execute("INSERT INTO users (name, phone, account_kind) VALUES ('X', '+919000000003', 'trustee')")
        except Exception as exc:  # noqa: BLE001 - the database's refusal, whatever its class
            assert "check constraint" in str(exc).lower(), exc
        else:
            raise AssertionError("accepted account_kind trustee")
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


async def _refused(sql: str, params: dict, what: str, needle: str = "check constraint") -> None:
    try:
        await _scratch_execute(sql, params)
    except Exception as exc:  # noqa: BLE001 - the database's refusal, whatever its class
        assert needle in str(exc).lower(), (what, exc)
    else:
        raise AssertionError(f"accepted {what}")


async def test_the_funeral_record_migration_holds_its_rules_and_comes_off_cleanly():
    """a3b4c5d6e7f9: a funeral record's title, obsequies, calendar, Roj and Mah,
    Geh-saarnu (day and geh together) and Uthamna (no time without a day) are
    held by the database; a request is one of five states, decided exactly when
    it is no longer waiting, and only one waits per record at a time; the
    manager who made them can go and the record stays (D8), while who was asked
    goes with that person's account - and the downgrade takes it all off."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "f1a2b3c4d5e7"))
        await _scratch_execute("INSERT INTO users (name, phone, account_kind) VALUES"
                               " ('Manager', '+919000000001', 'funeral_manager'), ('Er. Asked', '+919000000002', 'mobed')")
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        await _scratch_execute("INSERT INTO funeral_places (name, kind, city) VALUES ('Doongerwadi (test)', 'doongerwadi', 'Mumbai')")
        _ok(_alembic("upgrade", "head"))
        (manager,), (mobed,) = await _scratch_execute("SELECT id FROM users ORDER BY id")
        ((agyary,),) = await _scratch_execute("SELECT id FROM agyaries")
        ((place,),) = await _scratch_execute("SELECT id FROM funeral_places")

        insert = (
            "INSERT INTO funeral_records (funeral_place_id, departed_title, departed_name, death_date, death_given_by,"
            " death_roj, death_mah, death_year, calendar_system, obsequies, geh_saarnu_date, geh_saarnu_geh,"
            " uthamna_date, uthamna_time, mobeds_wanted, family_contact_name, family_contact_phone, created_by_user_id)"
            " VALUES (:p, :t, 'Rustom', '2026-11-17', :by, :roj, :mah, 1396, :cal, :ob, :gd, :gg, :ud, :ut, :mw,"
            " 'Family', '+919000000009', :u)"
        )
        base = {"p": place, "t": "behdin", "by": "date", "roj": 3, "mah": 4, "cal": "shenshai", "ob": "four_days",
                "gd": date(2026, 11, 18), "gg": 1, "ud": date(2026, 11, 20), "ut": time(16, 0), "mw": 5, "u": manager}
        await _scratch_execute(insert, base)
        await _scratch_execute(insert, {**base, "t": "ervad", "by": "roj_mah", "roj": 2, "mah": 13, "ob": "one_day",
                                        "gd": None, "gg": None, "ud": None, "ut": None, "mw": None})
        for change in ({"t": "mister"}, {"ob": "three_days"}, {"by": "guess"}, {"cal": "gregorian"},
                       {"mah": 14}, {"roj": 31}, {"gg": None}, {"gd": None}, {"gg": 6}, {"ud": None},
                       {"mw": 0}, {"mw": 21}):
            await _refused(insert, {**base, **change}, change)
        ((record,), _) = await _scratch_execute("SELECT id FROM funeral_records ORDER BY id")

        send = ("INSERT INTO funeral_requests (funeral_record_id, agyary_id, status, family_share_agreed_at,"
                " sent_by_user_id, decided_at) VALUES (:r, :a, :s, now(), :u, :d)")
        req = {"r": record, "a": agyary, "s": "waiting", "u": manager, "d": None}
        await _scratch_execute(send, req)
        # One waiting at a time; a withdrawn one beside it is fine.
        await _refused(send, req, "a second waiting request", needle="uq_funeral_requests_one_waiting")
        await _scratch_execute(send, {**req, "s": "withdrawn", "d": AT})
        for change in ({"s": "lost", "d": AT}, {"s": "declined", "d": None}, {"s": "waiting", "d": AT}):
            await _refused(send, {**req, **change}, change)
        await _refused("INSERT INTO funeral_requests (funeral_record_id, agyary_id, sent_by_user_id) VALUES (:r, :a, :u)",
                       {"r": record, "a": agyary, "u": manager}, "no family agreement", needle="not-null")
        ((request,), _) = await _scratch_execute("SELECT id FROM funeral_requests ORDER BY id")
        await _scratch_execute("INSERT INTO funeral_request_recipients (funeral_request_id, user_id) VALUES (:q, :u)",
                               {"q": request, "u": mobed})
        names = await _scratch_execute(
            "SELECT conname FROM pg_constraint WHERE conrelid IN ('funeral_records'::regclass,"
            " 'funeral_requests'::regclass, 'funeral_request_recipients'::regclass)")
        assert {"ck_funeral_records_departed_title", "ck_funeral_records_geh_saarnu", "ck_funeral_requests_status",
                "ck_funeral_requests_decided", "fk_funeral_records_created_by_user_id_users",
                "fk_funeral_request_recipients_user_id_users"} <= {n for (n,) in names}

        # The manager's account goes: the records and requests stay, unsigned.
        await _scratch_execute("DELETE FROM users WHERE id = :u", {"u": manager})
        assert await _scratch_execute("SELECT count(*) FROM funeral_records WHERE created_by_user_id IS NULL") == [(2,)]
        assert await _scratch_execute("SELECT count(*) FROM funeral_requests WHERE sent_by_user_id IS NULL") == [(2,)]
        # The mobed asked goes: who was asked goes with them, the request stays.
        await _scratch_execute("DELETE FROM users WHERE id = :u", {"u": mobed})
        assert await _scratch_execute("SELECT count(*) FROM funeral_request_recipients") == [(0,)]
        assert await _scratch_execute("SELECT count(*) FROM funeral_requests") == [(2,)]

        _ok(_alembic("downgrade", "f1a2b3c4d5e7"))
        tables = await _scratch_execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        assert not {"funeral_records", "funeral_requests", "funeral_request_recipients"} & {t for (t,) in tables}
        assert await _scratch_execute("SELECT name FROM funeral_places") == [("Doongerwadi (test)",)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_funeral_accept_migration_holds_its_rule_and_comes_off_cleanly():
    """b4c5d6e7f8a0: whether the accepter shared their name and number is kept
    only on an accepted request; requests from before have neither it nor a
    memorial; the downgrade takes both columns off and keeps the requests."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "a3b4c5d6e7f9"))
        await _scratch_execute("INSERT INTO users (name, phone, account_kind) VALUES"
                               " ('Manager', '+919000000001', 'funeral_manager'), ('Er. Asked', '+919000000002', 'mobed')")
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        await _scratch_execute("INSERT INTO funeral_places (name, kind, city) VALUES ('Doongerwadi (test)', 'doongerwadi', 'Mumbai')")
        await _scratch_execute(
            "INSERT INTO funeral_records (funeral_place_id, departed_title, departed_name, death_date, death_given_by,"
            " death_roj, death_mah, death_year, calendar_system, obsequies, family_contact_name, family_contact_phone)"
            " VALUES (1, 'behdin', 'Rustom', '2026-11-17', 'date', 3, 4, 1396, 'shenshai', 'four_days', 'Family',"
            " '+919000000009')")
        send = ("INSERT INTO funeral_requests (funeral_record_id, agyary_id, status, family_share_agreed_at, decided_at,"
                " accepted_by_user_id) VALUES (1, 1, :s, now(), :d, :a)")
        await _scratch_execute(send, {"s": "accepted", "d": AT, "a": 2})
        await _scratch_execute(send, {"s": "waiting", "d": None, "a": None})
        _ok(_alembic("upgrade", "head"))

        assert await _scratch_execute(
            "SELECT accepter_shared_contact, memorial_id FROM funeral_requests ORDER BY id") == [(None, None)] * 2
        await _scratch_execute("UPDATE funeral_requests SET accepter_shared_contact = true WHERE status = 'accepted'")
        await _refused("UPDATE funeral_requests SET accepter_shared_contact = false WHERE status = 'waiting'", {},
                       "a tick on a request nobody accepted")
        names = await _scratch_execute("SELECT conname FROM pg_constraint WHERE conrelid = 'funeral_requests'::regclass")
        assert {"ck_funeral_requests_shared_contact", "fk_funeral_requests_memorial_id_memorials"} <= {n for (n,) in names}

        _ok(_alembic("downgrade", "a3b4c5d6e7f9"))
        cols = await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'funeral_requests'")
        assert not {"accepter_shared_contact", "memorial_id"} & {c for (c,) in cols}
        assert await _scratch_execute("SELECT status FROM funeral_requests ORDER BY id") == [("accepted",), ("waiting",)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_whatsapp_and_callout_migrations_hold_their_rules_and_come_off_cleanly():
    """c5d6e7f8a9b1 and d6e7f8a9b0c2 (Steps 5b, 5c): a request from before the
    new tick has no WhatsApp agreement; a send can be to a family or a listed
    mobed; a fire temple lists a number once, with the consent's time; an
    answer is yes or no with its time, only a yes is picked, its token is
    unique, and a mobed is asked once per call-out; the downgrade takes it all
    off and keeps the requests."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "b4c5d6e7f8a0"))
        await _scratch_execute("INSERT INTO users (name, phone, account_kind) VALUES"
                               " ('Manager', '+919000000001', 'funeral_manager'), ('Er. Asked', '+919000000002', 'mobed')")
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        await _scratch_execute("INSERT INTO funeral_places (name, kind, city) VALUES ('Doongerwadi (test)', 'doongerwadi', 'Mumbai')")
        await _scratch_execute(
            "INSERT INTO funeral_records (funeral_place_id, departed_title, departed_name, death_date, death_given_by,"
            " death_roj, death_mah, death_year, calendar_system, obsequies, family_contact_name, family_contact_phone)"
            " VALUES (1, 'behdin', 'Rustom', '2026-11-17', 'date', 3, 4, 1396, 'shenshai', 'four_days', 'Family',"
            " '+919000000009')")
        await _scratch_execute("INSERT INTO funeral_requests (funeral_record_id, agyary_id, status, family_share_agreed_at,"
                               " decided_at, accepted_by_user_id) VALUES (1, 1, 'accepted', now(), now(), 2)")
        _ok(_alembic("upgrade", "head"))

        assert await _scratch_execute("SELECT family_whatsapp_agreed FROM funeral_requests") == [(False,)]
        send = ("INSERT INTO notifications (agyary_id, recipient_phone, recipient_type, recipient_id, notification_type,"
                " template_name) VALUES (1, '+919000000009', :t, 1, 'prayers_mobed_family', 'x')")
        for kind in ("family", "contact", "user"):
            await _scratch_execute(send, {"t": kind})
        await _refused(send, {"t": "stranger"}, "an unknown recipient type")

        add = ("INSERT INTO agyary_mobed_contacts (agyary_id, name, phone, consent_at, consent_by_user_id)"
               " VALUES (1, 'Er. Listed', :p, :c, 2)")
        await _scratch_execute(add, {"p": "+919000000005", "c": AT})
        await _refused(add, {"p": "+919000000005", "c": AT}, "the same number twice", needle="uq_agyary_mobed_contacts")
        await _refused(add, {"p": "98200", "c": AT}, "a number not in E.164")
        await _refused(add, {"p": "+919000000006", "c": None}, "no consent", needle="not-null")

        await _scratch_execute("INSERT INTO prayer_callouts (funeral_request_id, agyary_id, sent_by_user_id, asked)"
                               " VALUES (1, 1, 2, 1)")
        answer = ("INSERT INTO prayer_callout_answers (callout_id, contact_id, user_id, name, phone, token, answer,"
                  " answered_at, picked_at) VALUES (1, :c, :u, 'Er. Listed', :p, :t, :a, :at, :pk)")
        base = {"c": 1, "u": None, "p": "+919000000005", "t": "t" * 24, "a": "yes", "at": AT, "pk": AT}
        await _scratch_execute(answer, base)
        await _refused(answer, {**base, "p": "+919000000007"}, "a repeated token", needle="uq_prayer_callout_answers_token")
        await _refused(answer, {**base, "t": "u" * 24}, "one mobed twice in a call-out",
                       needle="uq_prayer_callout_answers_callout_phone")
        for change in ({"a": "maybe"}, {"at": None}, {"a": "no"}, {"u": 2}):
            await _refused(answer, {**base, "p": "+919000000008", "t": "v" * 24, **change}, change)
        await _scratch_execute(answer, {**base, "c": None, "u": 2, "p": "+919000000002", "t": "w" * 24,
                                        "a": None, "at": None, "pk": None})
        names = await _scratch_execute(
            "SELECT conname FROM pg_constraint WHERE conrelid IN ('agyary_mobed_contacts'::regclass,"
            " 'prayer_callouts'::regclass, 'prayer_callout_answers'::regclass, 'notifications'::regclass)")
        assert {"ck_agyary_mobed_contacts_phone_e164", "ck_prayer_callout_answers_answered",
                "ck_prayer_callout_answers_picked_said_yes", "ck_notifications_recipient_type",
                "fk_prayer_callout_answers_callout_id_prayer_callouts"} <= {n for (n,) in names}

        _ok(_alembic("downgrade", "b4c5d6e7f8a0"))
        tables = {t for (t,) in await _scratch_execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
        assert not {"agyary_mobed_contacts", "prayer_callouts", "prayer_callout_answers"} & tables
        cols = await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'funeral_requests'")
        assert "family_whatsapp_agreed" not in {c for (c,) in cols}
        assert await _scratch_execute("SELECT recipient_type FROM notifications") == [("user",)]
        assert await _scratch_execute("SELECT status FROM funeral_requests") == [("accepted",)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_khud_title_migration_lets_khud_in_and_comes_off_cleanly():
    """e7f8a9b0c1d4 (19 Nov 2026): a departed may be Khud; an unknown title is
    still refused; the downgrade calls a Khud record Behdin and keeps it."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "head"))
        await _scratch_execute("INSERT INTO funeral_places (name, kind, city) VALUES ('Doongerwadi (test)', 'doongerwadi', 'Mumbai')")
        insert = (
            "INSERT INTO funeral_records (funeral_place_id, departed_title, departed_name, death_date, death_given_by,"
            " death_roj, death_mah, death_year, calendar_system, obsequies, family_contact_name, family_contact_phone)"
            " VALUES (1, :t, 'Rustom', '2026-11-17', 'date', 3, 4, 1396, 'shenshai', 'four_days', 'Family',"
            " '+919000000009')"
        )
        await _scratch_execute(insert, {"t": "khud"})
        await _refused(insert, {"t": "mister"}, "an unknown title")
        _ok(_alembic("downgrade", "d6e7f8a9b0c2"))
        assert await _scratch_execute("SELECT departed_title, departed_name FROM funeral_records") == [("behdin", "Rustom")]
        await _refused(insert, {"t": "khud"}, "Khud before this migration")
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_funeral_book_migration_holds_its_rules_and_comes_off_cleanly():
    """f8a9b0c1d2e5 (19 Nov 2026): a place lists a number once, in E.164; the
    usual fire temple is cleared if it goes; the downgrade takes the table off."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "head"))
        await _scratch_execute("INSERT INTO funeral_places (name, kind, city) VALUES ('Doongerwadi (test)', 'doongerwadi', 'Mumbai')")
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        add = "INSERT INTO funeral_behdins (funeral_place_id, name, phone, usual_agyary_id) VALUES (1, 'Family', :p, :a)"
        await _scratch_execute(add, {"p": "+919000000009", "a": 1})
        await _refused(add, {"p": "+919000000009", "a": None}, "the same number twice", needle="uq_funeral_behdins")
        await _refused(add, {"p": "98200", "a": None}, "a number not in E.164")
        assert await _scratch_execute("SELECT is_active FROM funeral_behdins") == [(True,)]
        await _scratch_execute("DELETE FROM agyaries")
        assert await _scratch_execute("SELECT usual_agyary_id FROM funeral_behdins") == [(None,)]
        names = await _scratch_execute("SELECT conname FROM pg_constraint WHERE conrelid = 'funeral_behdins'::regclass")
        assert {"ck_funeral_behdins_phone_e164", "fk_funeral_behdins_funeral_place_id_funeral_places",
                "uq_funeral_behdins_place_phone"} <= {n for (n,) in names}
        _ok(_alembic("downgrade", "e7f8a9b0c1d4"))
        tables = {t for (t,) in await _scratch_execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
        assert "funeral_behdins" not in tables
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_request_settings_migration_holds_its_rules_and_comes_off_cleanly():
    """a9b0c1d2e3f6 (R3.1, 21 Nov 2026): a fire temple from before reads
    "everyone" and Never; the way is "everyone" or "panthaky_first", the safety
    net Never or 15, 30 or 60 minutes, under either way; the downgrade takes
    both columns off and keeps the fire temples."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "f8a9b0c1d2e5"))
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        _ok(_alembic("upgrade", "head"))
        assert await _scratch_execute("SELECT request_mode, request_escalate_minutes FROM agyaries") == [
            ("everyone", None)]
        change = "UPDATE agyaries SET request_mode = :m, request_escalate_minutes = :e"
        for ok in ({"m": "panthaky_first", "e": 15}, {"m": "panthaky_first", "e": 60},
                   {"m": "everyone", "e": 30}, {"m": "panthaky_first", "e": None}):
            await _scratch_execute(change, ok)
        for bad in ({"m": "whoever", "e": None}, {"m": "panthaky_first", "e": 45}, {"m": "everyone", "e": 0}):
            await _refused(change, bad, bad)
        await _refused("UPDATE agyaries SET request_mode = NULL", {}, "no way at all", needle="not-null")
        names = await _scratch_execute("SELECT conname FROM pg_constraint WHERE conrelid = 'agyaries'::regclass")
        assert {"ck_agyaries_request_mode", "ck_agyaries_request_escalate_minutes"} <= {n for (n,) in names}

        _ok(_alembic("downgrade", "f8a9b0c1d2e5"))
        cols = await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'agyaries'")
        assert not {"request_mode", "request_escalate_minutes"} & {c for (c,) in cols}
        assert await _scratch_execute("SELECT name FROM agyaries") == [("Agyari (test)",)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_safety_net_migration_adds_when_it_ran_and_comes_off_cleanly():
    """b0c1d2e3f4a7 (R3.1 step 2): a request from before reads NULL (the safety
    net has not run for it); it holds when the safety net ran; the downgrade
    takes the column off and keeps the requests."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "a9b0c1d2e3f6"))
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        await _scratch_execute("INSERT INTO funeral_places (name, kind, city) VALUES ('Doongerwadi (test)', 'doongerwadi', 'Mumbai')")
        await _scratch_execute(
            "INSERT INTO funeral_records (funeral_place_id, departed_title, departed_name, death_date, death_given_by,"
            " death_roj, death_mah, death_year, calendar_system, obsequies, family_contact_name, family_contact_phone)"
            " VALUES (1, 'behdin', 'Rustom', '2026-11-17', 'date', 3, 4, 1396, 'shenshai', 'four_days', 'Family',"
            " '+919000000009')")
        await _scratch_execute("INSERT INTO funeral_requests (funeral_record_id, agyary_id, status, family_share_agreed_at)"
                               " VALUES (1, 1, 'waiting', now())")
        _ok(_alembic("upgrade", "head"))
        assert await _scratch_execute("SELECT escalated_at FROM funeral_requests") == [(None,)]
        await _scratch_execute("UPDATE funeral_requests SET escalated_at = :at", {"at": AT})
        assert await _scratch_execute("SELECT escalated_at FROM funeral_requests") == [(AT,)]

        _ok(_alembic("downgrade", "a9b0c1d2e3f6"))
        cols = await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'funeral_requests'")
        assert "escalated_at" not in {c for (c,) in cols}
        assert await _scratch_execute("SELECT status FROM funeral_requests") == [("waiting",)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_board_migration_holds_its_rules_and_comes_off_cleanly():
    """c1d2e3f4a5b9 (R3.1 step 4): a request from before is not taken and not
    all set, and may now be all set; a call-out answer from before reads
    "whatsapp", and an answer comes by WhatsApp, the app, phone or "I'll pray"
    only; who took it and who recorded an answer can go without taking the
    request or the answer with them; the downgrade calls an all-set request
    accepted and takes the columns off, keeping every row."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "b0c1d2e3f4a7"))
        await _scratch_execute("INSERT INTO users (name, phone) VALUES ('Er. Panthaky', '+919000000001'),"
                               " ('Er. Asked', '+919000000002')")
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        await _scratch_execute("INSERT INTO funeral_places (name, kind, city) VALUES ('Doongerwadi (test)', 'doongerwadi', 'Mumbai')")
        await _scratch_execute(
            "INSERT INTO funeral_records (funeral_place_id, departed_title, departed_name, death_date, death_given_by,"
            " death_roj, death_mah, death_year, calendar_system, obsequies, family_contact_name, family_contact_phone)"
            " VALUES (1, 'behdin', 'Rustom', '2026-11-17', 'date', 3, 4, 1396, 'shenshai', 'four_days', 'Family',"
            " '+919000000009')")
        await _scratch_execute("INSERT INTO funeral_requests (funeral_record_id, agyary_id, status, family_share_agreed_at)"
                               " VALUES (1, 1, 'waiting', now())")
        await _scratch_execute("INSERT INTO prayer_callouts (funeral_request_id, agyary_id, asked) VALUES (1, 1, 1)")
        await _scratch_execute("INSERT INTO prayer_callout_answers (callout_id, user_id, name, phone, token)"
                               " VALUES (1, 2, 'Er. Asked', '+919000000002', :t)", {"t": "t" * 24})
        _ok(_alembic("upgrade", "head"))

        assert await _scratch_execute("SELECT status, taken_at, taken_by_user_id, all_set_at FROM funeral_requests") \
            == [("waiting", None, None, None)]
        assert await _scratch_execute("SELECT how, recorded_by_user_id FROM prayer_callout_answers") == [
            ("whatsapp", None)]
        await _scratch_execute("UPDATE funeral_requests SET taken_at = :at, taken_by_user_id = 1", {"at": AT})
        await _refused("UPDATE funeral_requests SET status = 'all_set'", {}, "all set but still undecided")
        await _scratch_execute("UPDATE funeral_requests SET status = 'all_set', all_set_at = :at, decided_at = :at",
                               {"at": AT})
        await _refused("UPDATE funeral_requests SET status = 'done'", {}, "an unknown state")
        answer = ("INSERT INTO prayer_callout_answers (callout_id, user_id, name, phone, token, how, recorded_by_user_id)"
                  " VALUES (1, 1, 'Er. Panthaky', '+919000000001', :t, :how, 1)")
        for how in ("app", "phone", "self"):
            await _scratch_execute("DELETE FROM prayer_callout_answers WHERE user_id = 1")
            await _scratch_execute(answer, {"t": how * 8, "how": how})
        await _refused(answer, {"t": "x" * 24, "how": "letter"}, "an unknown way")
        await _refused("UPDATE prayer_callout_answers SET how = NULL", {}, "no way at all", needle="not-null")
        names = await _scratch_execute(
            "SELECT conname FROM pg_constraint WHERE conrelid IN ('funeral_requests'::regclass,"
            " 'prayer_callout_answers'::regclass)")
        assert {"ck_funeral_requests_status", "fk_funeral_requests_taken_by_user_id_users",
                "ck_prayer_callout_answers_how", "fk_prayer_callout_answers_recorded_by_user_id_users"} <= {
            n for (n,) in names}
        await _scratch_execute("DELETE FROM users WHERE id = 1")
        assert await _scratch_execute("SELECT taken_by_user_id FROM funeral_requests") == [(None,)]
        assert await _scratch_execute("SELECT recorded_by_user_id FROM prayer_callout_answers ORDER BY id") == [
            (None,), (None,)]

        _ok(_alembic("downgrade", "b0c1d2e3f4a7"))
        cols = {c for (c,) in await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name IN"
            " ('funeral_requests', 'prayer_callout_answers')")}
        assert not {"taken_at", "taken_by_user_id", "all_set_at", "how", "recorded_by_user_id"} & cols
        assert await _scratch_execute("SELECT status FROM funeral_requests") == [("accepted",)]
        assert len(await _scratch_execute("SELECT id FROM prayer_callout_answers")) == 2
        await _refused("UPDATE funeral_requests SET status = 'all_set'", {}, "all set before this migration")
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_all_set_migration_holds_its_rules_and_comes_off_cleanly():
    """d2e3f4a5b6c0 (R3.1 step 5): a request from before is not confirmed short
    and was never told it is short; one book per person per request, which goes
    with the request or the person's account, while the record or the memorial
    going leaves it empty; the downgrade takes it all off, keeping the requests."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "c1d2e3f4a5b9"))
        await _scratch_execute("INSERT INTO users (name, phone) VALUES ('Er. Panthaky', '+919000000001'),"
                               " ('Er. Going', '+919000000002')")
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        await _scratch_execute("INSERT INTO funeral_places (name, kind, city) VALUES ('Doongerwadi (test)', 'doongerwadi', 'Mumbai')")
        await _scratch_execute(
            "INSERT INTO funeral_records (funeral_place_id, departed_title, departed_name, death_date, death_given_by,"
            " death_roj, death_mah, death_year, calendar_system, obsequies, family_contact_name, family_contact_phone)"
            " VALUES (1, 'behdin', 'Rustom', '2026-11-17', 'date', 3, 4, 1396, 'shenshai', 'four_days', 'Family',"
            " '+919000000009')")
        await _scratch_execute("INSERT INTO funeral_requests (funeral_record_id, agyary_id, status, family_share_agreed_at)"
                               " VALUES (1, 1, 'waiting', now())")
        _ok(_alembic("upgrade", "head"))

        assert await _scratch_execute("SELECT confirmed_short, short_alert_at FROM funeral_requests") == [(False, None)]
        await _scratch_execute("UPDATE funeral_requests SET confirmed_short = true, short_alert_at = :at", {"at": AT})
        await _refused("UPDATE funeral_requests SET confirmed_short = NULL", {}, "no answer", needle="not-null")
        await _scratch_execute("INSERT INTO customers (owner_user_id, name, phone) VALUES (2, 'Family', '+919000000009')")
        book = "INSERT INTO funeral_request_books (funeral_request_id, user_id, customer_id, is_panthaky) VALUES (1, :u, :c, :p)"
        await _scratch_execute(book, {"u": 1, "c": None, "p": True})
        await _scratch_execute(book, {"u": 2, "c": 1, "p": False})
        await _refused(book, {"u": 2, "c": 1, "p": False}, "a second book for one person", needle="unique")
        names = await _scratch_execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'funeral_request_books'::regclass")
        assert {"pk_funeral_request_books", "uq_funeral_request_books_request_user",
                "fk_funeral_request_books_funeral_request_id_funeral_requests",
                "fk_funeral_request_books_user_id_users", "fk_funeral_request_books_customer_id_customers",
                "fk_funeral_request_books_memorial_id_memorials"} <= {n for (n,) in names}
        # The family's record going (an erasure) leaves the book empty; the account going takes it.
        await _scratch_execute("DELETE FROM customers WHERE id = 1")
        assert await _scratch_execute("SELECT user_id, customer_id FROM funeral_request_books ORDER BY user_id") == [
            (1, None), (2, None)]
        await _scratch_execute("DELETE FROM users WHERE id = 1")
        assert await _scratch_execute("SELECT user_id FROM funeral_request_books") == [(2,)]

        _ok(_alembic("downgrade", "c1d2e3f4a5b9"))
        cols = {c for (c,) in await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'funeral_requests'")}
        assert not {"confirmed_short", "short_alert_at"} & cols
        assert await _scratch_execute("SELECT to_regclass('funeral_request_books')") == [(None,)]
        assert await _scratch_execute("SELECT status FROM funeral_requests") == [("waiting",)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_standby_migration_holds_its_rules_and_comes_off_cleanly():
    """e3f4a5b6c7d1 (R3.1 step 5b): an answer from before has not backed out and
    was never asked again; only someone going can back out, and who marked it
    can go without taking the answer; a re-ask has its own unguessable token
    (one per row, never another's) with when it was asked, one answer of yes or
    no with when, and when it moved on - none of them without being asked; the
    downgrade takes it all off, keeping every row, someone who backed out then
    reading as not going."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "d2e3f4a5b6c0"))
        await _scratch_execute("INSERT INTO users (name, phone) VALUES ('Er. Panthaky', '+919000000001'),"
                               " ('Er. Going', '+919000000002'), ('Er. Standby', '+919000000003')")
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        await _scratch_execute("INSERT INTO funeral_places (name, kind, city) VALUES ('Doongerwadi (test)', 'doongerwadi', 'Mumbai')")
        await _scratch_execute(
            "INSERT INTO funeral_records (funeral_place_id, departed_title, departed_name, death_date, death_given_by,"
            " death_roj, death_mah, death_year, calendar_system, obsequies, family_contact_name, family_contact_phone)"
            " VALUES (1, 'behdin', 'Rustom', '2026-11-17', 'date', 3, 4, 1396, 'shenshai', 'four_days', 'Family',"
            " '+919000000009')")
        await _scratch_execute("INSERT INTO funeral_requests (funeral_record_id, agyary_id, status, family_share_agreed_at)"
                               " VALUES (1, 1, 'waiting', now())")
        await _scratch_execute("INSERT INTO prayer_callouts (funeral_request_id, agyary_id, asked) VALUES (1, 1, 2)")
        answer = ("INSERT INTO prayer_callout_answers (callout_id, user_id, name, phone, token, answer, answered_at,"
                  " picked_at) VALUES (1, :u, :n, :p, :t, 'yes', :at, :picked)")
        await _scratch_execute(answer, {"u": 2, "n": "Er. Going", "p": "+919000000002", "t": "g" * 24, "at": AT,
                                        "picked": AT})
        await _scratch_execute(answer, {"u": 3, "n": "Er. Standby", "p": "+919000000003", "t": "s" * 24, "at": AT,
                                        "picked": None})
        _ok(_alembic("upgrade", "head"))

        assert await _scratch_execute(
            "SELECT backed_out_at, backed_out_by_user_id, reask_token, reasked_at, reask_answer, reask_answered_at,"
            " reask_passed_at FROM prayer_callout_answers ORDER BY id") == [(None,) * 7, (None,) * 7]
        going, standby = "WHERE user_id = 2", "WHERE user_id = 3"
        await _refused(f"UPDATE prayer_callout_answers SET backed_out_at = :at {standby}", {"at": AT},
                       "backing out without going")
        await _scratch_execute(f"UPDATE prayer_callout_answers SET backed_out_at = :at, backed_out_by_user_id = 1"
                               f" {going}", {"at": AT})
        await _refused(f"UPDATE prayer_callout_answers SET reask_token = :t {standby}", {"t": "r" * 24},
                       "a token without being asked")
        await _refused(f"UPDATE prayer_callout_answers SET reask_answer = 'yes', reask_answered_at = :at {standby}",
                       {"at": AT}, "an answer without being asked")
        await _refused(f"UPDATE prayer_callout_answers SET reask_passed_at = :at {standby}", {"at": AT},
                       "moving on without asking")
        await _scratch_execute(f"UPDATE prayer_callout_answers SET reask_token = :t, reasked_at = :at {standby}",
                               {"t": "r" * 24, "at": AT})
        await _refused(f"UPDATE prayer_callout_answers SET reask_answer = 'maybe', reask_answered_at = :at {standby}",
                       {"at": AT}, "an unknown answer")
        await _refused(f"UPDATE prayer_callout_answers SET reask_answer = 'no' {standby}", {}, "an answer with no time")
        await _scratch_execute(f"UPDATE prayer_callout_answers SET reask_answer = 'no', reask_answered_at = :at,"
                               f" reask_passed_at = :at {standby}", {"at": AT})
        await _refused(f"UPDATE prayer_callout_answers SET reask_token = :t, reasked_at = :at {going}",
                       {"t": "r" * 24, "at": AT}, "one re-ask token on two rows", needle="unique")
        names = await _scratch_execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'prayer_callout_answers'::regclass")
        assert {"uq_prayer_callout_answers_reask_token", "fk_prayer_callout_answers_backed_out_by_user_id_users",
                "ck_prayer_callout_answers_backed_out_was_going", "ck_prayer_callout_answers_reasked",
                "ck_prayer_callout_answers_reask_answer", "ck_prayer_callout_answers_reask_answered",
                "ck_prayer_callout_answers_reask_answer_asked",
                "ck_prayer_callout_answers_reask_passed_asked"} <= {n for (n,) in names}
        await _scratch_execute("DELETE FROM users WHERE id = 1")
        assert await _scratch_execute(f"SELECT backed_out_by_user_id FROM prayer_callout_answers {going}") == [(None,)]

        _ok(_alembic("downgrade", "d2e3f4a5b6c0"))
        cols = {c for (c,) in await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'prayer_callout_answers'")}
        assert not {"backed_out_at", "backed_out_by_user_id", "reask_token", "reasked_at", "reask_answer",
                    "reask_answered_at", "reask_passed_at"} & cols
        assert await _scratch_execute("SELECT user_id, answer, picked_at FROM prayer_callout_answers ORDER BY id") == [
            (2, "yes", None), (3, "yes", None)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_no_answer_migration_adds_when_the_place_was_told_and_comes_off_cleanly():
    """f4a5b6c7d8e2 (R3.1 step 6): a request from before reads NULL (the place
    was never told nobody answered); it holds when it was told, never before
    the request was sent; the downgrade takes it off and keeps the requests."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "e3f4a5b6c7d1"))
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        await _scratch_execute("INSERT INTO funeral_places (name, kind, city) VALUES ('Doongerwadi (test)', 'doongerwadi', 'Mumbai')")
        await _scratch_execute(
            "INSERT INTO funeral_records (funeral_place_id, departed_title, departed_name, death_date, death_given_by,"
            " death_roj, death_mah, death_year, calendar_system, obsequies, family_contact_name, family_contact_phone)"
            " VALUES (1, 'behdin', 'Rustom', '2026-11-17', 'date', 3, 4, 1396, 'shenshai', 'four_days', 'Family',"
            " '+919000000009')")
        await _scratch_execute("INSERT INTO funeral_requests (funeral_record_id, agyary_id, status, family_share_agreed_at,"
                               " sent_at) VALUES (1, 1, 'waiting', :at, :at)", {"at": AT})
        _ok(_alembic("upgrade", "head"))

        assert await _scratch_execute("SELECT no_answer_alert_at FROM funeral_requests") == [(None,)]
        await _refused("UPDATE funeral_requests SET no_answer_alert_at = :before",
                       {"before": datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)}, "told before it was sent")
        told = datetime(2026, 11, 18, 11, 0, tzinfo=timezone.utc)
        await _scratch_execute("UPDATE funeral_requests SET no_answer_alert_at = :at", {"at": told})
        assert await _scratch_execute("SELECT no_answer_alert_at FROM funeral_requests") == [(told,)]
        names = await _scratch_execute("SELECT conname FROM pg_constraint WHERE conrelid = 'funeral_requests'::regclass")
        assert "ck_funeral_requests_no_answer_after_sent" in {n for (n,) in names}

        _ok(_alembic("downgrade", "e3f4a5b6c7d1"))
        cols = await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'funeral_requests'")
        assert "no_answer_alert_at" not in {c for (c,) in cols}
        assert await _scratch_execute("SELECT status FROM funeral_requests") == [("waiting",)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_nobody_could_migration_marks_only_a_declined_request_and_comes_off_cleanly():
    """a5b6c7d8e9f4 (R3.1 step 7): every request from before reads false (declined by
    someone, even with who declined gone); only a declined request can be marked as closed
    because nobody could take it; the downgrade takes it off and keeps the requests."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "f4a5b6c7d8e2"))
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        await _scratch_execute("INSERT INTO funeral_places (name, kind, city) VALUES ('Doongerwadi (test)', 'doongerwadi', 'Mumbai')")
        for _ in range(2):
            await _scratch_execute(
                "INSERT INTO funeral_records (funeral_place_id, departed_title, departed_name, death_date, death_given_by,"
                " death_roj, death_mah, death_year, calendar_system, obsequies, family_contact_name, family_contact_phone)"
                " VALUES (1, 'behdin', 'Rustom', '2026-11-17', 'date', 3, 4, 1396, 'shenshai', 'four_days', 'Family',"
                " '+919000000009')")
        await _scratch_execute("INSERT INTO funeral_requests (funeral_record_id, agyary_id, status, family_share_agreed_at,"
                               " sent_at, decided_at) VALUES (1, 1, 'declined', :at, :at, :at)", {"at": AT})
        await _scratch_execute("INSERT INTO funeral_requests (funeral_record_id, agyary_id, status, family_share_agreed_at,"
                               " sent_at) VALUES (2, 1, 'waiting', :at, :at)", {"at": AT})
        _ok(_alembic("upgrade", "head"))

        assert await _scratch_execute("SELECT status, nobody_could FROM funeral_requests ORDER BY id") == [
            ("declined", False), ("waiting", False)]
        await _refused("UPDATE funeral_requests SET nobody_could = true WHERE status = 'waiting'", {},
                       "nobody could, on a request still waiting")
        await _refused("UPDATE funeral_requests SET nobody_could = NULL", {}, "no answer", needle="not-null")
        await _scratch_execute("UPDATE funeral_requests SET nobody_could = true WHERE status = 'declined'")
        assert await _scratch_execute("SELECT nobody_could FROM funeral_requests ORDER BY id") == [(True,), (False,)]
        names = await _scratch_execute("SELECT conname FROM pg_constraint WHERE conrelid = 'funeral_requests'::regclass")
        assert "ck_funeral_requests_nobody_could_declined" in {n for (n,) in names}

        _ok(_alembic("downgrade", "f4a5b6c7d8e2"))
        cols = await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'funeral_requests'")
        assert "nobody_could" not in {c for (c,) in cols}
        assert await _scratch_execute("SELECT status FROM funeral_requests ORDER BY id") == [("declined",), ("waiting",)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_join_confirmation_migration_confirms_every_membership_from_before_and_comes_off_cleanly():
    """b6c7d8e9f0a5 (D10, owner 22 Nov 2026): every membership that exists when it runs is
    confirmed for prayer requests (memberships from before stay confirmed), with nobody
    recorded as confirming it and nobody taken off; who did it is kept only with when, and
    goes without the membership if their account does; the downgrade takes it off and
    keeps every membership as it was."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "a5b6c7d8e9f4"))
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        for phone in ("+919000000001", "+919000000002", "+919000000003"):
            await _scratch_execute("INSERT INTO users (name, phone) VALUES ('Er. Test', :p)", {"p": phone})
        u1, u2, admin = [u for (u,) in await _scratch_execute("SELECT id FROM users ORDER BY id")]
        await _scratch_execute("INSERT INTO agyary_users (agyary_id, user_id, role) VALUES (1, :u, 'panthaky')",
                               {"u": u1})
        await _scratch_execute("INSERT INTO agyary_users (agyary_id, user_id, role, is_active)"
                               " VALUES (1, :u, 'mobed', false)", {"u": u2})
        _ok(_alembic("upgrade", "head"))

        rows = await _scratch_execute(
            "SELECT user_id, role, is_active, requests_confirmed_at IS NOT NULL, requests_confirmed_by_user_id,"
            " requests_off_at, requests_off_by_user_id FROM agyary_users ORDER BY user_id")
        assert rows == [(u1, "panthaky", True, True, None, None, None), (u2, "mobed", False, True, None, None, None)]
        # A membership made afterwards is not confirmed until someone confirms it.
        await _scratch_execute("INSERT INTO agyary_users (agyary_id, user_id, role) VALUES (1, :u, 'mobed')",
                               {"u": admin})
        assert await _scratch_execute(
            "SELECT requests_confirmed_at FROM agyary_users WHERE user_id = :u", {"u": admin}) == [(None,)]
        await _refused("UPDATE agyary_users SET requests_confirmed_by_user_id = :a, requests_confirmed_at = NULL"
                       " WHERE user_id = :u", {"a": u1, "u": u2}, "confirmed by someone, with no time")
        await _refused("UPDATE agyary_users SET requests_off_by_user_id = :a WHERE user_id = :u",
                       {"a": u1, "u": u2}, "taken off by someone, with no time")
        await _scratch_execute("UPDATE agyary_users SET requests_off_at = :at, requests_off_by_user_id = :a"
                               " WHERE user_id = :u", {"at": AT, "a": admin, "u": u2})
        names = await _scratch_execute("SELECT conname FROM pg_constraint WHERE conrelid = 'agyary_users'::regclass")
        assert {"ck_agyary_users_requests_confirmed_by", "ck_agyary_users_requests_off_by",
                "fk_agyary_users_requests_confirmed_by_user_id_users",
                "fk_agyary_users_requests_off_by_user_id_users"} <= {n for (n,) in names}
        # Whoever took them off goes; the membership and when stay.
        await _scratch_execute("DELETE FROM agyary_users WHERE user_id = :u", {"u": admin})
        await _scratch_execute("DELETE FROM users WHERE id = :u", {"u": admin})
        assert await _scratch_execute(
            "SELECT requests_off_at IS NOT NULL, requests_off_by_user_id FROM agyary_users WHERE user_id = :u",
            {"u": u2}) == [(True, None)]

        _ok(_alembic("downgrade", "a5b6c7d8e9f4"))
        cols = await _scratch_execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'agyary_users'")
        assert not {"requests_confirmed_at", "requests_confirmed_by_user_id", "requests_off_at",
                    "requests_off_by_user_id"} & {c for (c,) in cols}
        assert await _scratch_execute("SELECT user_id, role, is_active FROM agyary_users ORDER BY user_id") == [
            (u1, "panthaky", True), (u2, "mobed", False)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_lagan_and_vendidad_migration_renames_only_the_standard_names_and_comes_off_cleanly():
    """c7d8e9f0a1b6 (D11, the owner's word review of 23 Nov 2026): a fire temple's service
    named exactly "Wedding" or "Vandidad" (the old standard list) becomes "Lagan" or
    "Vendidad"; a service a mobed named differently is untouched, and so is one at a fire
    temple that already has the new name; the downgrade renames them back, exact matches only."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "b6c7d8e9f0a5"))
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai'),"
                               " ('Another agyari (test)', 'Surat')")
        before = [(1, "Jashan"), (1, "Wedding"), (1, "Vandidad"), (1, "Wedding ceremony"), (1, "vandidad night"),
                  (2, "Wedding"), (2, "lagan"), (2, "VANDIDAD")]
        for agyary_id, name in before:
            await _scratch_execute("INSERT INTO services (agyary_id, name) VALUES (:a, :n)",
                                   {"a": agyary_id, "n": name})
        ids = [i for (i,) in await _scratch_execute("SELECT id FROM services ORDER BY id")]
        _ok(_alembic("upgrade", "head"))

        renamed = [(1, "Jashan"), (1, "Lagan"), (1, "Vendidad"), (1, "Wedding ceremony"), (1, "vandidad night"),
                   # The second already has a "lagan" of its own, so its "Wedding" stays; "VANDIDAD" is not exact.
                   (2, "Wedding"), (2, "lagan"), (2, "VANDIDAD")]
        assert await _scratch_execute("SELECT id, agyary_id, name FROM services ORDER BY id") == [
            (i, a, n) for i, (a, n) in zip(ids, renamed)]

        _ok(_alembic("downgrade", "b6c7d8e9f0a5"))
        assert await _scratch_execute("SELECT id, agyary_id, name FROM services ORDER BY id") == [
            (i, a, n) for i, (a, n) in zip(ids, before)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_dasmu_and_chhamsi_migration_relabels_only_those_days_and_comes_off_cleanly():
    """d8e9f0a1b2c7 (D11, the owner's word review of 23 Nov 2026): a memorial's day labelled
    exactly "Dasmi" or "Chamsi", past or to come, reads "Dasmu" or "Chhamsi"; its date, Roj,
    Mah, code and everything else stay; any other label is untouched; the downgrade gives
    the old spelling back, exact matches only."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "c7d8e9f0a1b6"))
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Agyari (test)', 'Mumbai')")
        await _scratch_execute("INSERT INTO users (name, phone) VALUES ('Er. Test', '+919000000001')")
        await _scratch_execute("INSERT INTO customers (owner_user_id, name, phone) VALUES (1, 'Family', '+919000000009')")
        await _scratch_execute(
            "INSERT INTO memorials (agyary_id, customer_id, created_by_user_id, departed_name, death_gregorian,"
            " death_roj, death_mah, death_year, calendar_system, opening)"
            " VALUES (1, 1, 1, 'Rustom', '2026-05-01', 3, 10, 1395, 'shenshai', 'none')")
        before = [("day_10", "Dasmi", 10, date(2026, 5, 10)), ("day_29", "Deci", 29, date(2026, 5, 29)),
                  ("day_30", "Masiso", 30, date(2026, 5, 30)), ("day_180", "Chamsi", 180, date(2026, 10, 27)),
                  ("year_1", "Year 1", 361, date(2027, 4, 26)), ("day_9", "dasmi", 9, date(2026, 5, 9))]
        for code, label, day_number, when in before:
            await _scratch_execute(
                "INSERT INTO memorial_observances (memorial_id, code, label, day_number, gregorian_date,"
                " parsi_roj, parsi_mah, parsi_year, paid_at) VALUES (1, :c, :l, :n, :d, 3, 10, 1395, :paid)",
                {"c": code, "l": label, "n": day_number, "d": when, "paid": AT if code == "day_10" else None})
        read = ("SELECT code, label, day_number, gregorian_date, parsi_roj, parsi_mah, parsi_year, paid_at IS NOT NULL"
                " FROM memorial_observances ORDER BY id")
        kept = [(c, n, d, 3, 10, 1395, c == "day_10") for c, _, n, d in before]
        _ok(_alembic("upgrade", "head"))

        rows = await _scratch_execute(read)
        assert [r[1] for r in rows] == ["Dasmu", "Deci", "Masiso", "Chhamsi", "Year 1", "dasmi"]
        assert [(r[0], *r[2:]) for r in rows] == kept

        _ok(_alembic("downgrade", "c7d8e9f0a1b6"))
        rows = await _scratch_execute(read)
        assert [r[1] for r in rows] == [label for _, label, _, _ in before]
        assert [(r[0], *r[2:]) for r in rows] == kept
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_state_names_migration_changes_only_the_exact_token_and_comes_off_cleanly():
    """e9f0a1b2c3d8 (D11, the owner's word review of 23 Nov 2026): a fire temple's address
    that is, or ends in ", ", one of the list's old state names (Gujerat, Rajashtan, A.P,
    A.P., MP, UP) reads Gujarat, Rajasthan, Telangana, Madhya Pradesh or Uttar Pradesh;
    the same letters anywhere else, the name and the city are untouched; the downgrade puts
    the old names back, exact tokens only ("A.P." comes back as "A.P", as in the seed list)."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "d8e9f0a1b2c7"))
        rows = [
            ("Udwada Town, Gujerat", "Udwada Town, Gujarat"),
            ("Gujerat", "Gujarat"),
            ("Tilak Road, A.P", "Tilak Road, Telangana"),
            ("M G Road, A.P.", "M G Road, Telangana"),
            ("397, Centre Street, MP", "397, Centre Street, Madhya Pradesh"),
            ("M G Rd, Civil Lines, UP", "M G Rd, Civil Lines, Uttar Pradesh"),
            ("Shri Ambaji Road, Rajashtan", "Shri Ambaji Road, Rajasthan"),
            # Not the exact token: left as they are.
            ("UP Market Road, Maharashtra", "UP Market Road, Maharashtra"),
            ("Gujerat Lane, Tardeo", "Gujerat Lane, Tardeo"),
            ("Near MP", "Near MP"),
            ("Tarota Bazar,Gujerat", "Tarota Bazar,Gujerat"),
            (None, None),
        ]
        for i, (address, _) in enumerate(rows):
            await _scratch_execute("INSERT INTO agyaries (name, city, address) VALUES (:n, 'Gujerat', :a)",
                                   {"n": f"Gujerat Adarian {i} (test)", "a": address})
        read = "SELECT name, city, address FROM agyaries ORDER BY id"
        _ok(_alembic("upgrade", "head"))

        assert await _scratch_execute(read) == [
            (f"Gujerat Adarian {i} (test)", "Gujerat", new) for i, (_, new) in enumerate(rows)]

        _ok(_alembic("downgrade", "d8e9f0a1b2c7"))
        back = [old if old != "M G Road, A.P." else "M G Road, A.P" for old, _ in rows]
        assert await _scratch_execute(read) == [
            (f"Gujerat Adarian {i} (test)", "Gujerat", old) for i, old in enumerate(back)]
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_person_names_migration_holds_its_rules_and_comes_off_cleanly():
    """a1b2c3d4e5f9 (D12, 24 Nov 2026): the pool of a person's departed names holds an E.164
    number and a known title, keeps its row when the record that made it goes, and the
    downgrade takes the table off."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "head"))
        add = ("INSERT INTO person_names (phone, departed_title, departed_name, source_record_id)"
               " VALUES (:p, :t, 'Name (test)', :r)")
        await _scratch_execute(add, {"p": "+919000000009", "t": "ervad", "r": None})
        await _refused(add, {"p": "98200", "t": "ervad", "r": None}, "a number not in E.164")
        await _refused(add, {"p": "+919000000009", "t": "mr", "r": None}, "an unknown title")
        assert await _scratch_execute("SELECT source, departed_name FROM person_names") == [("death_record", "Name (test)")]
        names = await _scratch_execute("SELECT conname FROM pg_constraint WHERE conrelid = 'person_names'::regclass")
        assert {"ck_person_names_phone_e164", "ck_person_names_departed_title",
                "fk_person_names_source_record_id_funeral_records"} <= {n for (n,) in names}
        _ok(_alembic("downgrade", "e9f0a1b2c3d8"))
        tables = {t for (t,) in await _scratch_execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
        assert "person_names" not in tables
        _ok(_alembic("upgrade", "head"))
    finally:
        await _recreate(drop_only=True)


async def test_the_place_change_migration_holds_its_rules_and_comes_off_cleanly():
    """b2c3d4e5f6a0 (owner, 24 Nov 2026): a manager's request to move holds a known status, at most
    one is pending per manager, a decided one does not count against that, and the downgrade
    takes the table off without touching the places or the manager."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "head"))
        await _scratch_execute("INSERT INTO users (name, phone) VALUES ('Manager (test)', '+919000000011')")
        for n in ("Old place (test)", "New place (test)"):
            await _scratch_execute(
                "INSERT INTO funeral_places (name, kind, city) VALUES (:n, 'doongerwadi', 'Mumbai')", {"n": n})
        (user,), = await _scratch_execute("SELECT id FROM users")
        (old,), (new,) = await _scratch_execute("SELECT id FROM funeral_places ORDER BY id")
        add = ("INSERT INTO place_change_requests (user_id, from_place_id, to_place_id, status)"
               " VALUES (:u, :f, :t, :s)")
        args = {"u": user, "f": old, "t": new}
        await _scratch_execute(add, {**args, "s": "declined"})
        await _scratch_execute(add, {**args, "s": "pending"})
        await _refused(add, {**args, "s": "pending"}, "a second pending request for the same manager", "unique")
        await _refused(add, {**args, "s": "maybe"}, "an unknown status")
        await _scratch_execute(add, {**args, "s": "cancelled"})   # decided ones are not limited
        names = await _scratch_execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'place_change_requests'::regclass")
        assert {"ck_place_change_requests_status", "fk_place_change_requests_user_id_users",
                "fk_place_change_requests_decided_by_user_id_users"} <= {n for (n,) in names}
        _ok(_alembic("downgrade", "a1b2c3d4e5f9"))
        tables = {t for (t,) in await _scratch_execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
        assert "place_change_requests" not in tables
        assert len(await _scratch_execute("SELECT id FROM funeral_places")) == 2
        _ok(_alembic("upgrade", "head"))
        _ok(_alembic("check"))
    finally:
        await _recreate(drop_only=True)


async def test_the_behdin_kind_migration_allows_behdin_and_refuses_to_come_down_over_one():
    """c3d4e5f6a0b1: account_kind may be 'behdin'; nothing else new is allowed;
    going back refuses while a behdin account exists (nothing is deleted, D8)
    and works once there is none."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "head"))
        add = "INSERT INTO users (name, phone, account_kind) VALUES ('Person (test)', :p, :k)"
        await _scratch_execute(add, {"p": "+919000000021", "k": "behdin"})
        await _scratch_execute(add, {"p": "+919000000022", "k": "mobed"})
        await _scratch_execute(add, {"p": "+919000000023", "k": "funeral_manager"})
        await _refused(add, {"p": "+919000000024", "k": "trustee"}, "an unknown kind")
        down = _alembic("downgrade", "b2c3d4e5f6a0")
        assert down.returncode != 0 and "behdin account" in (down.stdout + down.stderr)
        assert len(await _scratch_execute("SELECT id FROM users")) == 3
        await _scratch_execute("UPDATE users SET account_kind = 'mobed' WHERE account_kind = 'behdin'")
        _ok(_alembic("downgrade", "b2c3d4e5f6a0"))
        await _refused(add, {"p": "+919000000025", "k": "behdin"}, "behdin after coming down")
        _ok(_alembic("upgrade", "head"))
        _ok(_alembic("check"))
    finally:
        await _recreate(drop_only=True)


async def test_the_r41_migration_backfills_kinds_holds_its_rules_and_refuses_to_come_down_over_data():
    """d4e5f6a0b1c2 (R4.1): agyari kinds are read from the name (else left empty), a person's own
    events and memorials hold their rules and go with the account, and going back refuses while a
    person's data exists (D8) and works once there is none."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "c3d4e5f6a0b1"))
        for n in ("Wadia Atash Behram (test)", "Test Dadgah", "Test Anjuman Adaran", "Test Agiyari",
                  "Test Trust Hall"):
            await _scratch_execute("INSERT INTO agyaries (name, city) VALUES (:n, 'Mumbai')", {"n": n})
        _ok(_alembic("upgrade", "head"))
        kinds = dict(await _scratch_execute("SELECT name, kind FROM agyaries"))
        assert kinds == {"Wadia Atash Behram (test)": "atash_behram", "Test Dadgah": "dadgah",
                         "Test Anjuman Adaran": "adaran", "Test Agiyari": "adaran", "Test Trust Hall": None}
        await _refused("UPDATE agyaries SET kind = 'temple' WHERE name = 'Test Dadgah'", {}, "an unknown kind")

        await _scratch_execute("INSERT INTO users (name, phone, account_kind) VALUES ('Person (test)', "
                               "'+919000000031', 'behdin')")
        (user,), = await _scratch_execute("SELECT id FROM users")
        (agyary,) = (await _scratch_execute("SELECT id FROM agyaries LIMIT 1"))[0]
        await _scratch_execute("INSERT INTO person_agyari (user_id, agyary_id) VALUES (:u, :a)",
                               {"u": user, "a": agyary})
        event = ("INSERT INTO person_events (user_id, title, kind, gregorian_date, repeats, parsi_roj, parsi_mah,"
                 " parsi_calendar) VALUES (:u, 'Birthday (test)', :k, '2000-01-01', :r, :roj, :mah, :cal)")
        ok = {"u": user, "k": "birthday", "r": "yearly_parsi", "roj": 1, "mah": 1, "cal": "shenshai"}
        await _scratch_execute(event, ok)
        await _refused(event, {**ok, "k": "party"}, "an unknown event kind")
        await _refused(event, {**ok, "r": "weekly"}, "an unknown repeat")
        await _refused(event, {**ok, "roj": None}, "a Parsi repeat without its Roj")
        await _refused(event, {**ok, "r": "none"}, "a Roj and Mah on an event that does not repeat by Parsi date")
        memorial = ("INSERT INTO person_memorials (user_id, departed_name, death_gregorian, death_roj, death_mah,"
                    " death_year, calendar_system, opening) VALUES (:u, 'Name (test)', '2026-01-01', 1, 1, 1395,"
                    " :c, :o)")
        await _scratch_execute(memorial, {"u": user, "c": "shenshai", "o": "none"})
        await _refused(memorial, {"u": user, "c": "gregorian", "o": "none"}, "an unknown calendar")
        await _refused(memorial, {"u": user, "c": "shenshai", "o": "forever"}, "an unknown opening")

        down = _alembic("downgrade", "c3d4e5f6a0b1")
        assert down.returncode != 0 and "own data exists" in (down.stdout + down.stderr)
        assert len(await _scratch_execute("SELECT id FROM person_events")) == 1
        # Deleting the account takes all of it (the foreign keys cascade).
        await _scratch_execute("DELETE FROM users WHERE id = :u", {"u": user})
        for table in ("person_agyari", "person_memorials", "person_memorial_observances", "person_events"):
            assert await _scratch_execute(f"SELECT 1 FROM {table}") == []
        _ok(_alembic("downgrade", "c3d4e5f6a0b1"))
        tables = {t for (t,) in await _scratch_execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
        assert not {"person_agyari", "person_memorials", "person_events"} & tables
        _ok(_alembic("upgrade", "head"))
        _ok(_alembic("check"))
    finally:
        await _recreate(drop_only=True)


async def test_the_service_asks_migration_holds_its_rules_and_comes_off_cleanly():
    """e5f6a0b1c2d3 (R4.2): an agyari does not take asks until switched on, an ask holds its rules
    (a kind, a status, a purpose, a geh or a time, a repeat only when repeating), goes with the
    person's account, leaves the panthaky's own record when that record goes, and going back
    refuses while any ask exists (D8)."""
    await _recreate()
    try:
        _ok(_alembic("upgrade", "d4e5f6a0b1c2"))
        await _scratch_execute("INSERT INTO agyaries (name, city) VALUES ('Asked (test)', 'Mumbai')")
        _ok(_alembic("upgrade", "head"))
        assert await _scratch_execute("SELECT takes_asks FROM agyaries") == [(False,)]
        await _scratch_execute("INSERT INTO users (name, phone, account_kind) VALUES ('Person (test)', "
                               "'+919000000041', 'behdin')")
        (user,), = await _scratch_execute("SELECT id FROM users")
        (agyary,), = await _scratch_execute("SELECT id FROM agyaries")
        await _scratch_execute("INSERT INTO services (agyary_id, name) VALUES (:a, 'Jashan (test)')", {"a": agyary})
        (service,), = await _scratch_execute("SELECT id FROM services")
        insert = ("INSERT INTO service_asks (user_id, agyary_id, service_id, kind, purpose, ceremony_date, geh,"
                  " ceremony_time, venue, status, repeat_pattern, memorial_codes)"
                  " VALUES (:u, :a, :s, :k, :p, '2026-12-01', :g, :t, :v, :st, :rp, :mc)")
        ok = {"u": user, "a": agyary, "s": service, "k": "single", "p": "gujrela_nu", "g": None, "t": None,
              "v": "agyari", "st": "waiting", "rp": None, "mc": None}
        ok["t"] = time(10, 0)
        await _scratch_execute(insert, ok)
        await _scratch_execute(insert, {**ok, "p": "patet", "g": 2, "t": None})
        await _refused(insert, {**ok, "k": "weekly"}, "an unknown kind")
        await _refused(insert, {**ok, "st": "maybe"}, "an unknown status")
        await _refused(insert, {**ok, "p": "tandarosti_x"}, "an unknown purpose")
        await _refused(insert, {**ok, "v": "street"}, "an unknown place")
        await _refused(insert, {**ok, "g": 6, "t": None}, "a geh that does not exist")
        await _refused(insert, {**ok, "t": None}, "neither a geh nor a time")
        await _refused(insert, {**ok, "g": 1}, "both a geh and a time")
        await _refused(insert, {**ok, "rp": "monthly"}, "a repeat on an ask that does not repeat")
        await _refused(insert, {**ok, "k": "repeating"}, "a repeating ask without its repeat")
        await _refused(insert, {**ok, "mc": '["day_10"]'}, "memorial dates on an ask that is not a memorial")

        # What an accept made is the panthaky's own: it can go without taking the ask with it.
        await _scratch_execute("INSERT INTO customers (owner_user_id, phone, name) VALUES (:u, '+919000000042', 'Fam')",
                               {"u": user})
        (customer,), = await _scratch_execute("SELECT id FROM customers")
        await _scratch_execute("UPDATE service_asks SET result_customer_id = :c", {"c": customer})
        await _scratch_execute("DELETE FROM customers WHERE id = :c", {"c": customer})
        assert await _scratch_execute("SELECT result_customer_id FROM service_asks") == [(None,), (None,)]

        down = _alembic("downgrade", "d4e5f6a0b1c2")
        assert down.returncode != 0 and "asks" in (down.stdout + down.stderr)
        assert len(await _scratch_execute("SELECT id FROM service_asks")) == 2
        # Deleting the account takes its asks (the foreign key cascades).
        await _scratch_execute("DELETE FROM users WHERE id = :u", {"u": user})
        assert await _scratch_execute("SELECT 1 FROM service_asks") == []
        _ok(_alembic("downgrade", "d4e5f6a0b1c2"))
        cols = await _scratch_execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'agyaries'")
        assert "takes_asks" not in {c for (c,) in cols}
        _ok(_alembic("upgrade", "head"))
        _ok(_alembic("check"))
    finally:
        await _recreate(drop_only=True)
