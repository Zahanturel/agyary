"""Review before saving: the slip as it will print, with nothing written.

The point of the review step is that the mobed checks the names BEFORE the
event exists, so the preview must (a) write nothing, (b) be the very slip that
saving then produces, and (c) carry the names it used so the screen edits what
will actually be saved.
"""

from __future__ import annotations

from sqlalchemy import func, select

from agyary.models import Booking, CeremonyName, Customer, Machi
from tests.test_mobed_api import _member_headers

PHONE = "+919944400801"


def _pair(group, first, second):
    return [
        {"title": "ervad", "name": first, "status": "departed", "pair_group": group},
        {"title": "ervad", "name": second, "status": "departed", "pair_group": group},
    ]


async def _behdin_with_pairs(client, aid, headers, phone=PHONE):
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                          json={"name": "Preview Behdin", "phone": phone}, headers=headers)
    cid = r.json()["id"]
    await client.put(f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names/pair",
                     json={"names": _pair(1, "Zahan", "Meherzad") + _pair(2, "Meherzad", "Parvex")},
                     headers=headers)
    return cid


def _booking_body(**over):
    body = {"behdin_phone": PHONE, "behdin_name": "Preview Behdin", "service_id": 2,
            "ceremony_datetime": "2027-08-01T10:00:00", "purpose": "gujrela_nu"}
    return {**body, **over}


async def test_preview_writes_nothing_and_offers_the_saved_names(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    await _behdin_with_pairs(client, aid, headers)

    r = await client.post(f"/api/mobed/agyaries/{aid}/slip-preview/booking",
                          json=_booking_body(), headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [n["name"] for n in body["names"] if n["section"] == "pair"] == ["Zahan", "Meherzad", "Meherzad", "Parvex"]
    assert body["slip"]["names_text"].splitlines() == ["Ervad Zahan, Ervad Meherzad", "Ervad Meherzad, Ervad Parvex"]
    assert body["pool_empty"] is False

    assert (await db.execute(select(func.count()).select_from(Booking))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(CeremonyName))).scalar_one() == 0


async def test_the_preview_is_the_slip_that_saving_produces(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    await _behdin_with_pairs(client, aid, headers)
    # Reordered, as a mobed would on the review screen.
    names = [{"section": "pair", **n} for n in _pair(1, "Meherzad", "Parvex") + _pair(2, "Zahan", "Meherzad")]

    preview = (await client.post(f"/api/mobed/agyaries/{aid}/slip-preview/booking",
                                 json=_booking_body(names=names), headers=headers)).json()["slip"]
    made = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/booking",
                             json=_booking_body(names=names), headers=headers)
    saved = (await client.get(f"/api/mobed/agyaries/{aid}/bookings/{made.json()['booking_id']}/slip",
                              headers=headers)).json()
    assert preview == saved


async def test_preview_for_a_number_not_yet_on_file_shows_what_was_typed(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    r = await client.post(f"/api/mobed/agyaries/{aid}/slip-preview/booking",
                          json=_booking_body(behdin_phone="+919944400899", behdin_name="Brand New"),
                          headers=headers)
    body = r.json()
    assert body["slip"]["behdin_name"] == "Brand New"
    assert body["names"] == [] and body["pool_empty"] is True
    assert (await db.execute(select(func.count()).select_from(Customer))).scalar_one() == 0


async def test_machi_preview_says_whether_the_slot_can_still_be_had(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    body = {"behdin_phone": PHONE, "behdin_name": "Preview Behdin", "roj": 4, "mah": 5, "year": 1396,
            "geh": 1, "gregorian": "2027-06-15", "purpose": "patet", "names": _pair(1, "A", "B") and
            [{"section": "pair", **n} for n in _pair(1, "A", "B")]}
    url = f"/api/mobed/agyaries/{aid}/slip-preview/machi"

    first = (await client.post(url, json=body, headers=headers)).json()
    assert first["slot_available"] is True
    assert first["slip"]["event"] == "Machi (patet)"
    assert (await db.execute(select(func.count()).select_from(Machi))).scalar_one() == 0

    made = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/machi", json=body, headers=headers)
    mid = made.json()["machi_id"]
    assert (await client.post(url, json=body, headers=headers)).json()["slot_available"] is False
    # ...but not for the machi that holds it, when reviewing its own edit.
    assert (await client.post(url, json={**body, "editing_machi_id": mid}, headers=headers)).json()["slot_available"] is True


async def test_editing_without_names_keeps_the_events_own_names(db, client, seeded):
    """An edit that says nothing about names must not re-pull the saved pool:
    the event's names may have been reviewed and reordered."""
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    cid = await _behdin_with_pairs(client, aid, headers)
    custom = [{"section": "pair", **n} for n in _pair(1, "Only", "These")]
    made = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/booking",
                             json=_booking_body(names=custom), headers=headers)
    bid = made.json()["booking_id"]

    edit = _booking_body(ceremony_datetime="2027-08-02T11:00:00")   # no names key
    r = await client.put(f"/api/mobed/agyaries/{aid}/bookings/{bid}", json=edit, headers=headers)
    assert r.status_code == 200, r.text
    slip = (await client.get(f"/api/mobed/agyaries/{aid}/bookings/{bid}/slip", headers=headers)).json()
    assert slip["names_text"] == "Ervad Only, Ervad These"

    # Changing the behdin is different: their saved names are the sensible start.
    other = await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                              json={"name": "Someone Else", "phone": "+919944400802"}, headers=headers)
    edit = _booking_body(behdin_phone="+919944400802", behdin_name="Someone Else")
    r = await client.put(f"/api/mobed/agyaries/{aid}/bookings/{bid}", json=edit, headers=headers)
    slip = (await client.get(f"/api/mobed/agyaries/{aid}/bookings/{bid}/slip", headers=headers)).json()
    assert slip["names_text"] == ""     # the new behdin has no saved names
