"""The first pair is prayed first - for the behdin's default, and per event.

A behdin's saved pairs have an order the mobed arranged, and an event starts
from it. An event can then be arranged differently without touching the
behdin's default. The order used to be lost twice over: the saved pool was read
back sorted by the pair's group number rather than by its position, and
complete_pairs re-sorted by group number again.
"""

from __future__ import annotations

from tests.test_mobed_api import _member_headers

PHONE = "+919944400601"


def _pair(group, first, second):
    return [
        {"title": "ervad", "name": first, "status": "departed", "pair_group": group},
        {"title": "ervad", "name": second, "status": "departed", "pair_group": group},
    ]


async def _behdin(client, aid, headers, pairs):
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                          json={"name": "Order Behdin", "phone": PHONE}, headers=headers)
    cid = r.json()["id"]
    r = await client.put(f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names/pair",
                         json={"names": pairs}, headers=headers)
    assert r.status_code == 200, r.text
    return cid


def _first_names(rows):
    return [n["name"] for n in rows if n["section"] == "pair"]


async def _book(client, aid, headers, names=None):
    body = {"behdin_phone": PHONE, "behdin_name": "Order Behdin", "service_id": 2,
            "ceremony_datetime": "2027-08-01T10:00:00", "purpose": "gujrela_nu"}
    if names is not None:
        body["names"] = names
    r = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/booking", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["booking_id"]


async def test_saved_pairs_keep_the_order_the_mobed_arranged(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    # Group numbers deliberately not in position order: 7 is first.
    cid = await _behdin(client, aid, headers, _pair(7, "Zahan", "Meherzad") + _pair(3, "Meherzad", "Parvex"))
    r = await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names", headers=headers)
    assert _first_names(r.json()) == ["Zahan", "Meherzad", "Meherzad", "Parvex"]

    # Reordering is just saving them in the new order.
    r = await client.put(f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names/pair",
                         json={"names": _pair(3, "Meherzad", "Parvex") + _pair(7, "Zahan", "Meherzad")},
                         headers=headers)
    assert _first_names(r.json()) == ["Meherzad", "Parvex", "Zahan", "Meherzad"]


async def test_a_new_event_starts_from_the_saved_order_and_the_slip_prints_it(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    await _behdin(client, aid, headers, _pair(7, "Zahan", "Meherzad") + _pair(3, "Meherzad", "Parvex"))

    bid = await _book(client, aid, headers)
    slip = (await client.get(f"/api/mobed/agyaries/{aid}/bookings/{bid}/slip", headers=headers)).json()
    assert slip["names_text"].splitlines() == ["Ervad Zahan, Ervad Meherzad", "Ervad Meherzad, Ervad Parvex"]


async def test_an_event_can_be_ordered_differently_from_the_default(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    cid = await _behdin(client, aid, headers, _pair(1, "Zahan", "Meherzad") + _pair(2, "Meherzad", "Parvex"))

    swapped = [{"section": "pair", **n} for n in _pair(1, "Meherzad", "Parvex") + _pair(2, "Zahan", "Meherzad")]
    bid = await _book(client, aid, headers, names=swapped)

    slip = (await client.get(f"/api/mobed/agyaries/{aid}/bookings/{bid}/slip", headers=headers)).json()
    assert slip["names_text"].splitlines()[0] == "Ervad Meherzad, Ervad Parvex"
    # The behdin's own default is untouched.
    r = await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names", headers=headers)
    assert _first_names(r.json()) == ["Zahan", "Meherzad", "Meherzad", "Parvex"]
