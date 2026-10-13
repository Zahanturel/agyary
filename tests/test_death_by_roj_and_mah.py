"""A death given by its Parsi day (docs/DECISIONS.md D5).

A death before sunrise belongs to the previous Parsi day, and the mobed knows
which Parsi day it was. So the memorial form and API take the death either as a
Gregorian date or as Roj and Mah (and year) in the family's calendar. Without a
year it is the most recent such day. The schedule is then counted exactly as
from the matching Gregorian date, and the preview shows both so the mobed can
confirm.
"""

from __future__ import annotations

from datetime import date

from agyary.calendar import CalendarSystem, gregorian_to_parsi, parsi_to_gregorian
from agyary.services.memorials import today_ist
from tests.test_mobed_api import _member_headers

SHENSHAI = CalendarSystem.SHENSHAI


async def _preview(client, seeded, **death):
    aid = seeded["agyary_id"]
    h = await _member_headers(client, seeded)
    body = {"departed_name": "Ardeshir Mehta", "opening": "tenth_only", "monthly": {"count": 2},
            "calendar": "shenshai", **death}
    return await client.post(f"/api/mobed/agyaries/{aid}/memorials/preview", headers=h, json=body)


async def test_roj_mah_and_year_give_the_same_schedule_as_the_date(client, db, seeded):
    by_parsi = await _preview(client, seeded, death_roj=9, death_mah=12, death_year=1395)
    assert by_parsi.status_code == 200, by_parsi.text
    by_date = await _preview(client, seeded, death_date="2026-07-19")       # Roj Adar, Mah Aspandard 1395
    assert by_parsi.json()["death_date"] == "2026-07-19"
    assert by_parsi.json()["death"] == by_date.json()["death"] == {"roj": 9, "mah": 12, "year": 1395}
    assert by_parsi.json()["observances"] == by_date.json()["observances"]


async def test_without_a_year_it_is_the_most_recent_such_day(client, db, seeded):
    today = today_ist()
    here = gregorian_to_parsi(today, SHENSHAI)
    r = await _preview(client, seeded, death_roj=1, death_mah=1)          # Roj Hormazd, Mah Fravardin
    assert r.status_code == 200, r.text
    got = date.fromisoformat(r.json()["death_date"])
    assert got <= today and gregorian_to_parsi(got, SHENSHAI).roj == 1
    assert (today - got).days < 366
    # It is the latest one: the same day a Parsi year later would be after today.
    nxt = parsi_to_gregorian(gregorian_to_parsi(got, SHENSHAI).year + 1, SHENSHAI, mah=1, roj=1)
    assert nxt > today or here.year == gregorian_to_parsi(got, SHENSHAI).year


async def test_a_gatha_day_can_be_given(client, db, seeded):
    r = await _preview(client, seeded, death_roj=5, death_mah=13, death_year=1395)   # Vahishtoisht
    assert r.status_code == 200, r.text
    assert r.json()["death_date"] == "2026-08-14" and r.json()["death"]["mah"] == 13


async def test_one_way_of_giving_the_death_not_both_or_neither(client, db, seeded):
    both = await _preview(client, seeded, death_date="2026-07-19", death_roj=9, death_mah=12)
    neither = await _preview(client, seeded)
    half = await _preview(client, seeded, death_roj=9)
    for r in (both, neither, half):
        assert r.status_code in (400, 422), r.text
    bad = await _preview(client, seeded, death_roj=31, death_mah=1)
    assert bad.status_code in (400, 422)


async def test_a_memorial_saved_by_roj_and_mah_stores_the_date(client, db, seeded):
    aid = seeded["agyary_id"]
    h = await _member_headers(client, seeded)
    cid = (await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=h,
                             json={"name": "Family", "phone": "+919944401901"})).json()["id"]
    sid = next(s["id"] for s in (await client.get(f"/api/mobed/agyaries/{aid}/services", headers=h)).json()
               if s["name"] == "Afringan")
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials", headers=h, json={
        "departed_name": "Ardeshir Mehta", "death_roj": 9, "death_mah": 12, "death_year": 1395,
        "calendar": "shenshai", "opening": "tenth_only", "monthly": {"count": 1}, "service_ids": [sid]})
    assert r.status_code == 200, r.text
    assert r.json()["death_date"] == "2026-07-19"


async def test_a_death_before_sunrise_is_counted_from_the_parsi_day_it_belonged_to(client, db, seeded):
    # Died at 4 am on Tue 18 Aug 2026, before sunrise: by Parsi reckoning that is
    # still the day of Mon 17 Aug. The mobed gives that Parsi day; the schedule
    # must then run from 17 Aug, not from the 18th printed on the certificate.
    parsi_day = gregorian_to_parsi(date(2026, 8, 17), SHENSHAI)
    by_parsi = await _preview(client, seeded, death_roj=parsi_day.roj, death_mah=parsi_day.mah,
                              death_year=parsi_day.year)
    assert by_parsi.status_code == 200, by_parsi.text
    assert by_parsi.json()["death_date"] == "2026-08-17"
    same_day = await _preview(client, seeded, death_date="2026-08-17")
    certificate = await _preview(client, seeded, death_date="2026-08-18")
    assert by_parsi.json()["observances"] == same_day.json()["observances"]
    assert by_parsi.json()["observances"] != certificate.json()["observances"]
    # Every observance is a day earlier than counting from the certificate's date.
    first = date.fromisoformat(by_parsi.json()["observances"][0]["date"])
    assert (date.fromisoformat(certificate.json()["observances"][0]["date"]) - first).days == 1
