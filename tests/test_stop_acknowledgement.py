"""A family's first STOP gets one short, kind reply naming their mobed.

Once per number, ever: a second STOP, Meta delivering the same one twice, or a
number that had stopped before gets nothing. It is a paid message, so it has
its own daily cap, respects the pause switch, and goes only while reminders are
live and only to a number we actually reminded.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agyary.core import config
from agyary.models import Customer, ReminderOptOut, User
from agyary.services import guardrails, reminders, wa_send
from tests.test_family_replies import _reminded, _signed
from tests.test_reminder_sender import BEHDIN_PHONE, _settings

STOP = {"type": "text", "from": BEHDIN_PHONE.lstrip("+"), "text": {"body": "Stop"}}


@pytest.fixture
def sent(monkeypatch):
    """Sending is live with a token; every text reply is caught here, not sent."""
    monkeypatch.setenv("REMINDERS_SEND_MODE", "live")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "555000111")
    config.get_settings.cache_clear()
    box = []

    async def fake_send_text(settings, phone, body, client=None):
        box.append((phone, body))
        return True

    monkeypatch.setattr(wa_send, "send_text", fake_send_text)
    yield box
    config.get_settings.cache_clear()


async def _mobed_name(db) -> str:
    first = (await db.execute(
        select(Customer).where(Customer.phone == BEHDIN_PHONE).order_by(Customer.id).limit(1))).scalar_one()
    return (await db.get(User, first.owner_user_id)).name


async def test_a_first_stop_gets_one_kind_reply_naming_the_mobed(client, db, seeded, sent):
    await _reminded(client, db, seeded)
    raw, h = _signed(STOP)
    assert (await client.post("/webhooks/whatsapp", content=raw, headers=h)).status_code == 200
    name = await _mobed_name(db)
    assert sent == [(BEHDIN_PHONE, reminders.STOP_ACK_TEXT.format(mobed=name))]
    assert "May you and your family be in peace." in sent[0][1]
    row = await db.get(ReminderOptOut, BEHDIN_PHONE)
    await db.refresh(row)
    assert row.acknowledged_at is not None


async def test_a_second_stop_or_a_redelivery_gets_nothing_more(client, db, seeded, sent):
    await _reminded(client, db, seeded)
    raw, h = _signed(STOP)
    for _ in range(2):                                   # Meta redelivering the same webhook
        await client.post("/webhooks/whatsapp", content=raw, headers=h)
    raw, h = _signed({**STOP, "text": {"body": "STOP!"}})  # and the family saying it again
    await client.post("/webhooks/whatsapp", content=raw, headers=h)
    assert len(sent) == 1


async def test_a_number_that_had_already_stopped_gets_no_reply(client, db, seeded, sent):
    await _reminded(client, db, seeded)
    await reminders.record_stop(db, BEHDIN_PHONE, said="stop")
    await db.commit()
    raw, h = _signed(STOP)
    await client.post("/webhooks/whatsapp", content=raw, headers=h)
    assert sent == []


async def test_a_number_we_never_reminded_gets_no_reply(client, db, seeded, sent):
    raw, h = _signed({**STOP, "from": "919944409999"})
    await client.post("/webhooks/whatsapp", content=raw, headers=h)
    assert sent == []


async def test_no_reply_while_paused_over_its_cap_or_not_live(client, db, seeded, sent):
    await _reminded(client, db, seeded)
    await reminders.record_stop(db, BEHDIN_PHONE, said="stop")
    assert await reminders.acknowledge_stop(db, _settings(reminders_send_mode="off"), BEHDIN_PHONE) == "not sending"
    assert await reminders.acknowledge_stop(db, _settings(whatsapp_access_token=""), BEHDIN_PHONE) == "not sending"
    assert await reminders.acknowledge_stop(
        db, _settings(reminders_stop_ack_daily_cap=0), BEHDIN_PHONE) == "over the daily limit"
    await guardrails.pause(db, _settings(), "checking the bill")
    assert await reminders.acknowledge_stop(db, _settings(), BEHDIN_PHONE) == "paused"
    await guardrails.resume(db)
    assert await reminders.acknowledge_stop(db, _settings(), BEHDIN_PHONE) == "sent"
    assert len(sent) == 1
