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

Roles: self-serve login can only ever produce a plain 'mobed' membership.
Panthaky/caretaker come from an invite issued by someone who already holds
one, redeemed by the OTP login that proves the invited phone (see
models/invite.py).

JWT pattern is unchanged (short-lived access token + longer-lived refresh
token in an httpOnly cookie), per 02-backend-api.md's auth section.
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
from agyary.models import AgyaryInvite, AgyaryUser, AuthOtp, User

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
# Membership / invites
# ---------------------------------------------------------------------------
async def get_membership(db: AsyncSession, agyary_id: int, user_id: int) -> AgyaryUser | None:
    result = await db.execute(
        select(AgyaryUser).where(AgyaryUser.agyary_id == agyary_id, AgyaryUser.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def pending_invites(
    db: AsyncSession, phone: str, agyary_id: int | None = None
) -> list[AgyaryInvite]:
    """Live invites addressed to ``phone`` - neither redeemed, revoked, nor
    expired. Optionally narrowed to one agyari."""
    stmt = select(AgyaryInvite).where(
        AgyaryInvite.phone == phone,
        AgyaryInvite.redeemed_at.is_(None),
        AgyaryInvite.revoked_at.is_(None),
        AgyaryInvite.expires_at > datetime.now(UTC),
    )
    if agyary_id is not None:
        stmt = stmt.where(AgyaryInvite.agyary_id == agyary_id)
    return list((await db.execute(stmt)).scalars())


async def ensure_agyary_membership(
    db: AsyncSession, agyary_id: int, user: User
) -> AgyaryUser:
    """Join ``user`` to an agyari, at their invited role if one is waiting.

    Self-service join stays open (doc 05: "OTP only, nothing more, for v1")
    and still lands on plain 'mobed'. The one thing that can raise that is a
    live invite addressed to this user's OTP-verified phone at this agyari -
    joining is then also the redemption, so an invitee who navigates to the
    temple themselves ends up in the same place as one who was carried there
    by the login flow.

    An existing membership keeps its role: this reactivates and promotes,
    but never silently demotes someone who is already established.
    """
    membership = await get_membership(db, agyary_id, user.id)
    invites = await pending_invites(db, user.phone, agyary_id)

    if membership is None:
        role = invites[0].role if invites else DEFAULT_ROLE
        membership = AgyaryUser(agyary_id=agyary_id, user_id=user.id, role=role)
        db.add(membership)
    else:
        if not membership.is_active:
            membership.is_active = True
        if invites and membership.role == DEFAULT_ROLE and invites[0].role != DEFAULT_ROLE:
            membership.role = invites[0].role

    for invite in invites:
        invite.redeemed_at = datetime.now(UTC)
        invite.redeemed_by_user_id = user.id
    await db.flush()
    return membership


async def redeem_all_invites(db: AsyncSession, user: User) -> list[AgyaryUser]:
    """Redeem every live invite for this user's phone, across agyaries.

    Called once per verified sign-in. This is what makes an invite a
    complete onboarding path rather than half of one: the invitee logs in
    and is already a member at the right role, with no "now go find the
    fire temple you were just invited to" step in between.
    """
    memberships = []
    for invite in await pending_invites(db, user.phone):
        memberships.append(await ensure_agyary_membership(db, invite.agyary_id, user))
    return memberships


async def is_admin_member(db: AsyncSession, agyary_id: int, user_id: int) -> bool:
    from agyary.models.enums import ADMIN_ROLES

    membership = await get_membership(db, agyary_id, user_id)
    return membership is not None and membership.is_active and membership.role in ADMIN_ROLES


async def agyary_has_admin(db: AsyncSession, agyary_id: int) -> bool:
    """Whether anyone at this agyari currently holds a privileged role.

    Every membership created before invites existed is a plain 'mobed', so
    a freshly migrated agyari has nobody who can issue the first invite.
    Rather than promoting someone by fiat in a migration - picking a
    panthaky out of a list of phone numbers is not a decision a data
    migration should be making - the invite endpoint treats "no admin
    exists here yet" as a bootstrap case (see routes/mobed.py).
    """
    from agyary.models.enums import ADMIN_ROLES

    result = await db.execute(
        select(AgyaryUser.user_id).where(
            AgyaryUser.agyary_id == agyary_id,
            AgyaryUser.is_active.is_(True),
            AgyaryUser.role.in_(ADMIN_ROLES),
        )
    )
    return result.first() is not None


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
