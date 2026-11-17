"""A mobed's access to the app: the owner's one switch per account (DECISIONS D9).

A new sign-up is "pending": it can choose its fire temple and nothing else,
and every admin is told in the app. An admin approves it ("on") or turns it
"off", and can turn any mobed off and on again from the admin screen. A mobed
who is not "on" sees one screen saying so; nothing is deleted, and nothing is
sent under their account (no automatic reminders, no daily report, no schedule
from our number) until they are on again. An admin is always on.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import Agyary, AgyaryUser, User
from agyary.models.enums import ACCESS_OFF, ACCESS_ON, ACCESS_PENDING
from agyary.services import guardrails, reminders, web_push

logger = logging.getLogger(__name__)

KIND_REQUEST = "mobed_request"
KIND_APPROVED = "access_on"
# A request must still be in front of the admin if they do not open the app for
# a few days; the Mobeds screen keeps it after that in any case.
REQUEST_TTL = timedelta(days=7)
# The mobed's "you're in" is shown when they next open the app, however long that is.
APPROVED_TTL = timedelta(days=7)

MOBEDS_LINK = "#/admin/mobeds"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def effective(settings: Settings, user: User) -> str:
    """The access this account has now: an admin is always on, whatever is stored."""
    if guardrails.is_admin(settings, user.phone):
        return ACCESS_ON
    return user.access or ACCESS_ON


def has_access(settings: Settings, user: User) -> bool:
    return effective(settings, user) == ACCESS_ON


async def tell_admins_of_request(
    db: AsyncSession, settings: Settings, user: User, agyary: Agyary, *, now: datetime | None = None
) -> int:
    """Tell every admin, in the app, that this mobed has chosen a fire temple
    and is waiting. Only for a pending account. Returns how many were told."""
    if user.access != ACCESS_PENDING:
        return 0
    now = now or _now()
    phones = guardrails.admin_phones(settings)
    if not phones:
        logger.error("Mobed %s is waiting for approval, but no ADMIN_PHONES is set, so nobody was told", user.id)
        return 0
    admins = (await db.execute(select(User.id).where(User.phone.in_(phones)))).scalars().all()
    for uid in admins:
        await reminders.notify(
            db, uid, KIND_REQUEST, "A new mobed is waiting",
            f"{user.name} ({user.phone}) from {agyary.name} wants to use Mobed Diary. "
            "Approve them on the Mobeds page.",
            link=MOBEDS_LINK, now=now, ttl=REQUEST_TTL,
        )
    # And on the admins' phones, if they turned that on. The number stays off
    # the lock screen; it is in the app.
    await web_push.send_to_users(
        db, settings, admins, title="A new mobed is waiting",
        body=f"{user.name} from {agyary.name} wants to use Mobed Diary. Tap to approve.",
        url="/mobed" + MOBEDS_LINK, tag="mobed-request",
    )
    return len(admins)


class AccessError(ValueError):
    """A change the admin may not make; the message is for them."""


async def set_access(
    db: AsyncSession, settings: Settings, user: User, access: str, *, now: datetime | None = None
) -> User:
    """Turn a mobed on or off. Turning one on tells them in the app."""
    if access not in (ACCESS_ON, ACCESS_OFF):
        raise AccessError("Access can only be turned on or off.")
    if access == ACCESS_OFF and guardrails.is_admin(settings, user.phone):
        raise AccessError("An admin cannot be turned off.")
    if user.access == access:
        return user
    now = now or _now()
    before = user.access
    user.access = access
    user.access_changed_at = now
    if access == ACCESS_ON:
        await reminders.notify(
            db, user.id, KIND_APPROVED,
            "You're in" if before == ACCESS_PENDING else "Your access is back on",
            "Your Mobed Diary account has been approved. Welcome!" if before == ACCESS_PENDING
            else "You can use Mobed Diary again. Everything you saved is as you left it.",
            link="#/calendar", now=now, ttl=APPROVED_TTL,
        )
    await db.flush()
    logger.warning("Mobed %s access %s -> %s", user.id, before, access)
    return user


async def list_mobeds(db: AsyncSession, settings: Settings) -> list[dict]:
    """Every account, waiting ones first and the newest of those at the top,
    then the rest by name."""
    users = (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
    temples: dict[int, list[str]] = {}
    for user_id, name in (
        await db.execute(
            select(AgyaryUser.user_id, Agyary.name)
            .join(Agyary, Agyary.id == AgyaryUser.agyary_id)
            .where(AgyaryUser.is_active.is_(True))
            .order_by(AgyaryUser.joined_at)
        )
    ).all():
        temples.setdefault(user_id, []).append(name)

    def row(u: User) -> dict:
        return {
            "id": u.id,
            "name": u.name,
            "phone": u.phone,
            "access": effective(settings, u),
            "is_admin": guardrails.is_admin(settings, u.phone),
            "agyaries": temples.get(u.id, []),
            "signed_up": u.created_at.isoformat() if u.created_at else None,
            "access_changed_at": u.access_changed_at.isoformat() if u.access_changed_at else None,
        }

    rows = [row(u) for u in users]
    waiting = sorted((r for r in rows if r["access"] == ACCESS_PENDING),
                     key=lambda r: r["signed_up"] or "", reverse=True)
    rest = sorted((r for r in rows if r["access"] != ACCESS_PENDING), key=lambda r: r["name"].lower())
    return waiting + rest
