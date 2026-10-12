"""Sign-in by a six digit code sent over WhatsApp.

This is the weaker of our two sign-ins and is built accordingly. The other
(services/wa_login.py) has the mobed message US, so their number is proven by
Meta and nothing paid is ever sent. Here the caller TYPES a number and we send a
paid message to it, which makes this endpoint three things at once: a way to
spend our money, a way to message strangers, and a way to guess at someone's
code. Each is limited:

  money       a daily cap on codes sent overall, a harder hourly cap on codes to
              numbers with no account, and the pause switch (guardrails) that
              stops all outbound WhatsApp. An account-level error from Meta
              pauses it automatically.
  strangers   a cool-down between codes to one number and a few per hour and
              per day, so nobody can be flooded.
  guessing    six digits, five wrong tries, five minutes, then it is dead. The
              code is never stored, only a salted digest, and only the newest
              code for a number counts, so requesting more does not multiply
              the guesses.

Nothing here says whether a number has an account: the request and the check
answer the same either way. (The caps do differ for new numbers, which is the
price of letting a first-time mobed in at all.)

The code is sent as an Authentication template with a Copy code button, which is
what lets the app pick it up from the clipboard when the user comes back.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import LoginOtp, User
from agyary.services import guardrails, mobed_auth
from agyary.services.reminder_sender import ACCOUNT_CODES

logger = logging.getLogger(__name__)

CODE_LENGTH = 6
COOLDOWN_SECONDS = 30
PER_PHONE_HOURLY = 3
PER_PHONE_DAILY = 8
MAX_ATTEMPTS = 5

# Exactly six digits, not six out of a longer number: a phone number in a pasted
# message is not a candidate code.
_CODE = re.compile(rf"(?<!\d)\d{{{CODE_LENGTH}}}(?!\d)")

# What a caller is told when we cannot send. Deliberately one message: the
# reason (a paused account, a cap, a Meta error) is for the admins, not for
# someone typing a number.
UNAVAILABLE = "We couldn't send a code just now. Please use the WhatsApp sign-in instead."


class OtpError(Exception):
    """Safe to show the caller. ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 400, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _secret(settings: Settings) -> str:
    return settings.jwt_secret_key


def _digest(settings: Settings, salt: str, phone: str, code: str) -> str:
    return hmac.new(
        _secret(settings).encode(), f"{salt}:{phone}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def _requester(settings: Settings, ip: str) -> str:
    return hashlib.sha256(f"{_secret(settings)}:{ip}".encode()).hexdigest()[:16]


def generate_code() -> str:
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


def extract_code(text: str) -> str | None:
    """A six digit code out of whatever was pasted: "123456", "123 456", or the
    whole WhatsApp message. None if there is not exactly one candidate."""
    squeezed = re.sub(r"(?<=\d)[\s-]+(?=\d)", "", text or "")
    found = _CODE.findall(re.sub(r"\D+", " ", squeezed).strip())
    return found[0] if len(found) == 1 else None


# ---------------------------------------------------------------------------
# Asking for a code
# ---------------------------------------------------------------------------
async def _count(db: AsyncSession, *where) -> int:
    return (await db.execute(select(func.count()).select_from(LoginOtp).where(*where))).scalar_one()


async def request_code(
    db: AsyncSession, settings: Settings, phone: str, ip: str, client: httpx.AsyncClient,
    now: datetime | None = None,
) -> dict:
    now = now or _now()
    if settings.otp_mode != "live":
        raise OtpError("Sign-in by code is not available. Please use the WhatsApp sign-in instead.", 503)
    if await guardrails.paused_reason(db):
        raise OtpError(UNAVAILABLE, 503)

    # Per-number limits count every request that was not a failure, including
    # "suppressed" ones (a number that could not sign in: nothing was sent, see
    # below), so a number that has no account meets the same cool-down as one
    # that does. The spend caps count only what could really have gone out.
    sent_ok = LoginOtp.status != "failed"
    really_sent = LoginOtp.status.notin_(("failed", "suppressed"))

    # One code at a time to a number, and only a few: nobody should be flooded
    # because somebody else typed their number.
    latest = (
        await db.execute(
            select(LoginOtp.created_at).where(LoginOtp.phone == phone).order_by(LoginOtp.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if latest is not None:
        wait = COOLDOWN_SECONDS - int((now - latest).total_seconds())
        if wait > 0:
            raise OtpError(f"Please wait {wait} seconds before asking for another code.", 429, retry_after=wait)
    if await _count(db, LoginOtp.phone == phone, sent_ok, LoginOtp.created_at > now - timedelta(hours=1)) >= PER_PHONE_HOURLY:
        raise OtpError("Too many codes were asked for this number. Please try again in an hour.", 429, retry_after=3600)
    if await _count(db, LoginOtp.phone == phone, sent_ok, LoginOtp.created_at > now - timedelta(days=1)) >= PER_PHONE_DAILY:
        raise OtpError("Too many codes were asked for this number today. Please try again tomorrow.", 429, retry_after=86400)

    # The money: a ceiling on codes sent today overall.
    day_start, day_end = guardrails.day_bounds(now)
    if await _count(db, really_sent, LoginOtp.created_at >= day_start, LoginOtp.created_at < day_end) >= settings.otp_daily_cap:
        await guardrails.alert_admins(
            db, settings, "Sign-in code limit reached",
            f"{settings.otp_daily_cap} sign-in codes have been sent today, so no more will go out until tomorrow. "
            "People can still use the WhatsApp sign-in. If this is not you signing in, someone may be abusing it.",
            now=now,
        )
        raise OtpError(UNAVAILABLE, 429)

    # Strangers are what an abuser would send to, so they get a harder cap.
    is_new = (await db.execute(select(User.id).where(User.phone == phone))).first() is None
    if is_new and await _count(
        db, LoginOtp.is_new_number.is_(True), really_sent, LoginOtp.created_at > now - timedelta(hours=1)
    ) >= settings.otp_new_number_hourly_cap:
        raise OtpError(UNAVAILABLE, 429)

    # A sweep on the way past: nothing here is worth keeping for long.
    await db.execute(delete(LoginOtp).where(LoginOtp.created_at < now - timedelta(days=2)))

    code, salt = generate_code(), secrets.token_hex(8)
    row = LoginOtp(
        phone=phone, salt=salt, code_hash=_digest(settings, salt, phone, code),
        expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
        is_new_number=is_new, requester=_requester(settings, ip), status="pending", created_at=now,
    )
    db.add(row)
    await db.flush()

    out = {"expires_in": settings.otp_ttl_seconds, "resend_after": COOLDOWN_SECONDS}
    if not settings.whatsapp_access_token and not settings.app_debug:
        raise OtpError(UNAVAILABLE, 503)

    # A number that could not sign in anyway (no account, and SIGNUP_MODE does
    # not let it make one) is sent nothing - no cost, no message to a stranger -
    # but answered exactly as any other, so this endpoint cannot be used to find
    # out who is a mobed. The row keeps the per-number limits honest.
    if not await mobed_auth.may_sign_in(db, phone):
        row.status = "suppressed"
        return out

    if not settings.whatsapp_access_token:
        # No way to send. Fine on a laptop, where the code comes back in the
        # response so the flow can be tried end to end (refused above anywhere else).
        row.status = "sent"
        out["debug_code"] = code
        return out

    try:
        row.wa_message_id = await _send(client, settings, phone, code)
    except _AccountProblem as exc:
        row.status = "failed"
        await guardrails.pause(db, settings, f"Meta reported a problem with the account ({exc.code}): {exc}", now=now)
        await db.commit()                      # the pause must outlive the error below
        raise OtpError(UNAVAILABLE, 503) from exc
    except _SendFailed as exc:
        row.status = "failed"
        logger.warning("Sign-in code could not be sent: %s", exc)
        await db.commit()
        raise OtpError(UNAVAILABLE, 503) from exc
    row.status = "sent"
    return out


class _SendFailed(Exception):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class _AccountProblem(_SendFailed):
    """Something wrong with the account itself: the token, payment, a throttle."""


def _payload(settings: Settings, phone: str, code: str) -> dict:
    # An Authentication template: the code is both the body's blank and the
    # Copy code button's value - Meta requires the button to carry it.
    return {
        "messaging_product": "whatsapp",
        "to": phone.lstrip("+"),
        "type": "template",
        "template": {
            "name": settings.otp_template,
            "language": {"code": settings.whatsapp_template_language},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": code}]},
                {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": code}]},
            ],
        },
    }


async def _send(client: httpx.AsyncClient, settings: Settings, phone: str, code: str) -> str:
    url = f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{settings.whatsapp_phone_number_id}/messages"
    try:
        resp = await client.post(
            url, json=_payload(settings, phone, code),
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        )
    except httpx.HTTPError as exc:
        raise _SendFailed(f"network error: {exc.__class__.__name__}") from exc
    if resp.status_code == 200:
        try:
            return resp.json()["messages"][0]["id"]
        except (KeyError, IndexError, ValueError) as exc:
            raise _SendFailed("Meta accepted the message but sent no id") from exc
    code_, reason = None, f"HTTP {resp.status_code}"
    try:
        error = resp.json()["error"]
        reason, code_ = error["message"], error.get("code")
    except (KeyError, ValueError, TypeError):
        pass
    if code_ in ACCOUNT_CODES:
        raise _AccountProblem(reason, code_)
    raise _SendFailed(reason, code_)


# ---------------------------------------------------------------------------
# Checking it
# ---------------------------------------------------------------------------
async def verify_code(
    db: AsyncSession, settings: Settings, phone: str, code: str, now: datetime | None = None
) -> bool:
    """True if ``code`` is the live code for ``phone``, which it then spends.

    Every wrong guess is counted against that one code, and after the limit it
    is dead even if the right digits arrive later. Only the newest code for a
    number counts.
    """
    now = now or _now()
    if not _CODE.fullmatch(code or ""):
        return False                     # not a guess at all; costs the real code nothing
    row = (
        await db.execute(
            select(LoginOtp)
            .where(LoginOtp.phone == phone, LoginOtp.status == "sent")
            .order_by(LoginOtp.created_at.desc(), LoginOtp.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.consumed_at is not None or row.expires_at <= now or row.attempts >= MAX_ATTEMPTS:
        return False
    row.attempts += 1
    if not hmac.compare_digest(_digest(settings, row.salt, phone, code), row.code_hash):
        await db.flush()
        return False
    row.consumed_at = now
    await db.flush()
    return True
