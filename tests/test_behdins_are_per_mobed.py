"""A behdin belongs to the mobed who keeps them (docs/DECISIONS.md D2).

Each mobed has their own record of a family: name, saved names, history,
events, memorials and the reminder consent. Typing a number another mobed
already has must neither reveal what they recorded nor attach to their record:
it makes a record of one's own. The one thing that is the person's, not any
mobed's, is a STOP: it reaches every mobed's record of that number, including
ones made later, and each mobed can lift it only for their own record, with
"they asked me to".
"""

from __future__ import annotations

from tests.test_mobed_api import _member_headers

PHONE = "+919944401001"
SAVED = {"Departed Father", "Departed Mother"}


async def _victims_behdin(client, seeded) -> tuple[int, dict, int]:
    aid = seeded["agyary_id"]
    victim = await _member_headers(client, seeded)
    made = await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=victim,
                             json={"name": "Private Family", "phone": PHONE})
    assert made.status_code == 200, made.text
    cid = made.json()["id"]
    r = await client.put(f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names/pair", headers=victim, json={
        "names": [
            {"title": "ervad", "name": "Departed Father", "status": "departed", "pair_group": 1},
            {"title": "behdin", "name": "Departed Mother", "status": "departed", "pair_group": 1},
        ]})
    assert r.status_code == 200, r.text
    return aid, victim, cid


async def _victims_view(client, aid, victim, cid) -> tuple[dict, set[str]]:
    record = (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}", headers=victim)).json()
    names = {n["name"] for n in (await client.get(
        f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names", headers=victim)).json()}
    return record, names


async def test_a_number_another_mobed_has_makes_a_record_of_ones_own(client, db, seeded):
    aid, victim, cid = await _victims_behdin(client, seeded)
    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944401002")

    made = await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=colleague,
                             json={"name": "Colleague's Name", "phone": PHONE})
    assert made.status_code == 200, made.text
    mine = made.json()
    # Nothing of the victim's record comes back: a fresh record, under the typed name...
    assert mine["created"] is True and mine["id"] != cid and mine["name"] == "Colleague's Name"
    assert "Private Family" not in made.text
    # ...with none of the family's saved names.
    names = (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{mine['id']}/saved-names",
                              headers=colleague)).json()
    assert names == []

    # Whatever the colleague does to their own record leaves the victim's alone.
    r = await client.patch(f"/api/mobed/agyaries/{aid}/behdins/{mine['id']}", headers=colleague,
                           json={"name": "Renamed", "phone": "+919944401003"})
    assert r.status_code == 200, r.text
    r = await client.put(f"/api/mobed/agyaries/{aid}/behdins/{mine['id']}/saved-names/pair",
                         headers=colleague, json={"names": []})
    assert r.status_code == 200, r.text
    record, victims_names = await _victims_view(client, aid, victim, cid)
    assert (record["name"], record["phone"]) == ("Private Family", PHONE)
    assert victims_names == SAVED

    # And the victim's id still means nothing to the colleague.
    assert (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}", headers=colleague)).status_code == 404


async def test_an_event_for_a_number_another_mobed_has_uses_ones_own_record(client, db, seeded):
    aid, victim, cid = await _victims_behdin(client, seeded)
    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944401004")

    made = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/machi", headers=colleague, json={
        "behdin_phone": PHONE, "behdin_name": "Typed Name", "roj": 1, "mah": 1, "year": 1400,
        "geh": 2, "gregorian": "2030-08-15", "purpose": "patet"})
    assert made.status_code == 200, made.text
    detail = (await client.get(f"/api/mobed/agyaries/{aid}/machis/{made.json()['machi_id']}/detail",
                               headers=colleague)).json()
    assert detail["behdin_name"] == "Typed Name"
    assert not SAVED & {n["name"] for n in detail["names"]}

    theirs = (await client.get(f"/api/mobed/agyaries/{aid}/behdins", headers=colleague)).json()
    assert [(b["name"], b["phone"]) for b in theirs] == [("Typed Name", PHONE)]
    assert theirs[0]["id"] != cid
    record, victims_names = await _victims_view(client, aid, victim, cid)
    assert record["name"] == "Private Family" and victims_names == SAVED


async def test_a_stop_reaches_every_record_but_is_lifted_only_where_asked(client, db, seeded):
    from agyary.services import reminders

    aid, victim, cid = await _victims_behdin(client, seeded)
    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944401005")
    other = (await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=colleague,
                               json={"name": "Same Family", "phone": PHONE})).json()["id"]
    for headers, rid in ((victim, cid), (colleague, other)):
        r = await client.put(f"/api/mobed/agyaries/{aid}/behdins/{rid}/reminders", headers=headers,
                             json={"enabled": True})
        assert r.status_code == 200, r.text

    # The person says STOP: both mobeds' records stop, and both are told.
    assert await reminders.record_stop(db, PHONE) == 2
    await db.commit()

    # The colleague was asked again, and lifts it - for their own record only.
    r = await client.put(f"/api/mobed/agyaries/{aid}/behdins/{other}/reminders", headers=colleague,
                         json={"enabled": True, "confirm_restart": True})
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["stopped_at"] is None
    record, _ = await _victims_view(client, aid, victim, cid)
    assert record["reminders"]["enabled"] is False and record["reminders"]["stopped_at"] is not None

    # A mobed who adds the number later starts with it stopped.
    late = await _member_headers(client, seeded, name="Latecomer", phone="+919944401006")
    rid = (await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=late,
                             json={"name": "Same Family", "phone": PHONE})).json()["id"]
    r = await client.put(f"/api/mobed/agyaries/{aid}/behdins/{rid}/reminders", headers=late,
                         json={"enabled": True})
    assert r.status_code == 409
