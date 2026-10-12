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
in an httpOnly cookie, both naming a server-side session that can be ended (AU-2).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import get_settings
from agyary.models import AgyaryUser, User, UserSession

JWT_ALGORITHM = "HS256"

DEFAULT_ROLE = "mobed"


class TokenError(Exception):
    """Invalid, expired, or wrong-type JWT - message is safe to show the caller."""


class SignupRefused(Exception):
    """A proven number that may not create an account. Safe to show."""


NOT_INVITED = (
    "This number is not set up for Mobed Diary yet. Ask the person who runs it "
    "to invite you, then sign in again."
)


def _listed(raw: str, phone: str) -> bool:
    return phone in {p.strip() for p in raw.split(",") if p.strip()}


def may_sign_up(phone: str) -> bool:
    """Whether a number with no account may create one under SIGNUP_MODE:
    anyone when it is "open"; when it is "invite" (the default), only a number
    in SIGNUP_ALLOWLIST or an admin, so the owner can never lock themselves out."""
    settings = get_settings()
    if settings.signup_mode.strip().lower() == "open":
        return True
    return _listed(settings.signup_allowlist, phone) or _listed(settings.admin_phones, phone)


async def may_sign_in(db: AsyncSession, phone: str) -> bool:
    """Whether ``phone`` would be let in: it has an account, or may sign up."""
    if may_sign_up(phone):
        return True
    return (await db.execute(select(User.id).where(User.phone == phone))).first() is not None


async def login_user(db: AsyncSession, phone: str, name: str) -> User:
    """Resolve (or create) the mobed's User row for a proven phone.

    First sign-in creates it - if SIGNUP_MODE lets this number sign up
    (``may_sign_up``), else SignupRefused. A later one refreshes the display
    name if the caller supplied a different one. Only ever called once wa_login
    has bound the number to a claimed attempt - this function itself
    proves nothing, so calling it with an unproven number would hand out
    a session for it.
    """
    result = await db.execute(select(User).where(User.phone == phone))
    user = result.scalar_one_or_none()
    if user is None:
        if not may_sign_up(phone):
            raise SignupRefused(NOT_INVITED)
        user = User(phone=phone, name=name, automatic_reminders=get_settings().reminders_automatic_default)
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


# ---------------------------------------------------------------------------
# Sessions and tokens (AU-2)
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(UTC)


async def start_session(db: AsyncSession, user: User) -> UserSession:
    """A new signed-in device for ``user``."""
    now = _now()
    session = UserSession(user_id=user.id, generation=0, created_at=now, last_used_at=now)
    db.add(session)
    await db.flush()
    return session


def issue_access_token(user_id: int, session_id: int) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "type": "access",
        "sid": session_id,
        "exp": datetime.now(UTC) + timedelta(minutes=settings.jwt_access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM)


def _session_ends(session: UserSession) -> datetime:
    created = session.created_at if session.created_at.tzinfo else session.created_at.replace(tzinfo=UTC)
    return created + timedelta(days=get_settings().jwt_session_max_days)


def issue_refresh_token(user_id: int, session: UserSession) -> str:
    """The cookie that keeps a device signed in: it names the session and its
    current generation, and lasts the sliding window but never past the
    session's own end."""
    settings = get_settings()
    exp = min(datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_days), _session_ends(session))
    payload = {"sub": str(user_id), "type": "refresh", "sid": session.id, "gen": session.generation, "exp": exp}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict:
    """The token's claims, or TokenError. ``sub`` is the user id."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired token") from exc
    if payload.get("type") != expected_type:
        raise TokenError("Wrong token type")
    try:
        payload["sub"] = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("Invalid token") from exc
    return payload


async def live_session(db: AsyncSession, claims: dict) -> UserSession | None:
    """The session a token names, if it still stands: not revoked, not past its
    absolute end, and the token's own user's."""
    sid = claims.get("sid")
    if not isinstance(sid, int):
        return None
    session = await db.get(UserSession, sid)
    if session is None or session.revoked_at is not None or session.user_id != claims["sub"]:
        return None
    if _now() >= _session_ends(session):
        return None
    return session


async def rotate(db: AsyncSession, claims: dict) -> UserSession:
    """Spend a refresh token: the session moves on a generation, or - if this
    token is an older generation, so somebody kept a copy - the session ends.
    A token from before sessions existed is moved into a new session, once,
    until jwt_legacy_tokens_until; "sign out everywhere" refuses those too."""
    if claims.get("sid") is None:
        return await _adopt_legacy(db, claims)
    session = await live_session(db, claims)
    if session is None:
        raise TokenError("This sign-in has ended. Please sign in again.")
    if claims.get("gen") != session.generation:
        session.revoked_at = _now()
        await db.flush()
        raise TokenError("This sign-in was used on another device, so it has been ended. Please sign in again.")
    session.generation += 1
    session.last_used_at = _now()
    await db.flush()
    return session


async def _adopt_legacy(db: AsyncSession, claims: dict) -> UserSession:
    settings = get_settings()
    until = date.fromisoformat(settings.jwt_legacy_tokens_until)
    if _now().date() > until:
        raise TokenError("This sign-in has ended. Please sign in again.")
    user = await db.get(User, claims["sub"])
    if user is None:
        raise TokenError("User not found")
    # A legacy token carries no issue time; it was minted for exactly the refresh
    # window, so its expiry says when.
    issued = datetime.fromtimestamp(claims["exp"], UTC) - timedelta(days=settings.jwt_refresh_token_days)
    after = user.tokens_valid_after
    if after is not None and issued < (after if after.tzinfo else after.replace(tzinfo=UTC)):
        raise TokenError("This sign-in has ended. Please sign in again.")
    return await start_session(db, user)


async def end_session(db: AsyncSession, session_id: int | None) -> None:
    if session_id is None:
        return
    session = await db.get(UserSession, session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = _now()
        await db.flush()


async def end_all_sessions(db: AsyncSession, user: User, *, keep: int | None = None) -> int:
    """End every session of ``user`` but ``keep``, and refuse every token from
    before sessions existed. Returns how many sessions were ended."""
    now = _now()
    rows = (
        await db.execute(
            select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        )
    ).scalars().all()
    ended = 0
    for session in rows:
        if session.id != keep:
            session.revoked_at = now
            ended += 1
    user.tokens_valid_after = now
    await db.flush()
    return ended
