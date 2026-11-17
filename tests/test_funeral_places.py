"""Doongerwadis, prayer halls and aramgahs on the admin side (DECISIONS D10).

Only an admin adds or changes a funeral place; a mobed gets the same 404 as
for any admin page. A place is turned off, never deleted (D8).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agyary.core import config
from agyary.models import FuneralPlace
from tests.conftest import sign_in

BASE = "/api/mobed/admin/funeral-places"
DOONGERWADI = {
    "name": "Doongerwadi (test)", "kind": "doongerwadi", "city": "Mumbai",
    "address": "Test Road", "run_by": "A test punchayet",
    "location": {"latitude": 18.9567, "longitude": 72.8051},
}
HALL = {"name": "Prayer hall (test)", "kind": "prayer_hall", "city": "Mumbai"}


@pytest.fixture
def admin_is_panthaky(monkeypatch, seeded):
    monkeypatch.setenv("ADMIN_PHONES", seeded["panthaky_phone"])
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def _as(client, phone) -> dict:
    body = await sign_in(client, phone)
    return {"Authorization": f"Bearer {body['access_token']}"}


async def test_the_admin_adds_lists_and_changes_funeral_places(client, db, seeded, admin_is_panthaky):
    admin = await _as(client, seeded["panthaky_phone"])
    r = await client.post(BASE, json=DOONGERWADI, headers=admin)
    assert r.status_code == 200, r.text
    place = r.json()
    assert place | {"id": None} == {
        "id": None, "name": "Doongerwadi (test)", "kind": "doongerwadi", "kind_label": "Doongerwadi",
        "city": "Mumbai", "address": "Test Road", "run_by": "A test punchayet",
        "location": {"latitude": 18.9567, "longitude": 72.8051}, "is_active": True,
    }
    hall = (await client.post(BASE, json=HALL, headers=admin)).json()
    assert hall["location"] is None and hall["run_by"] is None and hall["kind_label"] == "Prayer hall"

    row = (await db.execute(select(FuneralPlace).where(FuneralPlace.id == place["id"]))).scalar_one()
    admin_id = (await client.get("/api/mobed/auth/me", headers=admin)).json()["id"]
    assert row.created_by_user_id == admin_id

    listed = (await client.get(BASE, headers=admin)).json()["places"]
    assert [p["name"] for p in listed] == ["Doongerwadi (test)", "Prayer hall (test)"]
    assert listed[0]["managers"] == {"on": 0, "pending": 0, "off": 0}

    # Edited, pin moved, then the pin taken off.
    changed = {**DOONGERWADI, "name": "Doongerwadi, Malabar Hill (test)", "location": {"latitude": 18.95, "longitude": 72.80}}
    r = await client.put(f"{BASE}/{place['id']}", json=changed, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Doongerwadi, Malabar Hill (test)" and r.json()["location"] == {"latitude": 18.95, "longitude": 72.8}
    r = await client.put(f"{BASE}/{place['id']}", json={**changed, "location": None}, headers=admin)
    assert r.json()["location"] is None
    assert (await client.get(f"{BASE}/{place['id']}", headers=admin)).json()["name"] == "Doongerwadi, Malabar Hill (test)"


async def test_a_place_is_turned_off_and_on_never_deleted(client, db, seeded, admin_is_panthaky):
    admin = await _as(client, seeded["panthaky_phone"])
    place = (await client.post(BASE, json=HALL, headers=admin)).json()
    r = await client.post(f"{BASE}/{place['id']}/active", json={"active": False}, headers=admin)
    assert r.status_code == 200 and r.json()["is_active"] is False
    # Still there, listed after the ones in use.
    other = (await client.post(BASE, json=DOONGERWADI, headers=admin)).json()
    assert [p["id"] for p in (await client.get(BASE, headers=admin)).json()["places"]] == [other["id"], place["id"]]
    assert (await client.delete(f"{BASE}/{place['id']}", headers=admin)).status_code == 405
    r = await client.post(f"{BASE}/{place['id']}/active", json={"active": True}, headers=admin)
    assert r.json()["is_active"] is True
    assert (await db.execute(select(FuneralPlace))).scalars().all().__len__() == 2


@pytest.mark.parametrize("change, message", [
    ({"name": "  "}, "Please enter the place's name and town."),
    ({"city": ""}, "Please enter the place's name and town."),
    ({"name": "Call 9820012345"}, "The place's name cannot contain a phone number or a long number."),
    ({"name": "See www.example.com"}, "The place's name cannot contain a link or web address."),
    ({"location": {"latitude": 0, "longitude": 0}}, "That place is not on the map. Please put the pin on the place."),
    ({"location": {"latitude": 95, "longitude": 72.8}}, "That place is not on the map. Please put the pin on the place."),
    ({"location": {"latitude": "18.9", "longitude": 72.8}}, "That place is not on the map. Please put the pin on the place."),
])
async def test_what_cannot_be_saved_is_said_in_plain_words(client, db, seeded, admin_is_panthaky, change, message):
    admin = await _as(client, seeded["panthaky_phone"])
    r = await client.post(BASE, json={**DOONGERWADI, **change}, headers=admin)
    assert r.status_code == 400 and r.json()["detail"] == message
    assert (await db.execute(select(FuneralPlace))).first() is None


async def test_only_the_three_kinds(client, db, seeded, admin_is_panthaky):
    admin = await _as(client, seeded["panthaky_phone"])
    assert (await client.post(BASE, json={**HALL, "kind": "crematorium"}, headers=admin)).status_code == 422


async def test_a_mobed_who_is_not_an_admin_gets_a_404_for_every_funeral_place_page(client, db, seeded, admin_is_panthaky):
    admin = await _as(client, seeded["panthaky_phone"])
    place = (await client.post(BASE, json=HALL, headers=admin)).json()
    mobed = await _as(client, seeded["mobed_phone"])
    calls = [
        ("GET", BASE, None), ("POST", BASE, HALL), ("GET", f"{BASE}/{place['id']}", None),
        ("PUT", f"{BASE}/{place['id']}", HALL), ("POST", f"{BASE}/{place['id']}/active", {"active": False}),
    ]
    for method, path, body in calls:
        r = await client.request(method, path, json=body, headers=mobed)
        assert r.status_code == 404 and r.json()["detail"] == "Not found", (method, path)
        assert (await client.request(method, path, json=body)).status_code == 401, (method, path)
    assert (await db.execute(select(FuneralPlace.is_active))).scalars().all() == [True]
