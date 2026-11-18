"""A funeral place's book of behdins (DECISIONS D10, changed 19 Nov 2026).

The families a Doongerwadi deals with: a name, a number cleaned to E.164 and
their usual fire temple. Private to that place: its managers and the admin
acting for it; another place's manager, a mobed, and an admin who names no
place get nothing. Removing keeps the row (D8) and adding the number again
brings it back. A record's family from the book has their usual fire temple
suggested first. A family's erasure takes them out of every book.
"""

from __future__ import annotations

from sqlalchemy import func, select

from agyary.core import config
from agyary.models import FuneralBehdin
from agyary.services import erasure
from tests.conftest import sign_in
from tests.funeral_helpers import MUMBAI, agyari, auth, form, manager, place

BOOK = "/api/mobed/manager/behdins"
RECORDS = "/api/mobed/manager/records"
FAMILY, OTHER = "+919822200033", "+919822200034"


async def _count(db, *where) -> int:
    return (await db.execute(select(func.count()).select_from(FuneralBehdin).where(*where))).scalar_one()


async def test_a_manager_keeps_their_families(client, db, seeded):
    headers, at = await manager(client, db)
    usual = await agyari(db, "Usual Agyari (test)", MUMBAI)
    await db.commit()
    r = await client.post(BOOK, json={"name": "Test Family", "phone": "+91 098222 00033", "usual_agyary_id": usual.id},
                          headers=headers)
    assert r.status_code == 200, r.text
    fam = r.json()["behdin"]
    assert fam["phone"] == FAMILY and fam["usual_agyari"] == {"id": usual.id, "name": "Usual Agyari (test)",
                                                              "city": "Mumbai"}
    assert fam["funeral_place_id"] == at.id
    await client.post(BOOK, json={"name": "Another Family", "phone": OTHER}, headers=headers)

    listed = (await client.get(BOOK, headers=headers)).json()["behdins"]
    assert [b["name"] for b in listed] == ["Another Family", "Test Family"]
    by_name = (await client.get(BOOK, params={"q": "test fam"}, headers=headers)).json()["behdins"]
    assert [b["id"] for b in by_name] == [fam["id"]]
    by_number = (await client.get(BOOK, params={"q": "200034"}, headers=headers)).json()["behdins"]
    assert [b["name"] for b in by_number] == ["Another Family"]

    # What will not do is said, with the field.
    r = await client.post(BOOK, json={"name": "Twice", "phone": FAMILY}, headers=headers)
    assert r.status_code == 409 and r.headers["X-Field"] == "phone" and "Test Family" in r.json()["detail"]
    r = await client.post(BOOK, json={"name": "Call www.example.com", "phone": "+919822200035"}, headers=headers)
    assert r.status_code == 400 and r.headers["X-Field"] == "name"
    r = await client.post(BOOK, json={"name": "X", "phone": "+919822200035", "usual_agyary_id": 99999},
                          headers=headers)
    assert r.status_code == 400 and r.headers["X-Field"] == "usual_agyary_id"
    assert (await client.post(BOOK, json={"name": "X", "phone": "12"}, headers=headers)).status_code == 422

    # Changed; then taken out (kept, D8), and brought back by adding the number again.
    r = await client.put(f"{BOOK}/{fam['id']}", json={"name": "Test Family Mistry", "phone": FAMILY,
                                                       "usual_agyary_id": None}, headers=headers)
    assert r.status_code == 200 and r.json()["behdin"]["usual_agyari"] is None
    r = await client.put(f"{BOOK}/{fam['id']}", json={"name": "Test Family", "phone": OTHER}, headers=headers)
    assert r.status_code == 409 and r.headers["X-Field"] == "phone"
    assert (await client.delete(f"{BOOK}/{fam['id']}", headers=headers)).status_code == 200
    assert [b["name"] for b in (await client.get(BOOK, headers=headers)).json()["behdins"]] == ["Another Family"]
    assert await _count(db, FuneralBehdin.phone == FAMILY, FuneralBehdin.is_active.is_(False)) == 1
    assert (await client.delete(f"{BOOK}/{fam['id']}", headers=headers)).status_code == 404
    r = await client.post(BOOK, json={"name": "Test Family", "phone": FAMILY}, headers=headers)
    assert r.status_code == 200 and r.json()["behdin"]["id"] == fam["id"]


async def test_the_book_is_the_places_alone(client, db, seeded, monkeypatch):
    headers, at = await manager(client, db)
    fam = (await client.post(BOOK, json={"name": "Test Family", "phone": FAMILY}, headers=headers)).json()["behdin"]
    # A colleague at the same place sees and changes it.
    colleague, _ = await manager(client, db, phone="+919911100073", name="Colleague", at=at)
    assert [b["id"] for b in (await client.get(BOOK, headers=colleague)).json()["behdins"]] == [fam["id"]]
    # Another place's manager: nothing, and 404 for the one they guess.
    other_place = await place(db, "Prayer hall (test)", kind="prayer_hall")
    other, _ = await manager(client, db, phone="+919911100072", name="Other Manager", at=other_place)
    assert (await client.get(BOOK, headers=other)).json()["behdins"] == []
    for method in ("PUT", "DELETE"):
        r = await client.request(method, f"{BOOK}/{fam['id']}", json={"name": "X", "phone": FAMILY}, headers=other)
        assert r.status_code == 404
    r = await client.post(BOOK, json={"name": "X", "phone": OTHER, "funeral_place_id": at.id}, headers=other)
    assert r.status_code == 404
    # A mobed, and an admin who names no place: refused.
    mobed = auth(await sign_in(client, seeded["mobed_phone"]))
    assert (await client.get(BOOK, headers=mobed)).status_code == 403
    monkeypatch.setenv("ADMIN_PHONES", seeded["mobed_phone"])
    config.get_settings.cache_clear()
    try:
        assert (await client.get(BOOK, headers=mobed)).status_code == 403
        # Acting for the place: its book, and what they add is the place's.
        acting = (await client.get(f"{BOOK}?act_for={at.id}", headers=mobed)).json()["behdins"]
        assert [b["id"] for b in acting] == [fam["id"]]
        r = await client.post(f"{BOOK}?act_for={at.id}", json={"name": "Admin Added", "phone": OTHER}, headers=mobed)
        assert r.status_code == 200 and r.json()["behdin"]["funeral_place_id"] == at.id
        assert (await client.get(f"{BOOK}?act_for={other_place.id}", headers=mobed)).json()["behdins"] == []
    finally:
        config.get_settings.cache_clear()


async def test_a_family_from_the_book_has_their_usual_fire_temple_suggested_first(client, db, seeded):
    headers, _ = await manager(client, db)
    far = await agyari(db, "Far Agyari (test)", (23.0, 72.6), city="Ahmedabad")
    await db.commit()
    await client.post(BOOK, json={"name": "Test Family", "phone": FAMILY, "usual_agyary_id": far.id}, headers=headers)
    rec = (await client.post(RECORDS, json=form(family_contact_phone=FAMILY), headers=headers)).json()["record"]
    assert rec["preferred_agyari"] is None
    got = (await client.get(f"{RECORDS}/{rec['id']}/agyaries", headers=headers)).json()["agyaries"]
    assert got[0]["id"] == far.id and got[0]["preferred"] is True
    # A family the manager chose a fire temple for keeps that choice first.
    rec = (await client.post(RECORDS, json=form(family_contact_phone=FAMILY,
                                                preferred_agyary_id=seeded["agyary_id"]), headers=headers)).json()["record"]
    got = (await client.get(f"{RECORDS}/{rec['id']}/agyaries", headers=headers)).json()["agyaries"]
    assert got[0]["id"] == seeded["agyary_id"]


async def test_erasing_a_family_takes_them_out_of_every_book(client, db, seeded):
    headers, _ = await manager(client, db)
    other_place = await place(db, "Prayer hall (test)", kind="prayer_hall")
    other, _ = await manager(client, db, phone="+919911100072", name="Other Manager", at=other_place)
    for h in (headers, other):
        await client.post(BOOK, json={"name": "Test Family", "phone": FAMILY}, headers=h)
    await client.post(BOOK, json={"name": "Another Family", "phone": OTHER}, headers=headers)
    assert (await erasure.what_we_hold(db, FAMILY))["funeral_books"] == 2
    await erasure.erase_number(db, FAMILY)
    await db.commit()
    assert await _count(db, FuneralBehdin.phone == FAMILY) == 0
    assert await _count(db, FuneralBehdin.phone == OTHER) == 1


async def test_no_sign_in_no_book(client):
    assert (await client.get(BOOK)).status_code == 401
