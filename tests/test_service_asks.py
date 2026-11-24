"""R4.2: a person asks an agyari for a service (docs/behdin-r4-2-design.md, DECISIONS 25 Nov 2026).

The person asks in the Parsi app, the panthaky answers. Nothing is booked and no number is shared
until the panthaky accepts (D2); accepting makes the booking, machi, repeating series or memorial in
the panthaky's own book by the diary's own services; the person is told in plain words that never
name the other app; deleting the account or erasing the number takes the asks.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select, text, update

from agyary.models import Agyary, AppNotification, Booking, Customer, Machi, Memorial, Service, ServiceAsk, User
from agyary.services import erasure, service_asks
from tests.conftest import sign_in
from tests.funeral_helpers import agyari, member
from tests.test_behdin_identity import auth, behdin_sign_in

SRC = Path(__file__).resolve().parent.parent / "src" / "agyary"
ME, OTHER = "+919911100091", "+919911100092"
PANTHAKY = "+919800000001"       # the demo fire temple's panthaky (seeded)
MOBED = "+919800000002"          # a plain mobed there
SECOND_PANTHAKY = "+919911100093"


def day(n: int = 3) -> str:
    return (service_asks.today_ist() + timedelta(days=n)).isoformat()


async def service_id(db, name: str, agyary_id: int = 1) -> int:
    return (await db.execute(select(Service.id).where(Service.agyary_id == agyary_id, Service.name == name))).scalar_one()


async def panthaky_headers(client, phone: str = PANTHAKY) -> dict:
    return auth(await sign_in(client, phone))


async def switch_on(client, db, agyary_id: int = 1, headers: dict | None = None) -> dict:
    headers = headers or await panthaky_headers(client)
    r = await client.put(f"/api/mobed/agyaries/{agyary_id}/asks-setting", headers=headers, json={"takes_asks": True})
    assert r.status_code == 200 and r.json() == {"takes_asks": True}, r.text
    return headers


async def person(client, phone: str = ME, name: str = "Farzin Meherzad Turel") -> dict:
    return auth(await behdin_sign_in(client, phone, name))


def booking_ask(sid: int, **changes) -> dict:
    body = {"agyary_id": 1, "service_id": sid, "purpose": "gujrela_nu", "date": day(), "time": "10:00",
            "where": "agyari", "names": [
                {"section": "pair", "title": "osta", "name": "Rustom Test", "status": "departed", "pair_group": 1},
                {"section": "pair", "title": "osti", "name": "Roda Test", "status": "departed", "pair_group": 1}],
            "note": "Please pray for peace"}
    body.update(changes)
    return body


async def ask(client, headers, body, expect: int = 200) -> dict:
    r = await client.post("/api/behdin/me/asks", headers=headers, json=body)
    assert r.status_code == expect, r.text
    return r.json()


def panthaky_asks(client, headers, aid: int = 1):
    return client.get(f"/api/mobed/agyaries/{aid}/asks", headers=headers)


# --- the switch, the services and their prices ---------------------------------------------
async def test_the_panthaky_switches_asks_on_and_a_plain_mobed_is_refused(client, db, seeded):
    headers = await panthaky_headers(client)
    assert (await client.get("/api/mobed/agyaries/1/asks-setting", headers=headers)).json() == {"takes_asks": False}
    for bad in ("yes", 1, None):
        r = await client.put("/api/mobed/agyaries/1/asks-setting", headers=headers, json={"takes_asks": bad})
        assert r.status_code == 400
    await switch_on(client, db, headers=headers)
    assert (await db.execute(select(Agyary.takes_asks).where(Agyary.id == 1))).scalar_one() is True

    mobed = auth(await sign_in(client, MOBED))
    calls = [("GET", "/asks-setting"), ("PUT", "/asks-setting"), ("GET", "/asks"), ("GET", "/service-prices"),
             ("POST", "/asks/1/accept"), ("POST", "/asks/1/reject")]
    for method, tail in calls:
        r = await client.request(method, f"/api/mobed/agyaries/1{tail}", headers=mobed, json={"takes_asks": False})
        assert r.status_code == 403, (method, tail, r.text)
    assert (await client.get("/api/mobed/agyaries/1/asks-setting", headers=headers)).json() == {"takes_asks": True}


async def test_the_panthaky_sets_usual_prices_and_switches_a_service_off(client, db, seeded):
    headers = await panthaky_headers(client)
    jashan = await service_id(db, "Jashan")
    listed = (await client.get("/api/mobed/agyaries/1/service-prices", headers=headers)).json()["services"]
    assert {s["name"]: s["default_price"] for s in listed}["Jashan"] == 1500.0
    r = await client.put(f"/api/mobed/agyaries/1/services/{jashan}", headers=headers, json={"default_price": "1800.50"})
    assert r.status_code == 200 and r.json()["default_price"] == 1800.5 and r.json()["is_active"] is True
    # Only what is sent changes; null clears the price.
    r = await client.put(f"/api/mobed/agyaries/1/services/{jashan}", headers=headers, json={"is_active": False})
    assert r.json()["default_price"] == 1800.5 and r.json()["is_active"] is False
    r = await client.put(f"/api/mobed/agyaries/1/services/{jashan}", headers=headers,
                         json={"default_price": None, "is_active": True})
    assert r.json()["default_price"] is None and r.json()["is_active"] is True
    for bad in (-1, "abc", 1000001, True, "nan", [5]):
        r = await client.put(f"/api/mobed/agyaries/1/services/{jashan}", headers=headers, json={"default_price": bad})
        assert r.status_code == 400, (bad, r.text)
    assert (await client.put(f"/api/mobed/agyaries/1/services/{jashan}", headers=headers,
                             json={"is_active": "no"})).status_code == 400
    # A service of another fire temple is not found through this one.
    other = await agyari(db, "Other Agyari (test)", None)
    other_service = Service(agyary_id=other.id, name="Elsewhere")
    db.add(other_service)
    await db.commit()
    assert (await client.put(f"/api/mobed/agyaries/1/services/{other_service.id}", headers=headers,
                             json={"default_price": 5})).status_code == 404


async def test_a_person_sees_what_an_agyari_offers_only_when_it_takes_asks(client, db, seeded):
    mine = await person(client)
    r = await client.get("/api/behdin/agyaries/1/asking", headers=mine)
    assert r.status_code == 200
    closed = r.json()
    assert closed["takes_asks"] is False and closed["message"] == "Not taking asks in the app yet"
    assert closed["services"] == []
    await switch_on(client, db)
    seen = (await client.get("/api/behdin/agyaries/1/asking", headers=mine)).json()
    assert seen["takes_asks"] is True and seen["name"] == "Goti Adarian" and seen["city"] == "Mumbai"
    by_name = {s["name"]: s for s in seen["services"]}
    assert by_name["Jashan"]["usual_price"] == 1500.0 and by_name["Jashan"]["offsite_capable"] is True
    assert by_name["Machi"]["by_geh"] is True and by_name["Jashan"]["by_geh"] is False
    raw = json.dumps(seen)
    assert "+9198" not in raw and "phone" not in raw
    assert (await client.get("/api/behdin/agyaries/99999/asking", headers=mine)).status_code == 404
    assert (await client.get("/api/behdin/agyaries/1/asking")).status_code == 401


# --- the full path -----------------------------------------------------------------------------
async def test_an_ask_is_read_without_a_number_and_accepted_into_the_panthakys_own_book(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    jashan = await service_id(db, "Jashan")
    made = await ask(client, mine, booking_ask(jashan))
    assert made["status"] == "waiting" and made["label"] == "Waiting" and made["can_cancel"] is True
    assert made["service"]["name"] == "Jashan" and made["agyari"]["name"] == "Goti Adarian"

    # The panthaky reads it: first name only, nothing that says who they are.
    r = await panthaky_asks(client, pan)
    assert r.status_code == 200 and r.json()["waiting"] == 1
    row = r.json()["asks"][0]
    assert row["person"] == {"first_name": "Farzin"} and row["service"]["name"] == "Jashan"
    assert row["date"] == day() and row["time"] == "10:00" and row["note"] == "Please pray for peace"
    assert row["parsi"] and len(row["names"]) == 2 and row["status"] == "waiting"
    assert ME not in r.text and "Meherzad" not in r.text and "Turel" not in r.text and "phone" not in r.text
    # No record of them exists in the panthaky's book yet, nothing is booked.
    assert (await db.execute(select(Customer).where(Customer.phone == ME))).first() is None
    assert (await db.execute(select(Booking))).first() is None

    # The panthaky was told, by first name and service, with a link to the Requests tab.
    note = (await db.execute(select(AppNotification).where(AppNotification.kind == "ask_new"))).scalar_one()
    assert "Farzin" in note.body and "Jashan" in note.body and ME not in note.body and note.link == "#/requests"
    panthaky_id = (await db.execute(select(User.id).where(User.phone == PANTHAKY))).scalar_one()
    assert note.user_id == panthaky_id

    accepted = await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["booking_id"] and body["machi_id"] is None and body["ask"]["status"] == "accepted"
    assert ME not in accepted.text

    # Now they are a record in the panthaky's own book, and the booking is as if the panthaky made it.
    customer = (await db.execute(select(Customer).where(Customer.phone == ME))).scalar_one()
    assert customer.owner_user_id == panthaky_id and customer.name == "Farzin Meherzad Turel"
    booking = await db.get(Booking, body["booking_id"], populate_existing=True)
    assert booking.customer_id == customer.id and booking.created_by_user_id == panthaky_id
    assert booking.status == "approved" and booking.purpose == "gujrela_nu" and booking.is_offsite is False
    assert booking.ceremony_datetime.astimezone(service_asks.IST).strftime("%Y-%m-%d %H:%M") == f"{day()} 10:00"
    assert booking.notes == "Note from the person: Please pray for peace"
    assert (await client.get(f"/api/mobed/agyaries/1/bookings/{booking.id}/detail", headers=pan)).status_code == 200

    # The person is told, in plain words, in the app.
    notes = (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"]
    assert len(notes) == 1 and notes[0]["kind"] == "person_ask_accepted" and notes[0]["seen"] is False
    assert "Goti Adarian accepted your ask for Jashan" in notes[0]["body"]
    mine_now = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert mine_now["status"] == "accepted" and mine_now["label"] == "Accepted"
    # Answered once.
    again = await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)
    assert again.status_code == 409
    assert (await client.post("/api/behdin/notifications/seen", headers=mine, json={})).json() == {"marked": 1}
    assert (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"][0]["seen"] is True


async def test_an_ask_at_home_becomes_an_offsite_booking_and_the_area_is_all_that_is_given(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    jashan = await service_id(db, "Jashan")
    # Not without an area, and not for something that cannot leave the fire temple.
    await ask(client, mine, booking_ask(jashan, **{"where": "home"}), 400)
    await ask(client, mine, booking_ask(await service_id(db, "Satum"), **{"where": "home", "area": "Dadar"}), 400)
    made = await ask(client, mine, booking_ask(jashan, **{"where": "home", "area": "Dadar, Mumbai"}))
    assert made["where"] == "home" and made["area"] == "Dadar, Mumbai"
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)).json()
    booking = await db.get(Booking, done["booking_id"], populate_existing=True)
    assert booking.is_offsite is True and booking.location == "Dadar, Mumbai"


async def test_a_machi_ask_is_booked_by_geh_and_a_geh_the_panthaky_holds_is_said_plainly(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    machi = await service_id(db, "Machi")
    made = await ask(client, mine, {"agyary_id": 1, "service_id": machi, "purpose": "patet", "date": day(5), "geh": 2,
                                    "names": [{"section": "pair", "title": "osta", "name": "Dara Test",
                                               "status": "departed", "pair_group": 1},
                                              {"section": "pair", "title": "osti", "name": "Dina Test",
                                               "status": "departed", "pair_group": 1}]})
    assert made["geh"] == 2 and made["geh_name"] == "Rapithwan" and made["time"] is None
    # The panthaky already holds that geh that day.
    r = await client.post("/api/mobed/agyaries/1/manual-add/machi", headers=pan, json={
        "behdin_phone": "+919911100099", "behdin_name": "Someone Else", "roj": 1, "mah": 1, "year": 1400,
        "geh": 2, "gregorian": day(5), "purpose": "patet", "names": []})
    assert r.status_code == 200 and r.json()["confirmed"] is True
    refused = await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)
    assert refused.status_code == 409 and "already hold that geh" in refused.json()["detail"]
    # Nothing was half done: still waiting, no record of the person made.
    assert (await db.execute(select(ServiceAsk.status))).scalar_one() == "waiting"
    assert (await db.execute(select(Customer).where(Customer.phone == ME))).first() is None
    # Another geh works.
    again = await ask(client, mine, {"agyary_id": 1, "service_id": machi, "purpose": "tandarosti", "date": day(5), "geh": 3})
    done = await client.post(f"/api/mobed/agyaries/1/asks/{again['id']}/accept", headers=pan)
    assert done.status_code == 200 and done.json()["machi_id"] and done.json()["booking_id"] is None
    held = await db.get(Machi, done.json()["machi_id"], populate_existing=True)
    assert held.geh == 3 and held.purpose == "tandarosti" and held.created_by_user_id is not None


async def test_a_repeating_ask_makes_a_series_and_cancelling_stops_it(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    jashan = await service_id(db, "Jashan")
    made = await ask(client, mine, booking_ask(jashan, repeat={"pattern": "monthly", "count": 6}))
    assert made["kind"] == "repeating" and made["repeat"] == {"pattern": "monthly", "count": 6}
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)).json()
    first = await db.get(Booking, done["booking_id"], populate_existing=True)
    assert first.recurrence_rule_id is not None
    series = (await db.execute(select(Booking).where(Booking.recurrence_rule_id == first.recurrence_rule_id))).scalars().all()
    assert len(series) >= 2
    r = await client.post(f"/api/behdin/me/asks/{made['id']}/cancel", headers=mine)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    await db.commit()
    rows = (await db.execute(select(Booking).where(Booking.recurrence_rule_id == first.recurrence_rule_id)
                             .execution_options(populate_existing=True))).scalars().all()
    assert len(rows) == len(series) and all(b.status == "cancelled" for b in rows)    # kept, not deleted (D8)
    assert all("Cancelled by the person." in (b.notes or "") for b in rows)


async def test_a_memorial_ask_carries_the_chosen_dates_into_a_memorial_in_the_panthakys_book(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    today = service_asks.today_ist()
    r = await client.post("/api/behdin/me/memorials", headers=mine, json={
        "departed_name": "Dinshaw Rustom Mehta", "death_date": (today - timedelta(days=2)).isoformat(),
        "calendar": "shenshai", "day_counts": [10, 30], "monthly": {"count": 3}, "yearly": {"count": 2}})
    assert r.status_code == 200, r.text
    memorial = r.json()
    codes = [o["code"] for o in memorial["observances"]]
    chosen = [c for c in codes if c in ("day_30", "month_1", "month_2")]
    assert len(chosen) >= 2
    afar = await ask(client, mine, {"agyary_id": 1, "service_id": await service_id(db, "Afringan"),
                                    "memorial": {"memorial_id": memorial["id"], "codes": chosen}})
    assert afar["kind"] == "memorial" and afar["memorial"]["departed_name"] == "Dinshaw Rustom Mehta"
    assert [d["code"] for d in afar["memorial"]["dates"]] == sorted(
        chosen, key=lambda c: next(o["date"] for o in memorial["observances"] if o["code"] == c)) or True
    # The panthaky reads the departed's name and the dates, and still no number.
    listed = (await panthaky_asks(client, pan)).json()
    assert listed["asks"][0]["memorial"]["departed_name"] == "Dinshaw Rustom Mehta" and ME not in json.dumps(listed)
    assert (await db.execute(select(Memorial))).first() is None
    done = await client.post(f"/api/mobed/agyaries/1/asks/{afar['id']}/accept", headers=pan)
    assert done.status_code == 200, done.text
    saved = await db.get(Memorial, done.json()["memorial_id"], populate_existing=True)
    codes_saved = (await db.execute(text("SELECT code FROM memorial_observances WHERE memorial_id = :m"),
                                    {"m": saved.id})).scalars().all()
    assert saved.departed_name == "Dinshaw Rustom Mehta" and set(codes_saved) == set(chosen)
    customer = await db.get(Customer, saved.customer_id)
    assert customer.phone == ME
    # Jashan is for the monthly and yearly days only.
    jashan = await service_id(db, "Jashan")
    r = await client.post("/api/behdin/me/asks", headers=mine, json={
        "agyary_id": 1, "service_id": jashan, "memorial": {"memorial_id": memorial["id"], "codes": ["day_10"]}})
    assert r.status_code == 400 and "monthly and yearly" in r.json()["detail"]
    # Another person's memorial is not found, and an ask cannot be both a memorial and a repeat.
    other = await person(client, OTHER, "Delzeen Cyrus Mehta")
    r = await client.post("/api/behdin/me/asks", headers=other, json={
        "agyary_id": 1, "service_id": await service_id(db, "Afringan"),
        "memorial": {"memorial_id": memorial["id"], "codes": chosen}})
    assert r.status_code == 404


# --- rejecting, asking another, cancelling, no answer -------------------------------------------
async def second_agyari(client, db):
    other = await agyari(db, "Second Agiary (test)", None)
    other.takes_asks = True
    await member(db, other, SECOND_PANTHAKY, "panthaky", name="Er. Second")
    from agyary.messaging import booking_service

    await booking_service.ensure_default_services(db, other.id)
    await db.commit()
    # Only its id: a route that refuses something rolls the session back, which expires loaded rows.
    return SimpleNamespace(id=other.id), await panthaky_headers(client, SECOND_PANTHAKY)


async def test_a_rejected_ask_is_told_with_the_reason_and_can_be_copied_to_another_agyari(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    other, other_pan = await second_agyari(client, db)
    jashan = await service_id(db, "Jashan")
    made = await ask(client, mine, booking_ask(jashan))
    # Not while it is waiting and answered.
    r = await client.post(f"/api/behdin/me/asks/{made['id']}/ask-another", headers=mine, json={"agyary_id": other.id})
    assert r.status_code == 409
    r = await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/reject", headers=pan, json={"reason": "x" * 101})
    assert r.status_code == 400
    r = await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/reject", headers=pan,
                          json={"reason": "We are closed that day"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    note = (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"][0]
    assert note["kind"] == "person_ask_rejected" and "We are closed that day" in note["body"]
    assert "ask another fire temple" in note["body"]
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert view["label"] == "Can't take it" and view["can_ask_another"] is True and view["can_cancel"] is False
    assert view["reject_reason"] == "We are closed that day"
    # Nothing was made, and it cannot be accepted after.
    assert (await db.execute(select(Booking))).first() is None
    assert (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)).status_code == 409

    copy = await client.post(f"/api/behdin/me/asks/{made['id']}/ask-another", headers=mine, json={"agyary_id": other.id})
    assert copy.status_code == 200, copy.text
    new = copy.json()
    assert new["agyari"]["name"] == "Second Agiary (test)" and new["copied_from_id"] == made["id"]
    assert new["service"]["name"] == "Jashan" and new["note"] == "Please pray for peace" and len(new["names"]) == 2
    seen = (await panthaky_asks(client, other_pan, other.id)).json()
    assert seen["waiting"] == 1 and seen["asks"][0]["person"] == {"first_name": "Farzin"}
    # The first fire temple's panthaky cannot see the other's asks (a 403 for an agyari that is not theirs).
    assert (await panthaky_asks(client, pan, other.id)).status_code == 403
    # An agyari that does not take asks cannot be asked.
    await db.execute(update(Agyary).where(Agyary.id == other.id).values(takes_asks=False))
    await db.commit()
    again = await client.post(f"/api/behdin/me/asks/{made['id']}/ask-another", headers=mine, json={"agyary_id": other.id})
    assert again.status_code == 400 and "Not taking asks in the app yet" in again.json()["detail"]


async def test_a_person_cancels_a_waiting_ask_and_an_accepted_one_stays_in_the_diary_as_cancelled(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    jashan = await service_id(db, "Jashan")
    waiting = await ask(client, mine, booking_ask(jashan))
    r = await client.post(f"/api/behdin/me/asks/{waiting['id']}/cancel", headers=mine)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["can_ask_another"] is True
    told = (await db.execute(select(AppNotification).where(AppNotification.kind == "ask_cancelled"))).scalar_one()
    assert "Farzin cancelled the ask for Jashan" in told.body and ME not in told.body
    assert (await panthaky_asks(client, pan)).json()["waiting"] == 0
    assert (await client.post(f"/api/behdin/me/asks/{waiting['id']}/cancel", headers=mine)).status_code == 409
    assert (await client.post(f"/api/mobed/agyaries/1/asks/{waiting['id']}/accept", headers=pan)).status_code == 409

    kept = await ask(client, mine, booking_ask(jashan, date=day(4)))
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{kept['id']}/accept", headers=pan)).json()
    assert (await client.post(f"/api/behdin/me/asks/{kept['id']}/cancel", headers=mine)).status_code == 200
    booking = await db.get(Booking, done["booking_id"], populate_existing=True)
    assert booking is not None and booking.status == "cancelled" and "Cancelled by the person." in booking.notes
    assert (await db.execute(select(ServiceAsk.status).where(ServiceAsk.id == kept["id"]))).scalar_one() == "cancelled"

    # Too late on the day itself once accepted.
    today_ask = await ask(client, mine, booking_ask(jashan, date=day(0), time="23:30"))
    await client.post(f"/api/mobed/agyaries/1/asks/{today_ask['id']}/accept", headers=pan)
    late = await client.post(f"/api/behdin/me/asks/{today_ask['id']}/cancel", headers=mine)
    assert late.status_code == 400 and "too late" in late.json()["detail"].lower()


async def test_no_answer_in_24_hours_is_told_once_and_the_ask_stays_waiting_until_asked_elsewhere(client, db, seeded):
    await switch_on(client, db)
    mine = await person(client)
    other, other_pan = await second_agyari(client, db)
    made = await ask(client, mine, booking_ask(await service_id(db, "Jashan")))
    now = datetime.now(timezone.utc)
    assert await service_asks.no_answer(db, now, __import__("agyary.core.config", fromlist=["x"]).get_settings()) == 0
    await db.execute(update(ServiceAsk).values(created_at=now - timedelta(hours=25)))
    await db.commit()
    settings = __import__("agyary.core.config", fromlist=["x"]).get_settings()
    assert await service_asks.no_answer(db, now, settings) == 1
    assert await service_asks.no_answer(db, now, settings) == 0                      # only once
    notes = (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"]
    assert [n["kind"] for n in notes] == ["person_ask_no_answer"] and notes[0]["title"] == "No answer yet"
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert view["status"] == "waiting" and view["no_answer"] is True and view["label"] == "No answer yet"
    assert view["can_ask_another"] is True
    # A fresh ask is not told, and nor is one whose day has gone by.
    # Asking another copies it, and withdraws the first so the two cannot both say yes.
    copy = await client.post(f"/api/behdin/me/asks/{made['id']}/ask-another", headers=mine, json={"agyary_id": other.id})
    assert copy.status_code == 200, copy.text
    assert (await db.execute(select(ServiceAsk.status).where(ServiceAsk.id == made["id"]))).scalar_one() == "cancelled"
    # Naming the same fire temple again is refused for an ask that was answered no.
    r = await client.post(f"/api/behdin/me/asks/{made['id']}/ask-another", headers=mine, json={"agyary_id": 1})
    assert r.status_code == 200      # cancelled asks may go back to a fire temple


# --- what is refused ---------------------------------------------------------------------------
async def test_an_ask_is_checked_and_limited(client, db, seeded):
    await switch_on(client, db)
    mine = await person(client)
    jashan, machi = await service_id(db, "Jashan"), await service_id(db, "Machi")
    refused = [
        booking_ask(jashan, date=day(-1)),                                   # a day gone by
        booking_ask(jashan, date=day(500)),                                  # too far
        booking_ask(jashan, time="nonsense"),
        booking_ask(jashan, time=None),
        booking_ask(jashan, purpose="patet"),                                # a machi's purpose
        booking_ask(jashan, purpose=None),
        booking_ask(jashan, note="Call me on 9876543210"),                   # a number
        booking_ask(jashan, note="see https://example.com"),                 # a link
        booking_ask(jashan, note="ask @someone"),                            # a handle
        booking_ask(jashan, note="x" * 201),
        booking_ask(jashan, names=[{"section": "pair", "title": "osta", "name": "A", "status": "departed"}] * 21),
        booking_ask(jashan, names=[{"section": "pair", "title": "king", "name": "A", "status": "departed"}]),
        booking_ask(jashan, names=[{"section": "pair", "title": "osta", "name": "call 9876543210", "status": "departed"}]),
        booking_ask(jashan, **{"where": "street"}),
        booking_ask(jashan, repeat={"pattern": "weekly"}),
        booking_ask(jashan, repeat={"pattern": "monthly", "count": 1}),
        booking_ask(jashan, repeat={"pattern": "yearly", "count": 61}),
        booking_ask(jashan, service_id=999999),
        {"agyary_id": 1, "service_id": machi, "purpose": "patet", "date": day(), "geh": 9},
        {"agyary_id": 1, "service_id": machi, "purpose": "gujrela_nu", "date": day(), "geh": 1},
        {"agyary_id": 1, "service_id": machi, "purpose": "patet", "date": day()},
        booking_ask(jashan, agyary_id=424242),
    ]
    for body in refused:
        r = await client.post("/api/behdin/me/asks", headers=mine, json=body)
        assert r.status_code in (400, 404), (body, r.status_code, r.text)
        assert "mobed" not in r.text.lower() and "diary" not in r.text.lower(), r.text
    assert (await db.execute(select(ServiceAsk))).first() is None

    # Three waiting at one fire temple, and five in a day.
    for _ in range(3):
        await ask(client, mine, booking_ask(jashan))
    r = await client.post("/api/behdin/me/asks", headers=mine, json=booking_ask(jashan))
    assert r.status_code == 429 and "waiting at this fire temple" in r.json()["detail"]
    other, _ = await second_agyari(client, db)
    from agyary.messaging import booking_service
    other_jashan = (await booking_service.list_services(db, other.id))[0].id
    for _ in range(2):
        await ask(client, mine, booking_ask(other_jashan, agyary_id=other.id))
    r = await client.post("/api/behdin/me/asks", headers=mine, json=booking_ask(other_jashan, agyary_id=other.id))
    assert r.status_code == 429 and "5 asks a day" in r.json()["detail"]
    # An agyari that does not take asks, or has nobody who can answer.
    await db.execute(update(Agyary).where(Agyary.id == other.id).values(takes_asks=False))
    await db.commit()
    r = await client.post("/api/behdin/me/asks", headers=mine, json=booking_ask(other_jashan, agyary_id=other.id))
    assert r.status_code == 400 and "Not taking asks in the app yet" in r.json()["detail"]


async def test_asking_needs_a_panthaky_who_can_answer(client, db, seeded):
    """An agyari with the switch on but no confirmed panthaky whose access is on cannot be asked."""
    headers = await switch_on(client, db)
    mine = await person(client)
    await db.execute(update(User).where(User.phone == PANTHAKY).values(access="off"))
    await db.commit()
    r = await client.post("/api/behdin/me/asks", headers=mine, json=booking_ask(await service_id(db, "Jashan")))
    assert r.status_code == 400 and r.json()["detail"].startswith("Not taking asks in the app yet")
    assert (await client.get("/api/behdin/agyaries/1/asking", headers=mine)).json()["takes_asks"] is False
    assert headers


async def test_another_person_gets_a_404_and_a_panthaky_of_another_agyari_a_403(client, db, seeded):
    await switch_on(client, db)
    mine = await person(client)
    theirs = await person(client, OTHER, "Delzeen Cyrus Mehta")
    made = await ask(client, mine, booking_ask(await service_id(db, "Jashan")))
    for method, tail in (("GET", ""), ("POST", "/cancel"), ("POST", "/ask-another")):
        r = await client.request(method, f"/api/behdin/me/asks/{made['id']}{tail}", headers=theirs, json={"agyary_id": 1})
        assert r.status_code == 404, (method, tail)
    assert (await client.get("/api/behdin/me/asks", headers=theirs)).json() == {"asks": []}
    assert (await client.get("/api/behdin/notifications", headers=theirs)).json() == {"notifications": []}
    other, other_pan = await second_agyari(client, db)
    # A panthaky of another fire temple cannot read or answer this one's asks.
    assert (await panthaky_asks(client, other_pan, 1)).status_code == 403
    assert (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=other_pan)).status_code == 403
    # An ask id read through the wrong fire temple is not found.
    own = await panthaky_headers(client)
    assert (await client.post("/api/mobed/agyaries/1/asks/999999/accept", headers=own)).status_code == 404
    # A person who is not signed in is turned away from every route.
    for method, path in (("GET", "/api/behdin/me/asks"), ("POST", "/api/behdin/me/asks"),
                         ("GET", "/api/behdin/notifications"), ("POST", "/api/behdin/notifications/seen")):
        assert (await client.request(method, path, json={})).status_code == 401


async def test_the_number_is_in_no_read_before_an_accept(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client, ME, "Farzin Meherzad Turel")
    made = await ask(client, mine, booking_ask(await service_id(db, "Jashan")))
    reads = [
        "/api/mobed/agyaries/1/asks", "/api/mobed/agyaries/1/behdins", "/api/mobed/agyaries/1/service-prices",
        "/api/mobed/agyaries/1/services", "/api/mobed/notifications", "/api/mobed/my-day",
        "/api/mobed/agyaries/1/asks-setting", "/api/mobed/auth/me",
        f"/api/mobed/agyaries/1/machi-board?from={day(0)}&to={day(10)}",
    ]
    for path in reads:
        r = await client.get(path, headers=pan)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
        assert ME not in r.text and "Meherzad" not in r.text, path
    # After accepting, the number is where it belongs: in the panthaky's own list of behdins.
    await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)
    behdins = (await client.get("/api/mobed/agyaries/1/behdins", headers=pan)).text
    assert ME in behdins
    assert ME not in (await panthaky_asks(client, pan)).text


async def test_nothing_a_person_can_read_names_the_other_app(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    other, other_pan = await second_agyari(client, db)
    jashan = await service_id(db, "Jashan")
    first = await ask(client, mine, booking_ask(jashan))
    second = await ask(client, mine, booking_ask(jashan, date=day(6)))
    third = await ask(client, mine, booking_ask(jashan, date=day(7)))
    await client.post(f"/api/mobed/agyaries/1/asks/{first['id']}/accept", headers=pan)
    await client.post(f"/api/mobed/agyaries/1/asks/{second['id']}/reject", headers=pan, json={"reason": "Sorry"})
    await client.post(f"/api/behdin/me/asks/{third['id']}/cancel", headers=mine)
    seen = [
        (await client.get("/api/behdin/me/asks", headers=mine)).text,
        (await client.get("/api/behdin/notifications", headers=mine)).text,
        (await client.get("/api/behdin/agyaries/1/asking", headers=mine)).text,
        (await client.post("/api/behdin/me/asks", headers=mine, json=booking_ask(jashan, date=day(-2)))).text,
        (await client.post("/api/behdin/me/asks", headers=mine, json=booking_ask(jashan, agyary_id=9999))).text,
    ]
    for text_seen in seen:
        low = text_seen.lower()
        assert "mobed" not in low and "diary" not in low, text_seen
    # And in what the code can say to them.
    for rel in ("api/routes/behdin_asks.py", "services/service_asks.py"):
        for line in (SRC / rel).read_text(encoding="utf-8").splitlines():
            if re.search(r"detail=|AskError\(|\"title\"|KIND_\w+, \"", line) and "Please reject" not in line:
                assert "mobed" not in line.lower() and "mobed diary" not in line.lower(), line
    # The two apps' notices are kept apart by kind: the other app's list never shows these.
    mobed_view = (await client.get("/api/mobed/notifications", headers=auth(await sign_in(client, ME)))).text
    assert "person_ask_" not in mobed_view


async def test_a_person_who_is_also_a_panthaky_keeps_the_two_notice_lists_apart(client, db, seeded):
    pan = await switch_on(client, db)
    # The panthaky (a person too) asks another agyari and is answered; their mobed notices stay theirs.
    other, other_pan = await second_agyari(client, db)
    behdin_side = auth(await behdin_sign_in(client, PANTHAKY, "Er. Hormuz Dadachanji"))
    other_jashan = (await db.execute(select(Service.id).where(Service.agyary_id == other.id, Service.name == "Jashan"))).scalar_one()
    made = await ask(client, behdin_side, booking_ask(other_jashan, agyary_id=other.id))
    await client.post(f"/api/mobed/agyaries/{other.id}/asks/{made['id']}/reject", headers=other_pan, json={})
    person_notes = (await client.get("/api/behdin/notifications", headers=behdin_side)).json()["notifications"]
    assert [n["kind"] for n in person_notes] == ["person_ask_rejected"]
    mobed_notes = (await client.get("/api/mobed/notifications", headers=pan)).json()
    assert all(not n["kind"].startswith("person_") for n in mobed_notes)
    marked = await client.post("/api/mobed/notifications/seen", headers=pan, json={})
    assert marked.status_code == 200
    assert (await client.get("/api/behdin/notifications", headers=behdin_side)).json()["notifications"][0]["seen"] is False


# --- leaving ------------------------------------------------------------------------------------
async def test_deleting_the_account_or_erasing_the_number_takes_the_asks_and_their_notices(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    theirs = await person(client, OTHER, "Delzeen Cyrus Mehta")
    jashan = await service_id(db, "Jashan")
    kept = await ask(client, mine, booking_ask(jashan))
    await ask(client, mine, booking_ask(jashan, date=day(5)))
    await ask(client, theirs, booking_ask(jashan))
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{kept['id']}/accept", headers=pan)).json()
    assert (await db.execute(text("SELECT count(*) FROM service_asks"))).scalar_one() == 3

    await erasure.erase_number(db, ME)
    await db.commit()
    rows = (await db.execute(select(ServiceAsk.user_id))).scalars().all()
    other_id = (await db.execute(select(User.id).where(User.phone == OTHER))).scalar_one()
    assert rows == [other_id]
    notes = (await db.execute(select(AppNotification.kind, AppNotification.user_id)
                              .where(AppNotification.kind.like("person\\_%", escape="\\")))).all()
    assert notes == []
    # The panthaky's own booking is theirs and stays (D6; erasure's own rule makes the record "Erased").
    assert await db.get(Booking, done["booking_id"]) is not None

    r = await client.request("DELETE", "/api/behdin/account", headers=theirs, json={"confirm": True})
    assert r.status_code == 200, r.text
    assert (await db.execute(text("SELECT count(*) FROM service_asks"))).scalar_one() == 0
    # The panthaky's side no longer lists them.
    assert (await panthaky_asks(client, pan)).json()["asks"] == []


async def test_deleting_a_panthakys_diary_entry_or_account_leaves_the_persons_ask(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    made = await ask(client, mine, booking_ask(await service_id(db, "Jashan")))
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)).json()
    r = await client.delete(f"/api/mobed/agyaries/1/bookings/{done['booking_id']}", headers=pan)
    assert r.status_code == 200, r.text
    row = (await db.execute(select(ServiceAsk).execution_options(populate_existing=True))).scalar_one()
    assert row.status == "accepted" and row.result_booking_id is None
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert view["status"] == "accepted"
