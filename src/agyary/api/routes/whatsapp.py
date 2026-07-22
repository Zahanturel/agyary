"""WhatsApp Cloud API webhook: verify + receive inbound traffic.

The webhook's only job is to persist and return 200 fast. It never calls the
Graph API itself - every outbound send happens out of the request path, in
the background send worker (agyary.messaging.send_worker), which is the
piece that survives an ungraceful restart. This route just resolves the
tenant, hands the message to handle_message_with_outbox_ids, and pushes the
resulting outbox row ids onto the worker's queue for an immediate wake-up.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.messaging.handler import handle_message_with_outbox_ids
from agyary.messaging.send_worker import enqueue_send
from agyary.models import Agyary, WhatsAppMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


@router.get("", include_in_schema=False)
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> PlainTextResponse:
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


def _valid_signature(raw_body: bytes, header_value: str, app_secret: str) -> bool:
    if not header_value.startswith("sha256="):
        return False
    provided = header_value.removeprefix("sha256=")
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


@router.post("", include_in_schema=False)
async def receive_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    raw_body = await request.body()
    settings = get_settings()
    signature_header = request.headers.get("x-hub-signature-256", "")
    if not _valid_signature(raw_body, signature_header, settings.whatsapp_app_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(raw_body) if raw_body else {}

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for status in value.get("statuses", []):
                await _process_status(db, status)
            for message in value.get("messages", []):
                await _process_inbound_message(db, value.get("metadata") or {}, message)

    await db.commit()
    return Response(status_code=200)


def _extract_text(message: dict) -> str:
    msg_type = message.get("type")
    if msg_type == "text":
        return (message.get("text") or {}).get("body", "")
    if msg_type == "interactive":
        interactive = message.get("interactive") or {}
        if "button_reply" in interactive:
            return interactive["button_reply"].get("id", "")
        if "list_reply" in interactive:
            return interactive["list_reply"].get("id", "")
    return ""


async def _process_inbound_message(db: AsyncSession, metadata: dict, message: dict) -> None:
    wa_message_id = message.get("id")
    phone_number_id = metadata.get("phone_number_id")
    from_phone = message.get("from")

    if wa_message_id:
        existing = (
            await db.execute(
                select(WhatsAppMessage.id).where(
                    WhatsAppMessage.wa_message_id == wa_message_id,
                    WhatsAppMessage.direction == "inbound",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            # Meta retries deliveries - already processed, nothing to do.
            logger.info("Duplicate inbound wa_message_id=%s - skipping", wa_message_id)
            return

    agyary = (
        await db.execute(select(Agyary).where(Agyary.wa_phone_number_id == phone_number_id))
    ).scalar_one_or_none()
    if agyary is None:
        logger.error("Webhook message for unknown phone_number_id=%s", phone_number_id)
        return

    text = _extract_text(message)
    if not text or not from_phone:
        return

    pairs = await handle_message_with_outbox_ids(
        db, agyary.id, from_phone, text, inbound_wa_message_id=wa_message_id
    )
    for _outgoing, outbox_id in pairs:
        if outbox_id is not None:
            await enqueue_send(outbox_id)


async def _process_status(db: AsyncSession, status: dict) -> None:
    wa_message_id = status.get("id")
    new_status = status.get("status")
    if not wa_message_id or not new_status:
        return
    row = (
        await db.execute(
            select(WhatsAppMessage).where(
                WhatsAppMessage.wa_message_id == wa_message_id,
                WhatsAppMessage.direction == "outbound",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        logger.warning("Status update for unknown wa_message_id=%s", wa_message_id)
        return
    row.status = new_status
