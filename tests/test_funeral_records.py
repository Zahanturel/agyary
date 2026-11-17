"""A funeral place's manager records a death (DECISIONS D10, D5, D8; Phase 2
Step 4).

Only what the prayers need is asked; every piece of free text follows the rules
for text others will read; the death is given by date or by Roj and Mah and
both are kept, with the Roj and Mah shown to confirm. A record is seen only by
its own place's managers, and none of this is open to a mobed.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from agyary.api.routes import mobed as mobed_routes
from agyary.calendar import CalendarSystem, gregorian_to_parsi
from agyary.core import config
from agyary.models import FuneralPlace, FuneralRecord, FuneralRequest
from agyary.services import funeral_records
from tests.conftest import sign_in
from tests.funeral_helpers import FAMILY, agyari, auth, form, manager, place
from tests.test_funeral_managers import _api_calls

RECORDS = "/api/mobed/manager/records"


@pytest.fixture
def admin_is_panthaky(monkeypatch, seeded):
    monkeypatch.setenv("ADMIN_PHONES", seeded["panthaky_phone"])
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def test_a_death_by_its_date_is_kept_with_its_roj_and_mah(client, db, seeded):
    headers, _ = await manager(client, db)
    body = form()
    r = await client.post(RECORDS, json=body, headers=headers)
    assert r.status_code == 200, r.text
    rec = r.json()["record"]
    death = date.fromisoformat(body["death_date"])
    p = gregorian_to_parsi(death, CalendarSystem.SHENSHAI)
    assert rec["death"]["date"] == body["death_date"] and rec["death"]["given_by"] == "date"
    assert (rec["death"]["roj"], rec["death"]["year"]) == ((p.gatha_index if p.is_gatha else p.roj), p.year)
    assert rec["death"]["label"] == funeral_records.parsi_label(death, CalendarSystem.SHENSHAI)
    assert rec["prayed_name"] == "Behdin Rustom Jamshed"
    assert rec["geh_saarnu"]["geh_name"] == "Havan" and rec["uthamna"]["time"] == "16:00"
    assert rec["family_contact"] == {"name": "Test Family", "phone": FAMILY}
    assert rec["may_edit"] is True and rec["may_send"] is True and rec["requests"] == []


async def test_a_death_by_roj_and_mah_is_the_most_recent_such_day(client, db, seeded):
    """D5: a death before sunrise belongs to the previous Parsi day, so the
    manager can give the Roj and Mah; the date is worked out and shown."""
    headers, _ = await manager(client, db)
    day = funeral_records.today_ist() - timedelta(days=2)
    p = gregorian_to_parsi(day, CalendarSystem.KADMI)
    roj, mah = (p.gatha_index, 13) if p.is_gatha else (p.roj, p.mah)
    asked = {"calendar": "kadmi", "death_date": None, "death_roj": roj, "death_mah": mah}
    r = await client.post("/api/mobed/manager/death-day", json=asked, headers=headers)
    assert r.status_code == 200 and r.json()["date"] == day.isoformat() and r.json()["given_by"] == "roj_mah"
    rec = (await client.post(RECORDS, json=form(**asked), headers=headers)).json()["record"]
    assert rec["death"]["date"] == day.isoformat() and (rec["death"]["roj"], rec["death"]["mah"]) == (roj, mah)
    assert rec["death"]["calendar"] == "kadmi" and rec["death"]["given_by"] == "roj_mah"


async def test_a_gatha_day_is_a_death_day_too(client, db, seeded):
    headers, _ = await manager(client, db)
    r = await client.post("/api/mobed/manager/death-day", json={"death_roj": 2, "death_mah": 13}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["mah"] == 13 and r.json()["roj"] == 2 and "(Gatha day)" in r.json()["label"]


@pytest.mark.parametrize("changes, field", [
    ({"death_roj": 3, "death_mah": 4}, "death"),                       # a date and a Roj and Mah
    ({"death_date": None}, "death"),                                  # neither
    ({"death_date": "2099-01-01"}, "death"),                          # after today
    ({"death_date": "2020-01-01"}, "death"),                          # not this year's
    ({"death_date": None, "death_roj": 31, "death_mah": 4}, "death"),
    ({"calendar": "fasli"}, "calendar"),                              # no Fasli (D5)
    ({"departed_title": "khud"}, "departed_title"),
    ({"departed_name": "  "}, "departed_name"),
    ({"departed_name": "Rustom www.example.com"}, "departed_name"),
    ({"departed_parent_name": "@someone"}, "departed_parent_name"),
    ({"departed_name": "R" * 70}, "departed_name"),                   # with the title and parent, over 80
    ({"obsequies": "three_days"}, "obsequies"),
    ({"bungli": "Bungli 3, call 98765 43210"}, "bungli"),
    ({"geh_saarnu_geh": 4}, "geh_saarnu_geh"),                        # Aiwisruthrem is at night
    ({"geh_saarnu_geh": None}, "geh_saarnu_geh"),
    ({"geh_saarnu_date": None}, "geh_saarnu_date"),
    ({"geh_saarnu_date": "2020-01-01"}, "geh_saarnu_date"),           # before the death
    ({"uthamna_date": None}, "uthamna_date"),                         # a time and no day
    ({"mobeds_wanted": 0}, "mobeds_wanted"),
    ({"preferred_agyary_id": 99999}, "preferred_agyary_id"),
    ({"family_contact_name": ""}, "family_contact_name"),
    ({"family_contact_name": "Ask at https://x.example"}, "family_contact_name"),
    ({"family_contact_phone": "12345"}, "family_contact_phone"),
])
async def test_each_field_that_will_not_do_is_named(client, db, seeded, changes, field):
    headers, _ = await manager(client, db)
    r = await client.post(RECORDS, json=form(**changes), headers=headers)
    assert r.status_code == 400, (changes, r.text)
    assert r.headers["X-Field"] == field, (changes, r.json())
    assert (await db.execute(select(FuneralRecord))).first() is None


async def test_what_is_not_recorded_has_nowhere_to_go(client, db, seeded):
    """D10: cause of death, age, address, the certificate, ID numbers and how
    the body goes are not asked for, and are not kept if sent."""
    columns = set(FuneralRecord.__table__.columns.keys())
    for never in ("cause", "age", "address", "certificate", "aadhaar", "id_number", "disposal", "cremation"):
        assert not any(never in c for c in columns), never
    headers, _ = await manager(client, db)
    r = await client.post(RECORDS, json=form(cause_of_death="x", age=90, address="y"), headers=headers)
    assert r.status_code == 200 and not {"cause_of_death", "age", "address"} & set(r.json()["record"])


async def test_optional_parts_can_be_left_out(client, db, seeded):
    headers, _ = await manager(client, db)
    body = form(departed_parent_name=None, bungli="", geh_saarnu_date=None, geh_saarnu_geh=None,
                uthamna_date=None, uthamna_time=None, mobeds_wanted=None, obsequies="one_day")
    rec = (await client.post(RECORDS, json=body, headers=headers)).json()["record"]
    assert rec["prayed_name"] == "Behdin Rustom" and rec["bungli"] is None
    assert rec["geh_saarnu"] is None and rec["uthamna"] is None and rec["obsequies_label"] == "One day"


async def test_a_manager_sees_only_their_own_places_records(client, db, seeded):
    headers, mine = await manager(client, db)
    other_place = await place(db, "Prayer hall (test)", kind="prayer_hall")
    other, _ = await manager(client, db, phone="+919911100072", name="Other Manager", at=other_place)
    colleague, _ = await manager(client, db, phone="+919911100073", name="Colleague", at=mine)
    rec = (await client.post(RECORDS, json=form(), headers=headers)).json()["record"]

    assert (await client.get(RECORDS, headers=other)).json()["records"] == []
    for method in ("GET", "PUT"):
        r = await client.request(method, f"{RECORDS}/{rec['id']}", json=form(), headers=other)
        assert r.status_code == 404 and r.json()["detail"] == "That record could not be found."
    # A record of their place to one who is not its manager cannot be made either.
    r = await client.post(RECORDS, json=form(funeral_place_id=mine.id), headers=other)
    assert r.status_code == 404
    # A colleague at the same place sees and can change it.
    listed = (await client.get(RECORDS, headers=colleague)).json()["records"]
    assert [x["id"] for x in listed] == [rec["id"]]
    r = await client.put(f"{RECORDS}/{rec['id']}", json=form(bungli="Bungli 5"), headers=colleague)
    assert r.status_code == 200 and r.json()["record"]["bungli"] == "Bungli 5"


async def test_a_record_changes_until_a_fire_temple_accepts_it(client, db, seeded):
    headers, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(), headers=headers)).json()["record"]
    r = await client.put(f"{RECORDS}/{rec['id']}", json=form(departed_name="Rustomji"), headers=headers)
    assert r.status_code == 200 and r.json()["record"]["prayed_name"] == "Behdin Rustomji Jamshed"
    # Accepted (Step 5 does this): it is then the accepter's, and stays as it was.
    a = await agyari(db, "Agyari (test)", None)
    now = datetime.now(timezone.utc)
    db.add(FuneralRequest(funeral_record_id=rec["id"], agyary_id=a.id, status="accepted",
                          family_share_agreed_at=now, decided_at=now))
    await db.commit()
    r = await client.put(f"{RECORDS}/{rec['id']}", json=form(departed_name="Someone else"), headers=headers)
    assert r.status_code == 409 and "accepted" in r.json()["detail"]
    got = (await client.get(f"{RECORDS}/{rec['id']}", headers=headers)).json()["record"]
    assert got["departed_name"] == "Rustomji" and got["may_edit"] is False and got["may_send"] is False


async def test_a_place_that_is_turned_off_takes_no_new_record(client, db, seeded):
    headers, at = await manager(client, db)
    await db.execute(update(FuneralPlace).where(FuneralPlace.id == at.id).values(is_active=False))
    await db.commit()
    r = await client.post(RECORDS, json=form(), headers=headers)
    assert r.status_code == 409 and "turned off" in r.json()["detail"]


async def test_the_records_list_newest_first_a_page_at_a_time(client, db, seeded, monkeypatch):
    monkeypatch.setattr(funeral_records, "PAGE", 2)
    headers, _ = await manager(client, db)
    ids = [(await client.post(RECORDS, json=form(departed_name=f"Name {n}"), headers=headers)).json()["record"]["id"]
           for n in "abc"]
    first = (await client.get(RECORDS, headers=headers)).json()
    assert [r["id"] for r in first["records"]] == ids[:0:-1] and first["more"] is True
    rest = (await client.get(f"{RECORDS}?before={ids[1]}", headers=headers)).json()
    assert [r["id"] for r in rest["records"]] == [ids[0]]


async def test_no_mobed_reaches_the_managers_side(client, db, seeded, admin_is_panthaky):
    """Every manager route refuses a mobed's account, an admin's included."""
    manager_calls = sorted(c for c in _api_calls() if c[1].startswith("/api/mobed/manager/"))
    assert len(manager_calls) >= 6
    for phone in (seeded["mobed_phone"], seeded["panthaky_phone"]):
        headers = auth(await sign_in(client, phone))
        for method, path in manager_calls:
            r = await client.request(method, re.sub(r"\{[^}]+\}", "1", path), json={}, headers=headers)
            assert r.status_code == 403 and r.json()["detail"] == mobed_routes.NOT_FOR_MOBEDS, (phone, path)
        r = await client.request("GET", RECORDS)
        assert r.status_code == 401


async def test_a_managers_account_going_leaves_the_record(client, db, seeded):
    """D8: the record is the place's. The account goes, the record stays."""
    headers, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(), headers=headers)).json()["record"]
    r = await client.post("/api/mobed/auth/account/delete", json={"confirm": True}, headers=headers)
    assert r.status_code == 200
    row = (await db.execute(select(FuneralRecord).where(FuneralRecord.id == rec["id"]))).scalar_one()
    await db.refresh(row)
    assert row.created_by_user_id is None and row.departed_name == "Rustom"
