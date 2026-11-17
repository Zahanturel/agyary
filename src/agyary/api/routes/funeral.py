"""The Doongerwadi side of the app (DECISIONS D10): a funeral place's manager.

A manager's account sees only what is here and what every account has (who
they are, their notices, signing out, deleting the account); every mobed
route refuses it (api/routes/mobed.py, get_signed_in_user). Recording a death
and sending it to a fire temple come in the next steps.

Signing up as a manager: a brand-new account (one that has chosen neither a
fire temple nor a funeral place) lists the places the admin has added and
picks one. That makes it a manager's account for good, waiting for an admin's
approval (D9).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.api.routes.mobed import _serialize_user, get_current_manager, get_user_not_switched_off
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import FuneralPlace, User
from agyary.services import funeral_places

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
