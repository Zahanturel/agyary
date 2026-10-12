"""Reminders and the mobed's in-app notifications: the HTTP layer.

The rules are in services/reminders.py. Everything here is the signed-in
mobed's own - their behdins, their notifications.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api.routes.mobed import _require_behdin, get_current_user
from agyary.core.database import get_db
from agyary.models import AppNotification, User
from agyary.services import reminders

router = APIRouter(prefix="/api/mobed", tags=["reminders"])


class RemindersIn(BaseModel):
    enabled: bool
    # Needed only to turn reminders back on for someone who replied STOP.
    confirm_restart: bool = False


@router.put("/agyaries/{agyary_id}/behdins/{customer_id}/reminders")
async def set_behdin_reminders(
    agyary_id: int,
    customer_id: int,
    payload: RemindersIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Turn WhatsApp reminders on or off for one of this mobed's behdins.

    Turning them on records that the behdin agreed, in person, to this mobed.
    409 when the behdin has replied STOP and ``confirm_restart`` is not set.
    """
    customer = await _require_behdin(db, agyary_id, customer_id, user)
    try:
        state = await reminders.set_reminders(
            db, user.id, customer, payload.enabled, confirm_restart=payload.confirm_restart
        )
    except reminders.ReminderError as exc:
        status = 409 if exc.code == "stopped" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    await db.commit()
    return state


def _serialize(note: AppNotification) -> dict:
    return {
        "id": note.id,
        "kind": note.kind,
        "title": note.title,
        "body": note.body,
        "link": note.link,
        "created_at": note.created_at.isoformat(),
        "expires_at": note.expires_at.isoformat(),
        "seen": note.seen_at is not None,
    }


@router.get("/notifications")
async def list_notifications(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    """This mobed's notifications that have not yet lapsed, newest first.
    ``seen`` is whether the popup has already shown it."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(AppNotification)
            .where(AppNotification.user_id == user.id, AppNotification.expires_at > now)
            .order_by(AppNotification.created_at.desc(), AppNotification.id.desc())
        )
    ).scalars().all()
    return [_serialize(n) for n in rows]


class SeenIn(BaseModel):
    # Left out, every notification the mobed has is marked seen.
    ids: list[int] | None = None


@router.post("/notifications/seen")
async def mark_notifications_seen(
    payload: SeenIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """The popup has shown these; do not show them again on the next open."""
    stmt = (
        update(AppNotification)
        .where(AppNotification.user_id == user.id, AppNotification.seen_at.is_(None))
        .values(seen_at=datetime.now(timezone.utc))
    )
    if payload.ids is not None:
        stmt = stmt.where(AppNotification.id.in_(payload.ids))
    result = await db.execute(stmt)
    await db.commit()
    return {"marked": result.rowcount}
