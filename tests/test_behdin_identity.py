"""A number is a behdin's identity: one number, one behdin, one name.

The number is normalised before it is compared, so two spellings of one
person cannot become two behdins, and the name is only ever changed from
behdin management - never as a side effect of booking or editing an event.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from agyary.models import Customer
from agyary.services.phone import normalize_phone
from tests.test_mobed_api import _member_headers

OTHER_MOBED = "+919911100078"


@pytest.mark.parametrize(
    "typed, stored",
    [
        ("+919876543210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("+91-98765-43210", "+919876543210"),
        ("+91098765 43210", "+919876543210"),   # trunk 0 after the country code
        ("+12025550123", "+12025550123"),       # one-digit code, left alone
        ("+447911123456", "+447911123456"),
        ("+4407911123456", "+447911123456"),
    ],
)
def test_normalize_phone(typed, stored):
    assert normalize_phone(typed) == stored


def _migration_normalise():
    path = next(Path("alembic/versions").glob("f7a8b9c0d1e2_*.py"))
    spec = importlib.util.spec_from_file_location("phone_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._normalise


@pytest.mark.parametrize(
    "old, new",
    [
        ("9876543210", "+919876543210"),         # bare Indian mobile
        ("919876543210", "+919876543210"),       # bare with country code
        ("09876543210", "+919876543210"),        # bare with trunk 0
        ("+919876543210", "+919876543210"),      # already fine
        ("+91 98765 43210", "+919876543210"),
    ],
)
def test_migration_normalises_legacy_numbers_like_the_app(old, new):
    assert _migration_normalise()(old) == new
    assert normalize_phone(new) == new


async def test_two_spellings_of_a_number_are_one_behdin(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    first = await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                              json={"name": "Same Person", "phone": "+919944400301"}, headers=headers)
    again = await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                              json={"name": "Same Person", "phone": "+91 0 99444 00301"}, headers=headers)
    assert first.json()["created"] is True
    assert again.json()["created"] is False
    assert again.json()["id"] == first.json()["id"]
    assert len((await db.execute(select(Customer))).scalars().all()) == 1


async def test_the_database_refuses_a_number_in_the_wrong_shape(db, seeded):
    db.add(Customer(name="Bad", phone="9944400302"))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_booking_for_a_known_number_does_not_rename_the_behdin(db, client, seeded):
    aid = seeded["agyary_id"]
    owner = await _member_headers(client, seeded)
    other = await _member_headers(client, seeded, name="Other Mobed", phone=OTHER_MOBED)
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                          json={"name": "Original Name", "phone": "+919944400303"}, headers=owner)
    cid = r.json()["id"]

    r = await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/booking",
        json={"behdin_phone": "+919944400303", "behdin_name": "Typo Name", "service_id": 2,
              "ceremony_datetime": "2027-08-01T10:00:00", "purpose": "khushali_nu", "names": []},
        headers=other,
    )
    assert r.status_code == 200, r.text
    bid = r.json()["booking_id"]
    assert (await db.get(Customer, cid)).name == "Original Name"

    # ...and editing that booking doesn't either.
    r = await client.put(
        f"/api/mobed/agyaries/{aid}/bookings/{bid}",
        json={"behdin_phone": "+919944400303", "behdin_name": "Another Typo", "service_id": 2,
              "ceremony_datetime": "2027-08-02T10:00:00", "purpose": "khushali_nu", "names": []},
        headers=other,
    )
    assert r.status_code == 200, r.text
    await db.refresh(await db.get(Customer, cid))
    assert (await db.get(Customer, cid)).name == "Original Name"


async def test_the_name_is_edited_from_behdin_management(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                          json={"name": "Old", "phone": "+919944400304"}, headers=headers)
    cid = r.json()["id"]
    r = await client.patch(f"/api/mobed/agyaries/{aid}/behdins/{cid}", json={"name": "New"}, headers=headers)
    assert r.status_code == 200 and r.json()["name"] == "New"
