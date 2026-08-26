"""WhatsApp Cloud API webhook: the receiving half of inbound sign-in.

This is deliberately much smaller than the webhook that used to live here.
That one was the front door of a whole behdin-facing conversation bot: it
resolved a tenant from the phone_number_id, decrypted WhatsApp Flows
payloads, tracked delivery statuses, logged every message and pushed
replies onto a send-worker queue. All of that is gone.

What is left has one job. A mobed has opened the app, been given a code,
and sent it to us from their own WhatsApp. We check Meta signed the
payload, find the code, and record which number it arrived from. The
browser that started the attempt is polling and collects the session.

Nothing here sends anything. There is no outbound leg at all, which is the
entire reason this path is free: a business-initiated message needs an
approved template and costs money per conversation, and we never initiate.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.services import wa_login

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


@router.get("", include_in_schema=False)
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta's one-time subscription handshake: echo the challenge back if
    the verify token matches the one configured in the dashboard."""
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


def _extract_text(message: dict) -> str:
    """Only plain text matters now. The bot also routed button, list and
    Flow replies; a sign-in is someone sending a code."""
    if message.get("type") == "text":
        return (message.get("text") or {}).get("body", "")
    return ""


@router.post("", include_in_schema=False)
async def receive_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    """Always 200, as fast as possible.

    Meta retries anything that isn't a prompt 200, so an unrecognised
    message must not look like a failure - it is simply somebody messaging
    the number, which is allowed and not our business. The only thing that
    earns a rejection is a payload we cannot prove came from Meta.
    """
    raw_body = await request.body()
    settings = get_settings()

    # An unset app secret would make hmac compare against b"" and accept
    # anything, so refuse outright rather than verifying nothing.
    if not settings.whatsapp_app_secret:
        logger.error("Webhook received but WHATSAPP_APP_SECRET is unset - rejecting")
        raise HTTPException(status_code=503, detail="Webhook not configured")

    signature_header = request.headers.get("x-hub-signature-256", "")
    if not _valid_signature(raw_body, signature_header, settings.whatsapp_app_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(raw_body) if raw_body else {}
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for message in (change.get("value") or {}).get("messages", []):
                await _process_message(db, message)

    await db.commit()
    return Response(status_code=200)


async def _process_message(db: AsyncSession, message: dict) -> None:
    from_phone = message.get("from")
    code = wa_login.extract_code(_extract_text(message))
    if not code or not from_phone:
        return

    # wa.me strips the +; every phone we store is E.164 with one.
    if not from_phone.startswith("+"):
        from_phone = f"+{from_phone}"

    # A replayed delivery finds the attempt already claimed and is ignored -
    # which is why this needs no separate message-id dedupe table the way
    # the bot did. The attempt itself is the idempotency key.
    claimed = await wa_login.claim(db, code, from_phone)
    logger.info("Inbound sign-in code %s: %s", code, "claimed" if claimed else "no live attempt")



# ---------------------------------------------------------------------------
# Local development
# ---------------------------------------------------------------------------
@router.post("/simulate", include_in_schema=False)
async def simulate_inbound(
    payload: dict, db: AsyncSession = Depends(get_db)
) -> dict:
    """Stand in for Meta on a machine Meta cannot reach.

    Sign-in has no outbound leg at all, so the code is already on screen -
    the thing that cannot happen on a laptop is the message coming BACK.
    This closes that loop without standing up a tunnel.

    Debug-only and registered nowhere in the schema. It grants a session
    for any number the caller names, so APP_DEBUG=false in production is
    load-bearing: with it true this endpoint is a complete authentication
    bypass. The signed webhook above is the only way to claim an attempt
    once debug is off.
    """
    if not get_settings().app_debug:
        raise HTTPException(status_code=404)

    code = str(payload.get("code", "")).strip()
    phone = str(payload.get("phone", "")).strip()
    if not code or not phone:
        raise HTTPException(status_code=400, detail="code and phone are required")

    await _process_message(db, {"type": "text", "from": phone, "text": {"body": code}})
    await db.commit()
    return {"simulated": True, "code": code, "phone": phone}
