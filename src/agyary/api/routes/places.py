"""Finding a place on the map for a fire temple's pin (DECISIONS D10).

The location picker's searches, made by our server on the phone's behalf
(services/place_search.py). Signed in only, and not for an account that is
switched off; a mobed still signing up may search, because adding their fire
temple is part of signing up. Each mobed is limited, and the whole app keeps
to OpenStreetMap's one request a second.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from agyary.api import rate_limit
from agyary.api.routes.mobed import get_user_not_switched_off
from agyary.core.config import get_settings
from agyary.models import User
from agyary.services import place_search

router = APIRouter(prefix="/api/mobed/places", tags=["places"])

SEARCH_PER_MINUTE = 10
SEARCH_PER_DAY = 200

NOTHING_TO_SEARCH = "Please type an address or area to search for."


def _query(q: str) -> str:
    cleaned = place_search.clean_query(q)
    if cleaned is None:
        raise HTTPException(status_code=400, detail=NOTHING_TO_SEARCH)
    return cleaned


@router.get("/search")
async def search_address(q: str = Query(default=""), user: User = Depends(get_user_not_switched_off)) -> dict:
    """Up to five places on OpenStreetMap for an address or area."""
    query = _query(q)
    rate_limit.enforce_key(f"place_search:{user.id}", max_requests=SEARCH_PER_MINUTE, window_seconds=60)
    rate_limit.enforce_key(f"place_search_day:{user.id}", max_requests=SEARCH_PER_DAY, window_seconds=86400)
    try:
        results = await place_search.nominatim(get_settings(), query)
    except place_search.SearchUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"source": "openstreetmap", "results": results}
