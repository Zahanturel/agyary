"""The location picker's address search, made by our server on OpenStreetMap's
Nominatim (services/place_search.py, api/routes/places.py). No real request
leaves the building: the HTTP client is replaced by one that answers here."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import update

from agyary.models import User
from agyary.services import place_search
from tests.conftest import sign_in

MOBED = "+919800000002"
NEW = "+919911100066"

ANSWER = [
    {"name": "Banaji Atash Behram", "display_name": "Banaji Atash Behram, Charni Road, Mumbai, India",
     "lat": "18.9535", "lon": "72.8185"},
    {"name": "", "display_name": "Charni Road, Girgaon, Mumbai, Maharashtra, India", "lat": "18.95", "lon": "72.82"},
    {"name": "Broken", "display_name": "Broken", "lat": "north", "lon": "72.8"},
    {"name": "Off the globe", "display_name": "x", "lat": "95", "lon": "72.8"},
]


class FakeNominatim:
    """Answers like Nominatim and remembers what it was asked."""

    def __init__(self, status=200, body=None, fail=None):
        self.status, self.body, self.fail = status, ANSWER if body is None else body, fail
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            raise self.fail
        content = self.body if isinstance(self.body, (bytes, str)) else json.dumps(self.body)
        return httpx.Response(self.status, content=content)


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def osm(monkeypatch):
    place_search.reset()
    fake, clock = FakeNominatim(), FakeClock()
    monkeypatch.setattr(place_search, "_new_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    monkeypatch.setattr(place_search, "_clock", clock)
    monkeypatch.setattr(place_search, "_sleep", clock.sleep)
    yield fake, clock
    place_search.reset()


async def _headers(client, phone=MOBED, *, approve=True) -> dict:
    body = await sign_in(client, phone, "Er. Test Mobed", approve=approve)
    return {"Authorization": f"Bearer {body['access_token']}"}


async def _search(client, headers, q="Charni Road Mumbai"):
    return await client.get("/api/mobed/places/search", params={"q": q}, headers=headers)


async def test_it_finds_places_and_names_the_app_to_openstreetmap(client, seeded, osm):
    fake, _ = osm
    headers = await _headers(client)
    r = await _search(client, headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "openstreetmap"
    # The two good ones; a place with no usable position is dropped.
    assert body["results"] == [
        {"name": "Banaji Atash Behram", "address": "Banaji Atash Behram, Charni Road, Mumbai, India",
         "latitude": 18.9535, "longitude": 72.8185},
        {"name": "Charni Road", "address": "Charni Road, Girgaon, Mumbai, Maharashtra, India",
         "latitude": 18.95, "longitude": 72.82},
    ]
    (req,) = fake.requests
    assert req.url.host == "nominatim.openstreetmap.org" and req.url.path == "/search"
    assert req.url.params["q"] == "Charni Road Mumbai"
    assert req.url.params["format"] == "jsonv2" and req.url.params["limit"] == "5"
    assert req.headers["user-agent"].startswith("MobedDiary/")
    # Nothing about the mobed goes with it.
    assert MOBED.lstrip("+") not in str(req.url) and "authorization" not in req.headers


async def test_never_more_than_five(client, seeded, osm):
    fake, _ = osm
    fake.body = [{"name": f"Place {i}", "display_name": f"Place {i}, Mumbai", "lat": "18.9", "lon": "72.8"}
                 for i in range(12)]
    r = await _search(client, await _headers(client))
    assert len(r.json()["results"]) == 5


async def test_the_same_search_is_asked_once(client, seeded, osm):
    fake, _ = osm
    headers = await _headers(client)
    first = await _search(client, headers, "Charni Road Mumbai")
    second = await _search(client, headers, "  charni   ROAD mumbai ")
    assert first.json() == second.json() and len(fake.requests) == 1


async def test_the_whole_app_asks_at_most_once_a_second(client, seeded, osm):
    fake, clock = osm
    headers = await _headers(client)
    await _search(client, headers, "Charni Road")
    await _search(client, headers, "Tardeo")
    await _search(client, headers, "Navsari")
    assert len(fake.requests) == 3
    assert clock.slept == [pytest.approx(1.0), pytest.approx(1.0)]


async def test_a_search_waiting_too_long_for_its_turn_is_told_to_try_again(client, seeded, osm, monkeypatch):
    monkeypatch.setattr(place_search, "QUEUE_WAIT_SECONDS", 0.01)
    headers = await _headers(client)
    turn = place_search._turn()
    await turn.acquire()
    try:
        r = await _search(client, headers)
    finally:
        turn.release()
    assert r.status_code == 503 and r.json()["detail"] == place_search.BUSY


@pytest.mark.parametrize("q", ["", " ", "a", "x" * 201, "Mumbai\x00"])
async def test_nothing_sensible_to_search_is_not_sent(client, seeded, osm, q):
    fake, _ = osm
    r = await _search(client, await _headers(client), q)
    assert r.status_code == 400 and r.json()["detail"] == "Please type an address or area to search for."
    assert fake.requests == []


async def test_one_mobed_cannot_hammer_it(client, seeded, osm):
    headers = await _headers(client)
    codes = [(await _search(client, headers, f"Place {i}")).status_code for i in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


@pytest.mark.parametrize("fake_kwargs", [
    {"status": 503}, {"status": 429}, {"status": 200, "body": "<html>"},
    {"fail": httpx.ConnectTimeout("slow")}, {"fail": httpx.ConnectError("down")},
])
async def test_when_openstreetmap_fails_the_mobed_is_told_plainly(client, seeded, osm, fake_kwargs):
    fake, _ = osm
    for k, v in fake_kwargs.items():
        setattr(fake, k, v)
    r = await _search(client, await _headers(client))
    assert r.status_code == 503
    assert r.json()["detail"] == place_search.UNAVAILABLE


async def test_signed_in_only(client, seeded, osm):
    fake, _ = osm
    assert (await client.get("/api/mobed/places/search", params={"q": "Mumbai"})).status_code == 401
    assert fake.requests == []


async def test_a_mobed_still_signing_up_may_search_but_one_switched_off_may_not(client, db, seeded, osm):
    # Adding their fire temple, with its pin, is part of signing up.
    waiting = await _headers(client, NEW, approve=False)
    assert (await _search(client, waiting)).status_code == 200

    headers = await _headers(client)
    await db.execute(update(User).where(User.phone == MOBED).values(access="off"))
    await db.commit()
    r = await _search(client, headers, "Tardeo")
    assert r.status_code == 403 and r.headers["X-Mobed-Access"] == "off"


async def test_answers_are_kept_only_a_while(osm):
    fake, clock = osm
    from agyary.core.config import get_settings

    await place_search.nominatim(get_settings(), "Tardeo")
    clock.now += place_search.CACHE_SECONDS + 1
    await place_search.nominatim(get_settings(), "Tardeo")
    assert len(fake.requests) == 2
    # And the cache cannot grow without end.
    for i in range(place_search.CACHE_MAX + 20):
        place_search._remember(f"osm:{i}", [])
    assert len(place_search._cache) == place_search.CACHE_MAX
