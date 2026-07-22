"""Web-chat transport adapter: the thinnest possible wrapper around
handle_message, used by the browser-based WhatsApp simulator."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.database import get_db
from agyary.messaging import handle_message
from agyary.models import Agyary, AgyaryUser, User
from agyary.models.enums import ADMIN_ROLES

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessageIn(BaseModel):
    agyary_id: int
    phone_number: str = Field(min_length=5, max_length=20)
    text: str = Field(min_length=1, max_length=4096)


@router.post("/messages")
async def post_message(payload: ChatMessageIn, db: AsyncSession = Depends(get_db)) -> dict:
    agyary = await db.get(Agyary, payload.agyary_id)
    if agyary is None or not agyary.is_active:
        raise HTTPException(status_code=404, detail="Unknown agyary")
    messages = await handle_message(db, payload.agyary_id, payload.phone_number, payload.text)
    return {"messages": [m.as_dict() for m in messages]}


@router.get("/agyaries")
async def list_agyaries(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Agyaries + their admin phones, so the simulator can set up its panes."""
    agyaries = (
        (await db.execute(select(Agyary).where(Agyary.is_active.is_(True)))).scalars().all()
    )
    result = []
    for agyary in agyaries:
        admins = (
            await db.execute(
                select(User)
                .join(AgyaryUser, AgyaryUser.user_id == User.id)
                .where(
                    AgyaryUser.agyary_id == agyary.id,
                    AgyaryUser.role.in_(ADMIN_ROLES),
                    AgyaryUser.is_active.is_(True),
                    User.is_active.is_(True),
                )
            )
        ).scalars()
        result.append(
            {
                "id": agyary.id,
                "name": agyary.name,
                "city": agyary.city,
                "calendar_system": agyary.calendar_system,
                "admins": [{"name": u.name, "phone": u.phone} for u in admins],
            }
        )
    return result
