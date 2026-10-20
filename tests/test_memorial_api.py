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
from tests.test_mobed_api import NEW_MOBED_PHONE, _member_headers

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
    assert r.status_code == 400   # refused by the service now that the length may be years or a count


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


# --- Previewing before the behdin exists (the New behdin page) ---------------

async def test_a_preview_needs_no_behdin_and_matches_the_one_with_a_behdin(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    ids = await _service_ids(db, aid, "Afringan", "Baaj")
    body = _body(DEATH, service_ids=ids, calendar="kadmi")
    bare = await client.post(f"/api/mobed/agyaries/{aid}/memorials/preview", json=body, headers=headers)
    assert bare.status_code == 200, bare.text
    with_behdin = await client.post(
        f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials/preview", json=body, headers=headers)
    assert bare.json() == with_behdin.json()
    assert (await db.execute(select(func.count()).select_from(Memorial))).scalar_one() == 0


async def test_the_bare_preview_still_validates_and_needs_a_member(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    bad = await client.post(f"/api/mobed/agyaries/{aid}/memorials/preview",
                            json=_body(DEATH, service_ids=[], monthly={"count": 9999}), headers=headers)
    assert bad.status_code == 400
    from tests.test_mobed_api import _headers
    outsider = await _headers(client, name="Outsider", phone="+919911100066")   # signed in, not joined
    r = await client.post(f"/api/mobed/agyaries/{aid}/memorials/preview", json=_body(DEATH), headers=outsider)
    assert r.status_code == 403


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


# --- Reminders due ----------------------------------------------------------

def _reminders(client, aid, headers, **params):
    return client.get(f"/api/mobed/agyaries/{aid}/memorial-reminders", params=params, headers=headers)


async def _user_id(db, phone):
    from agyary.models import User

    return (await db.execute(select(User.id).where(User.phone == phone))).scalar_one()


async def _later_observances(client, db, aid, cid, headers, **over):
    """A memorial in the far future, and its observances after the opening days."""
    body = (await _create(client, db, aid, cid, headers, **over)).json()
    later = [o for o in body["observances"] if o["day_number"] > memorials.OPENING_DAYS]
    assert later, "the memorial should have observances after the opening days"
    return later


async def test_the_opening_days_are_never_reminded(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    # Death 3 days ago: today is day 4 and days 5-10 are ahead - all opening days,
    # when the family is at the fire temple every day, in mourning.
    death = memorials.today_ist() - timedelta(days=3)
    await _create(client, db, aid, cid, headers, death=death, monthly=None, day_counts=[])

    r = await _reminders(client, aid, headers, days=14)
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []
    assert r.json()["lead_days"] == memorials.REMINDER_LEAD_DAYS == 1


async def test_reminders_start_after_the_opening_and_flag_what_is_due(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    later = await _later_observances(client, db, aid, cid, headers, day_counts=[30])
    uid = await _user_id(db, NEW_MOBED_PHONE)
    first = date.fromisoformat(later[0]["date"])

    async def at(today, horizon=14):
        return await memorials.reminders_due(db, uid, aid, today, horizon)

    # The day before: due. Five days before: coming up, not due.
    [item, *_] = await at(first - timedelta(days=1))
    assert item["day_number"] == later[0]["day_number"] > memorials.OPENING_DAYS
    assert (item["days_away"], item["due"]) == (1, True)
    assert (await at(first))[0]["due"] is True                       # the day itself
    [item, *_] = await at(first - timedelta(days=5))
    assert (item["days_away"], item["due"]) == (5, False)
    # Once it has passed it is gone.
    assert all(i["date"] > first.isoformat() for i in await at(first + timedelta(days=1)))
    # Nothing at all in the opening, however close.
    assert await at(first - timedelta(days=40), horizon=20) == []


async def test_reminders_respect_the_horizon(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    later = await _later_observances(client, db, aid, cid, headers, day_counts=[30])
    uid = await _user_id(db, NEW_MOBED_PHONE)
    first = date.fromisoformat(later[0]["date"])
    assert await memorials.reminders_due(db, uid, aid, first - timedelta(days=3), 2) == []
    assert len(await memorials.reminders_due(db, uid, aid, first - timedelta(days=3), 3)) >= 1


async def test_reminders_are_the_callers_own(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    later = await _later_observances(client, db, aid, cid, headers, day_counts=[30])
    await _member_headers(client, seeded, name="Other", phone=OTHER_MOBED)
    first = date.fromisoformat(later[0]["date"])
    day_before = first - timedelta(days=1)

    assert await memorials.reminders_due(db, await _user_id(db, NEW_MOBED_PHONE), aid, day_before, 3)
    assert await memorials.reminders_due(db, await _user_id(db, OTHER_MOBED), aid, day_before, 3) == []


async def test_reminder_horizon_is_bounded(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    assert (await _reminders(client, aid, headers, days=61)).status_code == 422
    assert (await _reminders(client, aid, headers, days=-1)).status_code == 422
    assert (await _reminders(client, aid, headers, days=60)).status_code == 200


async def test_reminders_need_a_session(client, seeded):
    r = await client.get(f"/api/mobed/agyaries/{seeded['agyary_id']}/memorial-reminders")
    assert r.status_code in (401, 403)


async def test_each_reminder_carries_its_wording_and_a_whatsapp_link(client, db, seeded):
    from urllib.parse import parse_qs, urlparse

    aid, cid, headers = await _setup(client, db, seeded)
    later = await _later_observances(client, db, aid, cid, headers, day_counts=[30])
    uid = await _user_id(db, NEW_MOBED_PHONE)
    first = date.fromisoformat(later[0]["date"])

    [item, *_] = await memorials.reminders_due(db, uid, aid, first - timedelta(days=1), 3)
    assert item["behdin_phone"] == PHONE
    text = item["message"]
    agyary_name = (await db.execute(select(Agyary.name).where(Agyary.id == aid))).scalar_one()
    assert text.startswith(f"Reminder from {agyary_name}.\n\n")
    assert text.splitlines()[4].startswith("When: Tomorrow, ")
    assert "Roj " in text and "Afringan and Baaj for Dinshaw." in text
    assert text.endswith("Prayers: Afringan and Baaj for Dinshaw.")
    # It already is booked: nothing asks the family to arrange or reply.
    assert "arrange" not in text and "reply" not in text and "observance" not in text.lower()

    # The link opens a chat with the behdin (no +) and carries exactly that text.
    link = urlparse(item["wa_link"])
    assert (link.scheme, link.netloc, link.path) == ("https", "wa.me", "/" + PHONE.lstrip("+"))
    assert parse_qs(link.query)["text"] == [text]


async def test_no_opening_dasmi_birthday_and_removed_dates(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    ids = await _service_ids(db, aid, "Afringan", "Satum")
    body = _body(DEATH, opening="none", day_counts=[10, 30], monthly=None,
                 birthday={"roj": 9, "mah": 5, "years": 2}, service_ids=ids)
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials/preview",
                          json=body, headers=headers)
    assert r.status_code == 200, r.text
    labels = [o["label"] for o in r.json()["observances"]]
    assert labels.count("Birthday") == 2 and "Dasmi" in labels and "Masiso" in labels
    assert not any(l.startswith("Day ") for l in labels)

    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials",
                          json={**body, "exclude_codes": ["day_10"]}, headers=headers)
    assert r.status_code == 200, r.text
    saved = [o["label"] for o in r.json()["observances"]]
    assert "Dasmi" not in saved and "Masiso" in saved and saved.count("Birthday") == 2

    # a birthday given as a date is turned into its Roj and Mah; with no length it is refused
    bad = {**body, "birthday": {"roj": 9, "mah": 5, "years": 0}}
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials/preview",
                          json=bad, headers=headers)
    assert r.status_code == 400
    ok = {**body, "birthday": {"birth_date": "1950-06-01", "years": 1}}
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials/preview",
                          json=ok, headers=headers)
    assert r.status_code == 200, r.text


async def test_starting_late_books_only_what_is_still_ahead(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    ids = await _service_ids(db, aid, "Afringan")
    start = DEATH + timedelta(days=120)
    body = _body(DEATH, opening="none", day_counts=[10, 30], monthly={"count": 3},
                 start_from=start.isoformat(), service_ids=ids)
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials/preview",
                          json=body, headers=headers)
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["count"] == 3 and pv["passed_not_booked"] >= 2
    assert all(o["date"] >= start.isoformat() for o in pv["observances"])
    # everything already behind the start date: a plain message, not a crash
    body["day_counts"] = [10]
    body["monthly"] = None
    body["start_from"] = (DEATH + timedelta(days=400)).isoformat()
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials/preview",
                          json=body, headers=headers)
    assert r.status_code == 400 and "already passed" in r.json()["detail"]


async def test_roj_fravardin_every_month_is_saved_and_returned(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    ids = await _service_ids(db, aid, "Afringan")
    body = _body(DEATH, opening="none", day_counts=[], monthly=None,
                 fravardin_roj={"count": 3}, service_ids=ids)
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials", json=body, headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["fravardin_roj_months"] == 3 and out["total"] == 3
    assert all(o["label"] == "Roj Fravardin" for o in out["observances"])
    bad = {**body, "fravardin_roj": {"count": 0}}
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials/preview", json=bad, headers=headers)
    assert r.status_code == 400
