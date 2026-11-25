"""R4.1: what a person keeps for themselves in the behdin app (docs/DECISIONS.md, 25 Nov 2026).

My agyari and the list to choose it from (position in a body, never echoed, stored or logged),
the person's own memorials (the mobed side's engine, called as it is), their events and the
calendar that holds them. Everything is the one account's: another person gets a 404, the
account's deletion and an erasure take it all, and no mobed or admin code reads it.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select, text

from agyary.calendar import CalendarSystem, gregorian_to_parsi
from agyary.models import User
from agyary.services import erasure, memorials
from tests.funeral_helpers import agyari
from tests.test_behdin_identity import auth, behdin_sign_in

ME, OTHER = "+919911100081", "+919911100082"
SRC = Path(__file__).resolve().parent.parent / "src" / "agyary"
OWN_TABLES = ("person_agyari", "person_memorials", "person_memorial_observances", "person_events")
MUMBAI = (18.96, 72.83)
DELHI = (28.61, 77.21)


async def two_people(client):
    mine = auth(await behdin_sign_in(client, ME, "Farzin Meherzad Turel"))
    theirs = auth(await behdin_sign_in(client, OTHER, "Delzeen Cyrus Mehta"))
    return mine, theirs


async def count(db, table: str) -> int:
    return (await db.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


MEMORIAL = {
    "departed_name": "Dinshaw Rustom Mehta", "death_date": "2026-11-01", "calendar": "shenshai",
    "day_counts": [10, 30], "monthly": {"count": 3}, "yearly": {"count": 2},
}


# --- the list of agyaries, and my agyari -----------------------------------------------------
async def test_the_list_needs_a_sign_in_and_takes_the_position_in_the_body(client, db):
    # The list of fire temples taking requests is tested in tests/test_service_asks.py (R4.2 redesign).
    assert (await client.post("/api/behdin/agyaries/find", json={})).status_code == 401
    mine = auth(await behdin_sign_in(client, ME))
    # A position in the address is not a way in: only the body counts.
    assert (await client.post("/api/behdin/agyaries/find?lat=18.9&lng=72.8", headers=mine)).status_code == 422
    r = await client.post("/api/behdin/agyaries/find", headers=mine, json={"lat": 18.9, "lng": 72.8})
    assert r.status_code == 200 and r.json() == {"agyaries": []}      # nobody is taking requests yet


async def test_the_position_is_never_stored_or_logged(client, db, caplog):
    mine = auth(await behdin_sign_in(client, ME))
    with caplog.at_level(logging.DEBUG):
        await client.post("/api/behdin/agyaries/find", headers=mine, json={"lat": 18.123457, "lng": 72.654321})
    assert "18.123457" not in caplog.text and "72.654321" not in caplog.text
    columns = (await db.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"
        " AND (column_name IN ('lat', 'lng', 'latitude', 'longitude'))"
    ))).all()
    # Only places have a position (fire temples, Doongerwadis); nothing about a person does.
    assert {t for t, _c in columns} == {"agyaries", "funeral_places"}


async def test_my_agyari_is_one_per_person_and_free_to_change(client, db, seeded):
    mine, theirs = await two_people(client)
    other = await agyari(db, "Other Agyari (test)", MUMBAI)
    await db.commit()
    assert (await client.get("/api/behdin/me/agyari", headers=mine)).json() == {"agyari": None}
    r = await client.put("/api/behdin/me/agyari", headers=mine, json={"agyary_id": seeded["agyary_id"]})
    assert r.status_code == 200 and r.json()["agyari"]["name"] == "Goti Adarian"
    assert r.json()["agyari"]["answers_in_app"] is True
    r = await client.put("/api/behdin/me/agyari", headers=mine, json={"agyary_id": other.id})
    assert r.json()["agyari"]["name"] == "Other Agyari (test)"
    assert await count(db, "person_agyari") == 1
    assert (await client.get("/api/behdin/me/agyari", headers=theirs)).json() == {"agyari": None}
    assert (await client.put("/api/behdin/me/agyari", headers=mine, json={"agyary_id": 999999})).status_code == 404
    assert (await client.delete("/api/behdin/me/agyari", headers=mine)).json() == {"agyari": None}
    assert await count(db, "person_agyari") == 0


# --- memorials ---------------------------------------------------------------------------------
async def test_a_memorials_dates_are_the_engines_dates(client, db):
    mine = auth(await behdin_sign_in(client, ME))
    r = await client.post("/api/behdin/me/memorials", headers=mine, json=MEMORIAL)
    assert r.status_code == 200, r.text
    made = r.json()
    choice = memorials.Choice(
        departed_name="Dinshaw Rustom Mehta", death_date=date(2026, 11, 1), calendar="shenshai",
        day_counts=(10, 30), monthly_months=3, yearly_years=2,
    )
    schedule, death, death_date = memorials.plan(CalendarSystem.SHENSHAI, choice, memorials.today_ist())
    assert [(o["code"], o["date"]) for o in made["observances"]] == [
        (o.code, o.gregorian_date.isoformat()) for o in sorted(schedule, key=lambda o: (o.gregorian_date, o.day_number))
    ]
    assert (made["death_roj"], made["death_mah"], made["death_year"]) == death
    assert made["death_date"] == death_date.isoformat() and made["count"] == len(schedule)
    first = made["observances"][0]
    assert first["parsi_roj"] and first["parsi_mah"] and first["parsi"]["display"]
    assert made["choices"]["monthly"] == {"count": 3} and made["choices"]["day_counts"] == [10, 30]

    listed = (await client.get("/api/behdin/me/memorials", headers=mine)).json()["memorials"]
    assert [m["id"] for m in listed] == [made["id"]] and "observances" not in listed[0]
    assert listed[0]["departed_name"] == "Dinshaw Rustom Mehta"
    one = (await client.get(f"/api/behdin/me/memorials/{made['id']}", headers=mine)).json()
    assert one["observances"] == made["observances"]


async def test_a_memorial_without_a_name_reads_name_not_known_and_one_long_ago_hides_its_date(client, db):
    mine = auth(await behdin_sign_in(client, ME))
    r = await client.post("/api/behdin/me/memorials", headers=mine, json={
        "death_roj": 5, "death_mah": 3, "long_ago": True, "monthly": {"count": 2}, "yearly": {"count": 1},
    })
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["departed_name"] == "(name not known)" and m["name_known"] is False
    assert m["long_ago"] is True and m["death_date"] is None and m["death_year"] is None
    assert (m["death_roj"], m["death_mah"]) == (5, 3)
    # Nothing here says mobed, and a bad choice comes back in plain words.
    bad = await client.post("/api/behdin/me/memorials", headers=mine, json={"departed_name": "A B"})
    assert bad.status_code == 400 and "mobed" not in bad.text.lower()
    nothing = await client.post("/api/behdin/me/memorials", headers=mine, json={
        "departed_name": "A B", "death_date": "2026-11-01"})
    assert nothing.status_code == 400 and "mobed" not in nothing.text.lower()
    assert "Choose at least one day" in nothing.json()["detail"]


async def test_a_memorial_can_be_reworked_and_deleted(client, db):
    mine = auth(await behdin_sign_in(client, ME))
    made = (await client.post("/api/behdin/me/memorials", headers=mine, json=MEMORIAL)).json()
    before = made["count"]
    r = await client.patch(f"/api/behdin/me/memorials/{made['id']}", headers=mine,
                           json={**MEMORIAL, "monthly": {"count": 6}, "yearly": None})
    assert r.status_code == 200, r.text
    assert r.json()["count"] != before and r.json()["choices"]["monthly"] == {"count": 6}
    assert r.json()["choices"]["yearly"] is None
    assert await count(db, "person_memorial_observances") == r.json()["count"]
    assert (await client.delete(f"/api/behdin/me/memorials/{made['id']}", headers=mine)).json() == {"deleted": True}
    assert await count(db, "person_memorials") == 0 and await count(db, "person_memorial_observances") == 0
    assert (await client.get(f"/api/behdin/me/memorials/{made['id']}", headers=mine)).status_code == 404


async def test_a_memorials_name_is_copied_nowhere_else(client, db):
    mine = auth(await behdin_sign_in(client, ME))
    await client.post("/api/behdin/me/memorials", headers=mine, json=MEMORIAL)
    assert await count(db, "person_names") == 0 and await count(db, "customers") == 0
    assert await count(db, "memorials") == 0


# --- another person's ids are not there --------------------------------------------------------
async def test_another_person_gets_a_404_for_my_ids_and_never_sees_my_things(client, db):
    mine, theirs = await two_people(client)
    memorial = (await client.post("/api/behdin/me/memorials", headers=mine, json=MEMORIAL)).json()
    event = (await client.post("/api/behdin/me/events", headers=mine, json={
        "title": "Farzin's birthday", "kind": "birthday", "date": "1990-03-04", "repeats": "yearly_english",
    })).json()
    mid, eid = memorial["id"], event["id"]
    assert (await client.get(f"/api/behdin/me/memorials/{mid}", headers=theirs)).status_code == 404
    assert (await client.patch(f"/api/behdin/me/memorials/{mid}", headers=theirs, json=MEMORIAL)).status_code == 404
    assert (await client.delete(f"/api/behdin/me/memorials/{mid}", headers=theirs)).status_code == 404
    assert (await client.patch(f"/api/behdin/me/events/{eid}", headers=theirs, json={"title": "x"})).status_code == 404
    assert (await client.delete(f"/api/behdin/me/events/{eid}", headers=theirs)).status_code == 404
    assert (await client.get("/api/behdin/me/memorials", headers=theirs)).json() == {"memorials": []}
    assert (await client.get("/api/behdin/me/events", headers=theirs)).json() == {"events": []}
    cal = (await client.get("/api/behdin/me/calendar?from=2026-01-01&to=2027-01-01", headers=theirs)).json()
    assert cal["items"] == []
    # Still all there for me.
    assert (await client.get(f"/api/behdin/me/memorials/{mid}", headers=mine)).status_code == 200
    assert len((await client.get("/api/behdin/me/events", headers=mine)).json()["events"]) == 1


# --- events and the calendar -------------------------------------------------------------------
async def test_events_and_the_calendar_expand_yearly_ones_by_english_and_by_parsi_date(client, db):
    mine = auth(await behdin_sign_in(client, ME))
    post = lambda body: client.post("/api/behdin/me/events", headers=mine, json=body)  # noqa: E731
    once = (await post({"title": "Navjote", "kind": "navjote", "date": "2026-12-05", "notes": "At the agyari"})).json()
    english = (await post({"title": "Birthday", "kind": "birthday", "date": "2000-02-29",
                           "repeats": "yearly_english"})).json()
    parsi = (await post({"title": "Parsi birthday", "kind": "birthday", "date": "1990-03-04",
                         "repeats": "yearly_parsi"})).json()
    assert once["notes"] == "At the agyari" and once["repeats"] == "none"
    p = gregorian_to_parsi(date(1990, 3, 4), CalendarSystem.SHENSHAI)
    assert (parsi["parsi_roj"], parsi["parsi_mah"]) == (p.roj, p.mah)
    row = (await db.execute(text("SELECT parsi_roj, parsi_mah, parsi_calendar FROM person_events WHERE id = :i"),
                            {"i": parsi["id"]})).one()
    assert tuple(row) == (p.roj, p.mah, "shenshai")

    cal = (await client.get("/api/behdin/me/calendar?from=2026-12-01&to=2028-01-01", headers=mine)).json()
    items = cal["items"]
    assert [i["date"] for i in items if i["title"] == "Navjote"] == ["2026-12-05"]
    assert [i["date"] for i in items if i["title"] == "Birthday"] == ["2027-02-28"]
    leap = (await client.get("/api/behdin/me/calendar?from=2028-02-01&to=2028-03-01", headers=mine)).json()["items"]
    assert [i["date"] for i in leap if i["title"] == "Birthday"] == ["2028-02-29"]
    parsi_days = [i["date"] for i in items if i["title"] == "Parsi birthday"]
    assert len(parsi_days) in (1, 2)
    for day in parsi_days:
        again = gregorian_to_parsi(date.fromisoformat(day), CalendarSystem.SHENSHAI)
        assert (again.roj, again.mah) == (p.roj, p.mah)
    one = next(i for i in items if i["title"] == "Navjote")
    assert one["kind"] == "navjote" and one["parsi_roj"] and one["parsi_mah"] and one["parsi"]["display"]
    assert [i["date"] for i in items] == sorted(i["date"] for i in items)
    # An event is not shown before its own first day.
    early = (await client.get("/api/behdin/me/calendar?from=1989-01-01&to=1989-12-31", headers=mine)).json()
    assert early["items"] == []
    # Edit and delete.
    changed = await client.patch(f"/api/behdin/me/events/{english['id']}", headers=mine,
                                 json={"title": "Birthday party", "repeats": "none"})
    assert changed.status_code == 200 and changed.json()["title"] == "Birthday party"
    assert (await client.patch(f"/api/behdin/me/events/{english['id']}", headers=mine,
                               json={"kind": "party"})).status_code == 400
    assert (await client.delete(f"/api/behdin/me/events/{once['id']}", headers=mine)).json() == {"deleted": True}


async def test_the_calendar_holds_memorial_dates_and_refuses_a_range_over_400_days(client, db):
    mine = auth(await behdin_sign_in(client, ME))
    made = (await client.post("/api/behdin/me/memorials", headers=mine, json=MEMORIAL)).json()
    first, last = made["observances"][0], made["observances"][-1]
    start = date.fromisoformat(first["date"])
    cal = (await client.get(f"/api/behdin/me/calendar?from={start}&to={start + timedelta(days=399)}",
                            headers=mine)).json()
    mine_in_range = [i for i in cal["items"] if i["source"] == "memorial"]
    assert mine_in_range and mine_in_range[0]["date"] == first["date"] and mine_in_range[0]["kind"] == "memorial"
    assert mine_in_range[0]["parsi_roj"] == first["parsi_roj"] and mine_in_range[0]["parsi_mah"] == first["parsi_mah"]
    assert "Dinshaw Rustom Mehta" in mine_in_range[0]["title"]
    assert last["date"] >= first["date"]
    too_long = await client.get(f"/api/behdin/me/calendar?from={start}&to={start + timedelta(days=400)}", headers=mine)
    assert too_long.status_code == 400
    backwards = await client.get("/api/behdin/me/calendar?from=2026-02-01&to=2026-01-01", headers=mine)
    assert backwards.status_code == 400


# --- deletion, erasure, and who may read them --------------------------------------------------
async def _keep_things(client, mine) -> None:
    await client.post("/api/behdin/me/memorials", headers=mine, json=MEMORIAL)
    await client.post("/api/behdin/me/events", headers=mine, json={"title": "Day", "kind": "other", "date": "2026-12-05"})


async def test_deleting_the_account_removes_all_of_it_and_only_theirs(client, db, seeded):
    mine, theirs = await two_people(client)
    for headers in (mine, theirs):
        await _keep_things(client, headers)
        await client.put("/api/behdin/me/agyari", headers=headers, json={"agyary_id": seeded["agyary_id"]})
    before = {t: await count(db, t) for t in OWN_TABLES}
    assert all(n > 0 for n in before.values())
    r = await client.request("DELETE", "/api/behdin/account", headers=mine, json={"confirm": True})
    assert r.status_code == 200, r.text
    me = (await db.execute(select(User.id).where(User.phone == ME))).scalar_one_or_none()
    assert me is None
    for table in OWN_TABLES:
        assert await count(db, table) == before[table] // 2
    # What is left is the other person's, and still theirs alone.
    assert len((await client.get("/api/behdin/me/memorials", headers=theirs)).json()["memorials"]) == 1


async def test_erasing_a_number_takes_what_that_account_kept(client, db):
    mine, theirs = await two_people(client)
    await _keep_things(client, mine)
    await _keep_things(client, theirs)
    await erasure.erase_number(db, ME)
    await db.commit()
    assert await count(db, "person_memorials") == 1 and await count(db, "person_events") == 1
    owners = (await db.execute(text("SELECT DISTINCT user_id FROM person_events"))).scalars().all()
    other = (await db.execute(select(User.id).where(User.phone == OTHER))).scalar_one()
    assert owners == [other]


def test_no_mobed_or_admin_code_reads_a_persons_own_things():
    """The tables are named only where the person's own routes and services use them (and in the
    two wipes, by plain SQL): no mobed, fire temple or admin service or route imports the models."""
    allowed = {"api/routes/behdin_me.py", "services/behdin_me.py", "models/person_own.py", "models/__init__.py"}
    pattern = re.compile(r"PersonMemorial|PersonEvent|PersonAgyari|person_own")
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel not in allowed and pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert offenders == []
    for rel in ("api/routes/behdin_me.py", "services/behdin_me.py"):
        # Nothing a Parsi person can read names the other app.
        for line in (SRC / rel).read_text(encoding="utf-8").splitlines():
            if re.search(r"detail=|raise PersonError|Error\(", line):
                assert "mobed" not in line.lower() and "diary" not in line.lower(), line
