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


async def test_board_shows_a_colleagues_slot_as_booked_without_the_family(client, db, seeded):
    aid = seeded["agyary_id"]
    owner, mid = await _owners_machi(client, seeded)
    window = "from=2030-08-01&to=2030-08-31"

    [own] = (await client.get(f"/api/mobed/agyaries/{aid}/machi-board?{window}", headers=owner)).json()
    assert own["id"] == mid and own["behdin_name"] == "Private Family" and own["mine"] is True

    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944400703")
    r = await client.get(f"/api/mobed/agyaries/{aid}/machi-board?{window}&mine=false", headers=colleague)
    [theirs] = r.json()
    # The slot is still visibly taken - that is what the shared board is for...
    assert theirs["id"] == mid and theirs["geh"] == 1 and theirs["gregorian_date"] == "2030-08-15"
    # ...but not by whom.
    assert theirs["behdin_name"] == "" and theirs["mine"] is False
    assert "Private Family" not in r.text
