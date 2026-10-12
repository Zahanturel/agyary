"""Reminder consent, what STOP does, and the mobed's in-app notifications.

Consent is given in person and recorded by the mobed, so these tests are
about the rules around it: off by default, private to the mobed whose behdin
it is, withdrawn for good by a STOP, and restored only on purpose.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from agyary.models import Customer, UserCustomer
from agyary.services import reminders
from tests.test_mobed_api import NEW_MOBED_PHONE, _member_headers

BEHDIN_PHONE = "+919944400701"
OTHER_MOBED = "+919911100077"


async def _setup(client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                          json={"name": "Delzeen Test", "phone": BEHDIN_PHONE}, headers=headers)
    assert r.status_code == 200, r.text
    return aid, r.json()["id"], headers


def _url(aid, cid):
    return f"/api/mobed/agyaries/{aid}/behdins/{cid}/reminders"


async def _user_id(db, phone):
    from agyary.models import User

    return (await db.execute(select(User.id).where(User.phone == phone))).scalar_one()


# --- Consent ---------------------------------------------------------------

async def test_reminders_are_off_until_the_mobed_turns_them_on(client, seeded):
    aid, cid, headers = await _setup(client, seeded)
    r = await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}", headers=headers)
    assert r.json()["reminders"] == {"enabled": False, "stopped_at": None, "delivery": "off"}


async def test_the_mobed_can_turn_reminders_on_and_off(client, seeded):
    aid, cid, headers = await _setup(client, seeded)
    r = await client.put(_url(aid, cid), json={"enabled": True}, headers=headers)
    assert r.status_code == 200 and r.json() == {"enabled": True, "stopped_at": None, "delivery": "off"}
    got = await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}", headers=headers)
    assert got.json()["reminders"]["enabled"] is True

    r = await client.put(_url(aid, cid), json={"enabled": False}, headers=headers)
    assert r.json()["enabled"] is False


async def test_the_agreement_is_with_one_mobed_only(client, db, seeded):
    aid, cid, headers = await _setup(client, seeded)
    other = await _member_headers(client, seeded, name="Other", phone=OTHER_MOBED)
    # Not this mobed's behdin: a 404, as everywhere else in the behdin book.
    assert (await client.put(_url(aid, cid), json={"enabled": True}, headers=other)).status_code == 404

    await client.put(_url(aid, cid), json={"enabled": True}, headers=headers)
    row = await db.get(UserCustomer, (await _user_id(db, NEW_MOBED_PHONE), cid))
    assert row.reminders_enabled and row.reminders_enabled_at is not None


async def test_turning_reminders_on_needs_a_session(client, seeded):
    r = await client.put(_url(seeded["agyary_id"], 1), json={"enabled": True})
    assert r.status_code in (401, 403)


# --- STOP ------------------------------------------------------------------

def test_what_counts_as_a_stop():
    for text in ("STOP", "stop", "Stop.", "  stop  ", "Unsubscribe", "STOP!"):
        assert reminders.is_stop(text), text
    # A sentence that merely contains the word must not unsubscribe anyone.
    for text in ("please dont stop the afringan", "stop reminders please", "", "thanks", "stopped"):
        assert not reminders.is_stop(text), text


async def test_a_stop_turns_reminders_off_and_tells_the_mobed(client, db, seeded):
    aid, cid, headers = await _setup(client, seeded)
    await client.put(_url(aid, cid), json={"enabled": True}, headers=headers)

    assert await reminders.record_stop(db, BEHDIN_PHONE) == 1
    await db.commit()

    got = (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}", headers=headers)).json()
    assert got["reminders"]["enabled"] is False and got["reminders"]["stopped_at"]

    notes = (await client.get("/api/mobed/notifications", headers=headers)).json()
    assert len(notes) == 1
    assert notes[0]["kind"] == "reminder_stopped" and "Delzeen Test" in notes[0]["title"]
    assert notes[0]["link"] == f"#/behdins/{cid}" and notes[0]["seen"] is False


async def test_a_second_stop_changes_nothing_and_tells_nobody_again(client, db, seeded):
    aid, cid, headers = await _setup(client, seeded)
    await client.put(_url(aid, cid), json={"enabled": True}, headers=headers)
    await reminders.record_stop(db, BEHDIN_PHONE)
    await db.commit()
    assert await reminders.record_stop(db, BEHDIN_PHONE) == 0
    await db.commit()
    assert len((await client.get("/api/mobed/notifications", headers=headers)).json()) == 1


async def test_a_stop_from_a_stranger_does_nothing(db, seeded):
    assert await reminders.record_stop(db, "+919000000099") == 0


async def test_a_stop_only_tells_the_mobeds_who_had_reminders_on(client, db, seeded):
    aid, cid, headers = await _setup(client, seeded)
    other = await _member_headers(client, seeded, name="Other", phone=OTHER_MOBED)
    # The other mobed knows the same person but never turned reminders on.
    await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                      json={"name": "Delzeen Test", "phone": BEHDIN_PHONE}, headers=other)
    await client.put(_url(aid, cid), json={"enabled": True}, headers=headers)

    assert await reminders.record_stop(db, BEHDIN_PHONE) == 1
    await db.commit()
    assert len((await client.get("/api/mobed/notifications", headers=headers)).json()) == 1
    assert (await client.get("/api/mobed/notifications", headers=other)).json() == []


async def test_a_stop_is_the_persons_so_it_holds_for_every_mobed(client, db, seeded):
    aid, cid, headers = await _setup(client, seeded)
    await reminders.record_stop(db, BEHDIN_PHONE)
    await db.commit()
    other = await _member_headers(client, seeded, name="Other", phone=OTHER_MOBED)
    made = (await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                              json={"name": "Delzeen Test", "phone": BEHDIN_PHONE}, headers=other)).json()
    r = await client.put(_url(aid, made["id"]), json={"enabled": True}, headers=other)
    assert r.status_code == 409


async def test_turning_reminders_back_on_after_a_stop_needs_confirmation(client, db, seeded):
    aid, cid, headers = await _setup(client, seeded)
    await client.put(_url(aid, cid), json={"enabled": True}, headers=headers)
    await reminders.record_stop(db, BEHDIN_PHONE)
    await db.commit()

    r = await client.put(_url(aid, cid), json={"enabled": True}, headers=headers)
    assert r.status_code == 409 and "STOP" in r.json()["detail"]
    got = (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}", headers=headers)).json()
    assert got["reminders"]["enabled"] is False          # the refusal changed nothing

    r = await client.put(_url(aid, cid), json={"enabled": True, "confirm_restart": True}, headers=headers)
    assert r.status_code == 200 and r.json() == {"enabled": True, "stopped_at": None, "delivery": "off"}
    customer = (await db.execute(select(Customer).where(Customer.phone == BEHDIN_PHONE))).scalar_one()
    await db.refresh(customer)
    assert customer.reminders_stopped_at is None


async def test_turning_reminders_off_never_needs_confirmation(client, db, seeded):
    aid, cid, headers = await _setup(client, seeded)
    await reminders.record_stop(db, BEHDIN_PHONE)
    await db.commit()
    assert (await client.put(_url(aid, cid), json={"enabled": False}, headers=headers)).status_code == 200


# --- In-app notifications --------------------------------------------------

async def test_notifications_lapse_after_a_day(client, db, seeded):
    await _setup(client, seeded)
    uid = await _user_id(db, NEW_MOBED_PHONE)
    now = datetime.now(timezone.utc)
    await reminders.notify(db, uid, "x", "Old", "body", now=now - timedelta(hours=25))
    await reminders.notify(db, uid, "x", "Recent", "body", now=now - timedelta(hours=23))
    await db.commit()

    headers = await _member_headers(client, seeded)
    titles = [n["title"] for n in (await client.get("/api/mobed/notifications", headers=headers)).json()]
    assert titles == ["Recent"]


async def test_notifications_are_newest_first_and_marking_them_seen_keeps_them(client, db, seeded):
    await _setup(client, seeded)
    uid = await _user_id(db, NEW_MOBED_PHONE)
    now = datetime.now(timezone.utc)
    first = await reminders.notify(db, uid, "x", "First", "b", now=now - timedelta(hours=2))
    await reminders.notify(db, uid, "x", "Second", "b", now=now - timedelta(hours=1))
    await db.commit()
    headers = await _member_headers(client, seeded)

    notes = (await client.get("/api/mobed/notifications", headers=headers)).json()
    assert [n["title"] for n in notes] == ["Second", "First"] and not any(n["seen"] for n in notes)

    r = await client.post("/api/mobed/notifications/seen", json={"ids": [first.id]}, headers=headers)
    assert r.json() == {"marked": 1}
    notes = (await client.get("/api/mobed/notifications", headers=headers)).json()
    # Still listed - the bell can revisit them - but flagged so the popup skips them.
    assert [(n["title"], n["seen"]) for n in notes] == [("Second", False), ("First", True)]

    r = await client.post("/api/mobed/notifications/seen", json={}, headers=headers)
    assert r.json() == {"marked": 1}
    assert all(n["seen"] for n in (await client.get("/api/mobed/notifications", headers=headers)).json())


async def test_one_mobed_cannot_see_or_mark_anothers_notifications(client, db, seeded):
    await _setup(client, seeded)
    uid = await _user_id(db, NEW_MOBED_PHONE)
    note = await reminders.notify(db, uid, "x", "Private", "b")
    await db.commit()
    other = await _member_headers(client, seeded, name="Other", phone=OTHER_MOBED)

    assert (await client.get("/api/mobed/notifications", headers=other)).json() == []
    r = await client.post("/api/mobed/notifications/seen", json={"ids": [note.id]}, headers=other)
    assert r.json() == {"marked": 0}
    await db.refresh(note)
    assert note.seen_at is None


async def test_notifications_need_a_session(client, seeded):
    assert (await client.get("/api/mobed/notifications")).status_code in (401, 403)
    assert (await client.post("/api/mobed/notifications/seen", json={})).status_code in (401, 403)



# --- Through the real webhook ----------------------------------------------

def _signed_text(sender: str, text: str) -> tuple[bytes, dict]:
    import hashlib
    import hmac
    import json

    message = {"type": "text", "from": sender, "text": {"body": text}}
    raw = json.dumps({"entry": [{"changes": [{"value": {"messages": [message]}}]}]}).encode()
    digest = hmac.new(b"test-app-secret", raw, hashlib.sha256).hexdigest()
    return raw, {"x-hub-signature-256": f"sha256={digest}", "content-type": "application/json"}


async def test_a_stop_reply_through_the_webhook_switches_reminders_off(client, seeded, monkeypatch):
    from agyary.core import config

    monkeypatch.setenv("WHATSAPP_APP_SECRET", "test-app-secret")
    config.get_settings.cache_clear()
    try:
        aid, cid, headers = await _setup(client, seeded)
        await client.put(_url(aid, cid), json={"enabled": True}, headers=headers)

        # Meta sends the number without the +.
        raw, sig = _signed_text(BEHDIN_PHONE.lstrip("+"), "STOP")
        assert (await client.post("/webhooks/whatsapp", content=raw, headers=sig)).status_code == 200

        got = (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}", headers=headers)).json()
        assert got["reminders"]["enabled"] is False and got["reminders"]["stopped_at"]
        notes = (await client.get("/api/mobed/notifications", headers=headers)).json()
        assert [n["kind"] for n in notes] == ["reminder_stopped"]

        # A message that merely contains the word does not.
        await client.put(_url(aid, cid), json={"enabled": True, "confirm_restart": True}, headers=headers)
        raw, sig = _signed_text(BEHDIN_PHONE.lstrip("+"), "please dont stop the afringan")
        await client.post("/webhooks/whatsapp", content=raw, headers=sig)
        got = (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}", headers=headers)).json()
        assert got["reminders"]["enabled"] is True
    finally:
        config.get_settings.cache_clear()
