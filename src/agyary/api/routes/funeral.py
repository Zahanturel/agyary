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

Acting for a place (owner, 18 Nov 2026): an admin names one funeral place in
use with ``?act_for=<place id>`` on any of the manager's routes and is that
place's manager for the call - the same checks, limits and records, made in
the admin's own name, which the place's real managers see too
(get_acting_manager below). Without naming a place an admin is refused like
any mobed; a manager may not name one; a place that is unknown or turned off
answers 404.

The fire temple's side (Step 5): the requests a mobed was asked, answered from
their Requests tab (services/funeral_answers.py). These are mobed routes,
closed to a manager's account like the rest of the mobed app. Since R3.1 step
7 there is no Accept: a request is taken only by the board's actions
(routes/callouts.py), and a request accepted the old way before R3.1 is still
read here as it was (D8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.api.routes.mobed import (
    NOT_FOR_MOBEDS,
    _serialize_user,
    get_current_account,
    get_current_manager,
    get_current_user,
    get_signed_in_account,
    get_user_not_switched_off,
)
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import Agyary, FuneralPlace, FuneralRequest, User
from agyary.models.enums import ACCOUNT_FUNERAL_MANAGER
from agyary.services.phone import Phone
from agyary.services import (
    funeral_answers,
    funeral_book,
    funeral_places,
    funeral_records,
    funeral_requests,
    guardrails,
    prayer_callout,
    standbys,
)

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


# ---------------------------------------------------------------------------
# Who is acting for which places: a manager for their own, or an admin for one
# ---------------------------------------------------------------------------
ONLY_ADMINS_ACT = "Only the admin can act for a Doongerwadi or prayer hall."
NO_PLACE = "That place could not be found, or it is turned off in Mobed Diary."


@dataclass
class Acting:
    """Who is doing this, and for which places. ``user`` is who it is recorded
    under: the manager, or the admin acting for ``places[0]``."""

    user: User
    places: list[FuneralPlace]
    as_admin: bool = False

    @property
    def place_ids(self) -> list[int]:
        return [p.id for p in self.places]

    def place(self, place_id: int) -> FuneralPlace | None:
        return next((p for p in self.places if p.id == place_id), None)


async def get_acting_manager(
    act_for: int | None = Query(default=None, description="An admin acting for this funeral place"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_signed_in_account),
) -> Acting:
    """A manager (signed in, on) for their own places, as before; or an admin
    who names one funeral place in use, for that place alone. Nobody else:
    a mobed who is not an admin, an admin who names no place, and a manager
    who names any place are refused."""
    if act_for is None:
        manager = await get_current_manager(user)
        return Acting(manager, await funeral_places.places_of(db, manager.id))
    if user.account_kind == ACCOUNT_FUNERAL_MANAGER:
        raise HTTPException(status_code=403, detail=ONLY_ADMINS_ACT)
    if not guardrails.is_admin(get_settings(), user.phone):
        raise HTTPException(status_code=403, detail=NOT_FOR_MOBEDS)
    admin = await get_current_account(user)
    place = await db.get(FuneralPlace, act_for)
    if place is None or not place.is_active:
        raise HTTPException(status_code=404, detail=NO_PLACE)
    return Acting(admin, [place], as_admin=True)


@router.get("/manager/place")
async def my_funeral_place(acting: Acting = Depends(get_acting_manager)) -> dict:
    """The place (or places) this manager works at, for their home screen;
    for an admin acting for a place, that place."""
    return {"places": [funeral_places.summary(p) for p in acting.places], "as_admin": acting.as_admin}


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
async def check_death_day(payload: DeathDayIn, acting: Acting = Depends(get_acting_manager)) -> dict:
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
    acting: Acting = Depends(get_acting_manager),
) -> dict:
    """The deaths recorded at this manager's place(s), newest first, with each
    request's state. ``before`` gives the page after the one ending there."""
    records = await funeral_records.list_for_places(db, acting.place_ids, before=before)
    return {
        "records": await funeral_records.serialize(db, records),
        "more": len(records) == funeral_records.PAGE,
    }


@router.post("/manager/records")
async def create_record(
    payload: NewRecordIn, db: AsyncSession = Depends(get_db), acting: Acting = Depends(get_acting_manager),
) -> dict:
    user = acting.user
    rate_limit.enforce_key(f"funeral_record_save:{user.id}", max_requests=60, window_seconds=3600)
    if payload.funeral_place_id is not None:
        place = acting.place(payload.funeral_place_id)
    else:
        if len(acting.places) > 1:
            raise HTTPException(status_code=400, detail="Please choose which place this death is recorded at.")
        place = acting.places[0] if acting.places else None
    if place is None:
        raise HTTPException(status_code=404, detail="That place could not be found.")
    if not place.is_active:
        raise HTTPException(status_code=409, detail=f"{place.name} is turned off in Mobed Diary at the moment, "
                                                    "so a death cannot be recorded there. Please get in touch.")
    record = await funeral_records.create(db, user, place, await _values(db, payload))
    await db.commit()
    return await _record_response(db, record)


async def _own_record(db: AsyncSession, acting: Acting, record_id: int):
    record = await funeral_records.get_for_places(db, acting.place_ids, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=NO_RECORD)
    return record


@router.get("/manager/records/{record_id}")
async def get_record(
    record_id: int, db: AsyncSession = Depends(get_db), acting: Acting = Depends(get_acting_manager),
) -> dict:
    return await _record_response(db, await _own_record(db, acting, record_id))


@router.put("/manager/records/{record_id}")
async def update_record(
    record_id: int, payload: RecordIn, db: AsyncSession = Depends(get_db),
    acting: Acting = Depends(get_acting_manager),
) -> dict:
    """Change a record until a fire temple has accepted it. If it is waiting
    at a fire temple, those asked are sent the new details (``told``)."""
    user = acting.user
    rate_limit.enforce_key(f"funeral_record_save:{user.id}", max_requests=60, window_seconds=3600)
    record = await _own_record(db, acting, record_id)
    values = await _values(db, payload)
    try:
        changed = await funeral_records.update(db, record, user, values)
    except funeral_records.LockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    told = await funeral_requests.tell_of_change(db, get_settings(), record) if changed else 0
    await db.commit()
    return {**await _record_response(db, record), "told": told}


# ---------------------------------------------------------------------------
# The place's book of behdins (D10, 19 Nov 2026): the families it deals with
# ---------------------------------------------------------------------------
NO_FAMILY = "That family could not be found in the book."


class BehdinIn(BaseModel):
    name: str = Field(default="", max_length=300)
    phone: Phone
    usual_agyary_id: int | None = None


class NewBehdinIn(BehdinIn):
    # Which of their places; may be left out by a manager of one place.
    funeral_place_id: int | None = None


def _book_error(exc: funeral_book.BookError) -> HTTPException:
    headers = {FIELD_HEADER: exc.field} if exc.field else None
    return HTTPException(status_code=exc.status, detail=str(exc), headers=headers)


def _one_place(acting: Acting, place_id: int | None) -> FuneralPlace:
    if place_id is not None:
        place = acting.place(place_id)
    else:
        if len(acting.places) > 1:
            raise HTTPException(status_code=400, detail="Please choose which place this is for.")
        place = acting.places[0] if acting.places else None
    if place is None:
        raise HTTPException(status_code=404, detail="That place could not be found.")
    return place


@router.get("/manager/behdins")
async def list_book(
    q: str = Query(default="", max_length=200), db: AsyncSession = Depends(get_db),
    acting: Acting = Depends(get_acting_manager),
) -> dict:
    """The families in this place's book (the admin acting for it: that
    place's), by name; with ``q``, those whose name or number has it."""
    rate_limit.enforce_key(f"funeral_book_search:{acting.user.id}", max_requests=120, window_seconds=60)
    rows = await funeral_book.listed(db, acting.place_ids, q)
    return {"behdins": await funeral_book.serialize(db, rows), "more": len(rows) == funeral_book.PAGE}


@router.post("/manager/behdins")
async def add_to_book(
    payload: NewBehdinIn, db: AsyncSession = Depends(get_db), acting: Acting = Depends(get_acting_manager),
) -> dict:
    rate_limit.enforce_key(f"funeral_book_save:{acting.user.id}", max_requests=120, window_seconds=3600)
    place = _one_place(acting, payload.funeral_place_id)
    try:
        row = await funeral_book.add(db, acting.user, place, name=payload.name, phone=payload.phone,
                                     usual_agyary_id=payload.usual_agyary_id)
    except funeral_book.BookError as exc:
        raise _book_error(exc) from exc
    await db.commit()
    return {"behdin": (await funeral_book.serialize(db, [row]))[0]}


async def _own_behdin(db: AsyncSession, acting: Acting, behdin_id: int):
    row = await funeral_book.get(db, acting.place_ids, behdin_id)
    if row is None:
        raise HTTPException(status_code=404, detail=NO_FAMILY)
    return row


@router.put("/manager/behdins/{behdin_id}")
async def change_in_book(
    behdin_id: int, payload: BehdinIn, db: AsyncSession = Depends(get_db),
    acting: Acting = Depends(get_acting_manager),
) -> dict:
    rate_limit.enforce_key(f"funeral_book_save:{acting.user.id}", max_requests=120, window_seconds=3600)
    row = await _own_behdin(db, acting, behdin_id)
    try:
        await funeral_book.update(db, acting.user, row, name=payload.name, phone=payload.phone,
                                  usual_agyary_id=payload.usual_agyary_id)
    except funeral_book.BookError as exc:
        raise _book_error(exc) from exc
    await db.commit()
    return {"behdin": (await funeral_book.serialize(db, [row]))[0]}


@router.delete("/manager/behdins/{behdin_id}")
async def remove_from_book(
    behdin_id: int, db: AsyncSession = Depends(get_db), acting: Acting = Depends(get_acting_manager),
) -> dict:
    """Out of the book (kept, turned off: D8). Records already made keep their
    family contact."""
    row = await _own_behdin(db, acting, behdin_id)
    await funeral_book.remove(db, acting.user, row)
    await db.commit()
    return {"removed": row.id}


# ---------------------------------------------------------------------------
# Choosing the fire temple (D10): suggested nearest first, or any by search
# ---------------------------------------------------------------------------
@router.get("/manager/records/{record_id}/agyaries")
async def suggested_agyaries(
    record_id: int, db: AsyncSession = Depends(get_db), acting: Acting = Depends(get_acting_manager),
) -> dict:
    """The fire temples to suggest for this record: the family's preferred one
    first (or, if none was chosen, their usual one from the place's book of
    behdins), then within 500 km of the place, nearest first, each saying
    whether a request would reach anyone there."""
    record = await _own_record(db, acting, record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    first = record.preferred_agyary_id or await funeral_book.usual_agyari_of(
        db, record.funeral_place_id, record.family_contact_phone)
    return await funeral_requests.suggested(db, get_settings(), place, first)


@router.get("/manager/agyaries/search")
async def search_agyaries_for_manager(
    q: str = Query(default="", max_length=200),
    place_id: int | None = Query(default=None),
    preferred_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    acting: Acting = Depends(get_acting_manager),
) -> dict:
    """Any fire temple in the app by name or town, with its distance from the
    manager's place (``place_id``, or their first) where both are on the map."""
    rate_limit.enforce_key(f"funeral_agyari_search:{acting.user.id}", max_requests=60, window_seconds=60)
    if place_id is not None:
        place = acting.place(place_id)
    else:
        place = acting.places[0] if acting.places else None
    if place is None:
        raise HTTPException(status_code=404, detail="That place could not be found.")
    settings = get_settings()
    return {"agyaries": await funeral_requests.search(db, settings, place, q, preferred_id),
            "whatsapp_on": await funeral_requests.whatsapp_on(db, settings)}


# ---------------------------------------------------------------------------
# Sending the request, and withdrawing it (D10)
# ---------------------------------------------------------------------------
class SendIn(BaseModel):
    agyary_id: int
    # The tick: "The family agreed to share their name and number with this
    # agyari, and to get WhatsApp messages about the prayers from Mobed Diary".
    # The app sends both from that one tick; an app from before those words
    # sends only the first, and the family is then never messaged from our number.
    family_agreed: bool = False
    family_whatsapp_agreed: bool = False


def _send_error(exc: funeral_requests.SendError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/manager/records/{record_id}/requests")
async def send_request(
    record_id: int, payload: SendIn, db: AsyncSession = Depends(get_db),
    acting: Acting = Depends(get_acting_manager),
) -> dict:
    """Send the record to one fire temple: its confirmed panthakys, or if none,
    its mobeds whose access is on. Refused without the family's agreement, with
    nobody there to reach, or while another request waits. Once it is sent, by
    the fire temple's way (R3.1): in Everyone at once its mobeds are asked on
    WhatsApp; in Come to me first only the panthaky is told, and chooses who to
    ask. ``callout`` says which, what happened, or why nothing was sent; that
    never makes the send fail."""
    user = acting.user
    record = await _own_record(db, acting, record_id)
    if not payload.family_agreed:
        raise HTTPException(status_code=400, detail=funeral_requests.NO_TICK, headers={FIELD_HEADER: "family_agreed"})
    rate_limit.enforce_key(f"funeral_send:{user.id}", max_requests=20, window_seconds=3600)
    agyary = await db.get(Agyary, payload.agyary_id)
    if agyary is None:
        raise HTTPException(status_code=404, detail="That fire temple could not be found. Please choose it again.")
    try:
        request = await funeral_requests.send(db, get_settings(), user, record, agyary, family_agreed=True,
                                              family_whatsapp_agreed=payload.family_whatsapp_agreed)
    except funeral_requests.SendError as exc:
        raise _send_error(exc) from exc
    asked = len(await funeral_requests.asked(db, request))
    await db.commit()
    callout = await prayer_callout.after_send(db, get_settings(), request.id)
    # Read again: a failure in sending rolls the session back, which forgets it.
    await db.refresh(record)
    return {**await _record_response(db, record), "asked": asked, "callout": callout}


@router.post("/manager/requests/{request_id}/withdraw")
async def withdraw_request(
    request_id: int, db: AsyncSession = Depends(get_db), acting: Acting = Depends(get_acting_manager),
) -> dict:
    """Take back a waiting request (to send it to another fire temple)."""
    user = acting.user
    request = await db.get(FuneralRequest, request_id)
    record = await funeral_records.get_for_places(db, acting.place_ids, request.funeral_record_id) if request else None
    if record is None:
        raise HTTPException(status_code=404, detail="That request could not be found.")
    try:
        await funeral_requests.withdraw(db, get_settings(), user, request)
    except funeral_requests.SendError as exc:
        raise _send_error(exc) from exc
    await db.commit()
    # Mobeds who said yes on WhatsApp are told, inside WhatsApp's 24 hours.
    await prayer_callout.after_closed(db, get_settings(), request.id)
    await db.refresh(record)
    return await _record_response(db, record)


# ---------------------------------------------------------------------------
# The fire temple's side (D10, Step 5): the Requests tab of the people asked
# ---------------------------------------------------------------------------
# Mobed routes: get_current_user refuses a manager's account (and anyone whose
# access is not on). A request is 404 to anyone who was not asked.
class DeclineIn(BaseModel):
    reason: str | None = Field(default=None, max_length=600)


def _answer_error(exc: funeral_answers.AnswerError) -> HTTPException:
    headers = {FIELD_HEADER: exc.field} if exc.field else None
    return HTTPException(status_code=exc.status, detail=str(exc), headers=headers)


async def _asked_request(db: AsyncSession, user: User, request_id: int) -> FuneralRequest:
    request = await funeral_answers.get_for_user(db, user.id, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=funeral_answers.NOT_FOUND)
    return request


async def _one(db: AsyncSession, user: User, request: FuneralRequest) -> dict:
    return (await funeral_answers.serialize(db, user, [request]))[0]


@router.get("/requests/count")
async def my_request_count(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """How many requests wait for this mobed's answer: the red count on the tab."""
    return {"waiting": await funeral_answers.waiting_count(db, user.id)}


@router.get("/requests")
async def my_requests(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """The requests this mobed was asked: those waiting, and the last few
    answered or withdrawn. No family name or number until it is all set, and
    then only for those whose book it put the family in (or, on a request
    accepted the old way, for the one who accepted it)."""
    waiting, earlier = await funeral_answers.for_user(db, user.id)
    return {
        "waiting": await funeral_answers.serialize(db, user, waiting),
        "earlier": await funeral_answers.serialize(db, user, earlier),
    }


@router.get("/requests/{request_id}")
async def my_request(
    request_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    return {"request": await _one(db, user, await _asked_request(db, user, request_id))}


class AnswerIn(BaseModel):
    # "yes" (I can pray) or "no" (Not this time). Checked by
    # prayer_callout.answer_in_app, so a wrong value is said in plain words
    # (a 400 naming the field), never as a 422.
    answer: Any = None


def _callout_error(exc: prayer_callout.CalloutError) -> HTTPException:
    headers = {FIELD_HEADER: exc.field} if exc.field else None
    return HTTPException(status_code=exc.status, detail=str(exc), headers=headers)


async def _answer_in_app(db: AsyncSession, user: User, request: FuneralRequest, answer) -> dict:
    try:
        done = await prayer_callout.answer_in_app(db, get_settings(), user, request, answer)
    except prayer_callout.CalloutError as exc:
        raise _callout_error(exc) from exc
    await db.refresh(request)
    await db.refresh(user)
    return {"request": await _one(db, user, request), "done": done}


@router.post("/requests/{request_id}/answer")
async def answer_request(
    request_id: int, payload: AnswerIn, db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """An app mobed's "I can pray" or "Not this time" (R3.1, owner 21 Nov
    2026): only someone the request reached who is not the fire temple's
    confirmed panthaky (they use the board), and only their first answer,
    whichever way it came. ``done`` says where they stand."""
    rate_limit.enforce_key(f"funeral_answer:{user.id}", max_requests=30, window_seconds=3600)
    request = await _asked_request(db, user, request_id)
    return await _answer_in_app(db, user, request, payload.answer)


@router.post("/requests/{request_id}/back-out")
async def back_out_of_request(
    request_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    """ "I can't go any more" (R3.1 step 5b): someone going, the request
    reached them, can no longer go. Their place opens again, the panthaky is
    told, and the family stays in their own book. Refused in plain words for
    someone not going, a request that is closed, and once the prayers have
    begun. ``done`` says what happened."""
    rate_limit.enforce_key(f"funeral_answer:{user.id}", max_requests=30, window_seconds=3600)
    request = await _asked_request(db, user, request_id)
    try:
        done = await standbys.back_out_in_app(db, get_settings(), user, request)
    except prayer_callout.CalloutError as exc:
        raise _callout_error(exc) from exc
    await db.refresh(request)
    await db.refresh(user)
    return {"request": await _one(db, user, request), "done": done}


@router.post("/requests/{request_id}/decline")
async def decline_request(
    request_id: int, payload: DeclineIn, db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """A confirmed panthaky's "We can't take this": declined for the fire
    temple, with an optional short reason for the manager, who can then ask
    another fire temple. Anyone else the request reached says "Not this time"
    for themselves only (owner, 21 Nov 2026, third round): the same as
    answering no, and the request stays open for the others."""
    rate_limit.enforce_key(f"funeral_answer:{user.id}", max_requests=30, window_seconds=3600)
    request = await _asked_request(db, user, request_id)
    if not await prayer_callout.is_confirmed_panthaky(db, request.agyary_id, user.id):
        return await _answer_in_app(db, user, request, "no")
    try:
        await funeral_answers.decline(db, get_settings(), user, request, reason=payload.reason)
    except funeral_answers.AnswerError as exc:
        raise _answer_error(exc) from exc
    await db.commit()
    # Mobeds who said yes on WhatsApp are told, inside WhatsApp's 24 hours.
    await prayer_callout.after_closed(db, get_settings(), request.id)
    await db.refresh(request)
    await db.refresh(user)
    return {"request": await _one(db, user, request)}
