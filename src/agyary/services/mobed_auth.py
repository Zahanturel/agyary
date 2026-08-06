"""Mobed PWA authentication: name + phone -> JWT session.

Mobed-only v0 deliberately drops phone-OTP verification (that whole path,
and the AuthOtp usage behind it, is removed). We don't need proven phone
ownership yet; we need agyari/mobed data isolation. A mobed enters name +
phone once - the phone is the natural unique key for the User row (and the
key WhatsApp will reuse later, so it isn't throwaway). No verification step.

Accepted, stated risk: someone who knows another mobed's phone number could
enter it and see that mobed's calendar. Acceptable at current scale (every
mobed is personally onboarded); revisit when onboarding becomes self-serve.

JWT pattern is unchanged (short-lived access token + longer-lived refresh
token in an httpOnly cookie), per 02-backend-api.md's auth section.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import get_settings
from agyary.models import AgyaryUser, User

JWT_ALGORITHM = "HS256"


class TokenError(Exception):
    """Invalid, expired, or wrong-type JWT - message is safe to show the caller."""


async def login_user(db: AsyncSession, phone: str, name: str) -> User:
    """Resolve (or create) the mobed's User row by phone, the way the login
    screen does: first visit creates it; a returning visit that re-enters
    name + phone finds it and refreshes the display name if it changed. No
    verification - see the module docstring's accepted-risk note."""
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


async def get_membership(db: AsyncSession, agyary_id: int, user_id: int) -> AgyaryUser | None:
    result = await db.execute(
        select(AgyaryUser).where(AgyaryUser.agyary_id == agyary_id, AgyaryUser.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def ensure_agyary_membership(db: AsyncSession, agyary_id: int, user_id: int) -> AgyaryUser:
    """Self-service join: phone OTP is the only gate, no invite/approval
    (doc 05: "OTP only, nothing more, for v1. Revisit only if abuse
    actually shows up."). Callable both from onboarding (new user, first
    agyari) and from "join additional agyari" (existing user, standing
    action from their own menu, not onboarding-only)."""
    membership = await get_membership(db, agyary_id, user_id)
    if membership is None:
        membership = AgyaryUser(agyary_id=agyary_id, user_id=user_id, role="mobed")
        db.add(membership)
        await db.flush()
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
