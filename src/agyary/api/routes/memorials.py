"""Memorials: the observances a family keeps for a departed person.

Business logic is services/memorials.py and the date counting is
calendar/memorial.py; this is the HTTP layer. Everything is private to the
mobed who made it - the behdin routes already enforce that for the behdin,
and the memorial reads filter on the caller's id themselves.
"""

from __future__ import annotations

from datetime import date, time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api.routes.mobed import _require_behdin, _require_membership, get_current_user
from agyary.calendar.memorial import OPENING_ALL, OPENING_TENTH, PARAB_ALL, PARAB_FRAVARDIN_TIR
from agyary.core.database import get_db
from agyary.models import Memorial, User
from agyary.services import memorials

router = APIRouter(prefix="/api/mobed", tags=["memorials"])

MAX_FEED_RANGE_DAYS = 366


class SeriesIn(BaseModel):
    """A repeating series and how long it runs. ``count`` has no default on
    purpose: the mobed always chooses the length, so omitting it is an
    error rather than something quietly filled in."""

    count: int


class ParabsIn(BaseModel):
    which: Literal[PARAB_ALL, PARAB_FRAVARDIN_TIR]
    years: int


class MemorialIn(BaseModel):
    departed_name: str
    death_date: date
    opening: Literal[OPENING_ALL, OPENING_TENTH]
    day_counts: list[int] = []
    monthly: SeriesIn | None = None   # count = months
    yearly: SeriesIn | None = None    # count = years
    parabs: ParabsIn | None = None   # years = how many years they run


class CreateMemorialIn(MemorialIn):
    # The services every observance starts with; each can be changed later.
    service_ids: list[int]


def _choice(p: MemorialIn) -> memorials.Choice:
    return memorials.Choice(
        departed_name=p.departed_name,
        death_date=p.death_date,
        opening=p.opening,
        day_counts=tuple(p.day_counts),
        monthly_months=p.monthly.count if p.monthly else None,
        yearly_years=p.yearly.count if p.yearly else None,
        parabs=p.parabs.which if p.parabs else None,
        parab_years=p.parabs.years if p.parabs else None,
    )


def _bad_request(exc: memorials.MemorialError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _own_memorial(db: AsyncSession, agyary_id: int, memorial_id: int, user: User) -> Memorial:
    await _require_membership(db, agyary_id, user)
    memorial = await memorials.get_for_user(db, user.id, memorial_id)
    # 404 whether it is missing, someone else's, or at another temple: a
    # family's departed are not for a colleague to confirm the existence of.
    if memorial is None or memorial.agyary_id != agyary_id:
        raise HTTPException(status_code=404, detail="Unknown memorial")
    return memorial


@router.post("/agyaries/{agyary_id}/behdins/{customer_id}/memorials/preview")
async def preview_memorial(
    agyary_id: int,
    customer_id: int,
    payload: MemorialIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Every date this choice would produce, with nothing saved - the step
    where the mobed checks the schedule before confirming it."""
    await _require_behdin(db, agyary_id, customer_id, user)
    agyary = await _require_membership(db, agyary_id, user)
    try:
        schedule, (roj, mah, year) = memorials.plan(agyary, _choice(payload))
    except memorials.MemorialError as exc:
        raise _bad_request(exc) from exc
    return {
        "death": {"roj": roj, "mah": mah, "year": year},
        "count": len(schedule),
        "observances": [
            {
                "code": o.code, "label": o.label, "day_number": o.day_number,
                "date": o.gregorian_date.isoformat(),
                "roj": o.roj, "mah": o.mah, "year": o.year, "gatha_index": o.gatha_index,
            }
            for o in schedule
        ],
    }


@router.post("/agyaries/{agyary_id}/behdins/{customer_id}/memorials")
async def create_memorial(
    agyary_id: int,
    customer_id: int,
    payload: CreateMemorialIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    customer = await _require_behdin(db, agyary_id, customer_id, user)
    agyary = await _require_membership(db, agyary_id, user)
    try:
        memorial = await memorials.create_memorial(
            db, agyary, user.id, customer, _choice(payload), payload.service_ids
        )
    except memorials.MemorialError as exc:
        raise _bad_request(exc) from exc
    await db.commit()
    # Re-read so the response is exactly what a later GET would return.
    fresh = await memorials.get_for_user(db, user.id, memorial.id)
    return (await memorials.summaries(db, agyary_id, [fresh], detailed=True))[0]


@router.get("/agyaries/{agyary_id}/behdins/{customer_id}/memorials")
async def list_memorials(
    agyary_id: int,
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """This behdin's memorials: where each has got to, and what is next."""
    await _require_behdin(db, agyary_id, customer_id, user)
    found = await memorials.list_for_behdin(db, user.id, agyary_id, customer_id)
    return await memorials.summaries(db, agyary_id, found, detailed=False)


@router.get("/agyaries/{agyary_id}/memorials/{memorial_id}")
async def get_memorial(
    agyary_id: int,
    memorial_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    memorial = await _own_memorial(db, agyary_id, memorial_id, user)
    return (await memorials.summaries(db, agyary_id, [memorial], detailed=True))[0]


class UpdateObservanceIn(BaseModel):
    """Change one observance. Left out means unchanged; ``time`` and
    ``notes`` as an empty string mean clear it."""

    service_ids: list[int] | None = None
    time: str | None = None
    notes: str | None = None


def _parse_time(value: str) -> time:
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Time must look like 09:30.") from exc


@router.patch("/agyaries/{agyary_id}/memorials/{memorial_id}/observances/{observance_id}")
async def update_observance(
    agyary_id: int,
    memorial_id: int,
    observance_id: int,
    payload: UpdateObservanceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    memorial = await _own_memorial(db, agyary_id, memorial_id, user)
    observance = next((o for o in memorial.observances if o.id == observance_id), None)
    if observance is None:
        raise HTTPException(status_code=404, detail="Unknown observance")
    try:
        await memorials.update_observance(
            db, memorial, observance,
            service_ids=payload.service_ids,
            time_of_day=_parse_time(payload.time) if payload.time else None,
            clear_time=payload.time == "",
            notes=payload.notes,
            clear_notes=payload.notes == "",
        )
    except memorials.MemorialError as exc:
        raise _bad_request(exc) from exc
    await db.commit()
    names = await memorials._service_names(db, agyary_id)
    fresh = await memorials.get_for_user(db, user.id, memorial_id)
    done = next(o for o in fresh.observances if o.id == observance_id)
    return memorials.serialize_observance(done, names)


@router.delete("/agyaries/{agyary_id}/memorials/{memorial_id}")
async def delete_memorial(
    agyary_id: int,
    memorial_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    memorial = await _own_memorial(db, agyary_id, memorial_id, user)
    await memorials.delete_memorial(db, memorial)
    await db.commit()
    return {"deleted": True}


@router.get("/agyaries/{agyary_id}/memorial-feed")
async def memorial_feed(
    agyary_id: int,
    from_: date = Query(alias="from"),
    to: date = Query(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """This mobed's memorial observances (and closing notices) between two
    dates, inclusive - what the calendar overlays on its days."""
    await _require_membership(db, agyary_id, user)
    if to < from_:
        raise HTTPException(status_code=400, detail="`to` is before `from`")
    if (to - from_).days + 1 > MAX_FEED_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"Range too wide (max {MAX_FEED_RANGE_DAYS} days)")
    return await memorials.calendar_feed(db, user.id, agyary_id, from_, to)
