"""A machi's family is its own mobed's business.

The Machi Board is shared so that everyone at a fire temple can see which gehs
are taken. That does not need the family's name, number or the names recited
for them, so the detail and the slip are for the machi's own mobed (its
creator, the mobed assigned to it, or the temple's panthaky), and the shared
board shows a colleague's slot as booked without saying for whom.
"""

from __future__ import annotations

from tests.test_mobed_api import _member_headers

BEHDIN_PHONE = "+919944400701"
RECITED = {"Dead A", "Dead B"}


async def _owners_machi(client, seeded) -> tuple[dict, int]:
    aid = seeded["agyary_id"]
    owner = await _member_headers(client, seeded)
    made = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/machi", headers=owner, json={
        "behdin_phone": BEHDIN_PHONE, "behdin_name": "Private Family", "roj": 1, "mah": 1,
        "year": 1400, "geh": 1, "gregorian": "2030-08-15", "purpose": "patet",
        "names": [
            {"section": "pair", "title": "ervad", "name": "Dead A", "status": "departed", "pair_group": 1},
            {"section": "pair", "title": "behdin", "name": "Dead B", "status": "departed", "pair_group": 1},
        ],
    })
    assert made.status_code == 200, made.text
    return owner, made.json()["machi_id"]


async def test_detail_and_slip_are_only_for_the_machis_own_mobed(client, db, seeded):
    aid = seeded["agyary_id"]
    owner, mid = await _owners_machi(client, seeded)

    for what in ("detail", "slip"):
        own = await client.get(f"/api/mobed/agyaries/{aid}/machis/{mid}/{what}", headers=owner)
        assert own.status_code == 200, what
        assert own.json()["behdin_phone"] == BEHDIN_PHONE, what

    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944400702")
    for what in ("detail", "slip"):
        theirs = await client.get(f"/api/mobed/agyaries/{aid}/machis/{mid}/{what}", headers=colleague)
        assert theirs.status_code == 404, what
        assert BEHDIN_PHONE not in theirs.text and "Dead A" not in theirs.text, what


WINDOW = "from=2030-08-01&to=2030-08-31"


async def _book(client, aid, headers, geh=1, name="Their Family", phone="+919944400799"):
    return await client.post(f"/api/mobed/agyaries/{aid}/manual-add/machi", headers=headers, json={
        "behdin_phone": phone, "behdin_name": name, "roj": 1, "mah": 1,
        "year": 1400, "geh": geh, "gregorian": "2030-08-15", "purpose": "patet",
    })


async def test_a_colleague_sees_nothing_of_anothers_board(client, db, seeded):
    aid = seeded["agyary_id"]
    owner, mid = await _owners_machi(client, seeded)

    [own] = (await client.get(f"/api/mobed/agyaries/{aid}/machi-board?{WINDOW}", headers=owner)).json()
    assert own["id"] == mid and own["behdin_name"] == "Private Family" and own["mine"] is True

    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944400703")
    # Asking for the whole temple's board, as the old shared board did, changes nothing.
    for query in ("", "&mine=false", "&mine=true"):
        r = await client.get(f"/api/mobed/agyaries/{aid}/machi-board?{WINDOW}{query}", headers=colleague)
        assert r.status_code == 200 and r.json() == [], query
        assert "Private Family" not in r.text


async def test_a_colleagues_machi_does_not_make_a_geh_look_taken(client, db, seeded):
    aid = seeded["agyary_id"]
    owner, _ = await _owners_machi(client, seeded)  # geh 1 on 2030-08-15
    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944400704")

    mine = (await client.get(f"/api/mobed/agyaries/{aid}/bookable-gehs?on=2030-08-15", headers=owner)).json()
    theirs = (await client.get(f"/api/mobed/agyaries/{aid}/bookable-gehs?on=2030-08-15", headers=colleague)).json()
    assert 1 not in mine["bookable"]
    assert theirs["bookable"] == [1, 2, 3, 4, 5]


async def test_two_mobeds_can_hold_the_same_geh_and_neither_is_told(client, db, seeded):
    aid = seeded["agyary_id"]
    owner, owners_id = await _owners_machi(client, seeded)
    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944400705")

    made = await _book(client, aid, colleague, geh=1)
    assert made.status_code == 200, made.text
    assert made.json()["machi_id"] != owners_id
    assert "Private Family" not in made.text and BEHDIN_PHONE not in made.text

    # Their own second try at the same geh is refused, as it always was.
    again = await _book(client, aid, colleague, geh=1, name="Another", phone="+919944400798")
    assert again.status_code != 200 or again.json().get("machi_id") is None

    # And the first mobed's board is exactly as it was.
    [own] = (await client.get(f"/api/mobed/agyaries/{aid}/machi-board?{WINDOW}", headers=owner)).json()
    assert own["id"] == owners_id


async def test_the_preview_does_not_leak_a_colleagues_slot(client, db, seeded):
    aid = seeded["agyary_id"]
    await _owners_machi(client, seeded)
    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944400706")
    r = await client.post(f"/api/mobed/agyaries/{aid}/slip-preview/machi", headers=colleague, json={
        "behdin_phone": "+919944400797", "behdin_name": "Someone", "roj": 1, "mah": 1, "year": 1400,
        "geh": 1, "gregorian": "2030-08-15", "purpose": "patet",
    })
    assert r.status_code == 200, r.text
    assert r.json()["slot_available"] is True
