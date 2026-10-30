"""The mobed's paid / not paid tick on an event: bookings and their own machis.

It is the event's payment_status, set by the mobed and read back on the day's
list. Nothing is calculated, and it is private to the mobed's own events.
"""

from __future__ import annotations


from agyary.models import Booking, Machi
from tests.test_behdin_and_preferences import _add_machi
from tests.test_behdin_delete import _add, _book
from tests.test_mobed_api import _member_headers

OTHER = "+919911100071"


async def _day(client, headers, day="2027-08-01"):
    r = await client.get("/api/mobed/my-day", params={"from": day, "to": day}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_a_booking_starts_unpaid_and_can_be_ticked_both_ways(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    await _add(client, aid, headers)
    bid = await _book(client, aid, headers)
    assert [e["paid"] for e in await _day(client, headers)] == [False]

    r = await client.put(f"/api/mobed/agyaries/{aid}/bookings/{bid}/paid", json={"paid": True}, headers=headers)
    assert r.status_code == 200 and r.json() == {"paid": True}
    assert [e["paid"] for e in await _day(client, headers)] == [True]
    assert (await db.get(Booking, bid)).payment_status == "received"

    r = await client.put(f"/api/mobed/agyaries/{aid}/bookings/{bid}/paid", json={"paid": False}, headers=headers)
    assert r.status_code == 200
    assert [e["paid"] for e in await _day(client, headers)] == [False]


async def test_a_machi_can_be_ticked_and_shows_on_the_board(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    r = await _add_machi(client, aid, headers, "patet",
                         [{"section": "pair", "title": "khud", "name": "A", "status": "departed", "pair_group": 1},
                          {"section": "pair", "title": "khud", "name": "B", "status": "departed", "pair_group": 1}])
    assert r.status_code == 200, r.text
    mid = r.json()["machi_id"]
    board = lambda: client.get(f"/api/mobed/agyaries/{aid}/machi-board",   # noqa: E731
                               params={"from": "2027-06-01", "to": "2027-06-30", "mine": "true"}, headers=headers)
    assert [m["paid"] for m in (await board()).json()] == [False]
    r = await client.put(f"/api/mobed/agyaries/{aid}/machis/{mid}/paid", json={"paid": True}, headers=headers)
    assert r.status_code == 200, r.text
    assert [m["paid"] for m in (await board()).json()] == [True]
    assert (await db.get(Machi, mid)).payment_status == "received"


async def test_another_mobed_cannot_tick_or_see_it(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    await _add(client, aid, headers)
    bid = await _book(client, aid, headers)
    other = await _member_headers(client, seeded, name="Other", phone=OTHER)
    r = await client.put(f"/api/mobed/agyaries/{aid}/bookings/{bid}/paid", json={"paid": True}, headers=other)
    assert r.status_code == 404
    assert (await db.get(Booking, bid)).payment_status == "pending"
    r = await client.put(f"/api/mobed/agyaries/{aid}/machis/999999/paid", json={"paid": True}, headers=headers)
    assert r.status_code == 404
    r = await client.put(f"/api/mobed/agyaries/{aid}/bookings/{bid}/paid", json={}, headers=headers)
    assert r.status_code == 422


# --- Memorial dates ----------------------------------------------------------

async def test_memorial_dates_can_be_ticked_one_by_one_and_all_at_once(client, db, seeded):
    from tests.test_memorial_api import _create, _setup
    aid, cid, headers = await _setup(client, db, seeded)
    made = (await _create(client, db, aid, cid, headers)).json()
    mid, first = made["id"], made["observances"][0]["id"]
    assert made["paid_count"] == 0 and not any(o["paid"] for o in made["observances"])

    r = await client.put(f"/api/mobed/agyaries/{aid}/memorials/{mid}/observances/{first}/paid",
                         json={"paid": True}, headers=headers)
    assert r.status_code == 200 and r.json() == {"paid": True, "paid_count": 1}
    got = (await client.get(f"/api/mobed/agyaries/{aid}/memorials/{mid}", headers=headers)).json()
    assert [o["paid"] for o in got["observances"]].count(True) == 1 and got["observances"][0]["paid"]

    r = await client.put(f"/api/mobed/agyaries/{aid}/memorials/{mid}/paid", json={"paid": True}, headers=headers)
    assert r.json()["paid_count"] == made["total"]
    r = await client.put(f"/api/mobed/agyaries/{aid}/memorials/{mid}/paid", json={"paid": False}, headers=headers)
    assert r.json()["paid_count"] == 0

    # the calendar feed carries the tick, so the day list can show it
    await client.put(f"/api/mobed/agyaries/{aid}/memorials/{mid}/observances/{first}/paid",
                     json={"paid": True}, headers=headers)
    feed = (await client.get(f"/api/mobed/agyaries/{aid}/memorial-feed",
                             params={"from": "2030-01-01", "to": "2030-12-31"}, headers=headers)).json()
    paid = {i["id"]: i["paid"] for i in feed if i["kind"] == "memorial"}
    assert paid[first] is True and list(paid.values()).count(True) == 1


async def test_a_memorial_can_be_created_already_paid_for(client, db, seeded):
    from tests.test_memorial_api import _create, _setup
    aid, cid, headers = await _setup(client, db, seeded)
    made = (await _create(client, db, aid, cid, headers, all_paid=True)).json()
    assert made["paid_count"] == made["total"] > 0


async def test_another_mobed_cannot_tick_a_memorial(client, db, seeded):
    from tests.test_memorial_api import OTHER_MOBED, _create, _setup
    aid, cid, headers = await _setup(client, db, seeded)
    made = (await _create(client, db, aid, cid, headers)).json()
    other = await _member_headers(client, seeded, name="Other", phone=OTHER_MOBED)
    mid, oid = made["id"], made["observances"][0]["id"]
    for path in (f"/memorials/{mid}/paid", f"/memorials/{mid}/observances/{oid}/paid"):
        r = await client.put(f"/api/mobed/agyaries/{aid}{path}", json={"paid": True}, headers=other)
        assert r.status_code == 404, path
    r = await client.put(f"/api/mobed/agyaries/{aid}/memorials/{mid}/observances/999999/paid",
                         json={"paid": True}, headers=headers)
    assert r.status_code == 404
