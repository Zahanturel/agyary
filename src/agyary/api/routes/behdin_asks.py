"""Asking an agyari for a service, from the Parsi app (R4.2; docs/behdin-r4-2-design.md).

Every route is built on ``get_current_person`` and every row is scoped to that account: someone
else's ask id is a 404, like an id that does not exist. The person's number and full name never
leave here before a panthaky accepts. Nothing a person can read names the other app.
"""

from __future__ import annotations

import datetime as dt
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.api.routes.mobed import get_current_person
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import Agyary, AppNotification, User
from agyary.services import mobed_dashboard, service_asks

router = APIRouter(prefix="/api/behdin", tags=["behdin"])


def _limit(user: User, scope: str, *, per_minute: int) -> None:
    rate_limit.enforce_key(f"behdin_{scope}:{user.id}", max_requests=per_minute, window_seconds=60)


def _read(user: User) -> None:
    _limit(user, "read", per_minute=240)


def _write(user: User) -> None:
    _limit(user, "write", per_minute=90)


def _error(exc: service_asks.AskError) -> HTTPException:
    """A plain message. One written for the other side's screens never reaches a person."""
    text = str(exc)
    if "mobed" in text.lower() or "diary" in text.lower():
        text = "Please check what you entered and try again."
    return HTTPException(status_code=exc.status, detail=text)


async def _own_ask(db: AsyncSession, user: User, ask_id: int):
    ask = await service_asks.get_for_person(db, user.id, ask_id)
    if ask is None:
        raise HTTPException(status_code=404, detail=service_asks.NO_SUCH_ASK)
    return ask


# ---------------------------------------------------------------------------
# What an agyari offers, for the person about to ask
# ---------------------------------------------------------------------------
@router.get("/agyaries/{agyary_id}/asking")
async def agyari_asking(
    agyary_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    """The services, their usual prices and whether this agyari takes asks in the app. Nothing private."""
    _read(user)
    agyary = await db.get(Agyary, agyary_id)
    if agyary is None or not agyary.is_active:
        raise HTTPException(status_code=404, detail=service_asks.NO_SUCH_AGYARI)
    return await service_asks.asking_view(db, get_settings(), agyary)


# ---------------------------------------------------------------------------
# The person's asks
# ---------------------------------------------------------------------------
class AskIn(BaseModel):
    agyary_id: int
    service_id: int
    purpose: str | None = None
    date: dt.date | None = None
    geh: int | None = None
    time: str | None = None
    where: str = "agyari"
    area: str | None = None
    names: list[dict] | None = None
    note: str | None = None
    # {"pattern": "monthly" | "yearly", "count": 2..120 (60 for yearly) or left out}
    repeat: dict | None = None
    # {"memorial_id": the person's own memorial, "codes": the dates they want}
    memorial: dict | None = None


@router.post("/me/asks")
async def create_ask(
    payload: AskIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    _write(user)
    settings = get_settings()
    try:
        ask = await service_asks.create(db, settings, user, payload.model_dump())
        await db.commit()
    except service_asks.AskError as exc:
        await db.rollback()
        raise _error(exc) from exc
    await service_asks.told_new(db, settings, ask)
    return await service_asks.person_view(db, ask, await mobed_dashboard.reading_system(db, user.id))


@router.get("/me/asks")
async def list_asks(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    _read(user)
    return {"asks": await service_asks.list_for_person(db, user.id, await mobed_dashboard.reading_system(db, user.id))}


@router.get("/me/asks/{ask_id}")
async def get_ask(ask_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    _read(user)
    ask = await _own_ask(db, user, ask_id)
    return await service_asks.person_view(db, ask, await mobed_dashboard.reading_system(db, user.id))


@router.post("/me/asks/{ask_id}/cancel")
async def cancel_ask(ask_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    _write(user)
    ask = await _own_ask(db, user, ask_id)
    try:
        await service_asks.cancel(db, get_settings(), ask)
    except service_asks.AskError as exc:
        await db.rollback()
        raise _error(exc) from exc
    return await service_asks.person_view(db, ask, await mobed_dashboard.reading_system(db, user.id))


class AskAnotherIn(BaseModel):
    agyary_id: Any = None


@router.post("/me/asks/{ask_id}/ask-another")
async def ask_another(
    ask_id: int, payload: AskAnotherIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    """Copy an ask that was turned down, cancelled or not answered to another fire temple."""
    _write(user)
    settings = get_settings()
    ask = await _own_ask(db, user, ask_id)
    try:
        new = await service_asks.ask_another(db, settings, user, ask, payload.agyary_id)
        await db.commit()
    except service_asks.AskError as exc:
        await db.rollback()
        raise _error(exc) from exc
    await service_asks.told_new(db, settings, new)
    return await service_asks.person_view(db, new, await mobed_dashboard.reading_system(db, user.id))


# ---------------------------------------------------------------------------
# The person's notices (answers to their asks)
# ---------------------------------------------------------------------------
def _serialize_notice(note: AppNotification) -> dict:
    return {
        "id": note.id, "kind": note.kind, "title": note.title, "body": note.body, "link": note.link,
        "created_at": note.created_at.isoformat(), "expires_at": note.expires_at.isoformat(),
        "seen": note.seen_at is not None,
    }


@router.get("/notifications")
async def list_notifications(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    """The person's own notices that have not lapsed, newest first. Only those of the Parsi app:
    the other app's are told apart by kind and never shown here."""
    _read(user)
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(AppNotification).where(
            AppNotification.user_id == user.id, AppNotification.expires_at > now,
            service_asks.person_notices_clause())
        .order_by(AppNotification.created_at.desc(), AppNotification.id.desc())
    )).scalars().all()
    return {"notifications": [_serialize_notice(n) for n in rows]}


class SeenIn(BaseModel):
    # Left out, every notice the person has is marked read.
    ids: list[int] | None = None


@router.post("/notifications/seen")
async def mark_notifications_seen(
    payload: SeenIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    _write(user)
    stmt = (
        update(AppNotification)
        .where(AppNotification.user_id == user.id, AppNotification.seen_at.is_(None),
               service_asks.person_notices_clause())
        .values(seen_at=datetime.now(timezone.utc))
    )
    if payload.ids is not None:
        stmt = stmt.where(AppNotification.id.in_(payload.ids))
    result = await db.execute(stmt)
    await db.commit()
    return {"marked": result.rowcount}
