"""What a person keeps for themselves in the behdin app (R4.1, 25 Nov 2026).

Choosing "my agyari", the memorials of the person's own departed, their own
events, and the calendar that holds them. Every route is built on
``get_current_person`` and every row is scoped to that account: someone else's
id is a 404, like an id that does not exist. These dates are kept for the
person alone (DECISIONS D2, D6); no fire temple or admin screen reads them.

``POST /agyaries/nearby`` takes the person's position in a BODY on purpose: it
never goes in a URL, is used only to sort and measure, is never stored and is
never logged (nothing in this module logs a request body).
"""

from __future__ import annotations

import math
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.api.routes.memorials import MemorialIn, _choice
from agyary.api.routes.mobed import get_current_person
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import User
from agyary.services import behdin_me, mobed_dashboard, service_asks

router = APIRouter(prefix="/api/behdin", tags=["behdin"])

NOT_FOUND_MEMORIAL = "That memorial could not be found."
NOT_FOUND_EVENT = "That event could not be found."


def _limit(user: User, scope: str, *, per_minute: int) -> None:
    rate_limit.enforce_key(f"behdin_{scope}:{user.id}", max_requests=per_minute, window_seconds=60)


def _read(user: User) -> None:
    _limit(user, "read", per_minute=240)


def _write(user: User) -> None:
    _limit(user, "write", per_minute=90)


def _bad(exc: Exception) -> HTTPException:
    """A 400 in plain words. A rule written for the other side's screens never reaches
    a person here, so a message that names that side is replaced."""
    text = str(exc)
    if "mobed" in text.lower():
        text = "Please check what you entered and try again."
    return HTTPException(status_code=400, detail=text)


# ---------------------------------------------------------------------------
# Agyaries to choose from
# ---------------------------------------------------------------------------
class FindIn(BaseModel):
    town: str | None = None
    q: str | None = None
    lat: float | None = None
    lng: float | None = None


@router.post("/agyaries/find")
async def agyaries_find(
    payload: FindIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    """The fire temples that take requests, the person's town first. The position (optional) is in
    the BODY: used for this answer only to measure a distance to an exact pin, never stored or logged."""
    _limit(user, "nearby", per_minute=30)
    lat, lng = payload.lat, payload.lng
    if (lat is None) != (lng is None):
        raise HTTPException(status_code=400, detail="Please give both parts of the position, or neither.")
    if lat is not None and not (
        math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180
    ):
        raise HTTPException(status_code=400, detail="That position is not on the map.")
    found = await behdin_me.find(
        db, get_settings(), town=(payload.town or "").strip()[:100], q=(payload.q or "").strip()[:100], lat=lat, lng=lng)
    return {"agyaries": found}


@router.get("/agyaries/towns")
async def agyaries_towns(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    _read(user)
    return {"towns": await behdin_me.towns(db, get_settings())}


class MyAgyariIn(BaseModel):
    agyary_id: int


@router.get("/me/agyari")
async def get_my_agyari(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    _read(user)
    return {"agyari": await behdin_me.my_agyari(db, get_settings(), user.id)}


@router.put("/me/agyari")
async def put_my_agyari(
    payload: MyAgyariIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    """Choose (or change to) my agyari. Free to change at any time."""
    _write(user)
    try:
        await behdin_me.choose_agyari(db, user.id, payload.agyary_id)
    except behdin_me.PersonError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return {"agyari": await behdin_me.my_agyari(db, get_settings(), user.id)}


@router.delete("/me/agyari")
async def delete_my_agyari(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    _write(user)
    await behdin_me.forget_agyari(db, user.id)
    await db.commit()
    return {"agyari": None}


# ---------------------------------------------------------------------------
# The person's own memorials
# ---------------------------------------------------------------------------
class PersonMemorialIn(MemorialIn):
    # The name may be left out ("name not known"), as on the Doongerwadi side.
    departed_name: str = ""


async def _own_memorial(db: AsyncSession, user: User, memorial_id: int):
    row = await behdin_me.get_memorial(db, user.id, memorial_id)
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_MEMORIAL)
    return row


@router.post("/me/memorials")
async def create_memorial(
    payload: PersonMemorialIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    """Keep the observances for someone who has passed away: the dates come from the
    same Parsi calendar engine, and are kept for this person alone."""
    _write(user)
    try:
        row = await behdin_me.create_memorial(db, user.id, _choice(payload))
    except behdin_me.PersonError as exc:
        raise _bad(exc) from exc
    await db.commit()
    fresh = await behdin_me.get_memorial(db, user.id, row.id)
    return behdin_me.serialize_memorial(fresh, detailed=True)


@router.get("/me/memorials")
async def list_memorials(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    _read(user)
    today = behdin_me.today_ist()
    rows = [behdin_me.serialize_memorial(r, detailed=False, today=today) for r in await behdin_me.list_memorials(db, user.id)]
    # Those with a date still to come first, the soonest first; finished ones after.
    rows.sort(key=lambda m: (m["next"] is None, m["next"]["date"] if m["next"] else "", m["id"]))
    return {"memorials": rows}


@router.get("/me/memorials/{memorial_id}")
async def get_memorial(
    memorial_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    _read(user)
    return behdin_me.serialize_memorial(await _own_memorial(db, user, memorial_id), detailed=True)


@router.patch("/me/memorials/{memorial_id}")
async def rework_memorial(
    memorial_id: int, payload: PersonMemorialIn, db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_person),
) -> dict:
    """Change the choices: every date is counted again from the death."""
    _write(user)
    row = await _own_memorial(db, user, memorial_id)
    try:
        await behdin_me.rework_memorial(db, row, _choice(payload))
    except behdin_me.PersonError as exc:
        raise _bad(exc) from exc
    await db.commit()
    fresh = await behdin_me.get_memorial(db, user.id, memorial_id)
    return behdin_me.serialize_memorial(fresh, detailed=True)


@router.delete("/me/memorials/{memorial_id}")
async def delete_memorial(
    memorial_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    _write(user)
    row = await _own_memorial(db, user, memorial_id)
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# The person's own events
# ---------------------------------------------------------------------------
class EventIn(BaseModel):
    title: str
    kind: str = "other"
    date: dt.date
    repeats: str = "none"
    notes: str | None = None


class EventPatch(BaseModel):
    title: str | None = None
    kind: str | None = None
    date: dt.date | None = None
    repeats: str | None = None
    notes: str | None = None


async def _own_event(db: AsyncSession, user: User, event_id: int):
    row = await behdin_me.get_event(db, user.id, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_EVENT)
    return row


@router.post("/me/events")
async def create_event(
    payload: EventIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    _write(user)
    try:
        row = await behdin_me.save_event(
            db, user.id, None, title=payload.title, kind=payload.kind, when=payload.date,
            repeats=payload.repeats, notes=payload.notes,
        )
    except behdin_me.PersonError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return behdin_me.serialize_event(row, await mobed_dashboard.reading_system(db, user.id))


@router.get("/me/events")
async def list_events(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    _read(user)
    system = await mobed_dashboard.reading_system(db, user.id)
    return {"events": [behdin_me.serialize_event(e, system) for e in await behdin_me.list_events(db, user.id)]}


@router.patch("/me/events/{event_id}")
async def update_event(
    event_id: int, payload: EventPatch, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    _write(user)
    row = await _own_event(db, user, event_id)
    given = payload.model_fields_set
    try:
        row = await behdin_me.save_event(
            db, user.id, row,
            title=payload.title if "title" in given and payload.title is not None else row.title,
            kind=payload.kind if "kind" in given and payload.kind is not None else row.kind,
            when=payload.date if "date" in given and payload.date is not None else row.gregorian_date,
            repeats=payload.repeats if "repeats" in given and payload.repeats is not None else row.repeats,
            notes=payload.notes if "notes" in given else row.notes,
        )
    except behdin_me.PersonError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return behdin_me.serialize_event(row, await mobed_dashboard.reading_system(db, user.id))


@router.delete("/me/events/{event_id}")
async def delete_event(
    event_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    _write(user)
    row = await _own_event(db, user, event_id)
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# The calendar of the person's own things
# ---------------------------------------------------------------------------
@router.get("/me/calendar")
async def my_calendar(
    from_: dt.date = Query(alias="from"), to: dt.date = Query(),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person),
) -> dict:
    """The person's memorial dates and events between two days (at most 400 days),
    yearly events counted in for each time they come round."""
    _read(user)
    try:
        items = await behdin_me.calendar(db, user.id, from_, to)
    except behdin_me.PersonError as exc:
        raise _bad(exc) from exc
    # Confirmed requests, read from the fire temple's diary as it is now.
    items += await service_asks.calendar_items(db, user.id, from_, to, await mobed_dashboard.reading_system(db, user.id))
    items.sort(key=lambda i: (i["date"], i["source"] != "memorial", i["title"].lower(), i["id"]))
    return {"from": from_.isoformat(), "to": to.isoformat(), "items": items}
