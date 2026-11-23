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

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import Agyary, AgyaryUser, FuneralPlace, FuneralPlaceManager, User
from agyary.models.enums import ACCESS_OFF, ACCESS_ON, ACCESS_PENDING, ACCOUNT_FUNERAL_MANAGER, ROLE_PANTHAKY
from agyary.services import guardrails, panthaky, reminders, web_push

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
    db: AsyncSession, settings: Settings, user: User, agyary: Agyary, *,
    says_panthaky: bool = False, now: datetime | None = None,
) -> int:
    """Tell every admin, in the app, that this mobed has chosen a fire temple
    and is waiting - and whether they say they are its panthaky, which the
    admin confirms or not on the same page (D10). Only for a pending account.
    Returns how many were told."""
    if user.access != ACCESS_PENDING:
        return 0
    now = now or _now()
    phones = guardrails.admin_phones(settings)
    if not phones:
        logger.error("Mobed %s is waiting for approval, but no ADMIN_PHONES is set, so nobody was told", user.id)
        return 0
    admins = (await db.execute(select(User.id).where(User.phone.in_(phones)))).scalars().all()
    body = (
        f"{user.name} ({user.phone}) from {agyary.name} wants to use Mobed Diary, and says they are "
        "the panthaky there. Approve them, and confirm whether they are the panthaky, on the Mobeds page."
        if says_panthaky else
        f"{user.name} ({user.phone}) from {agyary.name} wants to use Mobed Diary. "
        "Approve them on the Mobeds page."
    )
    for uid in admins:
        await reminders.notify(
            db, uid, KIND_REQUEST, "A new mobed is waiting", body,
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


async def _confirm_sign_up(db: AsyncSession, user: User, by: User | None, now: datetime) -> int:
    """The admin's approval of a new sign-up confirms them for the prayer
    requests of the fire temple(s) they chose while waiting - the one they
    signed up at - unless taken off its list meanwhile. A fire temple joined
    later, from Settings, waits for its panthaky (services/join_confirmation.py).
    Returns how many memberships it confirmed."""
    done = (await db.execute(
        update(AgyaryUser)
        .where(AgyaryUser.user_id == user.id, AgyaryUser.is_active.is_(True),
               AgyaryUser.requests_confirmed_at.is_(None), AgyaryUser.requests_off_at.is_(None))
        .values(requests_confirmed_at=now, requests_confirmed_by_user_id=by.id if by is not None else None)
        .returning(AgyaryUser.agyary_id)
    )).scalars().all()
    if done:
        logger.info("Mobed %s approved: confirmed for the requests of fire temple(s) %s", user.id, sorted(done))
    return len(done)


async def set_access(
    db: AsyncSession, settings: Settings, user: User, access: str, *, now: datetime | None = None,
    by: User | None = None,
) -> User:
    """Turn a mobed or a Doongerwadi manager on or off (the same one switch,
    D9, D10). Turning one on tells them in the app. Approving a new sign-up
    (waiting -> on) also confirms them for the prayer requests of the fire
    temple they signed up at (D10, owner 22 Nov 2026), by admin ``by``."""
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
    if access == ACCESS_ON and before == ACCESS_PENDING:
        await _confirm_sign_up(db, user, by, now)
    if access == ACCESS_ON:
        await reminders.notify(
            db, user.id, KIND_APPROVED,
            "You can now use Mobed Diary" if before == ACCESS_PENDING else "Your access is back on",
            "Your Mobed Diary account has been approved. Welcome!" if before == ACCESS_PENDING
            else "You can use Mobed Diary again. Everything you saved is as you left it.",
            link="#/manager" if user.account_kind == ACCOUNT_FUNERAL_MANAGER else "#/calendar",
            now=now, ttl=APPROVED_TTL,
        )
    await db.flush()
    logger.warning("Mobed %s access %s -> %s", user.id, before, access)
    return user


async def list_mobeds(db: AsyncSession, settings: Settings) -> list[dict]:
    """Every account, waiting ones first and the newest of those at the top,
    then the rest by name. Each with what they are at each fire temple, or,
    for a Doongerwadi manager, which place they manage (D10)."""
    users = (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
    names = {u.id: u.name for u in users}
    by_id = {u.id: u for u in users}
    rows_by_user: dict[int, list[tuple[AgyaryUser, Agyary]]] = {}
    panthakys: dict[int, list[int]] = {}
    # Fire temples with a confirmed panthaky whose access is on: they confirm who joins
    # there; at the others the admin does, here (D10, 22 Nov 2026).
    headed: set[int] = set()
    for m, a in (
        await db.execute(
            select(AgyaryUser, Agyary)
            .join(Agyary, Agyary.id == AgyaryUser.agyary_id)
            .where(AgyaryUser.is_active.is_(True))
            .order_by(AgyaryUser.joined_at)
        )
    ).all():
        rows_by_user.setdefault(m.user_id, []).append((m, a))
        if m.role == ROLE_PANTHAKY:
            panthakys.setdefault(a.id, []).append(m.user_id)
            if m.user_id in by_id and has_access(settings, by_id[m.user_id]):
                headed.add(a.id)
    places_by_user: dict[int, list[FuneralPlace]] = {}
    for link, place in (
        await db.execute(
            select(FuneralPlaceManager, FuneralPlace)
            .join(FuneralPlace, FuneralPlace.id == FuneralPlaceManager.funeral_place_id)
            .where(FuneralPlaceManager.is_active.is_(True))
            .order_by(FuneralPlaceManager.joined_at)
        )
    ).all():
        places_by_user.setdefault(link.user_id, []).append(place)

    def membership(m: AgyaryUser, a: Agyary, u: User) -> dict:
        # What they are at each fire temple, what they said, and the owner's
        # last decision on it (D10) - with the temple's other panthakys, so the
        # admin knows before confirming a second one.
        return {
            "agyary_id": a.id,
            "name": a.name,
            "role": m.role,
            "claimed_role": m.claimed_role,
            "panthaky_claim_waiting": panthaky.waiting(m),
            "claim_decision": m.claim_decision,
            "claim_decided_at": m.claim_decided_at.isoformat() if m.claim_decided_at else None,
            "other_panthakys": [names[uid] for uid in panthakys.get(a.id, []) if uid != m.user_id and uid in names],
            # For its prayer requests (D10, 22 Nov 2026): "confirmed", "waiting" or "off";
            # and whether a confirmed panthaky (access on) there decides that, not the admin.
            "requests": panthaky.request_state(settings, m, u),
            "has_panthaky": a.id in headed,
        }

    def row(u: User) -> dict:
        mine = rows_by_user.get(u.id, [])
        return {
            "id": u.id,
            "name": u.name,
            "phone": u.phone,
            "access": effective(settings, u),
            "is_admin": guardrails.is_admin(settings, u.phone),
            # "mobed" or "funeral_manager"; a manager has places, not fire temples.
            "account_kind": u.account_kind,
            "funeral_places": [
                {"id": p.id, "name": p.name, "city": p.city, "kind": p.kind, "is_active": p.is_active}
                for p in places_by_user.get(u.id, [])
            ],
            "agyaries": [a.name for _, a in mine],
            "memberships": [membership(m, a, u) for m, a in mine],
            "panthaky_claim_waiting": any(panthaky.waiting(m) for m, _ in mine),
            "signed_up": u.created_at.isoformat() if u.created_at else None,
            "access_changed_at": u.access_changed_at.isoformat() if u.access_changed_at else None,
        }

    rows = [row(u) for u in users]
    waiting = sorted((r for r in rows if r["access"] == ACCESS_PENDING),
                     key=lambda r: r["signed_up"] or "", reverse=True)
    rest = sorted((r for r in rows if r["access"] != ACCESS_PENDING), key=lambda r: r["name"].lower())
    return waiting + rest
