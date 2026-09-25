"""Who may see, change and delete an event, and what a delete leaves behind.

Membership of the fire temple used to be the only check on a booking's slip,
detail, edit and delete, and ids are sequential - so any colleague could read
another mobed's behdin names and numbers by counting. A booking now belongs
to the mobed who entered it (or is assigned to it), plus the agyari's admins.
Machis stay readable across the shared board but only their owner or an admin
may change them.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from agyary.models import Booking, Machi, Notification, Payment
from tests.test_behdin_and_preferences import _add_machi
from tests.test_mobed_api import _member_headers

OTHER_MOBED = "+919911100077"
PANTHAKY = "+919800000001"


async def _add_booking(client, aid, headers, phone="+919944400201"):
    r = await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/booking",
        json={
            "behdin_phone": phone, "behdin_name": "Access Behdin", "service_id": 2,
            "ceremony_datetime": "2027-08-01T10:00:00", "purpose": "khushali_nu", "names": [],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["booking_id"]


async def test_another_mobed_cannot_read_edit_or_delete_a_booking(db, client, seeded):
    aid = seeded["agyary_id"]
    owner = await _member_headers(client, seeded)
    other = await _member_headers(client, seeded, name="Other Mobed", phone=OTHER_MOBED)
    bid = await _add_booking(client, aid, owner)
    base = f"/api/mobed/agyaries/{aid}/bookings/{bid}"

    assert (await client.get(f"{base}/slip", headers=other)).status_code == 404
    assert (await client.get(f"{base}/detail", headers=other)).status_code == 404
    edit = {
        "behdin_phone": "+919944400201", "behdin_name": "Access Behdin", "service_id": 2,
        "ceremony_datetime": "2027-08-02T10:00:00", "purpose": "khushali_nu",
    }
    assert (await client.put(base, json=edit, headers=other)).status_code == 404
    assert (await client.delete(base, headers=other)).status_code == 404
    assert await db.get(Booking, bid) is not None

    # The owner is unaffected.
    assert (await client.get(f"{base}/slip", headers=owner)).status_code == 200


async def test_an_admin_can_reach_any_booking_at_their_agyari(db, client, seeded):
    aid = seeded["agyary_id"]
    owner = await _member_headers(client, seeded)
    admin = await _member_headers(client, seeded, name="Er. Hormuz", phone=PANTHAKY)
    bid = await _add_booking(client, aid, owner)
    assert (await client.get(f"/api/mobed/agyaries/{aid}/bookings/{bid}/slip", headers=admin)).status_code == 200
    assert (await client.delete(f"/api/mobed/agyaries/{aid}/bookings/{bid}", headers=admin)).status_code == 200


async def test_only_the_owner_or_an_admin_can_change_a_machi(db, client, seeded):
    aid = seeded["agyary_id"]
    owner = await _member_headers(client, seeded)
    other = await _member_headers(client, seeded, name="Other Mobed", phone=OTHER_MOBED)
    r = await _add_machi(
        client, aid, owner, "patet",
        [{"section": "pair", "title": "ervad", "name": "A", "status": "departed", "pair_group": 1},
         {"section": "pair", "title": "ervad", "name": "B", "status": "departed", "pair_group": 1}],
    )
    mid = r.json()["machi_id"]
    base = f"/api/mobed/agyaries/{aid}/machis/{mid}"

    # Shared board: another member can still open it...
    assert (await client.get(f"{base}/slip", headers=other)).status_code == 200
    # ...but not change or remove it.
    assert (await client.delete(base, headers=other)).status_code == 404
    assert await db.get(Machi, mid) is not None
    assert (await client.delete(base, headers=owner)).status_code == 200


async def test_deleting_an_event_takes_its_pending_payment_and_notifications(db, client, seeded):
    """Both point at the event with no ON DELETE, so before this the delete
    was a 500 for any event that had ever been through the old WhatsApp flow."""
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    bid = await _add_booking(client, aid, headers)
    booking = await db.get(Booking, bid)
    db.add(Payment(agyary_id=aid, customer_id=booking.customer_id, booking_id=bid,
                   amount=Decimal("100"), method="upi", status="pending"))
    db.add(Notification(agyary_id=aid, recipient_phone="+919900000000", recipient_type="customer",
                        recipient_id=booking.customer_id, notification_type="reminder",
                        template_name="t", booking_id=bid))
    await db.commit()

    r = await client.delete(f"/api/mobed/agyaries/{aid}/bookings/{bid}", headers=headers)
    assert r.status_code == 200, r.text
    assert (await db.execute(select(Payment))).first() is None
    assert (await db.execute(select(Notification))).first() is None


async def test_an_event_with_a_received_payment_is_kept(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    r = await _add_machi(
        client, aid, headers, "patet",
        [{"section": "pair", "title": "ervad", "name": "A", "status": "departed", "pair_group": 1},
         {"section": "pair", "title": "ervad", "name": "B", "status": "departed", "pair_group": 1}],
    )
    mid = r.json()["machi_id"]
    machi = await db.get(Machi, mid)
    db.add(Payment(agyary_id=aid, customer_id=machi.customer_id, machi_id=mid,
                   amount=Decimal("100"), method="cash", status="received"))
    await db.commit()

    r = await client.delete(f"/api/mobed/agyaries/{aid}/machis/{mid}", headers=headers)
    assert r.status_code == 409
    assert "payment" in r.json()["detail"]
    assert await db.get(Machi, mid) is not None
