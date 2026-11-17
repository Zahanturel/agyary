"""A manager chooses a fire temple and sends a funeral record to it (DECISIONS
D10, D2, D9; Phase 2 Step 4).

Suggested: nearest first, by straight-line distance, within 500 km, with the
family's preferred fire temple first; and a search over all of them. Each says
whether a request reaches a confirmed panthaky, only mobeds, or nobody.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import update

from agyary.core import config
from agyary.models import AgyaryUser
from agyary.services import funeral_requests
from tests.funeral_helpers import agyari, form, manager, member, place

RECORDS = "/api/mobed/manager/records"
NAVSARI = (20.951, 72.923)
DELHI = (28.61, 77.21)


@pytest.fixture
def admin_is_panthaky(monkeypatch, seeded):
    monkeypatch.setenv("ADMIN_PHONES", seeded["panthaky_phone"])
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_the_distance_is_the_straight_line_over_the_globe():
    assert round(funeral_requests.km(0, 0, 0, 1), 1) == 111.2
    assert funeral_requests.km(18.957, 72.806, 18.957, 72.806) == 0
    assert 215 < funeral_requests.km(18.957, 72.806, *NAVSARI) < 230


async def _temples(db):
    """A fire temple near the Doongerwadi with a confirmed panthaky, one at
    Navsari with only mobeds, one near with nobody whose access is on, one
    turned off, one in Delhi, and one not on the map."""
    near = await agyari(db, "Near Agyari (test)", (18.96, 72.83))
    await member(db, near, "+919822200001", "panthaky")
    await member(db, near, "+919822200002", "mobed")
    navsari = await agyari(db, "Navsari Agyari (test)", NAVSARI, city="Navsari")
    claimed = await member(db, navsari, "+919822200003", "mobed")
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == claimed.id)
                     .values(claimed_role="panthaky", claimed_at=datetime.now(timezone.utc)))
    empty = await agyari(db, "Quiet Agyari (test)", (18.99, 72.84), status="unclaimed")
    await member(db, empty, "+919822200004", "mobed", access="pending")
    await member(db, empty, "+919822200005", "panthaky", access="off")
    off = await agyari(db, "Closed Agyari (test)", (18.958, 72.807))
    off.is_active = False
    delhi = await agyari(db, "Delhi Agyari (test)", DELHI, city="Delhi")
    nowhere = await agyari(db, "Unmapped Agyari (test)", None)
    await db.commit()
    return near, navsari, empty, delhi, nowhere


async def test_suggested_nearest_first_within_500_km_with_who_it_reaches(client, db, seeded):
    near, navsari, empty, delhi, nowhere = await _temples(db)
    headers, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(), headers=headers)).json()["record"]
    got = (await client.get(f"{RECORDS}/{rec['id']}/agyaries", headers=headers)).json()
    assert got["place_has_position"] is True and got["near_km"] == 500
    rows = got["agyaries"]
    # Delhi is too far, the closed one and the ones not on the map are not there.
    assert [r["name"] for r in rows] == ["Near Agyari (test)", "Quiet Agyari (test)", "Navsari Agyari (test)"]
    assert rows[0]["km"] < rows[1]["km"] < rows[2]["km"] and 215 < rows[2]["km"] < 230
    # A confirmed panthaky; only mobeds (a claim is not a panthaky); nobody whose access is on.
    assert [r["reach"] for r in rows] == ["panthaky", "nobody", "mobeds"]
    assert [r["may_send"] for r in rows] == [True, False, True]
    assert not any(r["preferred"] for r in rows)


async def test_the_familys_preferred_fire_temple_is_first_wherever_it_is(client, db, seeded):
    near, navsari, empty, delhi, nowhere = await _temples(db)
    headers, _ = await manager(client, db)
    for preferred, first_km in ((delhi, lambda k: k > 1000), (navsari, lambda k: 215 < k < 230)):
        rec = (await client.post(RECORDS, json=form(preferred_agyary_id=preferred.id), headers=headers)).json()
        rows = (await client.get(f"{RECORDS}/{rec['record']['id']}/agyaries", headers=headers)).json()["agyaries"]
        assert rows[0]["id"] == preferred.id and rows[0]["preferred"] is True and first_km(rows[0]["km"])
        assert [r["id"] for r in rows].count(preferred.id) == 1
        assert rec["record"]["preferred_agyari"]["name"] == preferred.name
    # One not on the map is still first, with no distance.
    rec = (await client.post(RECORDS, json=form(preferred_agyary_id=nowhere.id), headers=headers)).json()
    rows = (await client.get(f"{RECORDS}/{rec['record']['id']}/agyaries", headers=headers)).json()["agyaries"]
    assert rows[0]["id"] == nowhere.id and rows[0]["km"] is None and rows[0]["reach"] == "nobody"


async def test_a_place_with_no_pin_says_so_and_suggests_only_the_preferred(client, db, seeded):
    near, *_ = await _temples(db)
    unpinned = await place(db, "Aramgah (test)", position=None, kind="aramgah")
    headers, _ = await manager(client, db, at=unpinned)
    rec = (await client.post(RECORDS, json=form(), headers=headers)).json()["record"]
    got = (await client.get(f"{RECORDS}/{rec['id']}/agyaries", headers=headers)).json()
    assert got["place_has_position"] is False and got["agyaries"] == []
    rec = (await client.post(RECORDS, json=form(preferred_agyary_id=near.id), headers=headers)).json()["record"]
    got = (await client.get(f"{RECORDS}/{rec['id']}/agyaries", headers=headers)).json()
    assert [r["id"] for r in got["agyaries"]] == [near.id] and got["agyaries"][0]["km"] is None
    # Search still finds them all.
    found = (await client.get("/api/mobed/manager/agyaries/search?q=agyari", headers=headers)).json()["agyaries"]
    assert {"Near Agyari (test)", "Delhi Agyari (test)"} <= {r["name"] for r in found}


async def test_search_all_finds_any_fire_temple_by_name_or_town(client, db, seeded):
    await _temples(db)
    headers, _ = await manager(client, db)
    found = (await client.get("/api/mobed/manager/agyaries/search?q=delhi", headers=headers)).json()["agyaries"]
    assert [r["name"] for r in found] == ["Delhi Agyari (test)"] and found[0]["km"] > 1000
    assert found[0]["reach"] == "nobody" and found[0]["may_send"] is False
    goti = (await client.get("/api/mobed/manager/agyaries/search?q=goti", headers=headers)).json()["agyaries"]
    assert goti[0]["name"] == "Goti Adarian" and goti[0]["reach"] == "panthaky" and goti[0]["km"] is None
    assert (await client.get("/api/mobed/manager/agyaries/search?q=", headers=headers)).json()["agyaries"] == []


async def test_another_places_record_has_no_suggestions_for_them(client, db, seeded):
    headers, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(), headers=headers)).json()["record"]
    other_place = await place(db, "Prayer hall (test)", kind="prayer_hall")
    other, _ = await manager(client, db, phone="+919911100072", name="Other Manager", at=other_place)
    assert (await client.get(f"{RECORDS}/{rec['id']}/agyaries", headers=other)).status_code == 404
    mine = rec["funeral_place"]["id"]
    r = await client.get(f"/api/mobed/manager/agyaries/search?q=goti&place_id={mine}", headers=other)
    assert r.status_code == 404
