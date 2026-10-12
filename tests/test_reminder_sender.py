"""Sending reminders automatically: who is planned, what is posted to Meta,
and what happens when it goes wrong.

Meta is a mock transport throughout - nothing here can reach a real number.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from agyary.core.config import Settings
from agyary.models import Notification
from agyary.services import reminder_message, reminder_sender, reminder_worker, reminders
from agyary.services.reminder_sender import IST
from tests.test_mobed_api import NEW_MOBED_PHONE, _member_headers

BEHDIN_PHONE = "+919944400701"
OTHER_PHONE = "+919944400702"
DEATH = date(2030, 3, 10)


def _settings(**over) -> Settings:
    base = dict(
        reminders_send_mode="live", reminders_allowlist="*", whatsapp_access_token="test-token",
        whatsapp_phone_number_id="555000111", whatsapp_graph_version="v99.0",
        whatsapp_reminder_template="memorial_reminder", whatsapp_template_language="en",
        jwt_secret_key="x",
    )
    return Settings(**{**base, **over})


def _evening(day_before: date, hour: int = 19, minute: int = 30) -> datetime:
    """A moment on the evening before ``day_before + 1``, in IST."""
    return datetime.combine(day_before, time(hour, minute), tzinfo=IST)


class FakeMeta:
    """Stands in for graph.facebook.com and records what it was sent."""

    def __init__(self, status: int = 200, body: dict | None = None):
        self.status, self.calls = status, []
        self.body = body

    def client(self) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            body = self.body
            if body is None:
                body = ({"messages": [{"id": f"wamid.{len(self.calls)}"}]} if self.status == 200
                        else {"error": {"message": "Template not approved"}})
            return httpx.Response(self.status, json=body)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _scenario(client, db, seeded, *, enable=True, phone=BEHDIN_PHONE, which=0):
    """A mobed with a behdin and a memorial far ahead; returns the pieces and
    the evening on which one of its later observances is "tomorrow"."""
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    behdin = (await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                                json={"name": "Delzeen Test", "phone": phone}, headers=headers)).json()
    services = (await client.get(f"/api/mobed/agyaries/{aid}/services", headers=headers)).json()
    ids = [s["id"] for s in services if s["name"] in ("Afringan", "Baaj")]
    made = await client.post(
        f"/api/mobed/agyaries/{aid}/behdins/{behdin['id']}/memorials", headers=headers,
        json={"departed_name": "Ardeshir Mehta", "death_date": DEATH.isoformat(),
              "opening": "days_1_to_10", "day_counts": [30], "monthly": {"count": 3}, "service_ids": ids})
    assert made.status_code == 200, made.text
    observances = made.json()["observances"]
    later = [o for o in observances if o["day_number"] > 10]
    opening = [o for o in observances if o["day_number"] <= 10]
    if enable:
        r = await client.put(f"/api/mobed/agyaries/{aid}/behdins/{behdin['id']}/reminders",
                             json={"enabled": True}, headers=headers)
        assert r.status_code == 200, r.text
    target = date.fromisoformat(later[which]["date"])
    return aid, behdin["id"], headers, later, opening, _evening(target - timedelta(days=1))


async def _rows(db):
    return (await db.execute(select(Notification).order_by(Notification.id))).scalars().all()


async def _owner_notes(client, headers):
    return (await client.get("/api/mobed/notifications", headers=headers)).json()


# --- Planning ---------------------------------------------------------------

async def test_tomorrows_reminder_is_planned_with_the_template_blanks_filled(client, db, seeded):
    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 1
    await db.commit()

    [n] = await _rows(db)
    assert (n.status, n.notification_type, n.recipient_phone) == ("pending", "memorial_reminder", BEHDIN_PHONE)
    assert n.template_name == "memorial_reminder" and n.recipient_type == "customer" and n.recipient_id == cid
    assert n.template_params["1"] == "Goti Adarian"
    assert n.template_params["2"].startswith("Tomorrow, ")
    assert n.template_params["3"].startswith("Roj ")
    assert n.template_params["4"] == "Afringan and Baaj for Ardeshir Mehta."


async def test_planning_twice_plans_once(client, db, seeded):
    *_, now = await _scenario(client, db, seeded)
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 1
    await db.commit()
    # A restart, or two deploys overlapping: the second plan finds it done.
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 0
    await db.commit()
    assert len(await _rows(db)) == 1


async def test_nobody_is_planned_unless_the_mobed_turned_reminders_on(client, db, seeded):
    *_, now = await _scenario(client, db, seeded, enable=False)
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 0


async def test_a_person_who_said_stop_is_never_planned(client, db, seeded):
    *_, now = await _scenario(client, db, seeded)
    await reminders.record_stop(db, BEHDIN_PHONE)
    await db.commit()
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 0


async def test_the_opening_days_are_never_planned(client, db, seeded):
    aid, cid, headers, later, opening, _ = await _scenario(client, db, seeded)
    for obs in opening:
        evening = _evening(date.fromisoformat(obs["date"]) - timedelta(days=1))
        assert await reminder_sender.plan_tomorrow(db, evening, _settings()) == 0, obs["label"]


async def test_only_tomorrow_is_planned(client, db, seeded):
    *_, now = await _scenario(client, db, seeded)
    assert await reminder_sender.plan_tomorrow(db, now - timedelta(days=1), _settings()) == 0
    assert await reminder_sender.plan_tomorrow(db, now + timedelta(days=1), _settings()) == 0


async def test_tomorrow_is_the_indian_tomorrow_not_the_utc_one(client, db, seeded):
    *_, now = await _scenario(client, db, seeded)
    # 19:30 IST is 14:00 UTC the same day, but 00:30 IST is still "tomorrow's
    # eve" in India while UTC says yesterday. Both must agree on the IST date.
    assert await reminder_sender.plan_tomorrow(db, now.astimezone(tz=None), _settings()) == 1


async def test_off_plans_nothing_and_dry_run_writes_nothing(client, db, seeded, caplog):
    *_, now = await _scenario(client, db, seeded)
    assert await reminder_sender.plan_tomorrow(db, now, _settings(reminders_send_mode="off")) == 0

    with caplog.at_level("INFO"):
        assert await reminder_sender.plan_tomorrow(db, now, _settings(reminders_send_mode="dry_run")) == 1
    assert "DRY RUN" in caplog.text and "Reminder from Goti Adarian." in caplog.text
    await db.commit()
    assert await _rows(db) == []              # nothing to block the real run later


async def test_live_sends_only_to_the_allowlist(client, db, seeded):
    *_, now = await _scenario(client, db, seeded)
    assert await reminder_sender.plan_tomorrow(db, now, _settings(reminders_allowlist="")) == 0
    assert await reminder_sender.plan_tomorrow(db, now, _settings(reminders_allowlist=OTHER_PHONE)) == 0
    assert await reminder_sender.plan_tomorrow(
        db, now, _settings(reminders_allowlist=f" {OTHER_PHONE} , {BEHDIN_PHONE}")) == 1


async def test_one_fire_temple_cannot_send_more_than_its_daily_cap(client, db, seeded, monkeypatch):
    *_, now = await _scenario(client, db, seeded)
    monkeypatch.setattr(reminder_sender, "PER_AGYARY_DAILY_CAP", 0)
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 0


# --- Sending ----------------------------------------------------------------

async def _planned(client, db, seeded, **kw):
    scenario = await _scenario(client, db, seeded, **kw)
    now = scenario[-1]
    await reminder_sender.plan_tomorrow(db, now, _settings())
    await db.commit()
    return scenario


async def test_a_planned_reminder_is_posted_to_meta_as_the_approved_template(client, db, seeded):
    aid, cid, headers, later, opening, now = await _planned(client, db, seeded)
    meta = FakeMeta()
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now, _settings())
    assert (report.sent, report.failed) == (1, 0)

    [call] = meta.calls
    assert str(call.url) == "https://graph.facebook.com/v99.0/555000111/messages"
    assert call.headers["authorization"] == "Bearer test-token"
    body = json.loads(call.content)
    assert body["messaging_product"] == "whatsapp" and body["type"] == "template"
    assert body["to"] == BEHDIN_PHONE.lstrip("+")                       # digits, no +
    assert body["template"]["name"] == "memorial_reminder"
    assert body["template"]["language"] == {"code": "en"}
    params = [p["text"] for p in body["template"]["components"][0]["parameters"]]
    assert len(params) == 4 and params[0] == "Goti Adarian" and params[1].startswith("Tomorrow, ")
    # What we posted fills Meta's template to exactly what the family will read.
    assert reminder_message.render(reminder_message.TEMPLATE_BODY, params).endswith("reply STOP.")

    [n] = await _rows(db)
    assert n.status == "sent" and n.wa_message_id == "wamid.1" and n.sent_at is not None


async def test_the_mobed_is_told_what_was_sent(client, db, seeded):
    aid, cid, headers, later, opening, now = await _planned(client, db, seeded)
    meta = FakeMeta()
    async with meta.client() as http:
        await reminder_sender.send_pending(db, http, now, _settings())
    [note] = await _owner_notes(client, headers)
    assert note["kind"] == "reminders_sent" and "1 reminder sent" in note["title"]
    assert "Delzeen Test" in note["body"] and note["link"] == "#/reminders"


async def test_a_sent_reminder_is_never_sent_again(client, db, seeded):
    *_, now = await _planned(client, db, seeded)
    meta = FakeMeta()
    async with meta.client() as http:
        await reminder_sender.send_pending(db, http, now, _settings())
        await reminder_sender.send_pending(db, http, now, _settings())
        # Nor does planning bring it back, even after a restart.
        await reminder_sender.plan_tomorrow(db, now, _settings())
        await db.commit()
        await reminder_sender.send_pending(db, http, now, _settings())
    assert len(meta.calls) == 1


async def test_nothing_is_sent_unless_live(client, db, seeded):
    *_, now = await _planned(client, db, seeded)
    for mode in ("off", "dry_run"):
        meta = FakeMeta()
        async with meta.client() as http:
            report = await reminder_sender.send_pending(db, http, now, _settings(reminders_send_mode=mode))
        assert meta.calls == [] and report.sent == 0
    assert [n.status for n in await _rows(db)] == ["pending"]


async def test_nothing_is_sent_without_credentials(client, db, seeded, caplog):
    *_, now = await _planned(client, db, seeded)
    meta = FakeMeta()
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now, _settings(whatsapp_access_token=""))
    assert meta.calls == [] and report.sent == 0 and "not set" in caplog.text
    assert [n.status for n in await _rows(db)] == ["pending"]          # still there to send later


async def test_a_refusal_is_final_and_the_mobed_is_told(client, db, seeded):
    aid, cid, headers, later, opening, now = await _planned(client, db, seeded)
    meta = FakeMeta(status=400)
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now, _settings())
    assert (report.sent, report.failed) == (0, 1) and len(meta.calls) == 1   # not retried

    [n] = await _rows(db)
    assert n.status == "failed" and "Template not approved" in n.error_message
    [note] = await _owner_notes(client, headers)
    assert note["kind"] == "reminder_failed" and "Delzeen Test" in note["title"]
    assert "Remind on WhatsApp" in note["body"]                         # the way out


async def test_an_outage_is_retried_then_given_up_on(client, db, seeded):
    aid, cid, headers, later, opening, now = await _planned(client, db, seeded)
    meta = FakeMeta(status=503)
    async with meta.client() as http:
        for attempt in (1, 2):
            report = await reminder_sender.send_pending(db, http, now, _settings())
            assert report.failed == 0
            [n] = await _rows(db)
            assert (n.status, n.retry_count) == ("pending", attempt)
        assert await _owner_notes(client, headers) == []                 # not alarmed yet
        report = await reminder_sender.send_pending(db, http, now, _settings())
    assert report.failed == 1
    [n] = await _rows(db)
    assert (n.status, n.retry_count) == ("failed", 3)
    assert [x["kind"] for x in await _owner_notes(client, headers)] == ["reminder_failed"]


async def test_a_network_error_counts_as_an_outage(client, db, seeded):
    *_, now = await _planned(client, db, seeded)

    def boom(request):
        raise httpx.ConnectError("down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as http:
        await reminder_sender.send_pending(db, http, now, _settings())
    [n] = await _rows(db)
    assert (n.status, n.retry_count) == ("pending", 1)


async def test_past_the_cutoff_it_gives_up_instead_of_saying_tomorrow_at_midnight(client, db, seeded):
    aid, cid, headers, later, opening, now = await _planned(client, db, seeded)
    meta = FakeMeta()
    late = now.replace(hour=21, minute=5)
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, late, _settings())
    assert meta.calls == [] and report.missed == 1
    [n] = await _rows(db)
    assert n.status == "failed" and n.error_message == "Not sent in time"
    assert [x["kind"] for x in await _owner_notes(client, headers)] == ["reminder_failed"]


async def test_a_reminder_left_over_from_another_day_is_not_sent(client, db, seeded):
    *_, now = await _planned(client, db, seeded)
    meta = FakeMeta()
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now + timedelta(days=1), _settings())
    assert meta.calls == [] and report.missed == 1


async def test_a_person_who_stops_after_planning_is_still_not_sent_to(client, db, seeded):
    # Planned at 19:00, STOP arrives at 19:10, the sender runs at 19:15.
    *_, now = await _planned(client, db, seeded)
    await reminders.record_stop(db, BEHDIN_PHONE)
    await db.commit()
    meta = FakeMeta()
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now, _settings())
    assert meta.calls == [] and report.sent == 0
    [n] = await _rows(db)
    assert n.status == "failed" and "stop" in (n.error_message or "").lower()


# --- Delivery receipts ------------------------------------------------------

async def _sent(client, db, seeded):
    aid, cid, headers, later, opening, now = await _planned(client, db, seeded)
    meta = FakeMeta()
    async with meta.client() as http:
        await reminder_sender.send_pending(db, http, now, _settings())
    return headers, now


async def test_receipts_move_a_message_forward_only(client, db, seeded):
    headers, now = await _sent(client, db, seeded)
    wamid = (await _rows(db))[0].wa_message_id

    await reminder_sender.apply_status(db, wamid, "delivered", None, now)
    await reminder_sender.apply_status(db, wamid, "read", None, now)
    # Receipts arrive out of order and twice: a late "delivered" is ignored.
    await reminder_sender.apply_status(db, wamid, "delivered", None, now)
    await reminder_sender.apply_status(db, wamid, "sent", None, now)
    await db.commit()
    [n] = await _rows(db)
    assert n.status == "read" and n.delivered_at and n.read_at


async def test_a_failed_receipt_tells_the_mobed_once(client, db, seeded):
    headers, now = await _sent(client, db, seeded)
    wamid = (await _rows(db))[0].wa_message_id
    await reminder_sender.apply_status(db, wamid, "failed", "Number not on WhatsApp", now)
    await reminder_sender.apply_status(db, wamid, "failed", "Number not on WhatsApp", now)
    await db.commit()
    [n] = await _rows(db)
    assert n.status == "failed" and "not on WhatsApp" in n.error_message
    kinds = [x["kind"] for x in await _owner_notes(client, headers)]
    assert kinds.count("reminder_failed") == 1


async def test_a_receipt_for_a_message_we_do_not_know_is_ignored(db, seeded):
    await reminder_sender.apply_status(db, "wamid.unknown", "delivered", None, datetime.now(IST))


async def test_receipts_arrive_through_the_signed_webhook(client, db, seeded, monkeypatch):
    import hashlib
    import hmac

    from agyary.core import config

    monkeypatch.setenv("WHATSAPP_APP_SECRET", "test-app-secret")
    config.get_settings.cache_clear()
    try:
        headers, now = await _sent(client, db, seeded)
        wamid = (await _rows(db))[0].wa_message_id
        payload = {"entry": [{"changes": [{"value": {"statuses": [
            {"id": wamid, "status": "delivered", "timestamp": "1"}]}}]}]}
        raw = json.dumps(payload).encode()
        sig = hmac.new(b"test-app-secret", raw, hashlib.sha256).hexdigest()
        r = await client.post("/webhooks/whatsapp", content=raw,
                              headers={"x-hub-signature-256": f"sha256={sig}", "content-type": "application/json"})
        assert r.status_code == 200
        await db.rollback()          # see what the request committed
        assert (await _rows(db))[0].status == "delivered"
    finally:
        config.get_settings.cache_clear()


# --- The loop ---------------------------------------------------------------

async def test_a_tick_plans_and_sends_in_the_evening_window(client, db, seeded, monkeypatch):
    *_, now = await _scenario(client, db, seeded)
    monkeypatch.setattr(reminder_worker, "get_settings", lambda: _settings())
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    meta = FakeMeta()
    async with meta.client() as http:
        report = await reminder_worker.tick(now=now, client=http, session_factory=factory)
    assert (report.planned, report.sent) == (1, 1) and len(meta.calls) == 1


async def test_a_tick_before_the_send_hour_plans_nothing(client, db, seeded, monkeypatch):
    *_, now = await _scenario(client, db, seeded)
    monkeypatch.setattr(reminder_worker, "get_settings", lambda: _settings())
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    meta = FakeMeta()
    async with meta.client() as http:
        report = await reminder_worker.tick(now=now.replace(hour=15), client=http, session_factory=factory)
    assert report.planned == 0 and meta.calls == []


async def test_a_tick_with_sending_off_touches_nothing(client, db, seeded, monkeypatch):
    *_, now = await _scenario(client, db, seeded)
    monkeypatch.setattr(reminder_worker, "get_settings", lambda: _settings(reminders_send_mode="off"))
    meta = FakeMeta()
    async with meta.client() as http:
        report = await reminder_worker.tick(now=now, client=http)
    assert (report.planned, report.sent) == (0, 0) and meta.calls == []
    assert await db.scalar(select(func.count()).select_from(Notification)) == 0


async def test_the_shipped_defaults_send_nothing():
    s = Settings(jwt_secret_key="x", _env_file=None)
    assert s.reminders_send_mode == "off" and s.reminders_allowlist == ""
    assert s.whatsapp_access_token == "" and s.reminders_send_hour == 19 and s.reminders_cutoff_hour == 21


# --- What the Reminders list shows ------------------------------------------

async def test_the_list_shows_whether_it_will_go_on_its_own_and_whether_it_went(client, db, seeded):
    from tests.test_memorial_api import _user_id

    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    uid = await _user_id(db, NEW_MOBED_PHONE)
    first = date.fromisoformat(later[0]["date"])

    async def item():
        [i, *_] = await memorials_due(db, uid, aid, first - timedelta(days=1))
        return i

    before = await item()
    assert before["auto"] is True and before["sent_status"] is None

    await reminder_sender.plan_tomorrow(db, now, _settings())
    await db.commit()
    meta = FakeMeta()
    async with meta.client() as http:
        await reminder_sender.send_pending(db, http, now, _settings())
    assert (await item())["sent_status"] == "sent"

    # Turning it off for this behdin shows as not automatic.
    await client.put(f"/api/mobed/agyaries/{aid}/behdins/{cid}/reminders", json={"enabled": False}, headers=headers)
    assert (await item())["auto"] is False


async def memorials_due(db, uid, aid, today):
    from agyary.services import memorials

    return await memorials.reminders_due(db, uid, aid, today, 3)


async def test_the_reminders_endpoint_says_whether_sending_is_on(client, db, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    body = (await client.get(f"/api/mobed/agyaries/{aid}/memorial-reminders", headers=headers)).json()
    assert body["delivery"] == "off"


# --- Seeing what it does ----------------------------------------------------

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_dry_run_log():
    reminder_sender.reset_dry_run_log()
    yield
    reminder_sender.reset_dry_run_log()


async def test_a_dry_run_says_each_message_once_not_every_minute(client, db, seeded, caplog):
    *_, now = await _scenario(client, db, seeded)
    dry = _settings(reminders_send_mode="dry_run")
    with caplog.at_level("INFO"):
        for minute in range(5):          # the loop ticks every minute for two hours
            assert await reminder_sender.plan_tomorrow(db, now + timedelta(minutes=minute), dry) == 1
    assert caplog.text.count("DRY RUN - would send") == 1


def test_the_apps_own_log_lines_reach_the_server_log():
    # uvicorn only configures its own loggers, so without this the loop's
    # "planned 1, sent 1" would be dropped on the server. Importing the app
    # raises the agyary tree to INFO with a handler, and nothing else.
    import logging

    import agyary.api.main  # noqa: F401

    log = logging.getLogger("agyary")
    assert log.level == logging.INFO and log.handlers
    assert logging.getLogger("sqlalchemy.engine").getEffectiveLevel() > logging.INFO
