"""The panthaky's side of asks from people (R4.2; docs/behdin-r4-2-design.md).

Reading and answering asks, the switch "Take asks from people", and the services with their usual
prices. Only the agyari's confirmed panthaky (or the admin, to read and to switch) may use these; any
other mobed gets a 403. A person's number and full name are never in what is read here: only the first
name. After an accept the person is a record in the panthaky's own book, and that is where the number is.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api.routes.mobed import get_current_user
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import Agyary, Service, User
from agyary.services import mobed_dashboard, prayer_callout, service_asks

router = APIRouter(prefix="/api/mobed", tags=["asks"])

NO_AGYARI = "That fire temple could not be found."
NOT_PANTHAKY = "Only the panthaky of this fire temple can do this."


async def _managed(db: AsyncSession, user: User, agyary_id: int) -> Agyary:
    agyary = await db.get(Agyary, agyary_id)
    if agyary is None or not agyary.is_active:
        raise HTTPException(status_code=404, detail=NO_AGYARI)
    if not await prayer_callout.may_manage(db, get_settings(), user, agyary_id):
        raise HTTPException(status_code=403, detail=NOT_PANTHAKY)
    return agyary


def _error(exc: service_asks.AskError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


# --- Take asks from people ----------------------------------------------------------
@router.get("/agyaries/{agyary_id}/asks-setting")
async def get_asks_setting(agyary_id: int, db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)) -> dict:
    return await service_asks.read_switch(db, await _managed(db, user, agyary_id))


class AsksSettingIn(BaseModel):
    takes_asks: Any = None   # checked by the service, so a wrong value is said in plain words


@router.put("/agyaries/{agyary_id}/asks-setting")
async def put_asks_setting(agyary_id: int, payload: AsksSettingIn, db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)) -> dict:
    agyary = await _managed(db, user, agyary_id)
    try:
        saved = await service_asks.change_switch(db, agyary, payload.takes_asks)
    except service_asks.AskError as exc:
        raise _error(exc) from exc
    await db.commit()
    return saved


# --- Services and prices ---------------------------------------------------------------
@router.get("/agyaries/{agyary_id}/service-prices")
async def get_service_prices(agyary_id: int, db: AsyncSession = Depends(get_db),
                             user: User = Depends(get_current_user)) -> dict:
    """Every service of the fire temple with its usual price (None: "Ask the agyari for the price")."""
    await _managed(db, user, agyary_id)
    return {"services": await service_asks.list_prices(db, agyary_id)}


class ServiceChangeIn(BaseModel):
    default_price: Any = None
    offered: Any = None


class NewServiceIn(BaseModel):
    name: Any = None


@router.post("/agyaries/{agyary_id}/request-services")
async def add_service(agyary_id: int, payload: NewServiceIn, db: AsyncSession = Depends(get_db),
                      user: User = Depends(get_current_user)) -> dict:
    """The panthaky's own service, listed for people at once."""
    agyary = await _managed(db, user, agyary_id)
    try:
        saved = await service_asks.add_service(db, agyary, payload.name)
    except service_asks.AskError as exc:
        raise _error(exc) from exc
    await db.commit()
    return saved


@router.put("/agyaries/{agyary_id}/services/{service_id}")
async def put_service(agyary_id: int, service_id: int, payload: ServiceChangeIn, db: AsyncSession = Depends(get_db),
                      user: User = Depends(get_current_user)) -> dict:
    """Set the usual price (a number from 0, or null to clear it) and/or list the service for people or not.
    Only what is sent is changed. The diary's own catalog is not touched."""
    agyary = await _managed(db, user, agyary_id)
    service = (await db.execute(select(Service).where(
        Service.id == service_id, Service.agyary_id == agyary_id))).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=404, detail="That service could not be found.")
    try:
        saved = await service_asks.change_service(
            db, agyary, service, fields=payload.model_fields_set, price=payload.default_price, offered=payload.offered)
    except service_asks.AskError as exc:
        raise _error(exc) from exc
    await db.commit()
    return saved


# --- Asks from people ----------------------------------------------------------------------
@router.get("/agyaries/{agyary_id}/asks")
async def list_asks(agyary_id: int, db: AsyncSession = Depends(get_db),
                    user: User = Depends(get_current_user)) -> dict:
    """The Requests tab's "Asks from people": waiting ones first, then the answered. The person's
    first name only, never their number."""
    await _managed(db, user, agyary_id)
    system = await mobed_dashboard.reading_system(db, user.id)
    return {
        "waiting": await service_asks.waiting_count(db, agyary_id),
        "asks": await service_asks.list_for_agyary(db, agyary_id, system),
    }


async def _ask(db: AsyncSession, user: User, agyary_id: int, ask_id: int):
    await _managed(db, user, agyary_id)
    ask = await service_asks.for_agyary(db, agyary_id, ask_id, lock=True)
    if ask is None:
        raise HTTPException(status_code=404, detail=service_asks.NO_SUCH_ASK)
    if not await service_asks.may_answer(db, user, agyary_id):
        raise HTTPException(status_code=403, detail=NOT_PANTHAKY)
    return ask


async def _view(db: AsyncSession, user: User, ask) -> dict:
    system = await mobed_dashboard.reading_system(db, user.id)
    return (await service_asks.panthaky_views(db, [ask], system))[0]


class AcceptIn(BaseModel):
    # The time of day for each prayer the person left open: {"<item id>": "HH:MM"}.
    times: Any = None


@router.post("/agyaries/{agyary_id}/asks/{ask_id}/accept")
async def accept_ask(agyary_id: int, ask_id: int, payload: AcceptIn | None = None, db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)) -> dict:
    """Confirm the whole request: the person becomes a record in the panthaky's own book (their number is
    shared now) and one entry per prayer is made in the panthaky's own diary, in one go."""
    ask = await _ask(db, user, agyary_id, ask_id)
    try:
        made = await service_asks.accept(db, get_settings(), ask, user, payload.times if payload else None)
    except service_asks.AskError as exc:
        await db.rollback()
        raise _error(exc) from exc
    return {**made, "ask": await _view(db, user, ask)}


class RejectIn(BaseModel):
    reason: Any = None


@router.post("/agyaries/{agyary_id}/asks/{ask_id}/reject")
async def reject_ask(agyary_id: int, ask_id: int, payload: RejectIn, db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)) -> dict:
    """Say no, with a short reason (100 letters) the person is shown."""
    ask = await _ask(db, user, agyary_id, ask_id)
    try:
        await service_asks.reject(db, get_settings(), ask, user, payload.reason)
    except service_asks.AskError as exc:
        await db.rollback()
        raise _error(exc) from exc
    return await _view(db, user, ask)
