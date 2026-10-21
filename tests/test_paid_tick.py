"""The mobed's paid / not paid tick on an event: bookings and their own machis.

It is the event's payment_status, set by the mobed and read back on the day's
list. Nothing is calculated, and it is private to the mobed's own events.
"""

from __future__ import annotations

from sqlalchemy import select

from agyary.models import Booking, Machi
from tests.test_behdin_and_preferences import _add_machi
from tests.test_behdin_delete import PHONE, _add, _book
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
