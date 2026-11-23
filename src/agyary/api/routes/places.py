"""Finding a place on the map for a fire temple's pin (DECISIONS D10).

The location picker's searches, made by our server on the phone's behalf
(services/place_search.py). Signed in only, and not for an account that is
switched off; a mobed still signing up may search, because adding their fire
temple is part of signing up. Each mobed is limited, and the whole app keeps
to OpenStreetMap's one request a second. "Find on Google" is there only when
the server has GOOGLE_PLACES_API_KEY, and the key never leaves the server.
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


# --- "Find on Google" ----------------------------------------------------------
# Each search costs the owner money past Google's free tier, so it is tighter
# than the address search: per mobed here, and for the whole app per day in
# the service (GOOGLE_PLACES_DAILY_CAP), under the quota set in Google Cloud.
GOOGLE_PER_MINUTE = 5
GOOGLE_PER_DAY = 30


@router.get("/options")
async def search_options(user: User = Depends(get_user_not_switched_off)) -> dict:
    """What the picker may offer. Says only whether Google is set up, never the key."""
    return {"google": place_search.google_configured(get_settings())}


@router.get("/google")
async def search_google(q: str = Query(default=""), user: User = Depends(get_user_not_switched_off)) -> dict:
    """Up to five places Google finds by name. Not there at all without a key."""
    settings = get_settings()
    if not place_search.google_configured(settings):
        raise HTTPException(status_code=404, detail="This search is not available.")
    query = _query(q)
    rate_limit.enforce_key(f"google_search:{user.id}", max_requests=GOOGLE_PER_MINUTE, window_seconds=60)
    rate_limit.enforce_key(f"google_search_day:{user.id}", max_requests=GOOGLE_PER_DAY, window_seconds=86400)
    try:
        results = await place_search.google(settings, query)
    except place_search.SearchUnavailable as exc:
        status = 429 if str(exc) == place_search.GOOGLE_CAP_REACHED else 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"source": "google", "results": results}
