"""Where a fire temple is (DECISIONS D10): its mobeds see the position with
their fire temple, and only its approved mobeds and panthaky - or an admin -
can put its pin on the map or move it."""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from agyary.core import config
from agyary.models import Agyary, User
from tests.conftest import sign_in

MOBED = "+919800000002"     # the seeded mobed at Goti Adarian
OTHER = "+919911100055"     # a mobed of another fire temple
NEW = "+919911100066"       # a new sign-up
ADMIN = "+919911100099"

PIN = {"latitude": 18.9655, "longitude": 72.8148}


async def _headers(client, phone, name="Er. Test Mobed", *, approve=True) -> dict:
    body = await sign_in(client, phone, name, approve=approve)
    return {"Authorization": f"Bearer {body['access_token']}"}


async def _other_temple(db) -> Agyary:
    other = Agyary(name="Banaji Atash Behram", city="Mumbai", status="active")
    db.add(other)
    await db.commit()
    return other


@pytest.fixture
def admin_phone(monkeypatch):
    monkeypatch.setenv("ADMIN_PHONES", ADMIN)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def test_a_member_puts_the_pin_on_the_map_and_sees_it_with_their_fire_temple(client, db, seeded):
    headers = await _headers(client, MOBED)
    me = (await client.get("/api/mobed/auth/me", headers=headers)).json()
    assert me["agyaries"][0]["location"] is None

    r = await client.put(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", json=PIN, headers=headers)
    assert r.status_code == 200, r.text
    loc = r.json()["location"]
    assert (loc["latitude"], loc["longitude"], loc["source"]) == (18.9655, 72.8148, "pin")
    assert loc["set_at"]

    me = (await client.get("/api/mobed/auth/me", headers=headers)).json()
    assert me["agyaries"][0]["location"]["source"] == "pin"
    assert (await client.get(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", headers=headers)
            ).json()["location"]["latitude"] == 18.9655

    temple = await db.get(Agyary, seeded["agyary_id"])
    await db.refresh(temple)
    mobed = (await db.execute(select(User).where(User.phone == MOBED))).scalar_one()
    assert temple.location_set_by_user_id == mobed.id and temple.location_set_at is not None


async def test_moving_a_town_position_makes_it_a_pin(client, db, seeded):
    await db.execute(update(Agyary).where(Agyary.id == seeded["agyary_id"]).values(
        latitude=18.94, longitude=72.83, location_source="town"))
    await db.commit()
    headers = await _headers(client, MOBED)
    assert (await client.get("/api/mobed/auth/me", headers=headers)).json()["agyaries"][0]["location"]["source"] == "town"
    r = await client.put(f"/api/mobed/agyaries/{seeded['agyary_id']}/location",
                         json={"latitude": 18.9655123456, "longitude": 72.81481239}, headers=headers)
    assert r.json()["location"] | {"set_at": None} == {
        "latitude": 18.965512, "longitude": 72.814812, "source": "pin", "set_at": None}


async def test_the_panthaky_can_move_it_too(client, db, seeded):
    headers = await _headers(client, seeded["panthaky_phone"])
    r = await client.put(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", json=PIN, headers=headers)
    assert r.status_code == 200


async def test_a_mobed_of_another_fire_temple_cannot_move_it_or_read_it(client, db, seeded):
    other = await _other_temple(db)
    headers = await _headers(client, OTHER)
    assert (await client.post(f"/api/mobed/agyaries/{other.id}/join", headers=headers)).status_code == 200
    r = await client.put(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", json=PIN, headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"] == "Only the mobeds of this fire temple can change where it is."
    assert (await client.get(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", headers=headers)).status_code == 403
    temple = await db.get(Agyary, seeded["agyary_id"])
    await db.refresh(temple)
    assert temple.latitude is None and temple.location_source is None


async def test_a_mobed_waiting_for_approval_cannot_move_it(client, db, seeded):
    headers = await _headers(client, NEW, approve=False)
    assert (await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)).status_code == 200
    r = await client.put(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", json=PIN, headers=headers)
    assert r.status_code == 403 and r.headers["X-Mobed-Access"] == "pending"
    temple = await db.get(Agyary, seeded["agyary_id"])
    await db.refresh(temple)
    assert temple.latitude is None


async def test_a_mobed_switched_off_cannot_move_it(client, db, seeded):
    headers = await _headers(client, MOBED)
    await db.execute(update(User).where(User.phone == MOBED).values(access="off"))
    await db.commit()
    r = await client.put(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", json=PIN, headers=headers)
    assert r.status_code == 403 and r.headers["X-Mobed-Access"] == "off"


async def test_an_admin_can_place_any_fire_temple(client, db, seeded, admin_phone):
    other = await _other_temple(db)
    headers = await _headers(client, ADMIN, "Admin")
    # Not a member of either.
    for temple_id in (seeded["agyary_id"], other.id):
        r = await client.put(f"/api/mobed/agyaries/{temple_id}/location", json=PIN, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["location"]["source"] == "pin"


async def test_nobody_signed_out_and_no_such_fire_temple(client, db, seeded):
    assert (await client.put(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", json=PIN)).status_code == 401
    headers = await _headers(client, MOBED)
    assert (await client.put("/api/mobed/agyaries/99999/location", json=PIN, headers=headers)).status_code == 404
    await db.execute(update(Agyary).where(Agyary.id == seeded["agyary_id"]).values(is_active=False))
    await db.commit()
    assert (await client.put(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", json=PIN,
                             headers=headers)).status_code == 404


@pytest.mark.parametrize("body, status", [
    ({"latitude": 91, "longitude": 72.8}, 400),
    ({"latitude": -90.0001, "longitude": 72.8}, 400),
    ({"latitude": 18.9, "longitude": 180.5}, 400),
    ({"latitude": 18.9, "longitude": 432.1}, 400),     # a click on the map's next copy of the world
    ({"latitude": 0, "longitude": 0}, 400),
    ({"latitude": "18.9", "longitude": "72.8"}, 400),
    ({"latitude": True, "longitude": 72.8}, 400),
    ({"latitude": None, "longitude": 72.8}, 400),
    ({"latitude": 18.9}, 400),
    ({"latitude": [18.9], "longitude": 72.8}, 400),
    ({"latitude": {"x": 1}, "longitude": 72.8}, 400),
    ({}, 400),
    ({"latitude": 10 ** 400, "longitude": 72.8}, 400),
])
async def test_garbage_is_refused_and_nothing_is_saved(client, db, seeded, body, status):
    headers = await _headers(client, MOBED)
    r = await client.put(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", json=body, headers=headers)
    assert r.status_code == status, r.text
    if status == 400:
        assert r.json()["detail"] == "That place is not on the map. Please put the pin on the fire temple."
    temple = await db.get(Agyary, seeded["agyary_id"])
    await db.refresh(temple)
    assert temple.latitude is None


@pytest.mark.parametrize("raw", ['{"latitude": NaN, "longitude": 72.8}', '{"latitude": 1e400, "longitude": 72.8}',
                                 '{"latitude": Infinity, "longitude": 72.8}'])
async def test_not_a_number_is_refused_in_plain_words(client, db, seeded, raw):
    headers = await _headers(client, MOBED) | {"content-type": "application/json"}
    r = await client.put(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", content=raw, headers=headers)
    assert r.status_code == 400, r.text


async def test_moving_it_over_and_over_is_limited(client, db, seeded):
    headers = await _headers(client, MOBED)
    codes = [(await client.put(f"/api/mobed/agyaries/{seeded['agyary_id']}/location", json=PIN,
                               headers=headers)).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


# --- A new fire temple can be put on the map as it is added ------------------

async def test_a_new_fire_temple_can_come_with_its_pin(client, db, seeded):
    headers = await _headers(client, NEW, approve=False)   # still signing up
    r = await client.post("/api/mobed/agyaries", json={"name": "Banaji Atash Behram", "city": "Mumbai",
                                                       "location": PIN}, headers=headers)
    assert r.status_code == 200, r.text
    (temple,) = [a for a in r.json()["user"]["agyaries"] if a["name"] == "Banaji Atash Behram"]
    assert temple["location"]["source"] == "pin" and temple["location"]["latitude"] == 18.9655
    row = await db.get(Agyary, temple["id"])
    new = (await db.execute(select(User).where(User.phone == NEW))).scalar_one()
    assert row.location_set_by_user_id == new.id


async def test_a_new_fire_temple_without_a_pin_has_no_position(client, db, seeded):
    headers = await _headers(client, NEW)
    r = await client.post("/api/mobed/agyaries", json={"name": "Banaji Atash Behram", "city": "Mumbai"},
                          headers=headers)
    assert r.status_code == 200
    assert r.json()["user"]["agyaries"][0]["location"] is None


async def test_a_new_fire_temple_with_a_bad_pin_is_not_made_at_all(client, db, seeded):
    headers = await _headers(client, NEW)
    r = await client.post("/api/mobed/agyaries", json={"name": "Banaji Atash Behram", "city": "Mumbai",
                                                       "location": {"latitude": 123, "longitude": 72.8}},
                          headers=headers)
    assert r.status_code == 400
    assert (await db.execute(select(Agyary).where(Agyary.name == "Banaji Atash Behram"))).first() is None


async def test_the_open_search_does_not_give_out_positions(client, db, seeded):
    """Fire-temple search is open to anyone signing up; the position is for its members."""
    await db.execute(update(Agyary).where(Agyary.id == seeded["agyary_id"]).values(
        latitude=18.94, longitude=72.83, location_source="pin"))
    await db.commit()
    (hit,) = (await client.get("/api/mobed/agyaries/search?q=Goti")).json()
    assert "location" not in hit and "latitude" not in hit
