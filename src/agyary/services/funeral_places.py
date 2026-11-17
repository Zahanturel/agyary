"""Funeral places: Doongerwadis, prayer halls and aramgahs (DECISIONS D10).

Only an admin adds or changes one; nobody can add one themselves. A place is
never deleted (D8): an admin turns it off, and then it is no longer offered to
a manager signing up, but it stays for the record and for the managers already
there. Its managers are people whose account is a funeral manager's
(users.account_kind), linked to it in funeral_place_managers.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.models import FuneralPlace, FuneralPlaceManager, User
from agyary.models.enums import ACCESS_OFF, ACCESS_ON, ACCESS_PENDING, FUNERAL_PLACE_KINDS
from agyary.services import template_text

logger = logging.getLogger(__name__)

KIND_LABELS = {"doongerwadi": "Doongerwadi", "prayer_hall": "Prayer hall", "aramgah": "Aramgah"}
assert set(KIND_LABELS) == set(FUNERAL_PLACE_KINDS)

NAME_MAX = template_text.TEMPLE_MAX
CITY_MAX = 100
RUN_BY_MAX = 200
ADDRESS_MAX = 500


class PlaceError(ValueError):
    """Details an admin may not save; the message is for them."""


def summary(place: FuneralPlace) -> dict:
    return {
        "id": place.id,
        "name": place.name,
        "kind": place.kind,
        "kind_label": KIND_LABELS.get(place.kind, place.kind),
        "city": place.city,
        "address": place.address,
        "run_by": place.run_by,
        "location": (
            {"latitude": place.latitude, "longitude": place.longitude}
            if place.latitude is not None and place.longitude is not None else None
        ),
        "is_active": place.is_active,
    }


def _clean(text: str | None) -> str:
    return " ".join(str(text or "").split())


def checked_details(
    *, name: str, kind: str, city: str, address: str | None, run_by: str | None,
) -> dict:
    """The details tidied, or PlaceError saying what is wrong. The name is
    checked like a fire temple's (no link, handle or phone number): it will be
    read by mobeds in the requests a manager sends."""
    name, city = _clean(name), _clean(city)
    if not name or not city:
        raise PlaceError("Please enter the place's name and town.")
    if kind not in FUNERAL_PLACE_KINDS:
        raise PlaceError("Please choose what kind of place it is.")
    try:
        name = template_text.check(name, "place's name", max_len=NAME_MAX)
    except ValueError as exc:
        raise PlaceError(str(exc)) from exc
    if len(city) > CITY_MAX:
        raise PlaceError(f"The town is too long (at most {CITY_MAX} characters).")
    address = (address or "").strip() or None
    if address and len(address) > ADDRESS_MAX:
        raise PlaceError(f"The address is too long (at most {ADDRESS_MAX} characters).")
    run_by = _clean(run_by) or None
    if run_by and len(run_by) > RUN_BY_MAX:
        raise PlaceError(f"Who runs it is too long (at most {RUN_BY_MAX} characters).")
    return {"name": name, "kind": kind, "city": city, "address": address, "run_by": run_by}


async def create(
    db: AsyncSession, admin: User, details: dict, position: tuple[float, float] | None
) -> FuneralPlace:
    place = FuneralPlace(**details, created_by_user_id=admin.id)
    place.latitude, place.longitude = position if position else (None, None)
    db.add(place)
    await db.flush()
    logger.info("Funeral place %s added by admin %s", place.id, admin.id)
    return place


async def update(
    db: AsyncSession, place: FuneralPlace, admin: User, details: dict, position: tuple[float, float] | None
) -> FuneralPlace:
    for key, value in details.items():
        setattr(place, key, value)
    place.latitude, place.longitude = position if position else (None, None)
    await db.flush()
    logger.info("Funeral place %s changed by admin %s", place.id, admin.id)
    return place


async def set_active(db: AsyncSession, place: FuneralPlace, admin: User, active: bool) -> FuneralPlace:
    """Turn a place off (no longer offered at sign-up) or on again. Nothing is
    deleted, and its managers keep their accounts (their own switch is D9's)."""
    if place.is_active != active:
        place.is_active = active
        await db.flush()
        logger.warning("Funeral place %s turned %s by admin %s", place.id, "on" if active else "off", admin.id)
    return place


async def admin_list(db: AsyncSession) -> list[dict]:
    """Every place, those in use first, each by name, with how many managers it
    has whose access is on, waiting or off."""
    places = (await db.execute(select(FuneralPlace))).scalars().all()
    counts: dict[int, dict[str, int]] = {}
    for place_id, access, n in (
        await db.execute(
            select(FuneralPlaceManager.funeral_place_id, User.access, func.count())
            .join(User, User.id == FuneralPlaceManager.user_id)
            .where(FuneralPlaceManager.is_active.is_(True), User.is_active.is_(True))
            .group_by(FuneralPlaceManager.funeral_place_id, User.access)
        )
    ).all():
        counts.setdefault(place_id, {ACCESS_ON: 0, ACCESS_PENDING: 0, ACCESS_OFF: 0})[access] = n
    empty = {ACCESS_ON: 0, ACCESS_PENDING: 0, ACCESS_OFF: 0}
    rows = [summary(p) | {"managers": counts.get(p.id, empty)} for p in places]
    return sorted(rows, key=lambda r: (not r["is_active"], r["name"].lower()))


async def search_active(db: AsyncSession, q: str = "") -> list[FuneralPlace]:
    """The places a manager signing up may choose: those in use, by name, or
    those whose name or town has ``q`` in it."""
    stmt = select(FuneralPlace).where(FuneralPlace.is_active.is_(True))
    q = _clean(q)[:100]
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        stmt = stmt.where(or_(FuneralPlace.name.ilike(like, escape="\\"), FuneralPlace.city.ilike(like, escape="\\")))
    return list((await db.execute(stmt.order_by(FuneralPlace.name).limit(50))).scalars().all())


async def places_of(db: AsyncSession, user_id: int) -> list[FuneralPlace]:
    """The places this account manages, earliest first."""
    return list(
        (
            await db.execute(
                select(FuneralPlace)
                .join(FuneralPlaceManager, FuneralPlaceManager.funeral_place_id == FuneralPlace.id)
                .where(FuneralPlaceManager.user_id == user_id, FuneralPlaceManager.is_active.is_(True))
                .order_by(FuneralPlaceManager.joined_at)
            )
        ).scalars().all()
    )
