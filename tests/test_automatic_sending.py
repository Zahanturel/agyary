"""Whether a reminder goes on its own, and making sure it never goes twice.

D4: automatic sending is behind one per-account switch (users.automatic_reminders),
on for everyone in the pilot and set for new accounts by REMINDERS_AUTOMATIC_DEFAULT,
so turning it off for a free tier later is configuration.

RM-2: the mobed's Reminders list promises an automatic reminder only when the
planner would really send one - sending live, not paused, the account switched
on, the number on the allowlist - and otherwise keeps the manual button.

RM-3: a reminder is sent at most once. If Meta may have accepted it but we never
heard back (a timeout after the request went out, or a crash mid-send), it is not
retried; the mobed is told to check. Only a failure that certainly reached nobody
is tried again.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
from sqlalchemy import select, update

from agyary.core import config
from agyary.models import Notification, User
from agyary.services import guardrails, reminder_sender
from agyary.services.memorials import today_ist
from tests.conftest import sign_in
from tests.test_mobed_api import _member_headers
from tests.test_reminder_sender import BEHDIN_PHONE, _scenario, _settings


async def _rows(db):
    return (await db.execute(select(Notification).order_by(Notification.id))).scalars().all()


# --- D4: the per-account switch -----------------------------------------------

async def test_an_account_with_automatic_sending_off_gets_no_automatic_reminders(client, db, seeded):
    *_, now = await _scenario(client, db, seeded)
    await db.execute(update(User).values(automatic_reminders=False))
    await db.commit()
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 0
    await db.execute(update(User).values(automatic_reminders=True))
    await db.commit()
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 1


async def test_new_accounts_take_the_configured_default(client, db, seeded, monkeypatch):
    monkeypatch.setenv("REMINDERS_AUTOMATIC_DEFAULT", "false")
    config.get_settings.cache_clear()
    body = await sign_in(client, "+919944401401", "Free Tier Mobed")
    me = await db.get(User, body["user"]["id"])
    assert me.automatic_reminders is False and body["user"]["automatic_reminders"] is False

    monkeypatch.setenv("REMINDERS_AUTOMATIC_DEFAULT", "true")
    config.get_settings.cache_clear()
    client.cookies.clear()
    body = await sign_in(client, "+919944401402", "Pilot Mobed")
    assert (await db.get(User, body["user"]["id"])).automatic_reminders is True


# --- RM-2: the list says what will really happen -------------------------------

async def _list_item(client, aid, headers):
    r = await client.get(f"/api/mobed/agyaries/{aid}/memorial-reminders?days=60", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _near_family(client, seeded, phone="+919944401403"):
    """A memorial whose 30th day is within the list's window from today."""
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    cid = (await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=headers,
                             json={"name": "Near Family", "phone": phone})).json()["id"]
    sid = next(s["id"] for s in (await client.get(f"/api/mobed/agyaries/{aid}/services", headers=headers)).json()
               if s["name"] == "Afringan")
    made = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials", headers=headers, json={
        "departed_name": "Near Departed", "death_date": (today_ist() - timedelta(days=20)).isoformat(),
        "opening": "tenth_only", "day_counts": [30], "service_ids": [sid]})
    assert made.status_code == 200, made.text
    assert (await client.put(f"/api/mobed/agyaries/{aid}/behdins/{cid}/reminders", headers=headers,
                             json={"enabled": True})).status_code == 200
    return aid, headers


def _env(monkeypatch, **values):
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()


async def test_the_list_promises_an_automatic_reminder_only_when_one_will_go(client, db, seeded, monkeypatch):
    phone = "+919944401403"
    aid, headers = await _near_family(client, seeded, phone)

    _env(monkeypatch, REMINDERS_SEND_MODE="live", REMINDERS_ALLOWLIST=phone)
    data = await _list_item(client, aid, headers)
    assert data["items"][0]["auto"] is True and data["send_hour"] == 19

    _env(monkeypatch, REMINDERS_ALLOWLIST="+919900000001")         # somebody else's number only
    assert (await _list_item(client, aid, headers))["items"][0]["auto"] is False

    _env(monkeypatch, REMINDERS_ALLOWLIST="*")
    await guardrails.pause(db, _settings(), "testing", now=None)
    await db.commit()
    data = await _list_item(client, aid, headers)
    assert data["items"][0]["auto"] is False and data["paused"] is True
    await guardrails.resume(db)
    await db.commit()

    await db.execute(update(User).values(automatic_reminders=False))
    await db.commit()
    assert (await _list_item(client, aid, headers))["items"][0]["auto"] is False


# --- RM-3: at most once --------------------------------------------------------

async def _planned(client, db, seeded):
    *_, now = await _scenario(client, db, seeded)
    settings = _settings()
    assert await reminder_sender.plan_tomorrow(db, now, settings) == 1
    await db.commit()
    return now, settings


async def test_no_answer_after_the_request_went_out_is_never_retried(client, db, seeded):
    now, settings = await _planned(client, db, seeded)
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("Meta may have accepted it; the reply was lost")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        await reminder_sender.send_pending(db, c, now, settings)
        await reminder_sender.send_pending(db, c, now + timedelta(minutes=1), settings)
    assert len(calls) == 1
    [n] = await _rows(db)
    assert n.status == "failed" and "may or may not" in n.error_message


async def test_a_failure_that_reached_nobody_is_tried_again(client, db, seeded):
    now, settings = await _planned(client, db, seeded)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("the network is down; nothing left the building")
        return httpx.Response(200, json={"messages": [{"id": "wamid.ok"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        await reminder_sender.send_pending(db, c, now, settings)
        await reminder_sender.send_pending(db, c, now + timedelta(minutes=1), settings)
    assert len(calls) == 2
    assert (await _rows(db))[0].status == "sent"


async def test_a_reminder_caught_mid_send_by_a_crash_is_not_sent_again(client, db, seeded):
    now, settings = await _planned(client, db, seeded)
    # What a crash between "sending" and the answer leaves behind.
    await db.execute(update(Notification).values(status="sending"))
    await db.commit()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.again"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        await reminder_sender.send_pending(db, c, now + timedelta(minutes=1), settings)
    assert calls == []
    [n] = await _rows(db)
    assert n.status == "failed" and "may or may not" in n.error_message
    assert n.recipient_phone == BEHDIN_PHONE
