"""Sign-in that cannot be phished, and WhatsApp usernames (AU-1, AU-4, RM-8a).

AU-1: whoever starts a "send us a code" sign-in gets the account of whoever
sends the code - so a mobed tricked into tapping Send on an attacker's link used
to hand over their account. Now, when the code arrives, we reply to that phone
with a short number and a warning, and the sign-in finishes only when that
number is typed on the screen that started it. Someone who only started the
attempt never sees it. (Where nothing can be sent - a laptop with no token - the
flow is as before.)

AU-4: WhatsApp may leave out the sender's phone number for someone who uses a
username. A mobed who has signed in before is still recognised by the id
WhatsApp sends instead; one we cannot recognise is told plainly. A STOP from a
username still reaches the family's records, through the receipts of the
reminder they were sent.

RM-8a: every number we send to goes with its "+", so Meta never prefixes our own
country code to it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re

import pytest
from sqlalchemy import select

from agyary.core import config
from agyary.models import Customer, User
from agyary.services import otp, reminder_sender, wa_send
from tests.conftest import WA_APP_SECRET, signed_inbound
from tests.test_reminder_sender import BEHDIN_PHONE, FakeMeta, _scenario, _settings

VICTIM = "+919944401801"
BSUID = "IN.1349000000000000001"


class Sent:
    """Stands in for Meta's text messages; remembers what went where."""

    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    async def __call__(self, settings, phone, body, client=None):
        self.messages.append((phone, body))
        return True


@pytest.fixture
def can_send(monkeypatch):
    monkeypatch.setenv("SIGNIN_CONFIRMATION", "on")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "555000111")
    config.get_settings.cache_clear()
    box = Sent()
    monkeypatch.setattr(wa_send, "send_text", box)
    return box


def _signed(value: dict) -> tuple[bytes, dict]:
    raw = json.dumps({"entry": [{"changes": [{"value": value}]}]}).encode()
    digest = hmac.new(WA_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"x-hub-signature-256": f"sha256={digest}", "content-type": "application/json"}


async def _code_sent_from(client, code: str, phone: str | None, user_id: str | None = None):
    message = {"type": "text", "text": {"body": f"Mobed Diary sign-in: {code}"}}
    if phone:
        message["from"] = phone.lstrip("+")
    if user_id:
        message["from_user_id"] = user_id
    raw, h = _signed({"messages": [message]})
    assert (await client.post("/webhooks/whatsapp", content=raw, headers=h)).status_code == 200


# --- AU-1 ---------------------------------------------------------------------

async def test_starting_an_attempt_someone_else_sends_does_not_sign_you_in(client, db, seeded, can_send):
    started = (await client.post("/api/mobed/auth/wa/start")).json()        # the attacker's browser
    await _code_sent_from(client, started["code"], VICTIM)                    # the tricked victim taps Send
    polled = await client.get("/api/mobed/auth/wa/poll")
    assert polled.json() == {"status": "confirm"}                            # no session for the starter
    [(to, body)] = can_send.messages
    assert to == VICTIM and "not you" in body.lower()
    real = re.search(r"\b(\d{4})\b", body).group(1)
    # Guessing does not get them in: five wrong tries, and the attempt is dead,
    # even for the right number afterwards.
    wrong = [g for g in ("0000", "1111", "2222", "3333", "4444", "5555") if g != real][:5]
    for guess in wrong:
        assert (await client.post("/api/mobed/auth/wa/confirm", json={"number": guess})).status_code == 400
    assert (await client.post("/api/mobed/auth/wa/confirm", json={"number": real})).status_code == 400


async def test_the_phone_owner_types_the_number_and_is_signed_in(client, db, seeded, can_send):
    started = (await client.post("/api/mobed/auth/wa/start")).json()
    await _code_sent_from(client, started["code"], VICTIM)
    assert (await client.get("/api/mobed/auth/wa/poll")).json() == {"status": "confirm"}
    [(_, body)] = can_send.messages
    number = re.search(r"\b(\d{4})\b", body).group(1)
    r = await client.post("/api/mobed/auth/wa/confirm", json={"number": number})
    assert r.status_code == 200 and r.json()["status"] == "needs_name"
    done = await client.post("/api/mobed/auth/wa/complete", json={"name": "Real Mobed"})
    assert done.json()["status"] == "signed_in" and done.json()["user"]["phone"] == VICTIM


async def test_nothing_is_sent_until_the_owner_switches_confirmation_on(client, db, seeded, can_send, monkeypatch):
    """The confirmation is a real WhatsApp message to the person signing in, so
    it goes only once the owner turns it on (SIGNIN_CONFIRMATION=on)."""
    monkeypatch.setenv("SIGNIN_CONFIRMATION", "off")
    config.get_settings.cache_clear()
    started = (await client.post("/api/mobed/auth/wa/start")).json()
    await _code_sent_from(client, started["code"], VICTIM)
    assert can_send.messages == []
    assert (await client.get("/api/mobed/auth/wa/poll")).json()["status"] in ("needs_name", "signed_in")


# --- AU-4 ---------------------------------------------------------------------

async def test_a_known_mobed_who_uses_a_username_is_still_recognised(client, db, seeded):
    # Their first sign-in carried both the number and the id; it is kept.
    started = (await client.post("/api/mobed/auth/wa/start")).json()
    await _code_sent_from(client, started["code"], VICTIM, BSUID)
    body = (await client.get("/api/mobed/auth/wa/poll")).json()
    assert body["status"] == "needs_name"
    await client.post("/api/mobed/auth/wa/complete", json={"name": "Username Mobed"})
    user = (await db.execute(select(User).where(User.phone == VICTIM))).scalar_one()
    assert user.wa_user_id == BSUID

    # Later WhatsApp sends only the id.
    client.cookies.clear()
    started = (await client.post("/api/mobed/auth/wa/start")).json()
    await _code_sent_from(client, started["code"], None, BSUID)
    body = (await client.get("/api/mobed/auth/wa/poll")).json()
    assert body["status"] == "signed_in" and body["user"]["phone"] == VICTIM


async def test_someone_whose_number_whatsapp_withholds_is_told_plainly(client, db, seeded):
    started = (await client.post("/api/mobed/auth/wa/start")).json()
    await _code_sent_from(client, started["code"], None, "IN.9999000000000000009")
    r = await client.get("/api/mobed/auth/wa/poll")
    assert r.status_code == 403 and "username" in r.json()["detail"]


async def test_a_stop_from_a_username_reaches_the_family(client, db, seeded):
    *_, now = await _scenario(client, db, seeded)
    settings = _settings()
    await reminder_sender.plan_tomorrow(db, now, settings)
    await db.commit()
    async with FakeMeta().client() as c:
        await reminder_sender.send_pending(db, c, now, settings)
    # Meta's receipt for the reminder carries the family's username id...
    raw, h = _signed({"statuses": [{"id": "wamid.1", "status": "delivered",
                                    "recipient_id": BEHDIN_PHONE.lstrip("+"), "recipient_user_id": BSUID}]})
    await client.post("/webhooks/whatsapp", content=raw, headers=h)
    # ...so a STOP that comes with only that id still stops them.
    raw, h = _signed({"messages": [{"type": "text", "from_user_id": BSUID, "text": {"body": "STOP"}}]})
    await client.post("/webhooks/whatsapp", content=raw, headers=h)
    records = (await db.execute(select(Customer).where(Customer.phone == BEHDIN_PHONE))).scalars().all()
    for record in records:
        await db.refresh(record)
    assert records and all(r.reminders_stopped_at is not None for r in records)


# --- RM-8a --------------------------------------------------------------------

def test_every_number_is_sent_with_its_plus():
    class N:
        recipient_phone = "+919944401802"
        template_name = "memorial_reminder"
        template_params = {"1": "a", "2": "b", "3": "c", "4": "d"}

    assert reminder_sender._payload(N(), _settings())["to"] == "+919944401802"
    assert otp._payload(_settings(), "+919944401802", "123456")["to"] == "+919944401802"
    assert wa_send._payload("+919944401802", "hello")["to"] == "+919944401802"


async def test_a_signed_inbound_helper_still_works(client, db, seeded):
    # The suite's own sign-in helper (no token, nothing can be sent) keeps working.
    raw, h = signed_inbound("ABCDEFGHJK", "+919944401803")
    assert (await client.post("/webhooks/whatsapp", content=raw, headers=h)).status_code == 200
