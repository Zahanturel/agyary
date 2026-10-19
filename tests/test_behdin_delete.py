"""Deleting a behdin removes them from the mobed's book, never their events.

A ceremony that was performed is history. Bookings and machis require their
behdin, so a behdin with events cannot be erased - they are taken out of the
list, the record stays holding the number, and adding the number again brings
them back with their history. A behdin nothing refers to is erased outright,
which frees the number.
"""

from __future__ import annotations

from sqlalchemy import select

from agyary.models import Customer, CustomerSavedName
from tests.test_mobed_api import _member_headers

PHONE = "+919944400901"
OTHER = "+919911100079"


async def _add(client, aid, headers, phone=PHONE, name="Delete Behdin"):
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                          json={"name": name, "phone": phone}, headers=headers)
    return r.json()


async def _book(client, aid, headers, phone=PHONE):
    r = await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/booking",
        json={"behdin_phone": phone, "behdin_name": "Delete Behdin", "service_id": 2,
              "ceremony_datetime": "2027-08-01T10:00:00", "purpose": "khushali_nu", "names": []},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["booking_id"]


async def _listed(client, aid, headers):
    return [b["id"] for b in (await client.get(f"/api/mobed/agyaries/{aid}/behdins", headers=headers)).json()]


async def test_a_behdin_with_no_events_is_erased_and_the_number_is_free(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    b = await _add(client, aid, headers)
    await client.put(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}/saved-names/farmayeshne",
                     json={"names": [{"title": "khud", "name": "Someone", "status": "living", "pair_group": None}]},
                     headers=headers)

    r = await client.delete(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}", headers=headers)
    assert r.status_code == 200 and r.json() == {"deleted": True, "erased": True}
    assert await db.get(Customer, b["id"]) is None
    assert (await db.execute(select(CustomerSavedName))).first() is None   # went with them

    again = await _add(client, aid, headers)
    assert again["created"] is True    # the number really is free


async def test_a_behdin_with_events_leaves_the_list_but_the_events_stay(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    b = await _add(client, aid, headers)
    bid = await _book(client, aid, headers)

    r = await client.delete(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}", headers=headers)
    assert r.json() == {"deleted": True, "erased": False}
    assert b["id"] not in await _listed(client, aid, headers)
    assert (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}", headers=headers)).status_code == 404

    # The event, and its slip naming them, are untouched.
    slip = await client.get(f"/api/mobed/agyaries/{aid}/bookings/{bid}/slip", headers=headers)
    assert slip.status_code == 200 and slip.json()["behdin_name"] == "Delete Behdin"
    day = await client.get("/api/mobed/my-day", params={"from": "2027-08-01", "to": "2027-08-01"}, headers=headers)
    assert [e["behdin_name"] for e in day.json()] == ["Delete Behdin"]


async def test_adding_the_number_again_brings_them_back_with_their_history(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    b = await _add(client, aid, headers)
    await _book(client, aid, headers)
    await client.delete(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}", headers=headers)

    back = await _add(client, aid, headers)
    assert back["id"] == b["id"] and back["created"] is False
    assert b["id"] in await _listed(client, aid, headers)
    history = (await client.get(f"/api/mobed/customers/{b['id']}/history", headers=headers)).json()["history"]
    assert len(history) == 1


async def test_deleting_leaves_another_mobeds_book_alone(db, client, seeded):
    aid = seeded["agyary_id"]
    mine = await _member_headers(client, seeded)
    theirs = await _member_headers(client, seeded, name="Other Mobed", phone=OTHER)
    b = await _add(client, aid, mine)
    t = await _add(client, aid, theirs)      # same number: a record of their own (D2)
    assert t["id"] != b["id"]

    r = await client.delete(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}", headers=mine)
    assert r.json()["erased"] is True        # mine had nothing referring to it
    assert await _listed(client, aid, theirs) == [t["id"]]
    assert await db.get(Customer, t["id"]) is not None


async def test_you_cannot_delete_a_behdin_who_is_not_yours(db, client, seeded):
    aid = seeded["agyary_id"]
    mine = await _member_headers(client, seeded)
    theirs = await _member_headers(client, seeded, name="Other Mobed", phone=OTHER)
    b = await _add(client, aid, mine)

    r = await client.delete(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}", headers=theirs)
    assert r.status_code == 404
    assert b["id"] in await _listed(client, aid, mine)


async def _memorial(client, db, aid, cid, headers):
    from tests.test_memorial_api import _create
    r = await _create(client, db, aid, cid, headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_the_summary_says_what_a_delete_could_take(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    b = await _add(client, aid, headers)
    await _book(client, aid, headers)
    await _memorial(client, db, aid, b["id"], headers)
    r = await client.get(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}/delete-summary", headers=headers)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["memorials"] == 1 and s["memorial_dates_ahead"] > 0
    assert s["upcoming_events"] == 1 and s["past_events"] == 0 and s["payments"] == 0


async def test_deleting_with_memorials_keeps_the_bookings(db, client, seeded):
    from agyary.models import Memorial
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    b = await _add(client, aid, headers)
    bid = await _book(client, aid, headers)
    await _memorial(client, db, aid, b["id"], headers)

    r = await client.delete(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}?scope=memorials", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["memorials_deleted"] == 1 and r.json()["events_deleted"] == 0
    assert (await db.execute(select(Memorial))).first() is None
    slip = await client.get(f"/api/mobed/agyaries/{aid}/bookings/{bid}/slip", headers=headers)
    assert slip.status_code == 200          # the booking is still there


async def test_deleting_everything_removes_upcoming_events_and_memorials(db, client, seeded):
    from agyary.models import Booking, Memorial, MemorialObservance
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    b = await _add(client, aid, headers)
    await _book(client, aid, headers)
    await _memorial(client, db, aid, b["id"], headers)

    r = await client.delete(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}?scope=all", headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["memorials_deleted"] == 1 and out["events_deleted"] == 1 and out["events_kept"] == 0
    assert out["erased"] is True            # nothing left that refers to them
    assert (await db.execute(select(Booking))).first() is None
    assert (await db.execute(select(Memorial))).first() is None
    assert (await db.execute(select(MemorialObservance))).first() is None
    assert await db.get(Customer, b["id"]) is None


async def test_deleting_everything_keeps_performed_ceremonies_as_history(db, client, seeded):
    from agyary.models import Booking
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    b = await _add(client, aid, headers)
    past = await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/booking",
        json={"behdin_phone": PHONE, "behdin_name": "Delete Behdin", "service_id": 2,
              "ceremony_datetime": "2024-01-01T10:00:00", "purpose": "khushali_nu", "names": []},
        headers=headers)
    assert past.status_code == 200, past.text
    await _book(client, aid, headers)       # an upcoming one

    r = await client.delete(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}?scope=all", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["events_deleted"] == 1 and r.json()["erased"] is False
    left = (await db.execute(select(Booking))).scalars().all()
    assert len(left) == 1 and left[0].ceremony_datetime.year == 2024
    assert b["id"] not in await _listed(client, aid, headers)


async def test_an_unknown_scope_is_refused(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    b = await _add(client, aid, headers)
    r = await client.delete(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}?scope=everything", headers=headers)
    assert r.status_code == 400
    assert await db.get(Customer, b["id"]) is not None


async def test_deleting_everything_never_deletes_a_recorded_payment(db, client, seeded):
    from decimal import Decimal
    from agyary.models import Booking, Payment
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    b = await _add(client, aid, headers)
    bid = await _book(client, aid, headers)
    db.add(Payment(agyary_id=aid, customer_id=b["id"], booking_id=bid, amount=Decimal("500"),
                   method="cash", status="received"))
    await db.commit()

    r = await client.delete(f"/api/mobed/agyaries/{aid}/behdins/{b['id']}?scope=all", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["events_kept"] == 1 and r.json()["events_deleted"] == 0 and r.json()["erased"] is False
    assert (await db.execute(select(Payment))).first() is not None
    assert await db.get(Booking, bid) is not None
