"""A fire temple's own list of mobeds, the panthaky's call-out to them on
WhatsApp (DECISIONS D10, Phase 2 Step 5c; services/prayer_callout.py), and how
a prayer request reaches the fire temple (R3.1; services/request_settings.py).

Mobed routes (get_current_user: signed in, switched on, and never a manager's
account). Only a confirmed panthaky of that fire temple, or the admin, reaches
any of it; to everyone else - a mobed there, another fire temple's panthaky -
it answers 404, as if it did not exist. What is wrong with one field is said
with that field's name in the X-Field header.
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
from agyary.services import funeral_whatsapp, prayer_callout, request_settings
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
    confirmed panthakys and the admin (owner, 21 Nov 2026)."""
    settings = get_settings()
    return {
        "agyari": {"id": agyary.id, "name": agyary.name},
        "mobeds": await prayer_callout.our_mobeds(db, settings, agyary.id, me=user, with_numbers=True),
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


@router.delete("/agyaries/{agyary_id}/our-mobeds/{contact_id}")
async def remove_our_mobed(agyary_id: int, contact_id: int, db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)) -> dict:
    """Take a mobed added by hand off the list (kept, turned off)."""
    agyary = await _managed_agyary(db, user, agyary_id)
    try:
        await prayer_callout.remove_contact(db, agyary.id, contact_id, user)
    except prayer_callout.CalloutError as exc:
        raise _error(exc) from exc
    await db.commit()
    return await _list(db, user, agyary)


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


# --- The call-out on an accepted request ------------------------------------------
async def _request(db: AsyncSession, user: User, request_id: int):
    request = await prayer_callout.callout_request(db, get_settings(), user, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=NO_REQUEST)
    return request


@router.get("/requests/{request_id}/callout")
async def callout(request_id: int, db: AsyncSession = Depends(get_db),
                  user: User = Depends(get_current_user)) -> dict:
    """Everyone asked with their answer and who is going, and who can still be
    asked. No family details."""
    request = await _request(db, user, request_id)
    return await prayer_callout.view(db, get_settings(), user, request)


class CalloutIn(BaseModel):
    # "u<user id>" for a mobed in the app, "c<contact id>" for one added by hand.
    who: list[str] = Field(default_factory=list, max_length=200)


@router.post("/requests/{request_id}/callout")
async def send_callout(request_id: int, payload: CalloutIn, db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)) -> dict:
    """Ask again, by hand: the chosen mobeds not asked yet for this request
    (template 4). Everyone who could be was asked when the request was sent."""
    request = await _request(db, user, request_id)
    rate_limit.enforce_key(f"prayer_callout:{user.id}", max_requests=10, window_seconds=3600)
    settings = get_settings()
    try:
        sent = await prayer_callout.send(db, settings, user, request, [k[:24] for k in payload.who])
    except prayer_callout.CalloutError as exc:
        raise _error(exc) from exc
    return {**await prayer_callout.view(db, settings, user, request), "asked_now": sent}


@router.post("/requests/{request_id}/callout/details-again")
async def details_again(request_id: int, db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)) -> dict:
    """The first yeses go and get the details at once (19 Nov 2026); this sends
    them again to those going whose details did not go. Never twice."""
    request = await _request(db, user, request_id)
    rate_limit.enforce_key(f"prayer_callout_again:{user.id}", max_requests=30, window_seconds=3600)
    settings = get_settings()
    try:
        done = await prayer_callout.details_again(db, settings, user, request)
    except prayer_callout.CalloutError as exc:
        raise _error(exc) from exc
    return {**await prayer_callout.view(db, settings, user, request), "done": done}
