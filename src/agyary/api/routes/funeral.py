"""The Doongerwadi side of the app (DECISIONS D10): a funeral place's manager.

A manager's account sees only what is here and what every account has (who
they are, their notices, signing out, deleting the account); every mobed
route refuses it (api/routes/mobed.py, get_signed_in_user). Recording a death
and sending it to a fire temple come in the next steps.

Signing up as a manager: a brand-new account (one that has chosen neither a
fire temple nor a funeral place) lists the places the admin has added and
picks one. That makes it a manager's account for good, waiting for an admin's
approval (D9).

A manager's records (Step 4): the deaths recorded at their place(s), which
only that place's managers see (services/funeral_records.py). A record at
another place answers 404, the same as one that does not exist. What is wrong
with one field of the form is said with that field's name in the X-Field
header, so the app can mark it.
"""

from __future__ import annotations

from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.api.routes.mobed import _serialize_user, get_current_manager, get_user_not_switched_off
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import FuneralPlace, User
from agyary.services import funeral_places, funeral_records, funeral_requests

router = APIRouter(prefix="/api/mobed", tags=["funeral"])


async def _may_choose(db: AsyncSession, user: User) -> None:
    if not await funeral_places.may_choose_kind(db, get_settings(), user):
        raise HTTPException(status_code=409, detail=funeral_places.ALREADY_CHOSEN)


@router.get("/funeral-places")
async def list_funeral_places_to_join(
    q: str = Query(default="", max_length=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_user_not_switched_off),
) -> dict:
    """The Doongerwadis, prayer halls and aramgahs in use, for a new account
    choosing where it works: all of them, or those whose name or town has
    ``q`` in it. Only while that account may still choose."""
    await _may_choose(db, user)
    rate_limit.enforce_key(f"funeral_place_search:{user.id}", max_requests=60, window_seconds=60)
    places = await funeral_places.search_active(db, q)
    return {"places": [funeral_places.summary(p) for p in places]}


@router.post("/funeral-places/{place_id}/join")
async def join_funeral_place(
    place_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_user_not_switched_off),
) -> dict:
    """A new account says it works here: it becomes this place's manager's
    account and waits for an admin's approval. Every admin is told."""
    rate_limit.enforce_key(f"funeral_place_join:{user.id}", max_requests=10, window_seconds=3600)
    place = await db.get(FuneralPlace, place_id)
    if place is None or not place.is_active:
        raise HTTPException(status_code=404, detail="That place could not be found. Please choose it again.")
    try:
        await funeral_places.join_as_manager(db, get_settings(), user, place)
    except funeral_places.JoinError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return {"user": await _serialize_user(db, user)}


@router.get("/manager/place")
async def my_funeral_place(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_manager)) -> dict:
    """The place (or places) this manager works at, for their home screen."""
    return {"places": [funeral_places.summary(p) for p in await funeral_places.places_of(db, user.id)]}


# ---------------------------------------------------------------------------
# Recording a death (D10, Step 4)
# ---------------------------------------------------------------------------
FIELD_HEADER = "X-Field"
NO_RECORD = "That record could not be found."


def _field_error(exc: funeral_records.RecordError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc), headers={FIELD_HEADER: exc.field})


class DeathDayIn(BaseModel):
    """The death: its date, or its Roj and Mah (and Parsi year, if known) in
    the family's calendar - one or the other (D5). Mah 13 is a Gatha day."""

    calendar: str = Field(default="shenshai", max_length=10)
    death_date: date | None = None
    death_roj: int | None = None
    death_mah: int | None = None
    death_year: int | None = None


class RecordIn(DeathDayIn):
    departed_title: str = Field(default="", max_length=10)
    departed_name: str = Field(default="", max_length=300)
    departed_parent_name: str | None = Field(default=None, max_length=300)
    obsequies: str = Field(default="", max_length=20)
    bungli: str | None = Field(default=None, max_length=300)
    geh_saarnu_date: date | None = None
    geh_saarnu_geh: int | None = None
    uthamna_date: date | None = None
    uthamna_time: time | None = None
    mobeds_wanted: int | None = None
    preferred_agyary_id: int | None = None
    family_contact_name: str = Field(default="", max_length=300)
    family_contact_phone: str = Field(default="", max_length=40)


class NewRecordIn(RecordIn):
    # Which of their places; may be left out by a manager of one place.
    funeral_place_id: int | None = None


@router.post("/manager/death-day")
async def check_death_day(payload: DeathDayIn, user: User = Depends(get_current_manager)) -> dict:
    """The death's date and its Roj and Mah, worked out from whichever was
    given, for the form to show the manager to confirm (D5)."""
    try:
        day = funeral_records.death_day(
            calendar=payload.calendar, death_date=payload.death_date, roj=payload.death_roj,
            mah=payload.death_mah, year=payload.death_year,
        )
    except funeral_records.RecordError as exc:
        raise _field_error(exc) from exc
    return day.as_dict()


async def _values(db: AsyncSession, payload: RecordIn) -> dict:
    try:
        return await funeral_records.checked(db, payload.model_dump())
    except funeral_records.RecordError as exc:
        raise _field_error(exc) from exc


async def _record_response(db: AsyncSession, record) -> dict:
    return {"record": (await funeral_records.serialize(db, [record]))[0]}


@router.get("/manager/records")
async def list_records(
    before: int | None = Query(default=None), db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_manager),
) -> dict:
    """The deaths recorded at this manager's place(s), newest first, with each
    request's state. ``before`` gives the page after the one ending there."""
    records = await funeral_records.list_for_manager(db, user.id, before=before)
    return {
        "records": await funeral_records.serialize(db, records),
        "more": len(records) == funeral_records.PAGE,
    }


@router.post("/manager/records")
async def create_record(
    payload: NewRecordIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_manager),
) -> dict:
    rate_limit.enforce_key(f"funeral_record_save:{user.id}", max_requests=60, window_seconds=3600)
    if payload.funeral_place_id is not None:
        place = await funeral_records.managed_place(db, user.id, payload.funeral_place_id)
    else:
        places = await funeral_places.places_of(db, user.id)
        if len(places) > 1:
            raise HTTPException(status_code=400, detail="Please choose which place this death is recorded at.")
        place = places[0] if places else None
    if place is None:
        raise HTTPException(status_code=404, detail="That place could not be found.")
    if not place.is_active:
        raise HTTPException(status_code=409, detail=f"{place.name} is turned off in Mobed Diary at the moment, "
                                                    "so a death cannot be recorded there. Please get in touch.")
    record = await funeral_records.create(db, user, place, await _values(db, payload))
    await db.commit()
    return await _record_response(db, record)


async def _own_record(db: AsyncSession, user: User, record_id: int):
    record = await funeral_records.get_for_manager(db, user.id, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=NO_RECORD)
    return record


@router.get("/manager/records/{record_id}")
async def get_record(
    record_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_manager),
) -> dict:
    return await _record_response(db, await _own_record(db, user, record_id))


@router.put("/manager/records/{record_id}")
async def update_record(
    record_id: int, payload: RecordIn, db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_manager),
) -> dict:
    """Change a record until a fire temple has accepted it."""
    rate_limit.enforce_key(f"funeral_record_save:{user.id}", max_requests=60, window_seconds=3600)
    record = await _own_record(db, user, record_id)
    values = await _values(db, payload)
    try:
        await funeral_records.update(db, record, user, values)
    except funeral_records.LockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return await _record_response(db, record)


# ---------------------------------------------------------------------------
# Choosing the fire temple (D10): suggested nearest first, or any by search
# ---------------------------------------------------------------------------
@router.get("/manager/records/{record_id}/agyaries")
async def suggested_agyaries(
    record_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_manager),
) -> dict:
    """The fire temples to suggest for this record: the family's preferred one
    first, then within 500 km of the place, nearest first, each saying whether
    a request would reach anyone there."""
    record = await _own_record(db, user, record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    return await funeral_requests.suggested(db, get_settings(), place, record.preferred_agyary_id)


@router.get("/manager/agyaries/search")
async def search_agyaries_for_manager(
    q: str = Query(default="", max_length=200),
    place_id: int | None = Query(default=None),
    preferred_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_manager),
) -> dict:
    """Any fire temple in the app by name or town, with its distance from the
    manager's place (``place_id``, or their first) where both are on the map."""
    rate_limit.enforce_key(f"funeral_agyari_search:{user.id}", max_requests=60, window_seconds=60)
    if place_id is not None:
        place = await funeral_records.managed_place(db, user.id, place_id)
    else:
        places = await funeral_places.places_of(db, user.id)
        place = places[0] if places else None
    if place is None:
        raise HTTPException(status_code=404, detail="That place could not be found.")
    return {"agyaries": await funeral_requests.search(db, get_settings(), place, q, preferred_id)}
