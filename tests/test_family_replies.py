"""What a family says back (RM-4).

A family's only way back to us is a reply to a reminder. STOP must be honoured
however they put it - a short "please stop", "no more", in Hindi or Gujarati, or
a Stop button - while a sentence that merely mentions stopping is not one. And
anything else they write must reach a person: it goes to the mobed whose
reminder it answers (by the replied-to message, else the mobed who last reminded
that number), and to nobody else (D2).
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from sqlalchemy import select

from agyary.models import Customer
from agyary.services import reminder_sender, reminders
from tests.conftest import WA_APP_SECRET
from tests.test_mobed_api import _member_headers
from tests.test_reminder_sender import BEHDIN_PHONE, FakeMeta, _scenario, _settings


@pytest.mark.parametrize("said", [
    "STOP", "stop.", "Please stop", "STOP sending these", "no more messages please", "Unsubscribe me",
    "Don't send these", "बंद करो", "બંધ કરો", "band karo",
])
def test_a_stop_in_their_own_words_is_honoured(said):
    assert reminders.is_stop(said), said


@pytest.mark.parametrize("said", [
    "please don't stop the Afringan", "Thank you, we will come", "Do not stop the prayers for papa",
    "We will be there. Please make sure the Afringan does not stop before my brother arrives from Pune.",
])
def test_a_message_that_merely_mentions_stopping_is_not_a_stop(said):
    assert not reminders.is_stop(said), said


def _signed(message: dict) -> tuple[bytes, dict]:
    raw = json.dumps({"entry": [{"changes": [{"value": {"messages": [message]}}]}]}).encode()
    digest = hmac.new(WA_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"x-hub-signature-256": f"sha256={digest}", "content-type": "application/json"}


async def _reminded(client, db, seeded):
    """Mobed A's reminder has gone to the family (Meta's id wamid.1); colleague B
    also keeps a record of the same number, but never reminded them."""
    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    settings = _settings()
    await reminder_sender.plan_tomorrow(db, now, settings)
    await db.commit()
    async with FakeMeta().client() as c:
        await reminder_sender.send_pending(db, c, now, settings)
    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944401501")
    await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=colleague,
                      json={"name": "Same Family", "phone": BEHDIN_PHONE})
    for h in (headers, colleague):                     # clear the "sent" summary etc.
        await client.post("/api/mobed/notifications/seen", json={}, headers=h)
    return headers, colleague


async def _notes(client, headers, kind="behdin_reply"):
    return [n for n in (await client.get("/api/mobed/notifications", headers=headers)).json() if n["kind"] == kind]


async def test_a_stop_button_is_honoured(client, db, seeded):
    await _reminded(client, db, seeded)
    raw, h = _signed({"type": "button", "from": BEHDIN_PHONE.lstrip("+"),
                      "button": {"text": "Stop", "payload": "Stop"}})
    assert (await client.post("/webhooks/whatsapp", content=raw, headers=h)).status_code == 200
    records = (await db.execute(select(Customer).where(Customer.phone == BEHDIN_PHONE))).scalars().all()
    for c in records:
        await db.refresh(c)
    assert records and all(c.reminders_stopped_at is not None for c in records)


async def test_a_reply_reaches_the_mobed_whose_reminder_it_answers_and_nobody_else(client, db, seeded):
    mine, colleague = await _reminded(client, db, seeded)
    raw, h = _signed({"type": "text", "from": BEHDIN_PHONE.lstrip("+"), "context": {"id": "wamid.1"},
                      "text": {"body": "Thank you, we will come with my mother"}})
    assert (await client.post("/webhooks/whatsapp", content=raw, headers=h)).status_code == 200
    [note] = await _notes(client, mine)
    assert "we will come with my mother" in note["body"] and note["link"].startswith("#/behdins/")
    assert await _notes(client, colleague) == []


async def test_a_reply_without_context_goes_to_whoever_last_reminded_them(client, db, seeded):
    mine, colleague = await _reminded(client, db, seeded)
    raw, h = _signed({"type": "text", "from": BEHDIN_PHONE.lstrip("+"), "text": {"body": "Who is this?"}})
    await client.post("/webhooks/whatsapp", content=raw, headers=h)
    assert len(await _notes(client, mine)) == 1
    assert await _notes(client, colleague) == []


async def test_a_message_from_a_number_we_never_reminded_reaches_nobody(client, db, seeded):
    mine = await _member_headers(client, seeded)
    raw, h = _signed({"type": "text", "from": "919944401599", "text": {"body": "hello"}})
    assert (await client.post("/webhooks/whatsapp", content=raw, headers=h)).status_code == 200
    assert await _notes(client, mine) == []


async def test_the_mobed_is_shown_what_the_family_said_when_it_counted_as_stop(client, db, seeded):
    mine, _ = await _reminded(client, db, seeded)
    raw, h = _signed({"type": "text", "from": BEHDIN_PHONE.lstrip("+"), "text": {"body": "please stop now"}})
    await client.post("/webhooks/whatsapp", content=raw, headers=h)
    [note] = await _notes(client, mine, kind="reminder_stopped")
    assert "please stop now" in note["body"]
