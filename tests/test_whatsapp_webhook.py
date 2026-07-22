"""Tests for the WhatsApp Cloud API webhook route: verification handshake,
signature enforcement, message/status handling, and dedup."""

from __future__ import annotations

import hashlib
import hmac
import json

from sqlalchemy import select

from agyary.core.config import get_settings
from agyary.models import Agyary, WhatsAppMessage

PHONE_NUMBER_ID = "PNID_TEST_123"


def _sign(body: bytes) -> str:
    secret = get_settings().whatsapp_app_secret
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def post_webhook(client, payload: dict):
    body = json.dumps(payload).encode()
    return await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={
            "x-hub-signature-256": _sign(body),
            "content-type": "application/json",
        },
    )


def text_message_payload(phone_number_id: str, from_phone: str, wa_message_id: str, text: str) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": [
                                {
                                    "id": wa_message_id,
                                    "from": from_phone,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def interactive_message_payload(
    phone_number_id: str, from_phone: str, wa_message_id: str, reply_id: str, kind: str = "button_reply"
) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": [
                                {
                                    "id": wa_message_id,
                                    "from": from_phone,
                                    "type": "interactive",
                                    "interactive": {kind: {"id": reply_id, "title": "n/a"}},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def status_payload(wa_message_id: str, status: str) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": wa_message_id,
                                    "status": status,
                                    "timestamp": "1700000000",
                                    "recipient_id": "919900011111",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


async def _set_phone_number_id(db, agyary_id: int, phone_number_id: str) -> None:
    agyary = await db.get(Agyary, agyary_id)
    agyary.wa_phone_number_id = phone_number_id
    await db.commit()


async def test_verify_handshake_right_token(client):
    token = get_settings().whatsapp_verify_token
    r = await client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "abc123"},
    )
    assert r.status_code == 200
    assert r.text == "abc123"


async def test_verify_handshake_wrong_token(client):
    r = await client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "definitely-not-the-right-token",
            "hub.challenge": "abc123",
        },
    )
    assert r.status_code == 403


async def test_invalid_signature_rejected_and_handler_never_called(client, monkeypatch):
    from agyary.api.routes import whatsapp as whatsapp_routes

    calls = []

    async def fake_handle(*args, **kwargs):
        calls.append((args, kwargs))
        return []

    monkeypatch.setattr(whatsapp_routes, "handle_message_with_outbox_ids", fake_handle)

    body = json.dumps(text_message_payload(PHONE_NUMBER_ID, "+919900011111", "wamid.X", "hi")).encode()
    r = await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"x-hub-signature-256": "sha256=" + "0" * 64},
    )
    assert r.status_code == 401
    assert calls == []


async def test_valid_text_message_creates_pending_outbox_row(client, db, seeded):
    await _set_phone_number_id(db, seeded["agyary_id"], PHONE_NUMBER_ID)
    phone = "+919900077001"

    r = await post_webhook(client, text_message_payload(PHONE_NUMBER_ID, phone, "wamid.T1", "hi"))
    assert r.status_code == 200

    rows = (
        (await db.execute(select(WhatsAppMessage).where(WhatsAppMessage.wa_phone == phone)))
        .scalars()
        .all()
    )
    inbound = [row for row in rows if row.direction == "inbound"]
    outbound = [row for row in rows if row.direction == "outbound"]
    assert len(inbound) == 1
    assert inbound[0].wa_message_id == "wamid.T1"
    assert outbound  # at least the "may we have your name" reply
    assert all(row.status == "pending" for row in outbound)
    assert all(row.attempts == 0 for row in outbound)
    assert all(row.next_attempt_at is not None for row in outbound)


async def test_interactive_button_reply_resolves_to_button_id(client, db, seeded):
    await _set_phone_number_id(db, seeded["agyary_id"], PHONE_NUMBER_ID)
    phone = "+919900077002"

    await post_webhook(client, text_message_payload(PHONE_NUMBER_ID, phone, "wamid.I1", "hi"))
    await post_webhook(
        client, text_message_payload(PHONE_NUMBER_ID, phone, "wamid.I2", "Jaidev Patel")
    )
    r = await post_webhook(
        client, interactive_message_payload(PHONE_NUMBER_ID, phone, "wamid.I3", "book_machi")
    )
    assert r.status_code == 200

    latest = (
        (
            await db.execute(
                select(WhatsAppMessage)
                .where(WhatsAppMessage.wa_phone == phone, WhatsAppMessage.direction == "outbound")
                .order_by(WhatsAppMessage.id.desc())
            )
        )
        .scalars()
        .first()
    )
    assert "departed" in latest.content["text"].casefold()


async def test_duplicate_wa_message_id_calls_handler_once(client, db, seeded, monkeypatch):
    from agyary.api.routes import whatsapp as whatsapp_routes

    await _set_phone_number_id(db, seeded["agyary_id"], PHONE_NUMBER_ID)
    phone = "+919900077003"

    real_handle = whatsapp_routes.handle_message_with_outbox_ids
    calls = []

    async def counting_wrapper(*args, **kwargs):
        calls.append(1)
        return await real_handle(*args, **kwargs)

    monkeypatch.setattr(whatsapp_routes, "handle_message_with_outbox_ids", counting_wrapper)

    payload = text_message_payload(PHONE_NUMBER_ID, phone, "wamid.DUP1", "hi")
    r1 = await post_webhook(client, payload)
    r2 = await post_webhook(client, payload)  # Meta retry: identical message id
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(calls) == 1

    inbound_count = (
        await db.execute(
            select(WhatsAppMessage).where(
                WhatsAppMessage.wa_message_id == "wamid.DUP1",
                WhatsAppMessage.direction == "inbound",
            )
        )
    ).scalars().all()
    assert len(inbound_count) == 1


async def test_statuses_payload_updates_row_without_calling_handler(client, db, seeded, monkeypatch):
    from agyary.api.routes import whatsapp as whatsapp_routes

    await _set_phone_number_id(db, seeded["agyary_id"], PHONE_NUMBER_ID)

    calls = []

    async def fake_handle(*args, **kwargs):
        calls.append(1)
        return []

    monkeypatch.setattr(whatsapp_routes, "handle_message_with_outbox_ids", fake_handle)

    # Pre-create an outbound row as if it had already been sent successfully.
    row = WhatsAppMessage(
        agyary_id=seeded["agyary_id"],
        direction="outbound",
        wa_phone="+919900011111",
        wa_message_id="wamid.SENT1",
        message_type="text",
        content={"to": "+919900011111", "text": "hello", "buttons": [], "sections": []},
        status="sent",
        attempts=0,
    )
    db.add(row)
    await db.commit()

    r = await post_webhook(client, status_payload("wamid.SENT1", "delivered"))
    assert r.status_code == 200
    assert calls == []

    await db.refresh(row)
    assert row.status == "delivered"
