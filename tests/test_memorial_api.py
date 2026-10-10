"""Memorials over the API: creating a schedule, keeping it private to the
mobed who made it, editing one observance at a time, and the calendar feed
with its closing notice.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from agyary.calendar import CalendarSystem, parsi_to_gregorian
from agyary.models import (
    Agyary, Customer, Memorial, MemorialObservance, Service,
)
from agyary.services import memorials
from tests.test_mobed_api import _member_headers

PHONE = "+919944400701"
OTHER_MOBED = "+919911100077"

# A death well in the future, so every observance is still ahead.
DEATH = date(2030, 3, 10)


async def _setup(client, db, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins",
                          json={"name": "Behdin Memorial", "phone": PHONE}, headers=headers)
    assert r.status_code == 200, r.text
    return aid, r.json()["id"], headers


async def _service_ids(db, aid, *names):
    rows = (await db.execute(
        select(Service.name, Service.id).where(Service.agyary_id == aid, Service.name.in_(names))
    )).all()
    by_name = dict(rows)
    return [by_name[n] for n in names]


def _body(death: date, **over):
    body = {
        "departed_name": "Dinshaw", "death_date": death.isoformat(),
        "opening": "days_1_to_10", "day_counts": [30],
        "monthly": {"count": 3}, "service_ids": [],
    }
    body.update(over)
    return body


async def _create(client, db, aid, cid, headers, death=DEATH, **over):
    ids = over.pop("service_ids", None) or await _service_ids(db, aid, "Afringan", "Baaj")
    return await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials",
                             json=_body(death, service_ids=ids, **over), headers=headers)


async def test_baaj_is_in_the_catalog(db, seeded):
    names = (await db.execute(select(Service.name).where(Service.agyary_id == seeded["agyary_id"]))).scalars().all()
    assert "Baaj" in names and "Afringan" in names


async def test_create_gives_every_observance_the_same_services(db, client, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    ids = await _service_ids(db, aid, "Afringan", "Baaj")
    r = await _create(client, db, aid, cid, headers, service_ids=ids)
    assert r.status_code == 200, r.text
    body = r.json()
    # days 1-10 (10) + Masiso, which is the first of the 3 monthly (31, 61, 91)
    assert body["total"] == 13 and body["status"] == "running"
    assert all(o["service_ids"] == sorted(ids) for o in body["observances"])
    assert [o["time"] for o in body["observances"]] == [None] * 13   # time is optional, and blank
    dates = [o["date"] for o in body["observances"]]
    assert dates == sorted(dates)


async def test_preview_saves_nothing(db, client, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials/preview",
                          json=_body(DEATH), headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 13
    assert (await db.execute(select(func.count()).select_from(Memorial))).scalar_one() == 0


async def test_a_series_without_a_length_is_refused(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    ids = await _service_ids(db, aid, "Baaj")
    url = f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials"
    r = await client.post(url, json={**_body(DEATH, service_ids=ids), "monthly": {}}, headers=headers)
    assert r.status_code == 422
    r = await client.post(url, json={**_body(DEATH, service_ids=ids), "yearly": {}}, headers=headers)
    assert r.status_code == 422
    r = await client.post(url, json={**_body(DEATH, service_ids=ids), "monthly": None,
                                     "parabs": {"which": "all"}}, headers=headers)
    assert r.status_code == 422


async def test_lengths_are_bounded(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    for bad in ({"monthly": {"count": 0}}, {"monthly": {"count": 9999}}, {"yearly": {"count": 99}},
                {"parabs": {"which": "all", "years": 0}}, {"parabs": {"which": "all", "years": 99}}):
        r = await _create(client, db, aid, cid, headers, **bad)
        assert r.status_code == 400, (bad, r.text)


async def test_at_least_one_service_is_required(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    url = f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials"
    r = await client.post(url, json=_body(DEATH, service_ids=[]), headers=headers)
    assert r.status_code == 400
    r = await client.post(url, json=_body(DEATH, service_ids=[99999]), headers=headers)
    assert r.status_code == 400


async def test_a_death_on_a_gatha_day_starts_from_that_day(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    agyary = await db.get(Agyary, aid)
    gatha = parsi_to_gregorian(1400, CalendarSystem(agyary.calendar_system), gatha_index=2)
    r = await _create(client, db, aid, cid, headers, death=gatha, day_counts=[], monthly=None)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["death"]["mah"] == 13 and body["death"]["roj"] == 2
    first = body["observances"][0]
    assert first["date"] == gatha.isoformat() and first["gatha_index"] == 2
    assert body["total"] == 10
    # And it can be read back, and previewed, like any other.
    again = await client.get(f"/api/mobed/agyaries/{aid}/memorials/{body['id']}", headers=headers)
    assert again.status_code == 200 and again.json()["observances"][0]["gatha_index"] == 2


async def test_parabs_and_the_other_series(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    r = await _create(client, db, aid, cid, headers, monthly=None, day_counts=[],
                      yearly={"count": 2}, parabs={"which": "fravardin_tir", "years": 2})
    assert r.status_code == 200, r.text
    codes = [o["code"] for o in r.json()["observances"]]
    assert "year_1" in codes and "year_2" in codes
    # Fravardin and Tir, once a year for two years.
    assert sum(c.startswith("parab_") for c in codes) == 4


# --- The calendar the family keeps -------------------------------------------

async def _set_primary(client, headers, system):
    r = await client.put("/api/mobed/me/preferences", headers=headers, json={
        "visible_calendar_systems": ["gregorian", system], "default_secondary_system": system,
        "display_language": "en"})
    assert r.status_code == 200, r.text


async def test_the_calendar_defaults_to_the_mobeds_primary_and_is_stored(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    await _set_primary(client, headers, "kadmi")
    body = (await _create(client, db, aid, cid, headers, monthly=None, day_counts=[])).json()
    assert body["calendar"] == "kadmi"
    row = await db.get(Memorial, body["id"])
    assert row.calendar_system == "kadmi"   # the temple is shenshai; the family is not


async def test_a_memorial_can_be_counted_in_another_calendar(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    await _set_primary(client, headers, "shenshai")
    kw = dict(monthly=None, day_counts=[], parabs={"which": "all", "years": 1})
    by_system = {}
    for system in ("shenshai", "kadmi", "fasli"):
        r = await _create(client, db, aid, cid, headers, calendar=system, **kw)
        assert r.status_code == 200, r.text
        assert r.json()["calendar"] == system
        by_system[system] = {o["code"]: o["date"] for o in r.json()["observances"]
                             if o["code"].startswith("parab_")}
    # The Parab of a Mah is a different Gregorian day in each calendar.
    shen, kad = by_system["shenshai"], by_system["kadmi"]
    assert len(shen) == len(kad) == 12
    assert sorted(shen.values()) != sorted(kad.values())
    assert sorted(shen.values()) != sorted(by_system["fasli"].values())


async def test_the_preview_and_the_saved_memorial_agree_on_the_calendar(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    ids = await _service_ids(db, aid, "Baaj")
    url = f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials"
    body = _body(DEATH, service_ids=ids, calendar="fasli")
    preview = (await client.post(url + "/preview", json=body, headers=headers)).json()
    made = (await client.post(url, json=body, headers=headers)).json()
    assert preview["calendar"] == made["calendar"] == "fasli"
    assert [o["date"] for o in preview["observances"]] == [o["date"] for o in made["observances"]]
    assert preview["death"] == made["death"]


async def test_an_unknown_calendar_is_refused(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    r = await _create(client, db, aid, cid, headers, calendar="gregorian")
    assert r.status_code == 422


# --- Privacy ----------------------------------------------------------------

async def test_another_mobed_cannot_see_or_touch_a_memorial(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    mid = (await _create(client, db, aid, cid, headers)).json()["id"]
    other = await _member_headers(client, seeded, name="Other", phone=OTHER_MOBED)

    assert (await client.get(f"/api/mobed/agyaries/{aid}/memorials/{mid}", headers=other)).status_code == 404
    assert (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials", headers=other)).status_code == 404
    assert (await client.delete(f"/api/mobed/agyaries/{aid}/memorials/{mid}", headers=other)).status_code == 404
    r = await client.get(f"/api/mobed/agyaries/{aid}/memorial-feed",
                         params={"from": "2030-01-01", "to": "2030-12-31"}, headers=other)
    assert r.status_code == 200 and r.json() == []
    # And it is still there for its owner.
    assert (await client.get(f"/api/mobed/agyaries/{aid}/memorials/{mid}", headers=headers)).status_code == 200


# --- Editing one observance ------------------------------------------------

async def test_one_observance_can_be_changed_alone(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    created = (await _create(client, db, aid, cid, headers)).json()
    mid, obs = created["id"], created["observances"]
    farokshi, baaj, afringan = await _service_ids(db, aid, "Farokshi", "Baaj", "Afringan")
    target = obs[9]   # the 10th

    url = f"/api/mobed/agyaries/{aid}/memorials/{mid}/observances/{target['id']}"
    r = await client.patch(url, json={"service_ids": [afringan, farokshi, baaj],
                                      "time": "09:30", "notes": "Family arrives early"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["time"] == "09:30" and r.json()["notes"] == "Family arrives early"
    assert len(r.json()["service_ids"]) == 3

    again = (await client.get(f"/api/mobed/agyaries/{aid}/memorials/{mid}", headers=headers)).json()
    others = [o for o in again["observances"] if o["id"] != target["id"]]
    assert all(len(o["service_ids"]) == 2 and o["time"] is None for o in others)

    # An empty string clears; omitted leaves alone.
    r = await client.patch(url, json={"time": "", "notes": ""}, headers=headers)
    assert r.json()["time"] is None and r.json()["notes"] is None
    assert len(r.json()["service_ids"]) == 3


async def test_an_observance_cannot_be_left_with_no_services(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    created = (await _create(client, db, aid, cid, headers)).json()
    url = f"/api/mobed/agyaries/{aid}/memorials/{created['id']}/observances/{created['observances'][0]['id']}"
    assert (await client.patch(url, json={"service_ids": []}, headers=headers)).status_code == 400
    assert (await client.patch(url, json={"time": "25:99"}, headers=headers)).status_code == 400


# --- Calendar feed and the closing notice ----------------------------------

async def test_closing_notice_is_on_the_last_day_only(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    created = (await _create(client, db, aid, cid, headers)).json()
    last = created["observances"][-1]["date"]

    r = await client.get(f"/api/mobed/agyaries/{aid}/memorial-feed",
                         params={"from": "2030-01-01", "to": "2030-12-31"}, headers=headers)
    items = r.json()
    closings = [i for i in items if i["kind"] == "memorial_closing"]
    assert len(closings) == 1 and closings[0]["date"] == last
    assert "Dinshaw" in closings[0]["text"]
    assert [i["date"] for i in items if i["kind"] == "memorial" and i["is_last"]] == [last]

    # A window that stops short of the last day shows no closing notice.
    first_ten_end = created["observances"][9]["date"]
    r = await client.get(f"/api/mobed/agyaries/{aid}/memorial-feed",
                         params={"from": "2030-01-01", "to": first_ten_end}, headers=headers)
    assert r.json() and all(i["kind"] == "memorial" and not i["is_last"] for i in r.json())


async def test_feed_window_is_bounded(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    r = await client.get(f"/api/mobed/agyaries/{aid}/memorial-feed",
                         params={"from": "2030-01-01", "to": "2032-01-01"}, headers=headers)
    assert r.status_code == 400
    r = await client.get(f"/api/mobed/agyaries/{aid}/memorial-feed",
                         params={"from": "2030-02-01", "to": "2030-01-01"}, headers=headers)
    assert r.status_code == 400


# --- Lifecycle --------------------------------------------------------------

async def test_a_memorial_whose_dates_have_passed_is_completed(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    r = await _create(client, db, aid, cid, headers, death=date(2020, 1, 5), monthly=None, day_counts=[])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed" and r.json()["next"] is None
    listed = (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials", headers=headers)).json()
    assert listed[0]["status"] == "completed" and listed[0]["done"] == listed[0]["total"]
    assert "observances" not in listed[0]   # the list is a summary


async def test_next_observance_is_the_soonest_not_yet_past(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    # IST, like the app: on a UTC runner the two dates differ for a few hours a day.
    death = memorials.today_ist() - timedelta(days=3)
    body = (await _create(client, db, aid, cid, headers, death=death, monthly=None, day_counts=[])).json()
    assert body["status"] == "running"
    assert body["done"] == 3
    assert body["next"]["day_number"] == 4


async def test_deleting_a_memorial_removes_its_observances(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    mid = (await _create(client, db, aid, cid, headers)).json()["id"]
    assert (await client.delete(f"/api/mobed/agyaries/{aid}/memorials/{mid}", headers=headers)).status_code == 200
    assert (await db.execute(select(func.count()).select_from(MemorialObservance))).scalar_one() == 0


async def test_a_behdin_with_a_memorial_is_not_erased(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    await _create(client, db, aid, cid, headers)
    r = await client.delete(f"/api/mobed/agyaries/{aid}/behdins/{cid}", headers=headers)
    assert r.status_code == 200 and r.json() == {"deleted": True, "erased": False}
    assert await db.get(Customer, cid) is not None
