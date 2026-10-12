"""What is kept about a family's agreement (RM-6).

The mobed asks in person and records the yes. What they asked matters as much as
that they asked: the app shows the exact words to say (which name the business
and say how to stop, as Meta's opt-in rules expect), and when reminders are
turned on it keeps which version of those words was used, with the time. A
screen still showing older words is refused, so the record never claims words
that were not said.
"""

from __future__ import annotations

from agyary.models import Customer
from agyary.services import reminders
from tests.test_mobed_api import _member_headers


async def _behdin(client, seeded):
    aid = seeded["agyary_id"]
    h = await _member_headers(client, seeded)
    cid = (await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=h,
                             json={"name": "Consenting Family", "phone": "+919944401601"})).json()["id"]
    return aid, h, cid


async def test_the_words_to_say_come_from_the_server(client, db, seeded):
    _, h, _ = await _behdin(client, seeded)
    wording = (await client.get("/api/mobed/reminders/consent", headers=h)).json()
    assert wording["version"] == reminders.CONSENT_VERSION
    assert "Mobed Diary" in wording["text"] and "STOP" in wording["text"]


async def test_turning_reminders_on_keeps_which_words_were_said(client, db, seeded):
    aid, h, cid = await _behdin(client, seeded)
    r = await client.put(f"/api/mobed/agyaries/{aid}/behdins/{cid}/reminders", headers=h,
                         json={"enabled": True, "consent_version": reminders.CONSENT_VERSION})
    assert r.status_code == 200, r.text
    record = await db.get(Customer, cid)
    await db.refresh(record)
    assert record.reminders_consent_version == reminders.CONSENT_VERSION
    assert record.reminders_enabled_at is not None

    # Turning them off withdraws the agreement: nothing is kept that claims it stands.
    await client.put(f"/api/mobed/agyaries/{aid}/behdins/{cid}/reminders", headers=h, json={"enabled": False})
    await db.refresh(record)
    assert record.reminders_consent_version is None and record.reminders_enabled_at is None


async def test_a_screen_showing_old_words_is_refused(client, db, seeded):
    aid, h, cid = await _behdin(client, seeded)
    r = await client.put(f"/api/mobed/agyaries/{aid}/behdins/{cid}/reminders", headers=h,
                         json={"enabled": True, "consent_version": "an-older-wording"})
    assert r.status_code == 409 and "words" in r.json()["detail"]
    record = await db.get(Customer, cid)
    await db.refresh(record)
    assert record.reminders_enabled is False
