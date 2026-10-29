"""Machi booking, end to end, under the conditions that go wrong.

A machi is one slot - one geh on one day at one fire temple, on one mobed's own
board (colleagues' boards are invisible to each other) - and once it is
booked it must not be overwritten, double-booked or quietly lost. These run the
scenarios that threaten that: two people wanting the same slot at once, mobeds
who read different calendars, values a client should never send, edits, deletes,
and a repeating series running into somebody else's booking. Every request goes
through the API exactly as the mobed and Machi Board apps send it.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from agyary.calendar import CalendarSystem, gregorian_to_parsi
from agyary.messaging.availability import parsi_slot_fields
from agyary.models import Machi
from tests.conftest import TEST_DATABASE_URL
from tests.test_mobed_api import _headers, _member_headers

DAY = date(2031, 3, 10)          # well ahead, so nothing is "elapsed"
GEH = 2
PHONE = "+919933300001"
PANTHAKY = "+919800000001"


def keys(day: date, system: str) -> tuple[int, int, int]:
    """Roj, Mah and year as a browser works them out in the mobed's calendar."""
    return parsi_slot_fields(gregorian_to_parsi(day, CalendarSystem(system)))


def body(day: date = DAY, geh: int = GEH, *, system: str = "shenshai", phone: str = PHONE, **over) -> dict:
    roj, mah, year = keys(day, system)
    out = {
        "behdin_phone": phone, "behdin_name": "Scenario Behdin", "roj": roj, "mah": mah,
        "year": year, "geh": geh, "gregorian": day.isoformat(), "purpose": "patet", "names": [],
    }
    out.update(over)
    return out


async def book(client, aid, headers, **kw):
    return await client.post(f"/api/mobed/agyaries/{aid}/manual-add/machi", json=body(**kw), headers=headers)


async def set_primary(client, headers, system: str):
    r = await client.put("/api/mobed/me/preferences", headers=headers, json={
        "visible_calendar_systems": ["gregorian", system], "default_secondary_system": system,
        "display_language": "en"})
    assert r.status_code == 200, r.text


@contextlib.asynccontextmanager
async def separate_sessions():
    """Give every request its own database session and connection, as the real
    server does. The test client normally shares one session between requests,
    which cannot race - this can."""
    from agyary.api.main import app
    from agyary.core.database import get_db

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    shared = app.dependency_overrides[get_db]

    async def per_request():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = per_request
    try:
        yield
    finally:
        app.dependency_overrides[get_db] = shared
        await engine.dispose()


async def count(db, **filters) -> int:
    q = select(func.count()).select_from(Machi)
    for k, v in filters.items():
        q = q.where(getattr(Machi, k) == v)
    return (await db.execute(q)).scalar_one()


async def mobeds(client, seeded, n=2):
    return [await _member_headers(client, seeded, name=f"Scenario Mobed {i}", phone=f"+91993330010{i}")
            for i in range(n)]


# --- The slot cannot be taken twice ------------------------------------------------

async def test_a_booked_slot_cannot_be_booked_again_and_the_first_is_untouched(db, client, seeded):
    """A slot is each mobed's own: the same mobed cannot book it twice."""
    aid = seeded["agyary_id"]
    a, _ = await mobeds(client, seeded)
    first = await book(client, aid, a, phone="+919933300011")
    assert first.json()["confirmed"] is True
    machi_id = first.json()["machi_id"]
    owner = (await db.get(Machi, machi_id)).customer_id

    second = await book(client, aid, a, phone="+919933300012")
    assert second.status_code == 200 and second.json()["confirmed"] is False
    assert GEH not in second.json()["alternatives"]["same_day_gehs"]

    assert await count(db, geh=GEH) == 1
    kept = await db.get(Machi, machi_id)
    await db.refresh(kept)
    assert kept.customer_id == owner and kept.status == "confirmed"


async def test_simultaneous_requests_for_one_slot_book_exactly_one(db, client, seeded):
    aid = seeded["agyary_id"]
    (head,) = await mobeds(client, seeded, n=1)
    async with separate_sessions():
        results = await asyncio.gather(*[
            book(client, aid, head, phone=f"+91993330002{i}") for i in range(6)
        ])
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert sorted(r.json()["confirmed"] for r in results) == [False] * 5 + [True]
    assert await count(db, geh=GEH) == 1


async def test_a_released_slot_can_be_booked_again(db, client, seeded):
    aid = seeded["agyary_id"]
    (a,) = await mobeds(client, seeded, n=1)
    first = (await book(client, aid, a, phone="+919933300031")).json()
    assert (await client.delete(f"/api/mobed/agyaries/{aid}/machis/{first['machi_id']}", headers=a)).status_code == 200
    again = await book(client, aid, a, phone="+919933300032")
    assert again.json()["confirmed"] is True


# --- Mobeds who read a different calendar from the temple ------------------------

async def test_one_mobed_switching_calendars_cannot_double_book_a_day(db, client, seeded):
    """The temple is Shenshai. Once the mobed reads Kadmi, their browser sends Kadmi
    Roj/Mah; the same real day and geh must still count as taken."""
    aid = seeded["agyary_id"]
    (mobed,) = await mobeds(client, seeded, n=1)
    await set_primary(client, mobed, "shenshai")
    assert keys(DAY, "shenshai") != keys(DAY, "kadmi")        # the premise: the keys differ

    first = await book(client, aid, mobed, system="shenshai", phone="+919933300041")
    assert first.json()["confirmed"] is True
    await set_primary(client, mobed, "kadmi")
    second = await book(client, aid, mobed, system="kadmi", phone="+919933300042")
    assert second.json()["confirmed"] is False, "the same day and geh was booked twice"
    assert await count(db, gregorian_date=DAY, geh=GEH) == 1


async def test_what_the_form_shows_free_matches_what_booking_allows(db, client, seeded):
    aid = seeded["agyary_id"]
    (a,) = await mobeds(client, seeded, n=1)
    assert (await book(client, aid, a, phone="+919933300051")).json()["confirmed"] is True
    await set_primary(client, a, "kadmi")
    shown = (await client.get(f"/api/mobed/agyaries/{aid}/bookable-gehs", params={"on": DAY.isoformat()}, headers=a)).json()
    assert GEH not in shown["bookable"]                        # the geh picker greys it out
    forced = await book(client, aid, a, system="kadmi", phone="+919933300052")
    assert forced.json()["confirmed"] is False                 # and forcing it still fails


async def test_the_stored_slot_follows_the_date_not_what_the_browser_claims(db, client, seeded):
    aid = seeded["agyary_id"]
    (a,) = await mobeds(client, seeded, n=1)
    wrong = keys(date(2031, 8, 1), "shenshai")                 # a different day's Roj/Mah/year
    r = await book(client, aid, a, roj=wrong[0], mah=wrong[1], year=wrong[2], phone="+919933300061")
    assert r.json()["confirmed"] is True
    row = (await db.execute(select(Machi).where(Machi.id == r.json()["machi_id"]))).scalar_one()
    assert (row.parsi_roj, row.parsi_mah, row.parsi_year) == keys(DAY, "shenshai")
    # ...so the real day is taken, whatever the browser said.
    again = await book(client, aid, a, phone="+919933300062")
    assert again.json()["confirmed"] is False


async def test_an_admin_can_change_the_purpose_of_a_machi_booked_in_another_calendar(db, client, seeded):
    aid = seeded["agyary_id"]
    (m,) = await mobeds(client, seeded, n=1)
    await set_primary(client, m, "kadmi")
    made = (await book(client, aid, m, system="kadmi", phone="+919933300071")).json()
    panthaky = await _headers(client, "Er. Hormuz Dadachanji", PANTHAKY)
    edit = body(system="shenshai", phone="+919933300071", purpose="tandarosti")
    r = await client.put(f"/api/mobed/agyaries/{aid}/machis/{made['machi_id']}", json=edit, headers=panthaky)
    assert r.status_code == 200 and r.json()["confirmed"] is True, r.text


# --- Values a client should never be able to send ------------------------------------

@pytest.mark.parametrize("field,value", [
    ("geh", 0), ("geh", 6), ("geh", 99), ("roj", 0), ("roj", 31), ("mah", 0), ("mah", 14),
    ("year", 0), ("purpose", "bogus"), ("purpose", ""),
])
async def test_impossible_values_are_refused_not_reported_as_a_taken_slot(db, client, seeded, field, value):
    aid = seeded["agyary_id"]
    (a,) = await mobeds(client, seeded, n=1)
    r = await book(client, aid, a, **{field: value})
    assert r.status_code == 422, f"{field}={value!r} -> {r.status_code} {r.text}"
    assert await count(db) == 0


async def test_editing_with_impossible_values_is_refused_too(db, client, seeded):
    aid = seeded["agyary_id"]
    (a,) = await mobeds(client, seeded, n=1)
    made = (await book(client, aid, a)).json()
    r = await client.put(f"/api/mobed/agyaries/{aid}/machis/{made['machi_id']}",
                         json=body(geh=9), headers=a)
    assert r.status_code == 422
    kept = await db.get(Machi, made["machi_id"])
    assert kept.geh == GEH


# --- Editing a booked machi ----------------------------------------------------------

async def test_moving_a_machi_onto_a_taken_slot_leaves_it_where_it_was(db, client, seeded):
    aid = seeded["agyary_id"]
    (a,) = await mobeds(client, seeded, n=1)
    mine = (await book(client, aid, a, geh=2, phone="+919933300081")).json()
    await book(client, aid, a, geh=3, phone="+919933300082")
    r = await client.put(f"/api/mobed/agyaries/{aid}/machis/{mine['machi_id']}",
                         json=body(geh=3, phone="+919933300081"), headers=a)
    assert r.json()["confirmed"] is False
    kept = await db.get(Machi, mine["machi_id"])
    await db.refresh(kept)
    assert kept.geh == 2 and kept.status == "confirmed"
    assert await count(db, geh=3) == 1


async def test_a_name_only_edit_is_not_blocked_by_the_machi_itself(db, client, seeded):
    aid = seeded["agyary_id"]
    (a,) = await mobeds(client, seeded, n=1)
    made = (await book(client, aid, a, phone="+919933300091")).json()
    r = await client.put(f"/api/mobed/agyaries/{aid}/machis/{made['machi_id']}",
                         json=body(phone="+919933300091", purpose="tandarosti"), headers=a)
    assert r.json()["confirmed"] is True


# --- The mobed is told, before booking, what a repeating series will hit ----------------

async def test_a_repeating_series_reports_the_dates_it_could_not_book(db, client, seeded):
    aid = seeded["agyary_id"]
    (a,) = await mobeds(client, seeded, n=1)
    # The same mobed already holds the same geh one Parsi month on (for another family).
    month_on = keys(DAY, "shenshai")
    from agyary.calendar import parsi_to_gregorian
    next_mah = (month_on[1] % 12) + 1
    next_year = month_on[2] + (1 if month_on[1] == 12 else 0)
    taken = parsi_to_gregorian(next_year, CalendarSystem("shenshai"), mah=next_mah, roj=month_on[0])
    assert (await book(client, aid, a, day=taken, phone="+919933300101")).json()["confirmed"] is True

    r = await book(client, aid, a, phone="+919933300102", recurring="monthly")
    assert r.json()["confirmed"] is True
    assert taken.isoformat() in [s["gregorian"] for s in r.json()["skipped"]]


async def test_the_preview_warns_about_a_series_before_anything_is_booked(db, client, seeded):
    aid = seeded["agyary_id"]
    (a,) = await mobeds(client, seeded, n=1)
    from agyary.calendar import parsi_to_gregorian
    roj, mah, year = keys(DAY, "shenshai")
    taken = parsi_to_gregorian(year + (1 if mah == 12 else 0), CalendarSystem("shenshai"),
                               mah=(mah % 12) + 1, roj=roj)
    await book(client, aid, a, day=taken, phone="+919933300111")
    r = await client.post(f"/api/mobed/agyaries/{aid}/slip-preview/machi",
                          json={**body(phone="+919933300112"), "recurring": "monthly"}, headers=a)
    assert r.status_code == 200, r.text
    assert taken.isoformat() in r.json()["series_conflicts"]
    assert await count(db, geh=GEH) == 1                    # previewing booked nothing


async def test_a_machi_on_a_gatha_day_cannot_be_made_to_repeat(db, client, seeded):
    aid = seeded["agyary_id"]
    (a,) = await mobeds(client, seeded, n=1)
    from agyary.calendar import parsi_to_gregorian
    gatha = parsi_to_gregorian(1400, CalendarSystem("shenshai"), gatha_index=2)
    r = await book(client, aid, a, day=gatha, recurring="monthly", phone="+919933300121")
    assert r.status_code == 400 and "Gatha" in r.json()["detail"]
    assert await count(db) == 0                              # nothing half-made
    plain = await book(client, aid, a, day=gatha, phone="+919933300122")
    assert plain.json()["confirmed"] is True                 # a one-off on a Gatha day is fine


# --- Who can see and change what ---------------------------------------------------------

async def test_a_colleague_sees_nothing_of_the_slot_and_cannot_change_the_machi(db, client, seeded):
    aid = seeded["agyary_id"]
    a, b = await mobeds(client, seeded)
    made = (await book(client, aid, a, phone="+919933300131")).json()
    shown = (await client.get(f"/api/mobed/agyaries/{aid}/bookable-gehs", params={"on": DAY.isoformat()}, headers=b)).json()
    assert GEH in shown["bookable"]                          # not their slot, so not taken for them
    assert (await client.put(f"/api/mobed/agyaries/{aid}/machis/{made['machi_id']}",
                             json=body(geh=4, phone="+919933300131"), headers=b)).status_code == 404
    assert (await client.delete(f"/api/mobed/agyaries/{aid}/machis/{made['machi_id']}", headers=b)).status_code == 404
    kept = await db.get(Machi, made["machi_id"])
    assert kept.geh == GEH
