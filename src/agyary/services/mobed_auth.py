"""Mobed PWA authentication: a proven WhatsApp number -> JWT session.

There is one way in. The mobed opens the app, gets a one-time code, and
sends it to us from their own WhatsApp; the webhook hands us the number
off a payload Meta signed (see services/wa_login.py). This module turns
that proven number into a User row and a pair of JWTs.

The number is never typed by the caller, which is the point. An earlier
design had the caller claim a number and us text a code to it, and that
shape has to work hard to avoid confirming whether a given number belongs
to anyone here. Learning the number from Meta instead removes the claim,
and with it the enumeration surface, the approved Authentication
template, and the per-conversation cost.

Roles: every membership this app creates is a plain 'mobed'. The
panthaky/caretaker roles still exist in the schema, but nothing in this
app can grant them - the invite mechanism that used to do so was removed,
since an unreachable endpoint that hands out privilege is worse than no
endpoint at all.

JWT pattern: a short-lived access token plus a longer-lived refresh token
in an httpOnly cookie.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import get_settings
from agyary.models import AgyaryUser, User

JWT_ALGORITHM = "HS256"

DEFAULT_ROLE = "mobed"


class TokenError(Exception):
    """Invalid, expired, or wrong-type JWT - message is safe to show the caller."""


async def login_user(db: AsyncSession, phone: str, name: str) -> User:
    """Resolve (or create) the mobed's User row for a proven phone.

    First sign-in creates it; a later one refreshes the display name if
    the caller supplied a different one. Only ever called once wa_login
    has bound the number to a claimed attempt - this function itself
    proves nothing, so calling it with an unproven number would hand out
    a session for it.
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

    Self-service join stays open and always lands on DEFAULT_ROLE. Nothing in this app raises that -
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
