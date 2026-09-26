"""Names typed on an event are remembered for the behdin - as part of saving.

Names added on the review step used to belong to that one event, so adding the
same family's pairs again for the next event started from nothing. The first fix
made the app send a second request after saving; a phone still running an older
copy of the app never sent it and the names were lost again. Remembering now
happens inside the save itself, so no client can skip it.
"""

from __future__ import annotations

from tests.test_mobed_api import _member_headers

PHONE = "+919944400951"


def _row(section, title, name, group=None, status="departed"):
    return {"section": section, "title": title, "name": name, "status": status, "pair_group": group}


def _pair(group, a, b):
    return [_row("pair", "ervad", a, group), _row("pair", "ervad", b, group)]


FIVE = (_pair(1, "Zahan", "Meherzad") + _pair(2, "Meherzad", "Parvex") + _pair(3, "Parvex", "Jamshedji")
        + _pair(4, "Jamshedji", "Nariman") + _pair(5, "Nariman", "Dorabji"))


async def _book(client, aid, headers, names, day="2027-08-01", **extra):
    r = await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/booking",
        json={"behdin_phone": PHONE, "behdin_name": "Merge Behdin", "service_id": 2,
              "ceremony_datetime": f"{day}T10:00:00", "purpose": "gujrela_nu", "names": names, **extra},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["booking_id"]


async def _pool(client, aid, headers):
    behdin = (await client.get(f"/api/mobed/agyaries/{aid}/behdins", params={"q": PHONE}, headers=headers)).json()[0]
    rows = (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{behdin['id']}/saved-names", headers=headers)).json()
    return [n["name"] for n in rows if n["section"] == "pair"]


async def test_five_typed_pairs_are_remembered_by_the_save_alone(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    # No remember_names key: this is what an older copy of the app sends.
    await _book(client, aid, headers, FIVE)
    assert await _pool(client, aid, headers) == [
        "Zahan", "Meherzad", "Meherzad", "Parvex", "Parvex", "Jamshedji",
        "Jamshedji", "Nariman", "Nariman", "Dorabji"]


async def test_the_next_event_starts_from_them(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    await _book(client, aid, headers, FIVE)

    r = await client.post(f"/api/mobed/agyaries/{aid}/slip-preview/booking",
                          json={"behdin_phone": PHONE, "behdin_name": "Merge Behdin", "service_id": 2,
                                "ceremony_datetime": "2027-08-02T10:00:00", "purpose": "gujrela_nu"},
                          headers=headers)
    assert len([n for n in r.json()["names"] if n["section"] == "pair"]) == 10


async def test_it_only_adds_and_never_removes_or_duplicates(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    await _book(client, aid, headers, _pair(1, "Zahan", "Meherzad") + _pair(2, "Meherzad", "Parvex"))
    # A later event drops the second pair, re-types the first in other case, and adds one.
    await _book(client, aid, headers, _pair(1, "zahan", "MEHERZAD") + _pair(2, "Parvex", "Jamshedji"),
                day="2027-08-02")
    assert await _pool(client, aid, headers) == [
        "Zahan", "Meherzad", "Meherzad", "Parvex", "Parvex", "Jamshedji"]


async def test_the_mobed_can_opt_out_for_one_event(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    await _book(client, aid, headers, FIVE, remember_names=False)
    assert await _pool(client, aid, headers) == []


async def test_half_pairs_and_repeated_singles(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    names = [_row("farmayeshne", "ervad", "Zahan", status="living"),
             _row("farmayeshne", "ervad", "Zahan", status="living"),
             _row("pair", "ervad", "Only Half", 1)]
    await _book(client, aid, headers, names)
    behdin = (await client.get(f"/api/mobed/agyaries/{aid}/behdins", params={"q": PHONE}, headers=headers)).json()[0]
    rows = (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{behdin['id']}/saved-names", headers=headers)).json()
    assert [(n["section"], n["name"]) for n in rows] == [("farmayeshne", "Zahan")]


async def test_editing_an_event_remembers_names_added_there(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    bid = await _book(client, aid, headers, _pair(1, "Zahan", "Meherzad"))
    edit = {"behdin_phone": PHONE, "behdin_name": "Merge Behdin", "service_id": 2,
            "ceremony_datetime": "2027-08-01T10:00:00", "purpose": "gujrela_nu",
            "names": _pair(1, "Zahan", "Meherzad") + _pair(2, "Meherzad", "Parvex")}
    r = await client.put(f"/api/mobed/agyaries/{aid}/bookings/{bid}", json=edit, headers=headers)
    assert r.status_code == 200, r.text
    assert await _pool(client, aid, headers) == ["Zahan", "Meherzad", "Meherzad", "Parvex"]


async def test_a_patet_machi_remembers_its_pair(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    r = await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/machi",
        json={"behdin_phone": PHONE, "behdin_name": "Merge Behdin", "roj": 4, "mah": 5, "year": 1396,
              "geh": 1, "gregorian": "2027-06-15", "purpose": "patet",
              "names": _pair(1, "Zahan", "Meherzad")},
        headers=headers,
    )
    assert r.json()["confirmed"] is True
    assert await _pool(client, aid, headers) == ["Zahan", "Meherzad"]
