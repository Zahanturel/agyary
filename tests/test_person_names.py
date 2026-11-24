"""The departed's names that follow a person, by phone number (DECISIONS D12,
"Departed names for the family", 24 Nov 2026).

Written when a Doongerwadi manager records a death (one row per record, kept in
step on edit); readable only by the account that signs in with that number; and
given to a mobed only as copies in their own book at All set. Erasure and
account deletion take the rows away.
"""

from __future__ import annotations

from sqlalchemy import select

from agyary.models import Customer, CustomerSavedName, FuneralRecord, PersonName, User
from agyary.services import behdin_directory, erasure, person_names
from tests.conftest import sign_in
from tests.funeral_helpers import FAMILY, auth, form, manager
from tests.test_funeral_managers import _api_calls

RECORDS = "/api/mobed/manager/records"
MINE = "/api/mobed/me/person-names"
OTHER_FAMILY = "+919822200044"
STRANGER = "+919822200055"


async def _rows(db, phone=None) -> list[PersonName]:
    q = select(PersonName).order_by(PersonName.id).execution_options(populate_existing=True)
    if phone:
        q = q.where(PersonName.phone == phone)
    return list((await db.execute(q)).scalars())


async def test_the_pool_is_written_on_create_and_updated_on_edit_one_row_per_record(client, db, seeded):
    headers, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(), headers=headers)).json()["record"]
    rows = await _rows(db, FAMILY)
    assert [(r.departed_title, r.departed_name, r.departed_parent_name, r.source, r.source_record_id)
            for r in rows] == [("behdin", "Rustom", "Jamshed", "death_record", rec["id"])]

    r = await client.put(f"{RECORDS}/{rec['id']}", json=form(departed_name="Kersi", departed_parent_name=""),
                         headers=headers)
    assert r.status_code == 200, r.text
    assert [(r.departed_name, r.departed_parent_name) for r in await _rows(db, FAMILY)] == [("Kersi", None)]

    # A second death for the same family is a second row; editing the first leaves it alone.
    await client.post(RECORDS, json=form(departed_name="Meher"), headers=headers)
    assert len(await _rows(db, FAMILY)) == 2
    await client.put(f"{RECORDS}/{rec['id']}", json=form(departed_name="Kersi II"), headers=headers)
    assert sorted(r.departed_name for r in await _rows(db, FAMILY)) == ["Kersi II", "Meher"]

    # The number changed (nothing waiting on it): the row follows the record.
    r = await client.put(f"{RECORDS}/{rec['id']}",
                         json=form(departed_name="Kersi II", family_contact_phone=OTHER_FAMILY), headers=headers)
    assert r.status_code == 200, r.text
    assert [r.departed_name for r in await _rows(db, OTHER_FAMILY)] == ["Kersi II"]
    assert [r.departed_name for r in await _rows(db, FAMILY)] == ["Meher"]

    # Both names emptied: nothing is left of it.
    await client.put(f"{RECORDS}/{rec['id']}", json=form(departed_name="", departed_parent_name="",
                                                          family_contact_phone=OTHER_FAMILY), headers=headers)
    assert await _rows(db, OTHER_FAMILY) == []


async def test_nothing_is_written_when_both_names_are_empty(client, db, seeded):
    headers, _ = await manager(client, db)
    r = await client.post(RECORDS, json=form(departed_name="", departed_parent_name=""), headers=headers)
    assert r.status_code == 200, r.text
    assert await _rows(db) == []
    # Only the father's or husband's name known: that is kept.
    await client.post(RECORDS, json=form(departed_name="", departed_parent_name="Jamshed"), headers=headers)
    assert [(r.departed_name, r.departed_parent_name) for r in await _rows(db)] == [("", "Jamshed")]


async def test_get_returns_only_the_callers_own_number_newest_first(client, db, seeded):
    headers, _ = await manager(client, db)
    for name in ("First", "Second", "Third"):
        await client.post(RECORDS, json=form(departed_name=name), headers=headers)
    await client.post(RECORDS, json=form(departed_name="Elsewhere", family_contact_phone=OTHER_FAMILY),
                      headers=headers)

    family = auth(await sign_in(client, FAMILY, "Test Family"))
    got = (await client.get(MINE, headers=family)).json()["names"]
    assert [n["departed_name"] for n in got] == ["Third", "Second", "First"]
    assert set(got[0]) == {"id", "departed_title", "departed_name", "departed_parent_name", "created_at"}
    # A number in the query changes nothing: nothing takes a phone.
    got = (await client.get(MINE, params={"phone": OTHER_FAMILY}, headers=family)).json()["names"]
    assert [n["departed_name"] for n in got] == ["Third", "Second", "First"]

    # Another mobed, and the manager who recorded the death, see none.
    stranger = auth(await sign_in(client, STRANGER, "Er. Stranger"))
    assert (await client.get(MINE, headers=stranger)).json() == {"names": []}
    assert (await client.get(MINE, params={"phone": FAMILY}, headers=stranger)).json() == {"names": []}
    assert (await client.get(MINE, params={"phone": FAMILY}, headers=headers)).json() == {"names": []}
    # A manager's account whose own number has names reads its own pool, like any account.
    again, _ = await manager(client, db, phone=OTHER_FAMILY, name="Other Manager")
    assert [n["departed_name"] for n in (await client.get(MINE, headers=again)).json()["names"]] == ["Elsewhere"]
    # Not signed in: nothing.
    assert (await client.get(MINE)).status_code in (401, 403)


def test_the_only_route_that_reads_the_pool_takes_no_phone():
    # One per app (the behdin app's, R4.0, answers the same way: the signed-in number's own pool, no phone taken).
    assert {c for c in _api_calls() if "person-names" in c[1]} == {("GET", MINE), ("GET", "/api/behdin/me/person-names")}


async def test_a_pair_copies_on_top_once_and_only_whole_pairs(client, db, seeded):
    headers, _ = await manager(client, db)
    await client.post(RECORDS, json=form(), headers=headers)
    owner = (await db.execute(select(User))).scalars().first()
    c = Customer(owner_user_id=owner.id, name="Family (test)", phone=FAMILY)
    db.add(c)
    await db.flush()
    await behdin_directory.replace_section(db, c.id, "pair", [
        {"title": "ervad", "name": "Old Father", "status": "departed", "pair_group": 1},
        {"title": "osti", "name": "Old Mother", "status": "departed", "pair_group": 1},
    ])
    record = (await db.execute(select(FuneralRecord))).scalars().one()
    assert await person_names.copy_into_book(db, c.id, record) is True
    assert await person_names.copy_into_book(db, c.id, record) is False
    rows = await behdin_directory.list_saved_names(db, c.id)
    assert [(r["title"], r["name"], r["status"], r["pair_group"]) for r in rows] == [
        ("behdin", "Rustom", "departed", 2), ("behdin", "Jamshed", "departed", 2),
        ("ervad", "Old Father", "departed", 1), ("osti", "Old Mother", "departed", 1)]
    assert [r["display_order"] for r in rows] == [0, 1, 2, 3]
    # One name only: no half pair is written.
    record.departed_parent_name = None
    record.departed_name = "Solo"
    assert await person_names.copy_into_book(db, c.id, record) is False
    assert await db.scalar(select(CustomerSavedName.id).where(CustomerSavedName.name == "Solo")) is None


async def test_erasure_removes_the_pool_of_that_number_only(client, db, seeded):
    headers, _ = await manager(client, db)
    await client.post(RECORDS, json=form(), headers=headers)
    await client.post(RECORDS, json=form(departed_name="Elsewhere", family_contact_phone=OTHER_FAMILY),
                      headers=headers)
    await erasure.erase_number(db, FAMILY)
    await db.commit()
    assert await _rows(db, FAMILY) == []
    assert [r.departed_name for r in await _rows(db, OTHER_FAMILY)] == ["Elsewhere"]


async def test_deleting_an_account_removes_the_pool_of_its_number(client, db, seeded):
    headers, _ = await manager(client, db)
    await client.post(RECORDS, json=form(), headers=headers)
    await client.post(RECORDS, json=form(departed_name="Elsewhere", family_contact_phone=OTHER_FAMILY),
                      headers=headers)
    family = auth(await sign_in(client, FAMILY, "Test Family"))
    r = await client.post("/api/mobed/auth/account/delete", json={"confirm": True}, headers=family)
    assert r.status_code == 200, r.text
    assert await _rows(db, FAMILY) == []
    assert [r.departed_name for r in await _rows(db, OTHER_FAMILY)] == ["Elsewhere"]
