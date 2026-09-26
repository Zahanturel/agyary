"""Names typed on an event are remembered for the behdin - additively.

Before this, names added on the review step belonged to that one event, so
adding the same family's pairs again for the next event started from nothing.
"""

from __future__ import annotations

from tests.test_mobed_api import _member_headers

PHONE = "+919944400951"


def _row(section, title, name, group=None, status="departed"):
    return {"section": section, "title": title, "name": name, "status": status, "pair_group": group}


def _pair(group, a, b):
    return [_row("pair", "ervad", a, group), _row("pair", "ervad", b, group)]


async def _setup(client, aid, headers, pairs=None):
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                          json={"name": "Merge Behdin", "phone": PHONE}, headers=headers)
    cid = r.json()["id"]
    if pairs:
        await client.put(f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names/pair",
                         json={"names": [{k: v for k, v in n.items() if k != "section"} for n in pairs]},
                         headers=headers)
    return cid


async def _pool(client, aid, headers, cid):
    return (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names", headers=headers)).json()


async def _merge(client, aid, headers, names, phone=PHONE):
    return await client.post(f"/api/mobed/agyaries/{aid}/behdins/merge-names",
                             json={"behdin_phone": phone, "names": names}, headers=headers)


def _pairs(rows):
    return [n["name"] for n in rows if n["section"] == "pair"]


async def test_five_typed_pairs_are_all_remembered(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    cid = await _setup(client, aid, headers)          # no saved names at all
    typed = (_pair(1, "Zahan", "Meherzad") + _pair(2, "Meherzad", "Parvex") + _pair(3, "Parvex", "Jamshedji")
             + _pair(4, "Jamshedji", "Nariman") + _pair(5, "Nariman", "Dorabji"))

    r = await _merge(client, aid, headers, typed)
    assert r.status_code == 200 and r.json()["added_pairs"] == 5
    assert _pairs(await _pool(client, aid, headers, cid)) == [
        "Zahan", "Meherzad", "Meherzad", "Parvex", "Parvex", "Jamshedji",
        "Jamshedji", "Nariman", "Nariman", "Dorabji"]


async def test_merging_adds_only_what_is_new_and_removes_nothing(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    cid = await _setup(client, aid, headers, _pair(1, "Zahan", "Meherzad") + _pair(2, "Meherzad", "Parvex"))

    # An event that dropped the second pair and added a third (and spelled the
    # first in different case): the family's list keeps everything it had.
    event = _pair(1, "zahan", "MEHERZAD") + _pair(2, "Parvex", "Jamshedji")
    r = await _merge(client, aid, headers, event)
    assert r.json()["added_pairs"] == 1
    assert _pairs(await _pool(client, aid, headers, cid)) == [
        "Zahan", "Meherzad", "Meherzad", "Parvex", "Parvex", "Jamshedji"]

    # Merging the same thing again changes nothing.
    assert (await _merge(client, aid, headers, event)).json() == {"added_pairs": 0, "added_names": 0}


async def test_single_names_merge_and_half_pairs_are_ignored(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    cid = await _setup(client, aid, headers)
    names = [_row("farmayeshne", "ervad", "Zahan", status="living"),
             _row("farmayeshne", "ervad", "Zahan", status="living"),        # twice in one event
             _row("pair", "ervad", "Only Half", 1)]                          # never remembered
    r = await _merge(client, aid, headers, names)
    assert r.json() == {"added_pairs": 0, "added_names": 1}
    pool = await _pool(client, aid, headers, cid)
    assert [n["name"] for n in pool] == ["Zahan"]


async def test_you_cannot_add_names_to_a_behdin_who_is_not_yours(db, client, seeded):
    aid = seeded["agyary_id"]
    mine = await _member_headers(client, seeded)
    theirs = await _member_headers(client, seeded, name="Other Mobed", phone="+919911100080")
    await _setup(client, aid, mine)
    r = await _merge(client, aid, theirs, _pair(1, "A", "B"))
    assert r.status_code == 404
