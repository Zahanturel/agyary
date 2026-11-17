"""Sending a funeral record to a fire temple (DECISIONS D10, Phase 2 Step 4).

Choosing the fire temple: "Suggested" lists every fire temple in the app with a
position, nearest first by straight-line distance from the funeral place,
within NEAR_KM; the family's preferred one goes first whatever its distance.
"Search all" finds any of them by name or town. Each says whether a request
would reach anyone: a confirmed panthaky, only mobeds, or nobody in the app yet
(services/panthaky.py, the same rule as who it is sent to).
"""

from __future__ import annotations

import logging
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import Agyary, FuneralPlace
from agyary.services import mobed_dashboard, panthaky

logger = logging.getLogger(__name__)

NEAR_KM = 500
MAX_SUGGESTED = 100
SEARCH_LIMIT = 20
EARTH_RADIUS_KM = 6371.0


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line (great-circle) distance in km, by the haversine formula."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _has_position(x) -> bool:
    return x is not None and x.latitude is not None and x.longitude is not None


def _distance(place: FuneralPlace, agyary: Agyary) -> float | None:
    if not (_has_position(place) and _has_position(agyary)):
        return None
    return km(place.latitude, place.longitude, agyary.latitude, agyary.longitude)


async def _rows(
    db: AsyncSession, settings: Settings, place: FuneralPlace, agyaries: list[Agyary], preferred_id: int | None,
) -> list[dict]:
    reach = await panthaky.reach_of(db, settings, [a.id for a in agyaries])
    out = []
    for a in agyaries:
        d = _distance(place, a)
        out.append({
            "id": a.id, "name": a.name, "city": a.city, "address": a.address,
            "km": round(d, 1) if d is not None else None,
            # "town": only the town's position is known yet, so the distance is rough.
            "location_source": a.location_source,
            "reach": reach[a.id],
            "may_send": reach[a.id] != panthaky.REACH_NOBODY,
            "preferred": a.id == preferred_id,
        })
    return out


async def suggested(
    db: AsyncSession, settings: Settings, place: FuneralPlace, preferred_id: int | None = None,
) -> dict:
    """The fire temples to suggest for a record at ``place``: the family's
    preferred one first, then those within NEAR_KM, nearest first. With no
    position for the place there is nothing to measure from: only the
    preferred one, and ``place_has_position`` False (the app offers search)."""
    chosen: list[tuple[float, Agyary]] = []
    if _has_position(place):
        candidates = (
            await db.execute(
                select(Agyary).where(
                    Agyary.is_active.is_(True), Agyary.latitude.is_not(None), Agyary.longitude.is_not(None)
                )
            )
        ).scalars().all()
        for a in candidates:
            d = _distance(place, a)
            if d is not None and d <= NEAR_KM and a.id != preferred_id:
                chosen.append((d, a))
        chosen.sort(key=lambda pair: (pair[0], pair[1].name))
    agyaries = [a for _, a in chosen[:MAX_SUGGESTED]]
    if preferred_id is not None:
        preferred = await db.get(Agyary, preferred_id)
        if preferred is not None and preferred.is_active:
            agyaries.insert(0, preferred)
    return {
        "place_has_position": _has_position(place),
        "near_km": NEAR_KM,
        "agyaries": await _rows(db, settings, place, agyaries, preferred_id),
    }


async def search(
    db: AsyncSession, settings: Settings, place: FuneralPlace, q: str, preferred_id: int | None = None,
) -> list[dict]:
    """Any fire temple in the app by name or town (the sign-up search), with
    its distance from ``place`` where both have a position."""
    found = await mobed_dashboard.search_agyaries(db, q[:100], limit=SEARCH_LIMIT)
    return await _rows(db, settings, place, found, preferred_id)
