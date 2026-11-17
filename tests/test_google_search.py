""""Find on Google" (Google Places API (New) Text Search), made by our server
with the owner's key (services/place_search.py, api/routes/places.py).

No real request leaves the building, and no real key exists here: the HTTP
client is replaced by one that answers like Google.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest
from sqlalchemy import update

from agyary.core import config
from agyary.models import User
from agyary.services import place_search
from tests.conftest import sign_in

MOBED = "+919800000002"
NEW = "+919911100066"
KEY = "test-google-key-NOT-REAL-7f3a9c"

ANSWER = {"places": [
    {"id": "abc", "displayName": {"text": "Banaji Atash Behram", "languageCode": "en"},
     "formattedAddress": "Charni Road, Girgaon, Mumbai, Maharashtra 400004, India",
     "location": {"latitude": 18.9535, "longitude": 72.8185}},
    {"id": "def", "displayName": {"text": "Wadia Atash Behram"},
     "formattedAddress": "Dhobi Talao, Mumbai", "location": {"latitude": 18.946, "longitude": 72.829}},
    {"id": "bad", "displayName": {"text": "Nowhere"}, "formattedAddress": "x", "location": {}},
]}


class FakeGoogle:
    def __init__(self):
        self.status, self.body, self.fail = 200, ANSWER, None
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            raise self.fail
        return httpx.Response(self.status, content=self.body if isinstance(self.body, str) else json.dumps(self.body))


@pytest.fixture
def google(monkeypatch):
    """Google set up with a (made-up) key, and answering here."""
    place_search.reset()
    fake = FakeGoogle()
    monkeypatch.setattr(place_search, "_new_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", KEY)
    config.get_settings.cache_clear()
    yield fake
    config.get_settings.cache_clear()
    place_search.reset()


@pytest.fixture
def no_google(monkeypatch):
    place_search.reset()
    fake = FakeGoogle()
    monkeypatch.setattr(place_search, "_new_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "")
    config.get_settings.cache_clear()
    yield fake
    config.get_settings.cache_clear()


async def _headers(client, phone=MOBED, *, approve=True) -> dict:
    body = await sign_in(client, phone, "Er. Test Mobed", approve=approve)
    return {"Authorization": f"Bearer {body['access_token']}"}


async def _find(client, headers, q="Banaji Atash Behram Mumbai"):
    return await client.get("/api/mobed/places/google", params={"q": q}, headers=headers)


async def test_without_a_key_there_is_no_google_and_nothing_is_sent(client, seeded, no_google):
    headers = await _headers(client)
    assert (await client.get("/api/mobed/places/options", headers=headers)).json() == {"google": False}
    r = await _find(client, headers)
    assert r.status_code == 404
    assert no_google.requests == []


async def test_with_a_key_the_app_is_told_google_is_there_but_never_the_key(client, seeded, google):
    headers = await _headers(client)
    r = await client.get("/api/mobed/places/options", headers=headers)
    assert r.json() == {"google": True} and KEY not in r.text
    me = await client.get("/api/mobed/auth/me", headers=headers)
    assert KEY not in me.text


async def test_it_asks_google_for_only_four_fields_with_the_key_in_a_header(client, seeded, google, caplog):
    caplog.set_level(logging.DEBUG)
    headers = await _headers(client)
    r = await _find(client, headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"source": "google", "results": [
        {"name": "Banaji Atash Behram", "address": "Charni Road, Girgaon, Mumbai, Maharashtra 400004, India",
         "latitude": 18.9535, "longitude": 72.8185},
        {"name": "Wadia Atash Behram", "address": "Dhobi Talao, Mumbai", "latitude": 18.946, "longitude": 72.829},
    ]}
    assert KEY not in r.text
    (req,) = google.requests
    assert str(req.url) == "https://places.googleapis.com/v1/places:searchText"
    assert req.method == "POST"
    assert req.headers["x-goog-api-key"] == KEY
    assert req.headers["x-goog-fieldmask"] == "places.id,places.displayName,places.formattedAddress,places.location"
    assert json.loads(req.content) == {"textQuery": "Banaji Atash Behram Mumbai", "pageSize": 5, "languageCode": "en"}
    # The key is in no URL and no log line.
    assert KEY not in str(req.url)
    assert KEY not in caplog.text


async def test_the_key_never_shows_in_the_settings_or_a_failure(client, seeded, google, caplog):
    caplog.set_level(logging.DEBUG)
    assert KEY not in repr(config.get_settings()) and KEY not in str(config.get_settings())
    google.status, google.body = 403, {"error": {"message": f"API key {KEY} not valid", "status": "PERMISSION_DENIED"}}
    r = await _find(client, await _headers(client))
    assert r.status_code == 503 and r.json()["detail"] == place_search.GOOGLE_UNAVAILABLE
    assert KEY not in r.text and KEY not in caplog.text
    assert "Find on Google answered 403" in caplog.text


@pytest.mark.parametrize("fail", [httpx.ConnectTimeout("slow"), httpx.ConnectError("down")])
async def test_google_unreachable_is_said_plainly(client, seeded, google, fail, caplog):
    google.fail = fail
    r = await _find(client, await _headers(client))
    assert r.status_code == 503 and r.json()["detail"] == place_search.GOOGLE_UNAVAILABLE
    assert KEY not in caplog.text


async def test_nothing_found_is_an_empty_list(client, seeded, google):
    google.body = {}
    r = await _find(client, await _headers(client))
    assert r.status_code == 200 and r.json()["results"] == []


async def test_one_mobed_is_limited(client, seeded, google):
    headers = await _headers(client)
    codes = [(await _find(client, headers, f"Agyari {i}")).status_code for i in range(6)]
    assert codes == [200] * 5 + [429]


async def test_the_whole_app_stops_at_its_daily_ceiling(client, seeded, google, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_DAILY_CAP", "2")
    config.get_settings.cache_clear()
    first = await _headers(client)
    other = await _headers(client, NEW)
    assert (await _find(client, first, "Agyari one")).status_code == 200
    assert (await _find(client, other, "Agyari two")).status_code == 200
    # A search already made is answered from the short cache and costs nothing.
    assert (await _find(client, other, "agyari ONE")).status_code == 200
    r = await _find(client, other, "Agyari three")
    assert r.status_code == 429 and r.json()["detail"] == place_search.GOOGLE_CAP_REACHED
    assert len(google.requests) == 2


async def test_signed_in_only_and_not_switched_off(client, db, seeded, google):
    assert (await client.get("/api/mobed/places/google", params={"q": "Banaji"})).status_code == 401
    assert (await client.get("/api/mobed/places/options")).status_code == 401
    # Someone still signing up may use it to find the fire temple they are adding.
    waiting = await _headers(client, NEW, approve=False)
    assert (await _find(client, waiting)).status_code == 200
    headers = await _headers(client)
    await db.execute(update(User).where(User.phone == MOBED).values(access="off"))
    await db.commit()
    r = await _find(client, headers, "Wadia")
    assert r.status_code == 403 and r.headers["X-Mobed-Access"] == "off"
    assert len(google.requests) == 1


async def test_nothing_sensible_to_find_is_not_sent(client, seeded, google):
    r = await _find(client, await _headers(client), " ")
    assert r.status_code == 400 and google.requests == []


def test_the_button_is_shown_only_when_the_server_says_so():
    picker = (Path(__file__).parent.parent / "src" / "agyary" / "api" / "static" / "mobed" / "js"
              / "location_picker.js").read_text(encoding="utf-8")
    assert 'id="lpGoogle">Find on Google</button>' in picker and 'class="secondary small hidden" id="lpGoogle"' in picker
    assert "googleBtn.classList.remove(\"hidden\")" in picker
    assert "googleapis" not in picker
