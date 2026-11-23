"""A fire temple's own list of mobeds (the Mobeds page; DECISIONS D10;
services/prayer_callout.py), and how a prayer request reaches the fire temple
(R3.1; services/request_settings.py).

Mobed routes (get_current_user: signed in, switched on, and never a manager's
account). Only a confirmed panthaky of that fire temple, or the admin, reaches
any of it; to everyone else - a mobed there, another fire temple's panthaky -
it answers 404, as if it did not exist. What is wrong with one field is said
with that field's name in the X-Field header.

The "Who will pray" board on a request (R3.1 step 4): the board, Ask everyone,
I'll pray, and a call's result, for the confirmed panthakys the request reached
and the admin; (step 5) "Confirm with who's going"; and (step 5b) "Can't go" on
a place, for a mobed going who phoned to say they can no longer go. The board's
actions are the only way to take a request: the old call-out screen's routes
(GET and POST .../callout, .../callout/details-again) and the old Accept are
gone since R3.1 step 7.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.api.routes.mobed import get_current_user
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import Agyary, User
from agyary.services import funeral_whatsapp, join_confirmation, prayer_callout, request_settings, standbys
from agyary.services.phone import Phone

router = APIRouter(prefix="/api/mobed", tags=["callouts"])

FIELD_HEADER = "X-Field"
NO_LIST = "That list could not be found."
NO_AGYARI = "That fire temple could not be found."
NO_REQUEST = "That request could not be found."


def _error(exc: prayer_callout.CalloutError) -> HTTPException:
    headers = {FIELD_HEADER: exc.field} if exc.field else None
    return HTTPException(status_code=exc.status, detail=str(exc), headers=headers)


async def _managed_agyary(db: AsyncSession, user: User, agyary_id: int, missing: str = NO_LIST) -> Agyary:
    agyary = await db.get(Agyary, agyary_id)
    if agyary is None or not agyary.is_active or not await prayer_callout.may_manage(db, get_settings(), user, agyary_id):
        raise HTTPException(status_code=404, detail=missing)
    return agyary


async def _list(db: AsyncSession, user: User, agyary: Agyary) -> dict:
    """The Mobeds page. Only ever called with an ``agyary`` from
    _managed_agyary, so the app mobeds' numbers reach only that fire temple's
    confirmed panthakys and the admin (owner, 21 Nov 2026). Those who joined
    and wait to be confirmed, and those taken off the list (D10, 22 Nov 2026),
    are there apart by name only."""
    settings = get_settings()
    return {
        "agyari": {"id": agyary.id, "name": agyary.name},
        "mobeds": await prayer_callout.our_mobeds(db, settings, agyary.id, me=user, with_numbers=True),
        "joined": await join_confirmation.not_on_the_list(db, settings, agyary.id),
        "whatsapp": await funeral_whatsapp.status(db, settings),
        "consent_words": prayer_callout.CONSENT_WORDS,
    }


@router.get("/agyaries/{agyary_id}/our-mobeds")
async def our_mobeds(agyary_id: int, db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)) -> dict:
    """The Mobeds page: the fire temple's mobeds in the app and those added by
    hand, each with their number and saying whether they can be messaged (a
    STOP, an account switched off or waiting)."""
    return await _list(db, user, await _managed_agyary(db, user, agyary_id))


class ContactIn(BaseModel):
    name: str = Field(default="", max_length=200)
    phone: Phone
    # "They agreed to get WhatsApp messages from Mobed Diary about prayers."
    agreed: bool = False


@router.post("/agyaries/{agyary_id}/our-mobeds")
async def add_our_mobed(agyary_id: int, payload: ContactIn, db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)) -> dict:
    agyary = await _managed_agyary(db, user, agyary_id)
    if not payload.agreed:
        raise HTTPException(status_code=400, detail=prayer_callout.NO_TICK, headers={FIELD_HEADER: "agreed"})
    rate_limit.enforce_key(f"our_mobeds_add:{user.id}", max_requests=60, window_seconds=3600)
    try:
        contact = await prayer_callout.add_contact(db, get_settings(), user, agyary, name=payload.name,
                                                   phone=payload.phone, agreed=True)
    except prayer_callout.CalloutError as exc:
        raise _error(exc) from exc
    await db.commit()
    return {**await _list(db, user, agyary), "added": contact.id}


@router.put("/agyaries/{agyary_id}/our-mobeds/{contact_id}")
async def edit_our_mobed(agyary_id: int, contact_id: int, payload: ContactIn, db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)) -> dict:
    """The pen on a mobed added by hand (owner, 24 Nov 2026). The same number:
    only the name changes. A new number is a different person's: it needs the
    tick again, the old entry goes off the list (a place it held is freed, as
    Remove frees it) and the new one is added, all or nothing."""
    agyary = await _managed_agyary(db, user, agyary_id)
    rate_limit.enforce_key(f"our_mobeds_add:{user.id}", max_requests=60, window_seconds=3600)
    from agyary.models import AgyaryMobedContact   # here: only this route reads a row itself
    current = await db.get(AgyaryMobedContact, contact_id)
    if current is None or current.agyary_id != agyary.id or not current.is_active:
        raise HTTPException(status_code=404, detail="That mobed could not be found on the list.")
    try:
        if payload.phone == current.phone:
            await prayer_callout.rename_contact(db, agyary.id, contact_id, payload.name, user)
            await db.commit()
            await db.refresh(user)
            await db.refresh(agyary)
            return {**await _list(db, user, agyary), "done": {"message": "Saved.", "places_freed": 0}}
        if not payload.agreed:
            raise HTTPException(status_code=400, detail=prayer_callout.NO_TICK, headers={FIELD_HEADER: "agreed"})
        old = await prayer_callout.remove_contact(db, agyary.id, contact_id, user)
        old_name = old.name
        await prayer_callout.add_contact(db, get_settings(), user, agyary, name=payload.name,
                                         phone=payload.phone, agreed=True)
    except prayer_callout.CalloutError as exc:
        await db.rollback()
        raise _error(exc) from exc
    await db.commit()
    freed = await standbys.free_places_of(db, get_settings(), by_user=user, agyary_id=agyary.id,
                                          contact_id=contact_id)
    await db.refresh(user)
    await db.refresh(agyary)
    words = " ".join(w for w in (f"Saved. {old_name}'s old number is off the list.", standbys.freed_words(freed)) if w)
    return {**await _list(db, user, agyary), "done": {"message": words, "places_freed": len(freed)}}


@router.post("/agyaries/{agyary_id}/our-mobeds/{key}/start")
async def start_our_mobed_again(agyary_id: int, key: str, db: AsyncSession = Depends(get_db),
                                user: User = Depends(get_current_user)) -> dict:
    """"Turn WhatsApp back on" for someone on the list who replied STOP (owner, 24 Nov 2026): the
    panthaky's choice, since they asked them. The person can reply STOP again any time."""
    agyary = await _managed_agyary(db, user, agyary_id)
    rate_limit.enforce_key(f"our_mobeds_member:{user.id}", max_requests=60, window_seconds=3600)
    try:
        name = await prayer_callout.start_again(db, get_settings(), agyary.id, key, user)
    except prayer_callout.CalloutError as exc:
        raise _error(exc) from exc
    await db.commit()
    await db.refresh(user)
    await db.refresh(agyary)
    return {**await _list(db, user, agyary),
            "done": {"message": f"WhatsApp is on again for {name}. They can reply STOP any time."}}


@router.delete("/agyaries/{agyary_id}/our-mobeds/{contact_id}")
async def remove_our_mobed(agyary_id: int, contact_id: int, db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)) -> dict:
    """Take a mobed added by hand off the list (kept, turned off). A place
    they hold on one of its requests is freed as "Can't go" frees it (lead's
    decision, 22 Nov 2026); ``done`` says so."""
    agyary = await _managed_agyary(db, user, agyary_id)
    try:
        contact = await prayer_callout.remove_contact(db, agyary.id, contact_id, user)
    except prayer_callout.CalloutError as exc:
        raise _error(exc) from exc
    await db.commit()
    name = contact.name
    freed = await standbys.free_places_of(db, get_settings(), by_user=user, agyary_id=agyary.id,
                                          contact_id=contact.id)
    await db.refresh(user)
    await db.refresh(agyary)
    words = " ".join(w for w in (f"{name} is off the list.", standbys.freed_words(freed)) if w)
    return {**await _list(db, user, agyary), "done": {"message": words, "places_freed": len(freed)}}


# --- Joined, waiting for you; Off the list (D10, owner 22 Nov 2026) ----------------
# A mobed who joins the fire temple gets its prayer requests only once one of its
# confirmed panthakys (access on) - or the admin - confirms them here. The same
# 404 as for a list that does not exist to anyone else, and for someone who is not
# an app mobed of the fire temple.
async def _member_action(db: AsyncSession, user: User, agyary_id: int, act) -> dict:
    agyary = await _managed_agyary(db, user, agyary_id)
    rate_limit.enforce_key(f"our_mobeds_member:{user.id}", max_requests=60, window_seconds=3600)
    try:
        done = await act(agyary)
    except join_confirmation.JoinError as exc:   # refused before anything changed
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    await db.commit()
    # Read again: freeing a place may have rolled the session back, which forgets them.
    await db.refresh(user)
    await db.refresh(agyary)
    return {**await _list(db, user, agyary), "done": done}


@router.post("/agyaries/{agyary_id}/members/{user_id}/confirm")
async def confirm_member(agyary_id: int, user_id: int, db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)) -> dict:
    """ "Confirm": one who joined becomes one of its mobeds for prayer requests."""
    return await _member_action(db, user, agyary_id, lambda agyary: join_confirmation.confirm(
        db, get_settings(), user, agyary, user_id))


@router.post("/agyaries/{agyary_id}/members/{user_id}/off")
async def take_member_off(agyary_id: int, user_id: int, db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)) -> dict:
    """ "Not one of ours" or "Take off the list": no more prayer requests from
    this fire temple; they stay a member, and nothing else changes for them."""
    return await _member_action(db, user, agyary_id, lambda agyary: join_confirmation.take_off(
        db, get_settings(), user, agyary, user_id))


@router.post("/agyaries/{agyary_id}/members/{user_id}/on")
async def put_member_back(agyary_id: int, user_id: int, db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)) -> dict:
    """ "Put back": one taken off the list is one of its mobeds again."""
    return await _member_action(db, user, agyary_id, lambda agyary: join_confirmation.put_back(
        db, get_settings(), user, agyary, user_id))


# --- How a prayer request reaches the fire temple (R3.1) --------------------------
@router.get("/agyaries/{agyary_id}/request-settings")
async def get_request_settings(agyary_id: int, db: AsyncSession = Depends(get_db),
                               user: User = Depends(get_current_user)) -> dict:
    """Everyone at once or Come to me first, and the safety net's minutes
    (None is Never)."""
    return request_settings.read(await _managed_agyary(db, user, agyary_id, NO_AGYARI))


class RequestSettingsIn(BaseModel):
    # Checked by request_settings.change, so a wrong value is said in plain
    # words (a 400 naming the field), never as a 422.
    mode: Any = None
    escalate_minutes: Any = None


@router.put("/agyaries/{agyary_id}/request-settings")
async def put_request_settings(agyary_id: int, payload: RequestSettingsIn, db: AsyncSession = Depends(get_db),
                               user: User = Depends(get_current_user)) -> dict:
    """Both are saved as given: the minutes are kept under either way, and
    matter only in Come to me first."""
    agyary = await _managed_agyary(db, user, agyary_id, NO_AGYARI)
    try:
        saved = request_settings.change(agyary, user, mode=payload.mode, escalate_minutes=payload.escalate_minutes)
    except request_settings.SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc), headers={FIELD_HEADER: exc.field}) from exc
    await db.commit()
    return saved


# --- The board: "Who will pray" (R3.1 step 4) ---------------------------------------
# Only the fire temple's confirmed panthakys whom the request reached, and the
# admin (prayer_callout.board_request); anyone else gets the same 404 as for a
# request that does not exist. Every action takes the request for the fire
# temple once; "We can't take this" is the decline route (routes/funeral.py).
async def _board_request(db: AsyncSession, user: User, request_id: int):
    request = await prayer_callout.board_request(db, get_settings(), user, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=NO_REQUEST)
    return request


@router.get("/requests/{request_id}/board")
async def board(request_id: int, db: AsyncSession = Depends(get_db),
                user: User = Depends(get_current_user)) -> dict:
    """The request (no family name or number), the way, who took it, the
    places, the standbys, the Mobeds list with numbers and each one's state,
    whether Ask everyone can ask anyone now, and whether WhatsApp is on."""
    request = await _board_request(db, user, request_id)
    return await prayer_callout.board(db, get_settings(), user, request)


@router.post("/requests/{request_id}/ask-everyone")
async def board_ask_everyone(request_id: int, db: AsyncSession = Depends(get_db),
                             user: User = Depends(get_current_user)) -> dict:
    """Everyone on the list not asked yet: in the app, and on WhatsApp where
    they can be messaged. ``done`` says how many, or why not."""
    request = await _board_request(db, user, request_id)
    rate_limit.enforce_key(f"prayer_board:{user.id}", max_requests=60, window_seconds=3600)
    settings = get_settings()
    try:
        done = await prayer_callout.ask_from_board(db, settings, user, request)
    except prayer_callout.CalloutError as exc:
        raise _error(exc) from exc
    return {**await prayer_callout.board(db, settings, user, request), "done": done}


@router.post("/requests/{request_id}/self")
async def board_pray_myself(request_id: int, db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)) -> dict:
    """The panthaky's "I'll pray": a place filled with them."""
    request = await _board_request(db, user, request_id)
    rate_limit.enforce_key(f"prayer_board:{user.id}", max_requests=60, window_seconds=3600)
    settings = get_settings()
    try:
        done = await prayer_callout.pray_myself(db, settings, user, request)
    except prayer_callout.CalloutError as exc:
        raise _error(exc) from exc
    return {**await prayer_callout.board(db, settings, user, request), "done": done}


@router.post("/requests/{request_id}/confirm-short")
async def board_confirm_short(request_id: int, db: AsyncSession = Depends(get_db),
                              user: User = Depends(get_current_user)) -> dict:
    """ "Confirm with who's going" (R3.1 step 5): all set with those going,
    while at least one is and fewer than wanted are. ``done`` says so."""
    request = await _board_request(db, user, request_id)
    rate_limit.enforce_key(f"prayer_board:{user.id}", max_requests=60, window_seconds=3600)
    settings = get_settings()
    try:
        done = await prayer_callout.confirm_short(db, settings, user, request)
    except prayer_callout.CalloutError as exc:
        raise _error(exc) from exc
    return {**await prayer_callout.board(db, settings, user, request), "done": done}


class CallResultIn(BaseModel):
    # Checked by prayer_callout.call_result, so a wrong value is said in plain
    # words (a 400 naming the field), never as a 422.
    key: Any = None        # "u<user id>" or "c<contact id>", from the board's Mobeds list
    result: Any = None     # "going", "not_going" or "no_answer"


class CantGoIn(BaseModel):
    # Checked by standbys.mark_cant_go, so a wrong value is said in plain words.
    key: Any = None        # the place's "u<user id>" or "c<contact id>", from the board's places


@router.post("/requests/{request_id}/cant-go")
async def board_cant_go(request_id: int, payload: CantGoIn, db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)) -> dict:
    """The board's "Can't go" on a place (R3.1 step 5b), for a mobed going
    who phoned to say they can no longer go: their place opens again."""
    request = await _board_request(db, user, request_id)
    rate_limit.enforce_key(f"prayer_board:{user.id}", max_requests=60, window_seconds=3600)
    settings = get_settings()
    try:
        done = await standbys.mark_cant_go(db, settings, user, request, payload.key)
    except prayer_callout.CalloutError as exc:
        raise _error(exc) from exc
    return {**await prayer_callout.board(db, settings, user, request), "done": done}


@router.post("/requests/{request_id}/call-result")
async def board_call_result(request_id: int, payload: CallResultIn, db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)) -> dict:
    """What a call to one of the fire temple's mobeds came to."""
    request = await _board_request(db, user, request_id)
    rate_limit.enforce_key(f"prayer_board:{user.id}", max_requests=60, window_seconds=3600)
    settings = get_settings()
    try:
        done = await prayer_callout.call_result(db, settings, user, request, payload.key, payload.result)
    except prayer_callout.CalloutError as exc:
        raise _error(exc) from exc
    return {**await prayer_callout.board(db, settings, user, request), "done": done}
