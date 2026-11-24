"""A Doongerwadi manager asking to work at another place (owner, 24 Nov 2026).

The manager cannot change their place themselves: they ask, the admin
approves, and nothing changes until then, because a place's family records are
private to its managers (D2, D10). Approving moves the manager's link from the
old place to the new one in one transaction. The old place's records stay with
the old place and the manager no longer sees them; nothing is copied or deleted
(D8) - the old link is turned off, not removed. Asking follows the panthaky
claim's pattern (services/panthaky.py): the admins are told in the app and on
their phones, and the manager is told what was decided.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import FuneralPlace, FuneralPlaceManager, PlaceChangeRequest, User
from agyary.models.enums import (
    ACCOUNT_FUNERAL_MANAGER,
    CHANGE_APPROVED,
    CHANGE_CANCELLED,
    CHANGE_DECLINED,
    CHANGE_PENDING,
    FUNERAL_MANAGER,
)
from agyary.services import funeral_places, guardrails, reminders, web_push

logger = logging.getLogger(__name__)

KIND_REQUEST = "place_change_request"
KIND_DECISION = "place_change_decision"
TTL = timedelta(days=7)
ADMIN_LINK = "#/admin/funeral-places"


class ChangeError(ValueError):
    """A request or decision that cannot be made now; the message is for the person."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _where(place: FuneralPlace) -> str:
    return f"{place.name}, {place.city}" if place.city and place.city not in place.name else place.name


async def pending_of(db: AsyncSession, user_id: int) -> PlaceChangeRequest | None:
    return (await db.execute(
        select(PlaceChangeRequest).where(
            PlaceChangeRequest.user_id == user_id, PlaceChangeRequest.status == CHANGE_PENDING)
    )).scalar_one_or_none()


async def pending_summary(db: AsyncSession, user_id: int) -> dict | None:
    """The manager's own waiting request, for their screens, or None."""
    req = await pending_of(db, user_id)
    if req is None:
        return None
    to_place = await db.get(FuneralPlace, req.to_place_id)
    return {"id": req.id, "to_place": funeral_places.summary(to_place), "created_at": req.created_at.isoformat()}


async def choices(db: AsyncSession, user: User, q: str = "") -> list[FuneralPlace]:
    """The places a manager may ask for: those in use except their own."""
    mine = {p.id for p in await funeral_places.places_of(db, user.id)}
    return [p for p in await funeral_places.search_active(db, q) if p.id not in mine]


async def ask(
    db: AsyncSession, settings: Settings, user: User, to_place: FuneralPlace, *, now: datetime | None = None
) -> PlaceChangeRequest:
    """Record the manager's request and tell every admin. ChangeError if it cannot be made."""
    # Locked, so two taps cannot both pass the check below (the unique index is the backstop).
    await db.refresh(user, with_for_update=True)
    if user.account_kind != ACCOUNT_FUNERAL_MANAGER:
        raise ChangeError("Only a Doongerwadi or prayer hall manager can ask to change their place.")
    existing = await pending_of(db, user.id)
    if existing is not None:
        waiting_for = await db.get(FuneralPlace, existing.to_place_id)
        raise ChangeError(
            f"You have already asked to move to {waiting_for.name}. Please take that request back "
            "before you ask for another place."
        )
    if not to_place.is_active:
        raise ChangeError("That place is turned off in Mobed Diary at the moment. Please choose another.")
    mine = await funeral_places.places_of(db, user.id)
    if any(p.id == to_place.id for p in mine):
        raise ChangeError(f"You already work at {to_place.name}.")
    now = now or _now()
    req = PlaceChangeRequest(
        user_id=user.id, from_place_id=mine[0].id if mine else None, to_place_id=to_place.id,
        status=CHANGE_PENDING, created_at=now,
    )
    db.add(req)
    await db.flush()
    await tell_admins(db, settings, user, mine[0] if mine else None, to_place, now=now)
    logger.warning("Manager %s asked to move from place %s to place %s", user.id, req.from_place_id, to_place.id)
    return req


async def tell_admins(
    db: AsyncSession, settings: Settings, user: User, from_place: FuneralPlace | None, to_place: FuneralPlace,
    *, now: datetime | None = None,
) -> int:
    """Every admin is told in the app and on their phones, as a panthaky's claim tells them."""
    phones = guardrails.admin_phones(settings)
    if not phones:
        logger.error("Manager %s asked to change place, but no ADMIN_PHONES is set, so nobody was told", user.id)
        return 0
    admins = (await db.execute(select(User.id).where(User.phone.in_(phones)))).scalars().all()
    leaving = f"from {_where(from_place)} " if from_place else ""
    for uid in admins:
        await reminders.notify(
            db, uid, KIND_REQUEST, "A manager asks to change their place",
            f"{user.name} ({user.phone}) asks to move {leaving}to {_where(to_place)}. "
            "Approve or decline it on the Doongerwadis page.",
            link=ADMIN_LINK, now=now, ttl=TTL,
        )
    await web_push.send_to_users(
        db, settings, admins, title="A manager asks to change their place",
        body=f"{user.name} asks to move to {to_place.name}. Tap to decide.",
        url="/mobed" + ADMIN_LINK, tag="place-change-request",
    )
    return len(admins)


async def take_back(db: AsyncSession, user: User, *, now: datetime | None = None) -> PlaceChangeRequest:
    """The manager withdraws their waiting request."""
    await db.refresh(user, with_for_update=True)
    req = await pending_of(db, user.id)
    if req is None:
        raise ChangeError("You have no request waiting to take back.")
    req.status = CHANGE_CANCELLED
    req.decided_at = now or _now()
    await db.flush()
    logger.info("Manager %s took back their request to change place", user.id)
    return req


async def waiting_for_admin(db: AsyncSession) -> list[dict]:
    """Every waiting request, oldest first, for the admin's card."""
    rows = (await db.execute(
        select(PlaceChangeRequest, User).join(User, User.id == PlaceChangeRequest.user_id)
        .where(PlaceChangeRequest.status == CHANGE_PENDING)
        .order_by(PlaceChangeRequest.created_at, PlaceChangeRequest.id)
    )).all()
    out = []
    for req, user in rows:
        from_place = await db.get(FuneralPlace, req.from_place_id) if req.from_place_id else None
        to_place = await db.get(FuneralPlace, req.to_place_id)
        out.append({
            "id": req.id, "created_at": req.created_at.isoformat(),
            "manager": {"id": user.id, "name": user.name, "phone": user.phone, "is_active": user.is_active},
            "from_place": funeral_places.summary(from_place) if from_place else None,
            "to_place": funeral_places.summary(to_place),
        })
    return out


async def count_waiting(db: AsyncSession) -> int:
    return len((await db.execute(
        select(PlaceChangeRequest.id).where(PlaceChangeRequest.status == CHANGE_PENDING)
    )).scalars().all())


async def _lock_pending(db: AsyncSession, request_id: int) -> PlaceChangeRequest:
    req = await db.get(PlaceChangeRequest, request_id, with_for_update=True)
    if req is None:
        raise LookupError("That request could not be found.")
    if req.status != CHANGE_PENDING:
        raise ChangeError(
            "This request has already been approved." if req.status == CHANGE_APPROVED
            else "This request has already been decided or taken back."
        )
    return req


async def approve(
    db: AsyncSession, settings: Settings, request_id: int, admin: User, *, now: datetime | None = None
) -> PlaceChangeRequest:
    """Move the manager to the new place, in the caller's one transaction: the
    old link is turned off (its records stay with that place), the new one is
    made, the request is marked, and the manager is told."""
    req = await _lock_pending(db, request_id)
    manager = await db.get(User, req.user_id, with_for_update=True)
    to_place = await db.get(FuneralPlace, req.to_place_id, with_for_update=True)
    if manager is None or not manager.is_active or manager.account_kind != ACCOUNT_FUNERAL_MANAGER:
        raise ChangeError("This manager's account is no longer in use, so they cannot be moved.")
    if not to_place.is_active:
        raise ChangeError(f"{to_place.name} is turned off in Mobed Diary, so nobody can be moved there. "
                          "Turn it on first, or decline the request.")
    now = now or _now()
    links = (await db.execute(
        select(FuneralPlaceManager).where(FuneralPlaceManager.user_id == manager.id)
    )).scalars().all()
    if any(link.is_active and link.funeral_place_id == to_place.id for link in links):
        raise ChangeError(f"{manager.name} already works at {to_place.name}. Decline this request.")
    for link in links:
        # The place they asked to leave; any other place they somehow hold is left alone.
        if link.is_active and link.funeral_place_id == req.from_place_id:
            link.is_active = False
    existing = next((link for link in links if link.funeral_place_id == to_place.id), None)
    if existing is not None:
        existing.is_active, existing.joined_at = True, now     # moving back to a place they once had
    else:
        db.add(FuneralPlaceManager(
            funeral_place_id=to_place.id, user_id=manager.id, role=FUNERAL_MANAGER, joined_at=now))
    req.status, req.decided_by_user_id, req.decided_at = CHANGE_APPROVED, admin.id, now
    await db.flush()
    await reminders.notify(
        db, manager.id, KIND_DECISION, f"You now work at {to_place.name}",
        f"The admin has moved you to {_where(to_place)}. Mobed Diary now shows that place.",
        link="#/", now=now, ttl=TTL,
    )
    await web_push.send_to_users(
        db, settings, [manager.id], title=f"You now work at {to_place.name}",
        body="The admin has moved you to this place. Tap to open Mobed Diary.",
        url="/mobed#/", tag="place-change-decision",
    )
    logger.warning("Admin %s moved manager %s from place %s to place %s", admin.id, manager.id,
                   req.from_place_id, to_place.id)
    return req


async def decline(
    db: AsyncSession, settings: Settings, request_id: int, admin: User, *, now: datetime | None = None
) -> PlaceChangeRequest:
    req = await _lock_pending(db, request_id)
    to_place = await db.get(FuneralPlace, req.to_place_id)
    now = now or _now()
    req.status, req.decided_by_user_id, req.decided_at = CHANGE_DECLINED, admin.id, now
    await db.flush()
    title = f"The admin has not moved you to {to_place.name}"
    await reminders.notify(
        db, req.user_id, KIND_DECISION, title,
        "You stay where you are, and nothing else changes. If this is wrong, please get in touch.",
        link="#/", now=now, ttl=TTL,
    )
    await web_push.send_to_users(
        db, settings, [req.user_id], title=title, body="You stay where you are.",
        url="/mobed#/", tag="place-change-decision",
    )
    logger.warning("Admin %s declined manager %s's move to place %s", admin.id, req.user_id, to_place.id)
    return req
