"""A family can be erased from every mobed's book, and old records can be let go.

LEG-04: a number reaches every mobed who keeps it, but only that number. LEG-03:
retention deletes for good, so it does nothing until the owner switches it on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from agyary.core import config
from agyary.core.config import Settings
from agyary.models import (
    AppNotification,
    Booking,
    CeremonyName,
    Customer,
    CustomerSavedName,
    Machi,
    Memorial,
    MemorialObservance,
    Notification,
    ReminderOptOut,
)
from agyary.services import erasure
from tests.test_memorial_api import PHONE as FAMILY, _create, _setup
from tests.test_mobed_api import NEW_MOBED_PHONE, _member_headers

COLLEAGUE = "+919944400811"
ANOTHER_FAMILY = "+919944400812"
NOW = datetime(2030, 3, 14, 12, 0, tzinfo=timezone.utc)


def _settings(**over) -> Settings:
    return Settings(**{"jwt_secret_key": "x", **over})


async def _count(db, model, *where) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


async def _machi(client, aid, headers, phone, name, geh=1):
    r = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/machi", headers=headers, json={
        "behdin_phone": phone, "behdin_name": name, "roj": 1, "mah": 1, "year": 1400,
        "geh": geh, "gregorian": "2030-08-15", "purpose": "patet",
        "names": [{"section": "pair", "title": "ervad", "name": "Dead A", "status": "departed", "pair_group": 1},
                  {"section": "pair", "title": "behdin", "name": "Dead B", "status": "departed", "pair_group": 1}],
    })
    assert r.status_code == 200, r.text


async def _message(db, aid, customer) -> None:
    db.add(Notification(
        agyary_id=aid, recipient_phone=customer.phone, recipient_type="customer", recipient_id=customer.id,
        notification_type="memorial_share", template_name="memorial_schedule",
        template_params={"1": "Dinshaw Mehta"}, status="sent",
    ))
    await db.commit()


async def _two_books(client, db, seeded):
    """The same family in two mobeds' books, and another family beside them."""
    aid, cid, headers = await _setup(client, db, seeded)
    assert (await _create(client, db, aid, cid, headers)).status_code == 200
    await _machi(client, aid, headers, FAMILY, "The Family")
    await _machi(client, aid, headers, ANOTHER_FAMILY, "Another Family", geh=2)
    colleague = await _member_headers(client, seeded, name="Colleague", phone=COLLEAGUE)
    await _machi(client, aid, colleague, FAMILY, "Their Family")
    customer = await db.get(Customer, cid)
    db.add(CustomerSavedName(customer_id=cid, section="pair", title="behdin", name="Saved Name", status="living"))
    await _message(db, aid, customer)
    return aid, cid, headers, colleague


@pytest.fixture
def as_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_PHONES", NEW_MOBED_PHONE)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def test_a_number_is_erased_from_every_book_and_only_that_number(client, db, seeded):
    aid, cid, headers, colleague = await _two_books(client, db, seeded)
    db.add(ReminderOptOut(phone=FAMILY, stopped_at=NOW))
    await db.commit()

    found = await erasure.what_we_hold(db, FAMILY)
    assert found == {"records": 2, "mobeds": 2, "memorials": 1, "events": 2, "messages": 1}
    assert await erasure.erase_number(db, FAMILY) == found
    await db.commit()
    db.expire_all()

    assert await _count(db, Customer, Customer.phone == FAMILY) == 0
    assert await _count(db, Memorial) == 0 and await _count(db, MemorialObservance) == 0
    assert await _count(db, CustomerSavedName, CustomerSavedName.name == "Saved Name") == 0
    assert await _count(db, Notification) == 0

    # The events stay, with nothing to say whose they were.
    kept = (await db.execute(select(Customer).where(Customer.name == erasure.ERASED))).scalars().all()
    assert len(kept) == 2 and all(c.phone.startswith("+999") and not c.reminders_enabled for c in kept)
    assert await _count(db, Machi, Machi.customer_id.in_([c.id for c in kept])) == 2
    names = (await db.execute(select(CeremonyName.machi_id))).scalars().all()
    assert len(names) == 2, "only the other family's two names remain"

    # The other family is untouched, and so is the STOP.
    assert await _count(db, Customer, Customer.phone == ANOTHER_FAMILY) == 1
    assert await db.get(ReminderOptOut, FAMILY) is not None

    # Each mobed is told, in words that do not name the family.
    told = (await db.execute(select(AppNotification).where(AppNotification.kind == erasure.KIND_ERASED))).scalars().all()
    assert len(told) == 2 and all("Delzeen" not in n.body and FAMILY not in n.body for n in told)


async def test_a_record_nothing_points_at_goes_altogether(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    await erasure.erase_number(db, FAMILY)
    await db.commit()
    assert await db.get(Customer, cid) is None


async def test_the_notes_on_their_events_go_too(client, db, seeded):
    aid, cid, headers, _colleague = await _two_books(client, db, seeded)
    machi = (await db.execute(select(Machi).where(Machi.customer_id == cid))).scalar_one()
    machi.notes = "Delzeen's mother, 12 Cusrow Baug"
    await db.commit()
    await erasure.erase_number(db, FAMILY)
    await db.commit()
    await db.refresh(machi)
    assert machi.notes is None


async def test_the_admin_sees_counts_first_and_erasing_needs_the_confirmation(client, db, seeded, as_admin):
    aid, cid, headers, _colleague = await _two_books(client, db, seeded)
    admin = await _member_headers(client, seeded)
    url = "/api/mobed/admin/erase-number"
    r = await client.post(url, json={"phone": FAMILY}, headers=admin)
    assert r.status_code == 200 and r.json()["found"]["records"] == 2
    assert await _count(db, Customer, Customer.phone == FAMILY) == 2, "looking erases nothing"
    assert FAMILY not in r.text

    r = await client.post(url, json={"phone": FAMILY, "confirm": True}, headers=admin)
    assert r.status_code == 200 and r.json()["erased"]["records"] == 2
    db.expire_all()
    assert await _count(db, Customer, Customer.phone == FAMILY) == 0


async def test_a_mobed_who_is_not_an_admin_cannot_reach_it(client, db, seeded):
    _aid, _cid, headers, _colleague = await _two_books(client, db, seeded)
    r = await client.post("/api/mobed/admin/erase-number", json={"phone": FAMILY, "confirm": True}, headers=headers)
    assert r.status_code == 404
    assert await _count(db, Customer, Customer.phone == FAMILY) == 2


# --- Retention --------------------------------------------------------------

async def _an_old_message(db, aid, customer, age_days) -> None:
    db.add(Notification(
        agyary_id=aid, recipient_phone=customer.phone, recipient_type="customer", recipient_id=customer.id,
        notification_type="memorial_share", template_name="memorial_schedule", status="sent",
        created_at=NOW - timedelta(days=age_days),
    ))
    await db.commit()


async def test_nothing_is_swept_until_the_owner_switches_it_on(client, db, seeded):
    aid, cid, _headers = await _setup(client, db, seeded)
    await _an_old_message(db, aid, await db.get(Customer, cid), age_days=4000)
    assert await erasure.sweep_old(db, _settings(), NOW) == {"messages": 0, "records": 0}
    await db.commit()
    assert await _count(db, Notification) == 1


async def test_old_messages_go_and_recent_ones_stay(client, db, seeded):
    aid, cid, _headers = await _setup(client, db, seeded)
    customer = await db.get(Customer, cid)
    await _an_old_message(db, aid, customer, age_days=13 * 31 + 1)
    await _an_old_message(db, aid, customer, age_days=13 * 31 - 1)
    report = await erasure.sweep_old(db, _settings(retention_mode="on"), NOW)
    await db.commit()
    assert report["messages"] == 1 and await _count(db, Notification) == 1


async def test_a_quiet_hidden_behdin_is_erased_but_not_one_with_something_recent(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    await _machi(client, aid, headers, FAMILY, "The Family")
    await _machi(client, aid, headers, ANOTHER_FAMILY, "Another Family", geh=2)
    quiet = await db.get(Customer, cid)
    busy = (await db.execute(select(Customer).where(Customer.phone == ANOTHER_FAMILY))).scalar_one()
    quiet.is_active = busy.is_active = False
    await db.commit()

    # In 2040 the 2030 machi is long past. A later one keeps the other family.
    then = datetime(2040, 1, 1, tzinfo=timezone.utc)
    later = (await db.execute(select(Machi).where(Machi.customer_id == busy.id))).scalar_one()
    later.gregorian_date = then.date()
    await db.commit()

    report = await erasure.sweep_old(db, _settings(retention_mode="on"), then)
    await db.commit()
    await db.refresh(quiet)
    await db.refresh(busy)
    assert report["records"] == 1
    assert quiet.name == erasure.ERASED and busy.name == "Another Family"


async def test_a_listed_behdin_is_never_swept_however_old(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    await _machi(client, aid, headers, FAMILY, "The Family")
    report = await erasure.sweep_old(db, _settings(retention_mode="on"), datetime(2060, 1, 1, tzinfo=timezone.utc))
    await db.commit()
    assert report["records"] == 0 and (await db.get(Customer, cid)).name != erasure.ERASED


async def test_a_booking_keeps_its_slip_after_the_family_is_erased(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    r = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/booking", headers=headers, json={
        "behdin_phone": FAMILY, "behdin_name": "The Family", "service_id": 2,
        "ceremony_datetime": "2030-03-01T10:00:00", "purpose": "khushali_nu", "location": "14 Cusrow Baug",
        "names": [{"section": "farmayeshne", "title": "behdin", "name": "X", "status": "living", "pair_group": None}],
        "is_offsite": True,
    })
    assert r.status_code == 200, r.text
    await erasure.erase_number(db, FAMILY)
    await db.commit()
    db.expire_all()
    booking = (await db.execute(select(Booking))).scalar_one()
    assert booking.location is None and await _count(db, CeremonyName) == 0
    slip = await client.get(f"/api/mobed/agyaries/{aid}/bookings/{booking.id}/slip", headers=headers)
    assert slip.status_code == 200, slip.text
    assert erasure.ERASED in slip.text
