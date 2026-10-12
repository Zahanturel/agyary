"""Sign-in by a code sent over WhatsApp: the HTTP layer.

The rules, and the reasons for them, are in services/otp.py. This is the
second way in; the first (the mobed messages us a code) is in routes/mobed.py
and stays available, both as the way a brand new mobed is proven by Meta rather
than by a typed number, and as the fallback whenever this one is off, paused or
over its limit.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.api.routes.mobed import _wa_login_session
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.services import bot_check, otp, wa_login
from agyary.services.phone import Phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobed", tags=["otp"])


class OtpRequestIn(BaseModel):
    phone: Phone
    # The Cloudflare Turnstile token the login screen got from its widget.
    turnstile_token: str | None = None


class OtpVerifyIn(BaseModel):
    phone: Phone
    code: str


@router.get("/auth/options")
async def auth_options() -> dict:
    """What sign-in methods this server offers, so the login screen can show
    the right ones instead of finding out by failing. Codes are offered only
    when they are live AND the bot check is configured (D3), and the screen is
    given the check's public site key to show it."""
    settings = get_settings()
    offered = settings.otp_mode == "live" and bot_check.configured(settings)
    return {"otp": offered, "turnstile_site_key": settings.turnstile_site_key.strip() or None}


def _refused(exc: otp.OtpError) -> HTTPException:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return HTTPException(status_code=exc.status, detail=str(exc), headers=headers)


@router.post("/auth/otp/request")
async def otp_request(
    payload: OtpRequestIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    """Send a code to this number. The answer is the same whether or not the
    number has an account."""
    rate_limit.enforce(request, "otp_request", max_requests=10, window_seconds=600)
    rate_limit.enforce_key(f"otp_request_phone:{payload.phone}", max_requests=5, window_seconds=600)
    settings = get_settings()
    if settings.otp_mode == "live":
        # D3: no bot check, no codes - however the rest is configured.
        if not bot_check.configured(settings):
            logger.error("OTP_MODE is live but the bot check (TURNSTILE_*) is not configured; refusing codes")
            raise HTTPException(status_code=503, detail=otp.UNAVAILABLE)
        if not await bot_check.verify(settings, payload.turnstile_token, rate_limit.client_ip(request)):
            raise HTTPException(status_code=400, detail="Please complete the check and try again.")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            out = await otp.request_code(
                db, get_settings(), payload.phone, rate_limit.client_ip(request), client
            )
    except otp.OtpError as exc:
        raise _refused(exc) from exc
    await db.commit()
    return out


@router.post("/auth/otp/verify")
async def otp_verify(
    payload: OtpVerifyIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> dict:
    """Check the code. On success this signs the caller in exactly as the other
    method does - including asking a first-time mobed for their name."""
    rate_limit.enforce(request, "otp_verify", max_requests=30, window_seconds=600)
    rate_limit.enforce_key(f"otp_verify_phone:{payload.phone}", max_requests=15, window_seconds=600)
    # The app sends clean digits, but a pasted "123 456" or the whole message
    # should work too.
    code = otp.extract_code(payload.code) or payload.code.strip()
    if not await otp.verify_code(db, get_settings(), payload.phone, code):
        await db.commit()                      # a wrong guess must still be counted
        raise HTTPException(status_code=400, detail="That code is wrong or has expired.")

    poll_secret = await wa_login.create_claimed(db, payload.phone)
    settings = get_settings()
    response.set_cookie(
        "wa_login", poll_secret, httponly=True, secure=not settings.app_debug,
        samesite="lax", max_age=settings.wa_login_ttl_seconds,
    )
    return await _wa_login_session(db, response, poll_secret, payload.phone, "")



