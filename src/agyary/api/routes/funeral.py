"""The Doongerwadi side of the app (DECISIONS D10): a funeral place's manager.

A manager's account sees only what is here and what every account has (who
they are, their notices, signing out, deleting the account); every mobed
route refuses it (api/routes/mobed.py, get_signed_in_user). Recording a death
and sending it to a fire temple come in the next steps.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api.routes.mobed import get_current_manager
from agyary.core.database import get_db
from agyary.models import User
from agyary.services import funeral_places

router = APIRouter(prefix="/api/mobed", tags=["funeral"])


@router.get("/manager/place")
async def my_funeral_place(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_manager)) -> dict:
    """The place (or places) this manager works at, for their home screen."""
    return {"places": [funeral_places.summary(p) for p in await funeral_places.places_of(db, user.id)]}
