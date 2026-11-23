"""A funeral place's own book of behdins: the families it deals with (DECISIONS
D10, changed 19 Nov 2026).

Each family is a name, a number (cleaned to E.164 by services/phone.py, typed
or read from the phone's contacts inside the name-and-number form) and, if the
manager knows it, the fire temple they usually go to. Recording a death picks
the family from here: their name and number fill the family contact, and their
usual agyari is suggested first when the request goes out.

The book belongs to its place, like the place's records (services/
funeral_records.py): any manager of that place, and the admin acting for that
one place, see and change it; nobody else, however an id is guessed (404).
Removing a family turns it off and keeps it (D8); adding the same number again
brings it back. Only a family's own request to be erased takes it away
(services/erasure.py). The name is checked like any text others will read
(services/template_text.py), as the family contact on a record is.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.models import Agyary, FuneralBehdin, FuneralPlace, User
from agyary.services import template_text

logger = logging.getLogger(__name__)

NAME_MAX = 100          # as the family contact's name on a record
MAX_PER_PLACE = 5000
PAGE = 50


class BookError(ValueError):
    """What is wrong; ``field`` names the form's field, ``status`` the HTTP answer."""

    def __init__(self, message: str, *, field: str | None = None, status: int = 400):
        super().__init__(message)
        self.field = field
        self.status = status


def _name(value: str | None) -> str:
    value = " ".join(str(value or "").split())
    if not value:
        raise BookError("Please enter the behdin's name.", field="name")
    try:
        return template_text.check(value, "name", max_len=NAME_MAX)
    except ValueError as exc:
        raise BookError(str(exc), field="name") from exc


async def _agyari(db: AsyncSession, agyary_id: int | None) -> int | None:
    if agyary_id is None:
        return None
    agyary = await db.get(Agyary, agyary_id)
    if agyary is None or not agyary.is_active:
        raise BookError("That fire temple could not be found. Please choose it again.", field="usual_agyary_id")
    return agyary.id


async def listed(db: AsyncSession, place_ids: list[int], q: str = "", *,
                 limit: int = MAX_PER_PLACE) -> list[FuneralBehdin]:
    """The families in these places' books, by name; those whose name has
    every word of ``q`` in it, or whose number has its digits (three or more).
    All of them (22 Nov 2026: the list stopped at PAGE with no word of it, and
    the screen never asked for more): a book holds at most MAX_PER_PLACE."""
    if not place_ids:
        return []
    stmt = select(FuneralBehdin).where(FuneralBehdin.funeral_place_id.in_(place_ids), FuneralBehdin.is_active.is_(True))
    q = " ".join(q.split())[:100]
    digits = "".join(c for c in q if c.isdigit())
    if len(digits) >= 3:
        stmt = stmt.where(or_(FuneralBehdin.phone.contains(digits), *[
            FuneralBehdin.name.ilike(f"%{w}%") for w in q.split() if not w.isdigit()]))
    elif q:
        stmt = stmt.where(*[FuneralBehdin.name.ilike(f"%{w}%") for w in q.split()])
    stmt = stmt.order_by(func.lower(FuneralBehdin.name), FuneralBehdin.id).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def get(db: AsyncSession, place_ids: list[int], behdin_id: int) -> FuneralBehdin | None:
    """One family still in the book of one of these places; else None."""
    if not place_ids:
        return None
    return (await db.execute(select(FuneralBehdin).where(
        FuneralBehdin.id == behdin_id, FuneralBehdin.funeral_place_id.in_(place_ids),
        FuneralBehdin.is_active.is_(True)))).scalar_one_or_none()


async def _same_number(db: AsyncSession, place_id: int, phone: str) -> FuneralBehdin | None:
    return (await db.execute(select(FuneralBehdin).where(
        FuneralBehdin.funeral_place_id == place_id, FuneralBehdin.phone == phone))).scalar_one_or_none()


async def add(
    db: AsyncSession, user: User, place: FuneralPlace, *, name: str, phone: str, usual_agyary_id: int | None,
) -> FuneralBehdin:
    """Add a family; ``phone`` is already cleaned and checked. A number the
    book had before and was removed comes back, with these details."""
    name = _name(name)
    usual = await _agyari(db, usual_agyary_id)
    row = await _same_number(db, place.id, phone)
    if row is not None and row.is_active:
        raise BookError(f"That number is in the book already, as {row.name}.", field="phone", status=409)
    count = (await db.execute(select(func.count()).select_from(FuneralBehdin).where(
        FuneralBehdin.funeral_place_id == place.id, FuneralBehdin.is_active.is_(True)))).scalar_one()
    if count >= MAX_PER_PLACE:
        raise BookError(f"The book has {MAX_PER_PLACE} behdins, which is as many as it can hold.", status=409)
    if row is None:
        row = FuneralBehdin(funeral_place_id=place.id, phone=phone, created_by_user_id=user.id)
        db.add(row)
    row.name, row.usual_agyary_id, row.is_active = name, usual, True
    await db.flush()
    logger.info("Family %s added to funeral place %s's book by user %s", row.id, place.id, user.id)
    return row


async def update(
    db: AsyncSession, user: User, row: FuneralBehdin, *, name: str, phone: str, usual_agyary_id: int | None,
) -> FuneralBehdin:
    name = _name(name)
    usual = await _agyari(db, usual_agyary_id)
    if phone != row.phone:
        other = await _same_number(db, row.funeral_place_id, phone)
        if other is not None:
            raise BookError(f"That number is in the book already, as {other.name}." if other.is_active
                            else "That number was taken out of the book earlier. Add it as a new behdin to bring "
                                 "it back.", field="phone", status=409)
        row.phone = phone
    row.name, row.usual_agyary_id = name, usual
    await db.flush()
    logger.info("Family %s in funeral place %s's book changed by user %s", row.id, row.funeral_place_id, user.id)
    return row


async def remove(db: AsyncSession, user: User, row: FuneralBehdin) -> None:
    """Out of the book: turned off and kept (D8)."""
    row.is_active = False
    await db.flush()
    logger.info("Family %s taken out of funeral place %s's book by user %s", row.id, row.funeral_place_id, user.id)


async def usual_agyari_of(db: AsyncSession, place_id: int, phone: str) -> int | None:
    """The usual fire temple of the family with this number in the place's book."""
    return (await db.execute(select(FuneralBehdin.usual_agyary_id).where(
        FuneralBehdin.funeral_place_id == place_id, FuneralBehdin.phone == phone,
        FuneralBehdin.is_active.is_(True)))).scalar_one_or_none()


async def serialize(db: AsyncSession, rows: list[FuneralBehdin]) -> list[dict]:
    ids = {r.usual_agyary_id for r in rows if r.usual_agyary_id}
    agyaries = {a.id: a for a in (await db.execute(select(Agyary).where(Agyary.id.in_(ids)))).scalars()} if ids else {}
    out = []
    for r in rows:
        a = agyaries.get(r.usual_agyary_id)
        out.append({
            "id": r.id, "name": r.name, "phone": r.phone, "funeral_place_id": r.funeral_place_id,
            "usual_agyari": {"id": a.id, "name": a.name, "city": a.city} if a and a.is_active else None,
        })
    return out
