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
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import Notification, User
from agyary.services import reminder_sender, reminders, wa_login, wa_send

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])

MAX_WEBHOOK_BYTES = 1_000_000


@router.get("", include_in_schema=False)
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta's one-time subscription handshake: echo the challenge back if
    the verify token matches the one configured in the dashboard."""
    settings = get_settings()
    # Refused while the token is unset: "" must not match an empty request (I-6).
    expected = settings.whatsapp_verify_token
    if hub_mode == "subscribe" and expected and hmac.compare_digest(hub_verify_token.encode(), expected.encode()):
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


def _valid_signature(raw_body: bytes, header_value: str, app_secret: str) -> bool:
    if not header_value.startswith("sha256="):
        return False
    provided = header_value.removeprefix("sha256=")
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def _extract_text(message: dict) -> str:
    """What the person said: typed text, or the label of a button they tapped
    (a Stop button on a reminder, a quick reply)."""
    kind = message.get("type")
    if kind == "text":
        return (message.get("text") or {}).get("body", "")
    if kind == "button":
        button = message.get("button") or {}
        return button.get("text") or button.get("payload") or ""
    if kind == "interactive":
        reply = message.get("interactive") or {}
        chosen = reply.get("button_reply") or reply.get("list_reply") or {}
        return chosen.get("title", "")
    return ""


@router.post("", include_in_schema=False)
async def receive_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    """Always 200, as fast as possible.

    Meta retries anything that isn't a prompt 200, so an unrecognised
    message must not look like a failure - it is simply somebody messaging
    the number, which is allowed and not our business. The only thing that
    earns a rejection is a payload we cannot prove came from Meta.
    """
    # Meta's payloads are a few kilobytes. Refusing anything large costs a
    # genuine delivery nothing and stops an oversized body being read, hashed
    # and parsed for nothing. Its declared size is checked before it is read
    # (I-1), and the real size after, since a sender can leave that out.
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
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
    now = datetime.now(timezone.utc)
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            for message in value.get("messages", []):
                await _process_message(db, message)
            # Delivery receipts for reminders we sent.
            for receipt in value.get("statuses", []):
                errors = receipt.get("errors") or []
                reason = None
                if errors:
                    # Codes and details, not titles: Meta is retiring the titles (RM-8b).
                    first = errors[0]
                    detail = (first.get("error_data") or {}).get("details") or first.get("message") or first.get("title")
                    reason = f"{detail} ({first.get('code')})" if first.get("code") else detail
                if receipt.get("id") and receipt.get("status"):
                    await reminder_sender.apply_status(
                        db, receipt["id"], receipt["status"], reason, now,
                        recipient_user_id=receipt.get("recipient_user_id"),
                    )

    await db.commit()
    return Response(status_code=200)


async def _sender_phone(db: AsyncSession, message: dict) -> str | None:
    """The sender's number. WhatsApp may leave it out for someone who uses a
    username, sending only their id (``from_user_id``, a BSUID); then it is the
    number of the mobed who signed in with that id before, or of the family a
    reminder with that id went to - else unknown (AU-4)."""
    from_phone = message.get("from")
    if from_phone:
        # wa.me strips the +; every phone we store is E.164 with one.
        return from_phone if from_phone.startswith("+") else f"+{from_phone}"
    wa_user_id = message.get("from_user_id")
    if not wa_user_id:
        return None
    mobed = (await db.execute(select(User.phone).where(User.wa_user_id == wa_user_id))).scalar_one_or_none()
    if mobed:
        return mobed
    return (
        await db.execute(
            select(Notification.recipient_phone)
            .where(Notification.recipient_user_id == wa_user_id)
            .order_by(Notification.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _process_message(db: AsyncSession, message: dict) -> None:
    from_phone = await _sender_phone(db, message)
    wa_user_id = message.get("from_user_id")
    text = _extract_text(message)
    if not from_phone:
        # Nothing to stop, forward or prove - except a sign-in, which is told
        # plainly that WhatsApp did not share the number.
        code = wa_login.extract_code(text)
        if code and wa_user_id:
            await wa_login.claim(db, code, None, wa_user_id=wa_user_id)
        return

    # A family replying STOP to a reminder. Handled before sign-in because
    # honouring it must never depend on anything else about the message.
    if reminders.is_stop(text):
        first = not await reminders.already_stopped(db, from_phone)
        told = await reminders.record_stop(db, from_phone, said=text)
        logger.info("Inbound STOP: %d mobed(s) notified", told)
        if first:
            # One kind line back - once per number, never to one that had stopped.
            context = (message.get("context") or {}).get("id")
            outcome = await reminders.acknowledge_stop(db, get_settings(), from_phone, context_id=context)
            logger.info("STOP acknowledgement: %s", outcome)
        return

    code = wa_login.extract_code(text)
    if not code:
        # Anything else a family writes back reaches the mobed whose reminder it
        # answers - never dropped unread, and never anyone else's (RM-4, D2).
        context = (message.get("context") or {}).get("id")
        if text.strip() and await reminders.forward_reply(db, from_phone, text, context_id=context):
            logger.info("Inbound reply passed to its mobed")
        return

    # A replayed delivery finds the attempt already claimed and is ignored -
    # which is why this needs no separate message-id dedupe table the way
    # the bot did. The attempt itself is the idempotency key.
    attempt = await wa_login.claim(db, code, from_phone, wa_user_id=wa_user_id)
    logger.info("Inbound sign-in code: %s", "claimed" if attempt else "no live attempt")
    if attempt is None:
        return
    # AU-1: the screen that started this finishes only with a number sent back
    # to this phone. If nothing can be sent (a laptop, or Meta refusing), the
    # sign-in goes ahead as before rather than locking everyone out.
    settings = get_settings()
    if settings.signin_confirmation.strip().lower() == "on" and wa_send.can_send(settings):
        number = await wa_login.require_confirmation(db, attempt)
        if not await wa_send.send_text(settings, from_phone, wa_login.confirmation_message(number)):
            attempt.confirm_hash = None
            logger.warning("Sign-in confirmation could not be sent; finishing without it")



# ---------------------------------------------------------------------------
# Local development
# ---------------------------------------------------------------------------
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@router.post("/simulate", include_in_schema=False)
async def simulate_inbound(
    payload: dict, request: Request, db: AsyncSession = Depends(get_db)
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

    And even with debug on it answers only a caller on this machine: on a
    server, every request arrives through the tunnel from another container,
    so a debug flag left on by mistake still opens nothing to the internet.
    """
    peer = request.client.host if request.client else ""
    if not get_settings().app_debug or peer not in _LOOPBACK:
        raise HTTPException(status_code=404)

    code = str(payload.get("code", "")).strip()
    phone = str(payload.get("phone", "")).strip()
    if not code or not phone:
        raise HTTPException(status_code=400, detail="code and phone are required")

    await _process_message(db, {"type": "text", "from": phone, "text": {"body": code}})
    await db.commit()
    return {"simulated": True, "code": code, "phone": phone}
