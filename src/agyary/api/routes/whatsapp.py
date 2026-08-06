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
from agyary.messaging import wa_flows
from agyary.messaging.handler import handle_message_with_outbox_ids
from agyary.messaging.send_worker import enqueue_send
from agyary.messaging.wa_flows_crypto import (
    FLOW_ENDPOINT_ERROR_STATUS,
    FlowDecryptionError,
    decrypt_request,
    encrypt_response,
)
from agyary.models import Agyary, AgyaryUser, Service, User, WhatsAppMessage

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
        if "nfm_reply" in interactive:
            return _extract_flow_reply(interactive["nfm_reply"])
    return ""


def _extract_flow_reply(nfm_reply: dict) -> str:
    """A completed WhatsApp Flow (nfm_reply) carries its submitted fields as
    a JSON string in response_json. Every Flow this codebase sends has
    exactly one Dropdown field per screen (wa_flows.py), so its single
    value - already an option id like "roj_2" or "svc_5" - is the routable
    text, letting the existing button/list step handlers (matched_option)
    consume it without a parallel input-handling path."""
    try:
        response_data = json.loads(nfm_reply.get("response_json") or "{}")
    except (TypeError, ValueError):
        return ""
    if isinstance(response_data, dict) and response_data:
        return str(next(iter(response_data.values())))
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


async def _resolve_dynamic_options(db: AsyncSession, purpose: str, agyary_id: int) -> list[dict]:
    """The current option list for a dynamic Flow (module 2 plumbing; the
    actual "choose who to book with" / services-list steps that SEND these
    Flows are built in modules 4/5 - this resolver is what the data-exchange
    endpoint calls regardless of which flow triggered it)."""
    if purpose == wa_flows.PURPOSE_PRIEST_PICKER:
        result = await db.execute(
            select(User)
            .join(AgyaryUser, AgyaryUser.user_id == User.id)
            .where(
                AgyaryUser.agyary_id == agyary_id,
                AgyaryUser.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
        return [{"id": f"priest_{u.id}", "title": u.name[:24]} for u in result.scalars()]
    if purpose == wa_flows.PURPOSE_SERVICES_PICKER:
        result = await db.execute(
            select(Service)
            .where(Service.agyary_id == agyary_id, Service.is_active.is_(True))
            .order_by(Service.display_order, Service.id)
        )
        services = [s for s in result.scalars() if s.name.strip().lower() != "machi"]
        return [{"id": f"svc_{s.id}", "title": s.name[:24]} for s in services]
    return []


@router.post("/flows/data-exchange", include_in_schema=False)
async def flows_data_exchange(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    """Meta's Flows Data Exchange endpoint for the dynamic Flows (priest
    picker, per-agyari services list). Encryption per wa_flows_crypto.py,
    verified against Meta's primary doc - see that module's docstring.
    Also signed the same way as the main webhook (X-Hub-Signature-256
    against the app secret) - confirmed against the same primary doc during
    module 2's review pass, not assumed by analogy: "Meta signs all
    endpoint requests with a SHA256 signature and includes the signature in
    the request's X-Hub-Signature-256 header." Reuses _valid_signature,
    the exact check receive_webhook already does.
    Decryption failure -> HTTP 421 (Meta's required status, not a generic
    4xx/5xx), so the client knows to refresh its public key rather than
    silently retrying against a stale one.
    """
    settings = get_settings()
    raw_body = await request.body()
    signature_header = request.headers.get("x-hub-signature-256", "")
    if not _valid_signature(raw_body, signature_header, settings.whatsapp_app_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        body = json.loads(raw_body) if raw_body else {}
        decrypted, aes_key, iv = decrypt_request(
            body, settings.whatsapp_flows_private_key_pem.encode()
        )
    except (FlowDecryptionError, ValueError, KeyError):
        return PlainTextResponse(status_code=FLOW_ENDPOINT_ERROR_STATUS, content="")

    if decrypted.get("action") == "ping":
        response_payload: dict = {"data": {"status": "active"}}
    else:
        flow_token = decrypted.get("flow_token", "")
        try:
            purpose, agyary_id, _nonce = wa_flows.parse_flow_token(flow_token)
        except ValueError:
            return PlainTextResponse(status_code=FLOW_ENDPOINT_ERROR_STATUS, content="")
        options = await _resolve_dynamic_options(db, purpose, agyary_id)
        response_payload = {"screen": decrypted.get("screen"), "data": {"options": options}}

    encrypted = encrypt_response(response_payload, aes_key, iv)
    return PlainTextResponse(content=encrypted, status_code=200)
