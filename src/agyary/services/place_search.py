"""Finding a place for a fire temple's pin: an address or area on OpenStreetMap.

The location picker's search box. The phone never talks to the search service
itself: it asks our server, which asks OpenStreetMap's Nominatim. That keeps
Nominatim's usage policy in our hands - one request a second at most from the
whole app, an honest User-Agent naming the app, answers kept a while so the
same search is not sent twice, and no searching as someone types (the picker
searches when the mobed taps Search) - and it means a mobed's phone and address
are never handed to a third party by the page.

Per-mobed limits are the route's job (api/routes/places.py).
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict, dataclass

import httpx

from agyary.core.config import Settings

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
MAX_RESULTS = 5
QUERY_MIN, QUERY_MAX = 2, 200
# Nominatim's policy: an absolute maximum of one request per second, app-wide.
NOMINATIM_GAP_SECONDS = 1.0
# How long a search waits for its turn before the mobed is asked to try again.
QUEUE_WAIT_SECONDS = 8.0
CACHE_SECONDS = 600
CACHE_MAX = 500
TIMEOUT_SECONDS = 8.0

UNAVAILABLE = ("The address search is not answering just now. Please try again in a minute, "
               "or move the pin on the map yourself.")
BUSY = "The address search is busy. Please try again in a moment."


class SearchUnavailable(Exception):
    """The search could not be made. The message is for the mobed."""


@dataclass(frozen=True)
class Place:
    name: str
    address: str
    latitude: float
    longitude: float


# Swapped by the tests: the clock, the wait and the HTTP client.
_clock = time.monotonic
_sleep = asyncio.sleep


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_SECONDS)


_cache: dict[str, tuple[float, list[dict]]] = {}
_nominatim_turn: asyncio.Lock | None = None
_nominatim_last = -math.inf


def reset() -> None:
    """Forget the cache and the last call (tests)."""
    global _nominatim_turn, _nominatim_last
    _cache.clear()
    _nominatim_turn = None
    _nominatim_last = -math.inf


def clean_query(raw: str) -> str | None:
    """The search as it is sent, or None when there is nothing sensible to send."""
    q = " ".join((raw or "").split())
    if not (QUERY_MIN <= len(q) <= QUERY_MAX) or any(ord(c) < 32 for c in q):
        return None
    return q


def _cached(key: str) -> list[dict] | None:
    hit = _cache.get(key)
    if hit is None:
        return None
    if hit[0] < _clock():
        _cache.pop(key, None)
        return None
    return hit[1]


def _remember(key: str, places: list[dict]) -> None:
    if len(_cache) >= CACHE_MAX:
        # The oldest goes first (dicts keep insertion order).
        _cache.pop(next(iter(_cache)))
    _cache[key] = (_clock() + CACHE_SECONDS, places)


def _place(name: str, address: str, lat: object, lon: object) -> Place | None:
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError, OverflowError):
        return None
    if not (math.isfinite(lat_f) and math.isfinite(lon_f) and -90 <= lat_f <= 90 and -180 <= lon_f <= 180):
        return None
    address = (address or "").strip()[:300]
    name = (name or "").strip()[:120] or address.split(",")[0].strip()
    if not name:
        return None
    return Place(name=name, address=address, latitude=round(lat_f, 6), longitude=round(lon_f, 6))


def _turn() -> asyncio.Lock:
    global _nominatim_turn
    if _nominatim_turn is None:
        _nominatim_turn = asyncio.Lock()
    return _nominatim_turn


async def nominatim(settings: Settings, query: str) -> list[dict]:
    """Up to five places on OpenStreetMap matching ``query`` (already cleaned),
    each {name, address, latitude, longitude}. Raises SearchUnavailable."""
    global _nominatim_last
    key = "osm:" + query.lower()
    hit = _cached(key)
    if hit is not None:
        return hit
    turn = _turn()
    try:
        await asyncio.wait_for(turn.acquire(), timeout=QUEUE_WAIT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise SearchUnavailable(BUSY) from exc
    try:
        # Someone ahead in the queue may just have asked the same thing.
        hit = _cached(key)
        if hit is not None:
            return hit
        wait = _nominatim_last + NOMINATIM_GAP_SECONDS - _clock()
        if wait > 0:
            await _sleep(wait)
        try:
            async with _new_client() as client:
                resp = await client.get(
                    NOMINATIM_URL,
                    params={"q": query, "format": "jsonv2", "limit": MAX_RESULTS, "addressdetails": 0},
                    headers={"User-Agent": settings.place_search_user_agent, "Accept-Language": "en"},
                )
        except httpx.HTTPError as exc:
            logger.warning("Address search failed: %s", exc.__class__.__name__)
            raise SearchUnavailable(UNAVAILABLE) from exc
        finally:
            _nominatim_last = _clock()
    finally:
        turn.release()

    if resp.status_code != 200:
        logger.warning("Address search answered %s", resp.status_code)
        raise SearchUnavailable(UNAVAILABLE)
    try:
        items = resp.json()
    except ValueError as exc:
        logger.warning("Address search answered something that is not JSON")
        raise SearchUnavailable(UNAVAILABLE) from exc
    places: list[dict] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        p = _place(str(item.get("name") or ""), str(item.get("display_name") or ""), item.get("lat"), item.get("lon"))
        # OpenStreetMap can list one place twice (a building and its entrance).
        if p and asdict(p) not in places:
            places.append(asdict(p))
        if len(places) == MAX_RESULTS:
            break
    _remember(key, places)
    return places
