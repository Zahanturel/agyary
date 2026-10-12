"""Sign-in: the mobed messages us, not the other way round.

The path this replaced sent a code out, which needs a pre-approved
Authentication template, an API token and a billable conversation per
send. This one needs none of those, because the mobed sends US a message
and nothing is business-initiated. It still needs a real WABA number for
the webhook to receive on - added, ownership-verified and registered - but
no template, no System User token and no per-send cost.

The security shape is better than outbound, not merely cheaper. Outbound
starts from a phone number the caller typed, which we then have to be
careful not to confirm or deny. Here the caller supplies no number at all -
we learn it from ``message.from`` on a payload Meta signed - so the number
is proven rather than claimed, and there is nothing to enumerate.

Two secrets, deliberately not the same one:

``code`` goes into the wa.me link, through the user's WhatsApp, and back to
us via the webhook. It is a bearer token by construction - anyone who sees
the link can send that code from their own WhatsApp, and doing so binds THEIR
number to the attempt. That cuts both ways: an attacker who starts an attempt
and tricks a mobed into tapping Send on the link would get the mobed's
account. So (AU-1) when the code arrives we reply to that phone with a short
confirmation number and a warning, and the attempt finishes only when that
number is typed on the screen that started it - which the attacker never
sees. Where nothing can be sent (a laptop with no token), that step is skipped.

``poll_secret`` never leaves the originating browser, as an httpOnly
cookie. The poll endpoint matches on its digest rather than on the code, so
holding the code is not enough to collect the session it created.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import get_settings
from agyary.models import WaLoginAttempt

# Crockford's base32: no I, L, O or U. The first three because a code gets
# read off one screen and typed or checked on another; U because excluding
# it keeps accidental words out of a code the user will actually look at.
_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ0123456789"
CODE_LENGTH = 10

# Ten characters of a 32-symbol alphabet is about 2^50. The code is not
# delivered to one known phone the way a texted code is - it is a token anyone can
# send to a number they can look up - so it has to survive being sprayed at,
# which six digits would not.
_CODE_RE = re.compile(f"[{_ALPHABET}]{{{CODE_LENGTH}}}")

MESSAGE_PREFIX = "Mobed Diary sign-in:"


class WaLoginError(Exception):
    """Safe to show the caller."""


@dataclass(frozen=True)
class StartedLogin:
    code: str
    poll_secret: str
    wa_link: str
    expires_at: datetime


def generate_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def build_wa_link(code: str, number: str) -> str:
    """A wa.me deep link with the message pre-filled.

    wa.me wants the number without a leading +. The text is prefilled, not
    forced - the user can edit or retype it, which is why extraction below
    scans for the code rather than requiring an exact match.
    """
    text = f"{MESSAGE_PREFIX} {code}"
    return f"https://wa.me/{number.lstrip('+')}?text={quote(text)}"


def extract_code(text: str) -> str | None:
    """Pull a candidate code out of whatever the user actually sent.

    Permissive on purpose. The prefill is editable, phones interfere with
    capitalisation, and people add words. A false positive costs nothing:
    an unrecognised code simply matches no pending row.
    """
    if not text:
        return None
    match = _CODE_RE.search(text.upper())
    return match.group(0) if match else None


async def start(db: AsyncSession) -> StartedLogin:
    """Open an attempt. Nothing here identifies anybody yet."""
    settings = get_settings()
    if not settings.whatsapp_signin_number:
        raise WaLoginError(
            "WhatsApp sign-in is not configured on this server. "
            "Please contact the administrator."
        )

    # Sweep on the way past: these rows are short-lived and worthless once
    # expired, and this is the only endpoint that creates them.
    await db.execute(delete(WaLoginAttempt).where(WaLoginAttempt.expires_at < datetime.now(UTC)))

    code = generate_code()
    poll_secret = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.wa_login_ttl_seconds)

    db.add(
        WaLoginAttempt(
            code=code,
            poll_secret_hash=_hash_secret(poll_secret),
            expires_at=expires_at,
        )
    )
    await db.flush()
    return StartedLogin(
        code=code,
        poll_secret=poll_secret,
        wa_link=build_wa_link(code, settings.whatsapp_signin_number),
        expires_at=expires_at,
    )


def _expired(row: WaLoginAttempt) -> bool:
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at < datetime.now(UTC)


async def claim(
    db: AsyncSession, code: str, phone: str | None, *, wa_user_id: str | None = None
) -> WaLoginAttempt | None:
    """Bind the sender to the attempt ``code`` opened. Called by the webhook.

    ``phone`` is None when WhatsApp withheld the number (a username it could not
    map to a mobed); the attempt is then claimed with no number, and polling
    tells the person plainly. Returns the attempt, or None for anything that
    isn't a live, unclaimed attempt: an unknown code, an expired one, or one
    already claimed. All three are ordinary - Meta retries deliveries, and a
    retry of an already-claimed message must not reopen it.
    """
    row = (
        await db.execute(select(WaLoginAttempt).where(WaLoginAttempt.code == code))
    ).scalar_one_or_none()
    if row is None or row.claimed_at is not None or _expired(row):
        return None
    row.claimed_phone = phone
    row.claimed_wa_user_id = wa_user_id
    row.claimed_at = datetime.now(UTC)
    await db.flush()
    return row


CONFIRM_MAX_ATTEMPTS = 5


def _confirm_digest(row: WaLoginAttempt, number: str) -> str:
    return hashlib.sha256(f"{row.poll_secret_hash}:{number}".encode()).hexdigest()


async def require_confirmation(db: AsyncSession, row: WaLoginAttempt) -> str:
    """Put a fresh four digit confirmation number on a claimed attempt and
    return it, for the webhook to send to the phone. Only its digest is kept."""
    number = f"{secrets.randbelow(10_000):04d}"
    row.confirm_hash = _confirm_digest(row, number)
    row.confirm_attempts = 0
    await db.flush()
    return number


def confirmation_message(number: str) -> str:
    return (
        f"Mobed Diary: someone is signing in to Mobed Diary as you. If that is you, type {number} "
        "on the sign-in screen. If it is not you, do not share this number with anyone - "
        "nobody can sign in as you without it."
    )


async def peek(db: AsyncSession, poll_secret: str) -> WaLoginAttempt | None:
    """This browser's attempt, live or not. Does NOT consume it."""
    return (
        await db.execute(
            select(WaLoginAttempt).where(WaLoginAttempt.poll_secret_hash == _hash_secret(poll_secret))
        )
    ).scalar_one_or_none()


async def confirm(db: AsyncSession, row: WaLoginAttempt, number: str) -> bool:
    """Check the typed confirmation number. Five wrong tries and the attempt is
    spent, even for the right number afterwards."""
    if row.confirm_hash is None or row.confirm_attempts >= CONFIRM_MAX_ATTEMPTS or _expired(row):
        return False
    row.confirm_attempts += 1
    if not hmac.compare_digest(_confirm_digest(row, (number or "").strip()), row.confirm_hash):
        await db.flush()
        return False
    row.confirm_hash = None
    await db.flush()
    return True


async def create_claimed(db: AsyncSession, phone: str) -> str:
    """An attempt that is claimed from the start, for a phone already proven by
    another route (a code sent to it and typed back). Returns the poll secret
    for the cookie. Reusing this row is what lets that route share the rest of
    the flow - the first-time name step, the session, the cookie - unchanged."""
    settings = get_settings()
    poll_secret = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(
        WaLoginAttempt(
            code=generate_code(),
            poll_secret_hash=_hash_secret(poll_secret),
            expires_at=now + timedelta(seconds=settings.wa_login_ttl_seconds),
            claimed_phone=phone,
            claimed_at=now,
        )
    )
    await db.flush()
    return poll_secret


async def peek_claimed_phone(db: AsyncSession, poll_secret: str) -> str | None:
    """The phone this browser's attempt was claimed by, or None if it is
    still waiting. Does NOT consume the row.

    Split from consume() because a first-ever sign-in needs two round trips
    - claimed, then named - and the attempt has to survive the gap. Keeping
    it means the poll cookie stays the only credential in the flow; the
    alternative was handing the browser its own phone number back in a
    second cookie to post again, which is a bearer identity claim invented
    for no reason.

    An expired-or-missing attempt reads the same as a pending one here on
    purpose; the caller decides what to say based on whether it still holds
    a cookie at all.
    """
    row = await peek(db, poll_secret)
    if row is None or row.claimed_at is None or row.confirm_hash is not None:
        return None
    return row.claimed_phone


async def consume(db: AsyncSession, poll_secret: str) -> None:
    """Retire the attempt once a session has actually been issued for it."""
    await db.execute(
        delete(WaLoginAttempt).where(
            WaLoginAttempt.poll_secret_hash == _hash_secret(poll_secret)
        )
    )
    await db.flush()
