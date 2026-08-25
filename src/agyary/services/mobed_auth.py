"""Mobed PWA authentication: phone + WhatsApp OTP -> JWT session.

Login is two steps. The caller submits a phone number; a short numeric
code goes to it over WhatsApp (services/otp_delivery.py); the caller
submits phone + code and gets the session back. The phone is the natural
unique key for the User row and the same key WhatsApp already uses, so
proving possession of it is the whole of the identity claim - there is no
password to remember, and priests were never going to want one.

This replaces an earlier name+phone step with no verification at all,
whose stated accepted risk was that anyone who knew a mobed's number could
type it in and read that mobed's calendar. The OTP is what turns "knows
the number" into "holds the phone".

Codes are hashed at rest (salted with the phone, so one stolen hash can't
be matched against another row), expire in minutes, and are capped at a
few attempts - a 6-digit code is only safe while all three hold.

Roles: every membership this app creates is a plain 'mobed'. The
panthaky/caretaker roles still exist in the schema and still gate the
WhatsApp booking flows, but nothing in this app can grant them - the
invite mechanism that used to do so was removed, since this app has no
role management and an unreachable endpoint that hands out privilege is
worse than no endpoint at all.

JWT pattern is unchanged: a short-lived access token plus a
longer-lived refresh token in an httpOnly cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import get_settings
from agyary.models import AgyaryUser, AuthOtp, User

JWT_ALGORITHM = "HS256"

DEFAULT_ROLE = "mobed"


class TokenError(Exception):
    """Invalid, expired, or wrong-type JWT - message is safe to show the caller."""


class OtpError(Exception):
    """OTP missing, expired, wrong, or out of attempts - safe to show the caller."""


# ---------------------------------------------------------------------------
# OTP issue / verify
# ---------------------------------------------------------------------------
def _hash_code(phone: str, code: str) -> str:
    """Salted with the phone so the stored digest is only meaningful for the
    row it sits in. A bare digest of a 6-digit code is a million-entry
    lookup table; per-phone salting makes each row its own problem, and the
    expiry plus attempt cap do the rest of the work."""
    return hashlib.sha256(f"{phone}:{code}".encode()).hexdigest()


def generate_code(length: int) -> str:
    """A uniformly random numeric code, leading zeros preserved."""
    return "".join(secrets.choice("0123456789") for _ in range(length))


async def issue_otp(db: AsyncSession, phone: str) -> str:
    """Mint a fresh code for ``phone`` and return the plaintext for sending.

    One live code per phone: requesting again replaces whatever was there,
    which both resets the attempt counter for an honest user who mistyped
    three times and stops a caller from farming a pile of simultaneously
    valid codes.
    """
    settings = get_settings()
    code = generate_code(settings.otp_length)
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.otp_ttl_seconds)

    row = await db.get(AuthOtp, phone)
    if row is None:
        row = AuthOtp(phone=phone, code_hash=_hash_code(phone, code), expires_at=expires_at, attempts=0)
        db.add(row)
    else:
        row.code_hash = _hash_code(phone, code)
        row.expires_at = expires_at
        row.attempts = 0
    await db.flush()
    return code


async def verify_otp(db: AsyncSession, phone: str, code: str) -> None:
    """Consume the live code for ``phone``; raise OtpError if it isn't valid.

    A correct code is deleted on use, so it is good exactly once. A wrong
    one burns an attempt, and running out invalidates the code entirely
    rather than merely refusing this guess - otherwise the cap would only
    slow an attacker down between fresh requests instead of stopping them.
    """
    settings = get_settings()
    row = await db.get(AuthOtp, phone)
    if row is None:
        raise OtpError("No sign-in code was requested for this number. Please request one.")

    expires_at = row.expires_at
    if expires_at.tzinfo is None:  # tz-naive only if a caller wrote it that way
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        await db.delete(row)
        await db.flush()
        raise OtpError("That sign-in code has expired. Please request a new one.")

    if row.attempts >= settings.otp_max_attempts:
        await db.delete(row)
        await db.flush()
        raise OtpError("Too many incorrect attempts. Please request a new code.")

    if not hmac.compare_digest(row.code_hash, _hash_code(phone, code.strip())):
        row.attempts += 1
        remaining = settings.otp_max_attempts - row.attempts
        await db.flush()
        if remaining <= 0:
            raise OtpError("Too many incorrect attempts. Please request a new code.")
        raise OtpError(
            f"That code isn't right. {remaining} attempt{'s' if remaining != 1 else ''} left."
        )

    await db.delete(row)
    await db.flush()


async def login_user(db: AsyncSession, phone: str, name: str) -> User:
    """Resolve (or create) the mobed's User row for an OTP-verified phone.

    First verified sign-in creates it; a later one refreshes the display
    name if the caller supplied a different one. Only ever called after
    verify_otp has passed - this function itself proves nothing.
    """
    result = await db.execute(select(User).where(User.phone == phone))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(phone=phone, name=name)
        db.add(user)
        await db.flush()
        return user
    if name and user.name != name:
        user.name = name
        await db.flush()
    return user


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------
async def get_membership(db: AsyncSession, agyary_id: int, user_id: int) -> AgyaryUser | None:
    result = await db.execute(
        select(AgyaryUser).where(AgyaryUser.agyary_id == agyary_id, AgyaryUser.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def ensure_agyary_membership(
    db: AsyncSession, agyary_id: int, user: User
) -> AgyaryUser:
    """Join ``user`` to an agyari as a plain 'mobed'.

    Self-service join stays open (doc 05: "OTP only, nothing more, for v1")
    and always lands on DEFAULT_ROLE. Nothing in this app raises that -
    see the module docstring.

    An existing membership keeps whatever role it already has: this
    reactivates, but never silently demotes someone already established.
    Seed data and the WhatsApp flows are the only things that set a
    privileged role, and a plain re-join must not undo them.
    """
    membership = await get_membership(db, agyary_id, user.id)

    if membership is None:
        membership = AgyaryUser(agyary_id=agyary_id, user_id=user.id, role=DEFAULT_ROLE)
        db.add(membership)
    elif not membership.is_active:
        membership.is_active = True

    await db.flush()
    return membership


def issue_access_token(user_id: int) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "type": "access",
        "exp": datetime.now(UTC) + timedelta(minutes=settings.jwt_access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM)


def issue_refresh_token(user_id: int) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_days),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: str) -> int:
    """Returns the user id encoded in the token, or raises TokenError."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired token") from exc
    if payload.get("type") != expected_type:
        raise TokenError("Wrong token type")
    return int(payload["sub"])
