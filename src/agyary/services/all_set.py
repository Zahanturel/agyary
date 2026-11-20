"""All set: a request whose places are all filled (DECISIONS D10, changed 21 Nov
2026; docs/phase2-requests-redesign.md, "All set"; R3.1).

When the last place on a request's "Who will pray" board fills - by a WhatsApp
Yes, an "I can pray" in the app, the panthaky's "I'll pray", or a mobed marked
Going after a call - services/prayer_callout.py's ``fill`` calls ``on_full``.
Only a request still waiting becomes all set: one accepted the old way before
R3.1 keeps its state (D8).

Step 4 (now) only marks it: status "all_set", ``all_set_at``, and
``decided_at`` (which every request that is no longer waiting has). Safe to
call twice, or from two places at once: a conditional update does it once.

Step 5 adds the rest here, once, for the call that made it all set: the family
into the panthaky's and each praying app mobed's own book (D2, reminders off,
D4) through the accept code, the Geh-saarnu and Uthamna on each one's calendar,
the memorial one tap away, the notices and phone notifications, the WhatsApp
templates 5-8 behind FUNERAL_WHATSAPP_MODE, and the "still short" timer.
Until then nobody is given the family's contact at All set either.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import FuneralRequest
from agyary.models.enums import REQUEST_ALL_SET, REQUEST_WAITING

logger = logging.getLogger(__name__)


async def on_full(
    db: AsyncSession, settings: Settings, request: FuneralRequest, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """The request's places are all filled: mark it all set, once. Commits.
    Returns whether this call made it all set (False if it already was, or
    is no longer waiting)."""
    now = now or datetime.now(timezone.utc)
    done = (await db.execute(
        update(FuneralRequest)
        .where(FuneralRequest.id == request.id, FuneralRequest.status == REQUEST_WAITING)
        .values(status=REQUEST_ALL_SET, all_set_at=now, decided_at=now)
        .returning(FuneralRequest.id)
    )).scalar_one_or_none()
    await db.commit()
    await db.refresh(request)
    if done is None:
        return False
    logger.warning("Funeral request %s is all set at fire temple %s", request.id, request.agyary_id)
    return True
