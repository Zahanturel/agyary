"""R4.2: a person makes a request to a fire temple (docs/behdin-r4-2-design.md, DECISIONS 25 Nov 2026).

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
    assert r.status_code == 200 and r.json()["takes_asks"] is True, r.text
    return headers


async def person(client, phone: str = ME, name: str = "Farzin Meherzad Turel") -> dict:
    return auth(await behdin_sign_in(client, phone, name))


def item(sid: int, **changes) -> dict:
    """One prayer of a request: a service on a day at a time."""
    body = {"service_id": sid, "date": day(), "time": "10:00"}
    body.update(changes)
    return body


def request(*items: dict, **changes) -> dict:
    """A request to the demo fire temple, with typed names."""
    body = {"agyary_id": 1, "items": list(items), "names": ["Rustom Test", "Roda Test"]}
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
    first = (await client.get("/api/mobed/agyaries/1/asks-setting", headers=headers)).json()
    assert first["takes_asks"] is False and first["ready"] is True       # the seeded services all have prices
    assert {s["name"] for s in first["services"]} >= {"Jashan", "Machi"} and all(s["price"] is not None for s in first["services"])
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
    assert (await client.get("/api/mobed/agyaries/1/asks-setting", headers=headers)).json()["takes_asks"] is True


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


async def test_a_person_sees_what_a_fire_temple_offers_only_when_it_takes_requests(client, db, seeded):
    mine = await person(client)
    r = await client.get("/api/behdin/agyaries/1/offering", headers=mine)
    assert r.status_code == 200
    closed = r.json()
    assert closed["takes_requests"] is False and closed["message"] == "Not taking requests yet"
    assert closed["services"] == [] and closed["memorial"] is None
    await switch_on(client, db)
    seen = (await client.get("/api/behdin/agyaries/1/offering", headers=mine)).json()
    assert seen["takes_requests"] is True and seen["name"] == "Goti Adarian" and seen["city"] == "Mumbai"
    by_name = {s["name"]: s for s in seen["services"]}
    assert by_name["Jashan"]["price"] == 1500.0 and by_name["Jashan"]["type"] == "service"
    assert by_name["Machi"]["by_geh"] is True and by_name["Jashan"]["by_geh"] is False
    assert seen["memorial"] == {"type": "memorial", "name": "Memorial", "price": None,
                                "prayers": ["Afringan", "Farokshi", "Baaj"]}
    assert seen["repeats"] == {"monthly": {"max": 120}, "yearly": {"max": 60}}
    raw = json.dumps(seen)
    assert "+9198" not in raw and "phone" not in raw
    # A service with no price is not offered.
    await client.put(f"/api/mobed/agyaries/1/services/{await service_id(db, 'Lagan')}",
                     headers=await panthaky_headers(client), json={"is_active": False})
    await db.execute(update(Service).where(Service.name == "Satum").values(default_price=None))
    await db.commit()
    again = (await client.get("/api/behdin/agyaries/1/offering", headers=mine)).json()
    assert {"Satum", "Lagan"}.isdisjoint(s["name"] for s in again["services"])
    assert (await client.get("/api/behdin/agyaries/99999/offering", headers=mine)).status_code == 404
    assert (await client.get("/api/behdin/agyaries/1/offering")).status_code == 401
    assert (await client.get("/api/behdin/agyaries/1/asking", headers=mine)).status_code in (404, 405)   # replaced


# --- the full path -----------------------------------------------------------------------------
async def test_a_request_is_read_without_a_number_and_confirmed_into_the_panthakys_own_book(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    jashan = await service_id(db, "Jashan")
    made = await ask(client, mine, request(item(jashan)))
    assert made["status"] == "waiting" and made["label"] == "Pending" and made["can_cancel"] is True
    assert made["agyari"]["name"] == "Goti Adarian" and made["names"] == ["Rustom Test", "Roda Test"]
    [one] = made["items"]
    assert one["name"] == "Jashan" and one["date"] == day() and one["time"] == "10:00" and one["time_open"] is False
    assert one["price"] == 1500.0 and one["total"] == 1500.0 and made["total"] == 1500.0
    assert made["total_is_estimate"] is False and one["state"] == "waiting"

    # The panthaky reads it: first name only, nothing that says who they are.
    r = await panthaky_asks(client, pan)
    assert r.status_code == 200 and r.json()["waiting"] == 1
    row = r.json()["asks"][0]
    assert row["person"] == {"first_name": "Farzin"} and row["names"] == ["Rustom Test", "Roda Test"]
    assert row["items"][0]["name"] == "Jashan" and row["items"][0]["parsi"] and row["total"] == 1500.0
    assert ME not in r.text and "Meherzad" not in r.text and "Turel" not in r.text and "phone" not in r.text
    # No record of them exists in the panthaky's book yet, nothing is booked.
    assert (await db.execute(select(Customer).where(Customer.phone == ME))).first() is None
    assert (await db.execute(select(Booking))).first() is None

    # The panthaky was told, by first name and the first prayer, with a link to the Requests tab.
    note = (await db.execute(select(AppNotification).where(AppNotification.kind == "ask_new"))).scalar_one()
    assert note.title == "New request" and note.body.startswith("Farzin: Jashan on ") and ME not in note.body
    assert note.link == "#/requests"
    panthaky_id = (await db.execute(select(User.id).where(User.phone == PANTHAKY))).scalar_one()
    assert note.user_id == panthaky_id

    confirmed = await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    entry = body["items"][0]
    assert entry["booking_id"] and entry["machi_id"] is None and body["ask"]["status"] == "accepted"
    assert ME not in confirmed.text

    # Now they are a record in the panthaky's own book, and the booking is as if the panthaky made it.
    customer = (await db.execute(select(Customer).where(Customer.phone == ME))).scalar_one()
    assert customer.owner_user_id == panthaky_id and customer.name == "Farzin Meherzad Turel"
    booking = await db.get(Booking, entry["booking_id"], populate_existing=True)
    assert booking.customer_id == customer.id and booking.created_by_user_id == panthaky_id
    assert booking.status == "approved" and booking.purpose == "gujrela_nu" and booking.is_offsite is False
    assert booking.ceremony_datetime.astimezone(service_asks.IST).strftime("%Y-%m-%d %H:%M") == f"{day()} 10:00"
    detail = (await client.get(f"/api/mobed/agyaries/1/bookings/{booking.id}/detail", headers=pan)).text
    assert "Rustom Test" in detail and "Roda Test" in detail                  # the typed names are on the slip

    # The person is told, tersely, in the app.
    notes = (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"]
    assert len(notes) == 1 and notes[0]["kind"] == "person_ask_accepted" and notes[0]["seen"] is False
    assert notes[0]["title"] == "Request confirmed" and notes[0]["body"].startswith("Goti Adarian: Jashan on ")
    mine_now = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert mine_now["status"] == "accepted" and mine_now["label"] == "Confirmed" and mine_now["items"][0]["state"] == "accepted"
    assert (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)).status_code == 409
    assert (await client.post("/api/behdin/notifications/seen", headers=mine, json={})).json() == {"marked": 1}
    assert (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"][0]["seen"] is True


async def test_a_request_of_several_prayers_is_confirmed_whole_and_the_open_time_is_the_panthakys_to_give(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    jashan, afringan, machi = [await service_id(db, n) for n in ("Jashan", "Afringan", "Machi")]
    made = await ask(client, mine, request(
        item(jashan, time="09:30"), item(afringan, date=day(5), time=None),
        {"service_id": machi, "date": day(6), "geh": 2}, item(jashan, date=day(7), recurring="monthly", recurring_count=3)))
    items = made["items"]
    assert [i["name"] for i in items] == ["Jashan", "Afringan", "Machi", "Jashan"]
    assert [i["date"] for i in items] == [day(), day(5), day(6), day(7)]       # each prayer has its own day
    assert items[1]["time"] is None and items[1]["time_open"] is True
    assert items[2]["geh"] == 2 and items[2]["geh_name"] == "Rapithwan" and items[2]["time_open"] is False
    assert items[3]["repeat"] == {"recurring": "monthly", "recurring_count": 3} and items[3]["kind"] == "repeating"
    # Prices: each item's, a repeat is the price each time times the count (an estimate), the sum, flagged.
    assert [i["price"] for i in items] == [1500.0, 200.0, 300.0, 1500.0]
    assert [i["total"] for i in items] == [1500.0, 200.0, 300.0, 4500.0] and items[3]["times"] == 3
    assert made["total"] == 6500.0 and made["total_is_estimate"] is True
    assert made["id"] and (await db.execute(select(ServiceAsk))).scalars().all().__len__() == 1

    # The panthaky confirms the whole request; the open time must be given, and nothing is half made.
    url = f"/api/mobed/agyaries/1/asks/{made['id']}/accept"
    refused = await client.post(url, headers=pan)
    assert refused.status_code == 409 and refused.json()["detail"].startswith("Enter a time for Afringan")
    assert (await db.execute(select(Booking))).first() is None and (await db.execute(select(Machi))).first() is None
    assert (await db.execute(select(Customer).where(Customer.phone == ME))).first() is None
    done = await client.post(url, headers=pan, json={"times": {str(items[1]["id"]): "11:00"}})
    assert done.status_code == 200, done.text
    entries = done.json()["items"]
    assert entries[0]["booking_id"] and entries[1]["booking_id"] and entries[2]["machi_id"] and entries[3]["booking_id"]
    second = await db.get(Booking, entries[1]["booking_id"], populate_existing=True)
    assert second.ceremony_datetime.astimezone(service_asks.IST).strftime("%H:%M") == "11:00"
    series = await db.get(Booking, entries[3]["booking_id"], populate_existing=True)
    assert series.recurrence_rule_id is not None
    assert len((await db.execute(select(Customer).where(Customer.phone == ME))).scalars().all()) == 1
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert view["status"] == "accepted" and view["items"][1]["time"] == "11:00" and view["items"][1]["time_open"] is False
    cal = (await client.get(f"/api/behdin/me/calendar?from={day(0)}&to={day(9)}", headers=mine)).json()["items"]
    assert {(i["date"], i["time"], i["geh"]) for i in cal if i["source"] == "request"} >= {
        (day(), "09:30", None), (day(5), "11:00", None), (day(6), None, 2), (day(7), "10:00", None)}


async def test_one_item_the_diary_refuses_leaves_the_whole_request_unconfirmed(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    machi, jashan = await service_id(db, "Machi"), await service_id(db, "Jashan")
    made = await ask(client, mine, request(item(jashan), {"service_id": machi, "date": day(5), "geh": 2}))
    # The panthaky already holds that geh that day.
    r = await client.post("/api/mobed/agyaries/1/manual-add/machi", headers=pan, json={
        "behdin_phone": "+919911100099", "behdin_name": "Someone Else", "roj": 1, "mah": 1, "year": 1400,
        "geh": 2, "gregorian": day(5), "purpose": "patet", "names": []})
    assert r.status_code == 200 and r.json()["confirmed"] is True
    refused = await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)
    assert refused.status_code == 409 and "already hold that geh" in refused.json()["detail"]
    # Nothing was half done: still pending, the Jashan before it was not made, no record of the person.
    assert (await db.execute(select(ServiceAsk.status))).scalar_one() == "waiting"
    assert (await db.execute(select(Booking))).first() is None
    assert (await db.execute(select(Customer).where(Customer.phone == ME))).first() is None


async def test_a_repeating_item_makes_a_series_and_cancelling_stops_it(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    made = await ask(client, mine, request(item(await service_id(db, "Jashan"), recurring="monthly", recurring_count=6)))
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)).json()
    first = await db.get(Booking, done["items"][0]["booking_id"], populate_existing=True)
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


async def test_a_memorial_item_carries_the_name_and_date_of_passing_and_is_made_with_the_diarys_defaults(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    today = service_asks.today_ist()
    died = (today - timedelta(days=2)).isoformat()
    made = await ask(client, mine, {"agyary_id": 1, "items": [
        {"type": "memorial", "departed_name": "Dinshaw Rustom Mehta", "death_date": died,
         "recurring": "monthly", "recurring_count": 3},
        {"type": "memorial", "death_date": (today - timedelta(days=40)).isoformat()}]})
    first, unnamed = made["items"]
    assert first["type"] == "memorial" and first["name"] == "Memorial" and first["price"] is None and made["total"] is None
    assert first["memorial"]["departed_name"] == "Dinshaw Rustom Mehta" and first["memorial"]["death_date"] == died
    assert first["memorial"]["recurring"] == "monthly" and first["memorial"]["recurring_count"] == 3
    assert unnamed["memorial"]["departed_name"] == "(name not known)" and unnamed["memorial"]["name_known"] is False
    assert made["total_is_estimate"] is True
    # The panthaky reads the departed's name and the date of passing, and still no number.
    listed = (await panthaky_asks(client, pan)).json()
    assert listed["asks"][0]["items"][0]["memorial"]["departed_name"] == "Dinshaw Rustom Mehta"
    assert ME not in json.dumps(listed) and (await db.execute(select(Memorial))).first() is None

    done = await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)
    assert done.status_code == 200, done.text
    first_memorial = await db.get(Memorial, done.json()["items"][0]["memorial_id"], populate_existing=True)
    codes = set((await db.execute(text("SELECT code FROM memorial_observances WHERE memorial_id = :m"),
                                  {"m": first_memorial.id})).scalars().all())
    assert {"day_10", "day_30", "day_360"} <= codes and {"month_2", "month_3"} <= codes     # the defaults + the series
    prayers = set((await db.execute(text(
        "SELECT s.name FROM memorial_observance_services mos JOIN services s ON s.id = mos.service_id"
        " JOIN memorial_observances o ON o.id = mos.observance_id WHERE o.memorial_id = :m"),
        {"m": first_memorial.id})).scalars().all())
    assert prayers == {"Afringan", "Farokshi", "Baaj"}
    assert first_memorial.departed_name == "Dinshaw Rustom Mehta"
    other = await db.get(Memorial, done.json()["items"][1]["memorial_id"], populate_existing=True)
    assert other.departed_name == "(name not known)"
    assert (await db.get(Customer, first_memorial.customer_id)).phone == ME
    # The date of passing may not be in the future; a repeat of a memorial needs its count.
    for bad in ({"type": "memorial", "death_date": (today + timedelta(days=1)).isoformat()},
                {"type": "memorial"}, {"type": "memorial", "death_date": died, "recurring": "yearly"}):
        assert (await client.post("/api/behdin/me/asks", headers=mine, json={"agyary_id": 1, "items": [bad]})).status_code == 400


# --- declining, asking another, cancelling, no answer ----------------------------------------------
async def second_agyari(client, db):
    other = await agyari(db, "Second Agiary (test)", None)
    other.takes_asks = True
    await member(db, other, SECOND_PANTHAKY, "panthaky", name="Er. Second")
    from agyary.messaging import booking_service

    await booking_service.ensure_default_services(db, other.id)
    await db.execute(update(Service).where(Service.agyary_id == other.id).values(default_price=100))
    await db.commit()
    # Only its id: a route that refuses something rolls the session back, which expires loaded rows.
    return SimpleNamespace(id=other.id), await panthaky_headers(client, SECOND_PANTHAKY)


async def test_a_declined_request_is_told_with_the_reason_and_can_be_copied_to_another_fire_temple(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    other, other_pan = await second_agyari(client, db)
    jashan, machi = await service_id(db, "Jashan"), await service_id(db, "Machi")
    made = await ask(client, mine, request(item(jashan), {"service_id": machi, "date": day(5), "geh": 3}))
    # Not while it is pending.
    r = await client.post(f"/api/behdin/me/asks/{made['id']}/ask-another", headers=mine, json={"agyary_id": other.id})
    assert r.status_code == 409
    r = await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/reject", headers=pan, json={"reason": "x" * 101})
    assert r.status_code == 400
    r = await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/reject", headers=pan,
                          json={"reason": "We are closed that day"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    note = (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"][0]
    assert note["kind"] == "person_ask_rejected" and note["title"] == "Request declined"
    assert note["body"].startswith("Goti Adarian: Jashan on ") and "+1 more" in note["body"]
    assert "Reason: We are closed that day" in note["body"]
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert view["label"] == "Declined" and view["can_ask_another"] is True and view["can_cancel"] is False
    assert view["reject_reason"] == "We are closed that day"
    assert (await db.execute(select(Booking))).first() is None
    assert (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)).status_code == 409

    copy = await client.post(f"/api/behdin/me/asks/{made['id']}/ask-another", headers=mine, json={"agyary_id": other.id})
    assert copy.status_code == 200, copy.text
    new = copy.json()
    assert new["agyari"]["name"] == "Second Agiary (test)" and new["copied_from_id"] == made["id"]
    assert [i["name"] for i in new["items"]] == ["Jashan", "Machi"] and new["names"] == ["Rustom Test", "Roda Test"]
    assert [i["price"] for i in new["items"]] == [100.0, 100.0]               # that fire temple's prices
    seen = (await panthaky_asks(client, other_pan, other.id)).json()
    assert seen["waiting"] == 1 and seen["asks"][0]["person"] == {"first_name": "Farzin"}
    assert (await panthaky_asks(client, pan, other.id)).status_code == 403
    # A fire temple that does not offer one of the prayers, or is not taking requests, cannot be asked.
    await db.execute(update(Service).where(Service.agyary_id == other.id, Service.name == "Machi").values(is_active=False))
    await db.commit()
    again = await client.post(f"/api/behdin/me/asks/{made['id']}/ask-another", headers=mine, json={"agyary_id": other.id})
    assert again.status_code == 400 and "does not offer Machi" in again.json()["detail"]
    await db.execute(update(Service).where(Service.agyary_id == other.id, Service.name == "Machi").values(is_active=True))
    await db.execute(update(Agyary).where(Agyary.id == other.id).values(takes_asks=False))
    await db.commit()
    again = await client.post(f"/api/behdin/me/asks/{made['id']}/ask-another", headers=mine, json={"agyary_id": other.id})
    assert again.status_code == 400 and "Not taking requests yet" in again.json()["detail"]


async def test_a_person_cancels_a_pending_request_and_a_confirmed_one_stays_in_the_diary_as_cancelled(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    jashan = await service_id(db, "Jashan")
    waiting = await ask(client, mine, request(item(jashan)))
    r = await client.post(f"/api/behdin/me/asks/{waiting['id']}/cancel", headers=mine)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["can_ask_another"] is True
    told = (await db.execute(select(AppNotification).where(AppNotification.kind == "ask_cancelled"))).scalar_one()
    assert told.title == "Request cancelled" and told.body.startswith("Farzin: Jashan on ") and ME not in told.body
    assert (await panthaky_asks(client, pan)).json()["waiting"] == 0
    assert (await client.post(f"/api/behdin/me/asks/{waiting['id']}/cancel", headers=mine)).status_code == 409
    assert (await client.post(f"/api/mobed/agyaries/1/asks/{waiting['id']}/accept", headers=pan)).status_code == 409

    kept = await ask(client, mine, request(item(jashan, date=day(4)), item(await service_id(db, "Afringan"), date=day(5))))
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{kept['id']}/accept", headers=pan)).json()
    assert (await client.post(f"/api/behdin/me/asks/{kept['id']}/cancel", headers=mine)).status_code == 200
    for entry in done["items"]:
        booking = await db.get(Booking, entry["booking_id"], populate_existing=True)
        assert booking is not None and booking.status == "cancelled" and "Cancelled by the person." in booking.notes
    assert (await db.execute(select(ServiceAsk.status).where(ServiceAsk.id == kept["id"]))).scalar_one() == "cancelled"

    # Too late once the first day has come.
    today_ask = await ask(client, mine, request(item(jashan, date=day(0), time="23:30")))
    await client.post(f"/api/mobed/agyaries/1/asks/{today_ask['id']}/accept", headers=pan)
    late = await client.post(f"/api/behdin/me/asks/{today_ask['id']}/cancel", headers=mine)
    assert late.status_code == 400 and "too late" in late.json()["detail"].lower()


async def test_no_answer_in_24_hours_is_told_once_and_the_request_stays_pending_until_asked_elsewhere(client, db, seeded):
    await switch_on(client, db)
    mine = await person(client)
    other, other_pan = await second_agyari(client, db)
    made = await ask(client, mine, request(item(await service_id(db, "Jashan"))))
    now = datetime.now(timezone.utc)
    settings = __import__("agyary.core.config", fromlist=["x"]).get_settings()
    assert await service_asks.no_answer(db, now, settings) == 0
    await db.execute(update(ServiceAsk).values(created_at=now - timedelta(hours=25)))
    await db.commit()
    assert await service_asks.no_answer(db, now, settings) == 1
    assert await service_asks.no_answer(db, now, settings) == 0                      # only once
    notes = (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"]
    assert [n["kind"] for n in notes] == ["person_ask_no_answer"] and notes[0]["title"] == "No answer yet"
    assert notes[0]["body"].startswith("Goti Adarian: Jashan on ")
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert view["status"] == "waiting" and view["no_answer"] is True and view["label"] == "No answer yet"
    assert view["can_ask_another"] is True
    # Asking another copies it, and withdraws the first so the two cannot both say yes.
    copy = await client.post(f"/api/behdin/me/asks/{made['id']}/ask-another", headers=mine, json={"agyary_id": other.id})
    assert copy.status_code == 200, copy.text
    assert (await db.execute(select(ServiceAsk.status).where(ServiceAsk.id == made["id"]))).scalar_one() == "cancelled"
    r = await client.post(f"/api/behdin/me/asks/{made['id']}/ask-another", headers=mine, json={"agyary_id": 1})
    assert r.status_code == 200      # a cancelled request may go back to a fire temple


# --- what is refused ---------------------------------------------------------------------------
async def test_a_request_is_checked_and_limited(client, db, seeded):
    await switch_on(client, db)
    mine = await person(client)
    jashan, machi = await service_id(db, "Jashan"), await service_id(db, "Machi")
    names = [{"x": 1}]
    refused = [
        request(item(jashan, date=day(-1))),                                  # a day gone by
        request(item(jashan, date=day(500))),                                 # too far
        request(item(jashan, time="nonsense")),
        request(item(jashan, date=None)),
        request(item(jashan, purpose="patet")),                               # a machi's purpose
        request(item(jashan), names=["Call 9876543210"]),                     # a number
        request(item(jashan), names=["see https://example.com"]),             # a link
        request(item(jashan), names=["ask @someone"]),                        # a handle
        request(item(jashan), names=["x" * 81]),
        request(item(jashan), names=["A"] * 21),
        request(item(jashan), names=names),
        request(item(jashan, recurring="weekly")),
        request(item(jashan, recurring="monthly", recurring_count=1)),
        request(item(jashan, recurring="yearly", recurring_count=61)),
        request(item(jashan, recurring_count=3)),
        request(item(999999)),
        request(item(jashan, service_id=None)),
        request({"service_id": machi, "date": day(), "geh": 9}),
        request({"service_id": machi, "date": day()}),                        # a machi needs its geh
        {"agyary_id": 1, "items": []},
        {"agyary_id": 1, "items": [item(jashan)] * 11},
        {"agyary_id": 1},
        request(item(jashan), agyary_id=424242),
    ]
    for body in refused:
        r = await client.post("/api/behdin/me/asks", headers=mine, json=body)
        assert r.status_code in (400, 404, 422), (body, r.status_code, r.text)
        assert "mobed" not in r.text.lower() and "diary" not in r.text.lower(), r.text
    assert (await db.execute(select(ServiceAsk))).first() is None
    # The free note is gone: it is not a field any more (ignored if sent), nor shown.
    ok = await ask(client, mine, {**request(item(jashan)), "note": "hello"})
    assert "note" not in ok
    await client.post(f"/api/behdin/me/asks/{ok['id']}/cancel", headers=mine)

    # Three pending at one fire temple, and five in a day.
    for _ in range(3):
        await ask(client, mine, request(item(jashan)))
    r = await client.post("/api/behdin/me/asks", headers=mine, json=request(item(jashan)))
    assert r.status_code == 429 and "pending here" in r.json()["detail"]
    other, _ = await second_agyari(client, db)
    from agyary.messaging import booking_service
    other_jashan = (await booking_service.list_services(db, other.id))[0].id
    await ask(client, mine, request(item(other_jashan), agyary_id=other.id))
    r = await client.post("/api/behdin/me/asks", headers=mine, json=request(item(other_jashan), agyary_id=other.id))
    assert r.status_code == 429 and "5 requests a day" in r.json()["detail"]
    await db.execute(update(Agyary).where(Agyary.id == other.id).values(takes_asks=False))
    await db.commit()
    r = await client.post("/api/behdin/me/asks", headers=mine, json=request(item(other_jashan), agyary_id=other.id))
    assert r.status_code == 400 and "Not taking requests yet" in r.json()["detail"]


async def test_asking_needs_a_panthaky_who_can_answer(client, db, seeded):
    """A fire temple with the switch on but no confirmed panthaky whose access is on cannot be asked."""
    await switch_on(client, db)
    mine = await person(client)
    await db.execute(update(User).where(User.phone == PANTHAKY).values(access="off"))
    await db.commit()
    r = await client.post("/api/behdin/me/asks", headers=mine, json=request(item(await service_id(db, "Jashan"))))
    assert r.status_code == 400 and r.json()["detail"].startswith("Not taking requests yet")
    assert (await client.get("/api/behdin/agyaries/1/offering", headers=mine)).json()["takes_requests"] is False


async def test_another_person_gets_a_404_and_a_panthaky_of_another_fire_temple_a_403(client, db, seeded):
    await switch_on(client, db)
    mine = await person(client)
    theirs = await person(client, OTHER, "Delzeen Cyrus Mehta")
    made = await ask(client, mine, request(item(await service_id(db, "Jashan"))))
    for method, tail in (("GET", ""), ("POST", "/cancel"), ("POST", "/ask-another")):
        r = await client.request(method, f"/api/behdin/me/asks/{made['id']}{tail}", headers=theirs, json={"agyary_id": 1})
        assert r.status_code == 404, (method, tail)
    assert (await client.get("/api/behdin/me/asks", headers=theirs)).json() == {"asks": []}
    assert (await client.get("/api/behdin/notifications", headers=theirs)).json() == {"notifications": []}
    other, other_pan = await second_agyari(client, db)
    assert (await panthaky_asks(client, other_pan, 1)).status_code == 403
    assert (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=other_pan)).status_code == 403
    own = await panthaky_headers(client)
    assert (await client.post("/api/mobed/agyaries/1/asks/999999/accept", headers=own)).status_code == 404
    for method, path in (("GET", "/api/behdin/me/asks"), ("POST", "/api/behdin/me/asks"),
                         ("GET", "/api/behdin/notifications"), ("POST", "/api/behdin/notifications/seen")):
        assert (await client.request(method, path, json={})).status_code == 401


async def test_the_number_is_in_no_read_before_a_confirm(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client, ME, "Farzin Meherzad Turel")
    made = await ask(client, mine, request(item(await service_id(db, "Jashan"))))
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
    await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)
    assert ME in (await client.get("/api/mobed/agyaries/1/behdins", headers=pan)).text
    assert ME not in (await panthaky_asks(client, pan)).text


async def test_nothing_a_person_can_read_names_the_other_app(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    other, other_pan = await second_agyari(client, db)
    jashan = await service_id(db, "Jashan")
    first = await ask(client, mine, request(item(jashan)))
    second = await ask(client, mine, request(item(jashan, date=day(6))))
    third = await ask(client, mine, request(item(jashan, date=day(7))))
    await client.post(f"/api/mobed/agyaries/1/asks/{first['id']}/accept", headers=pan)
    await client.post(f"/api/mobed/agyaries/1/asks/{second['id']}/reject", headers=pan, json={"reason": "Sorry"})
    await client.post(f"/api/behdin/me/asks/{third['id']}/cancel", headers=mine)
    seen = [
        (await client.get("/api/behdin/me/asks", headers=mine)).text,
        (await client.get("/api/behdin/notifications", headers=mine)).text,
        (await client.get("/api/behdin/agyaries/1/offering", headers=mine)).text,
        (await client.post("/api/behdin/me/asks", headers=mine, json=request(item(jashan, date=day(-2))))).text,
        (await client.post("/api/behdin/me/asks", headers=mine, json=request(item(jashan), agyary_id=9999))).text,
    ]
    for text_seen in seen:
        low = text_seen.lower()
        assert "mobed" not in low and "diary" not in low, text_seen
    for rel in ("api/routes/behdin_asks.py", "services/service_asks.py"):
        for line in (SRC / rel).read_text(encoding="utf-8").splitlines():
            if re.search(r"detail=|AskError\(|\"title\"|KIND_\w+, \"", line) and "Decline the request" not in line:
                assert "mobed" not in line.lower() and "mobed diary" not in line.lower(), line
    mobed_view = (await client.get("/api/mobed/notifications", headers=auth(await sign_in(client, ME)))).text
    assert "person_ask_" not in mobed_view


async def test_a_person_who_is_also_a_panthaky_keeps_the_two_notice_lists_apart(client, db, seeded):
    pan = await switch_on(client, db)
    other, other_pan = await second_agyari(client, db)
    behdin_side = auth(await behdin_sign_in(client, PANTHAKY, "Er. Hormuz Dadachanji"))
    other_jashan = (await db.execute(select(Service.id).where(Service.agyary_id == other.id, Service.name == "Jashan"))).scalar_one()
    made = await ask(client, behdin_side, request(item(other_jashan), agyary_id=other.id))
    await client.post(f"/api/mobed/agyaries/{other.id}/asks/{made['id']}/reject", headers=other_pan, json={})
    person_notes = (await client.get("/api/behdin/notifications", headers=behdin_side)).json()["notifications"]
    assert [n["kind"] for n in person_notes] == ["person_ask_rejected"]
    mobed_notes = (await client.get("/api/mobed/notifications", headers=pan)).json()
    assert all(not n["kind"].startswith("person_") for n in mobed_notes)
    assert (await client.post("/api/mobed/notifications/seen", headers=pan, json={})).status_code == 200
    assert (await client.get("/api/behdin/notifications", headers=behdin_side)).json()["notifications"][0]["seen"] is False


# --- leaving ------------------------------------------------------------------------------------
async def test_deleting_the_account_or_erasing_the_number_takes_the_requests_and_their_notices(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    theirs = await person(client, OTHER, "Delzeen Cyrus Mehta")
    jashan = await service_id(db, "Jashan")
    kept = await ask(client, mine, request(item(jashan), item(jashan, date=day(8))))
    await ask(client, mine, request(item(jashan, date=day(5))))
    await ask(client, theirs, request(item(jashan)))
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{kept['id']}/accept", headers=pan)).json()
    assert (await db.execute(text("SELECT count(*) FROM service_asks"))).scalar_one() == 3
    assert (await db.execute(text("SELECT count(*) FROM service_ask_items"))).scalar_one() == 4

    await erasure.erase_number(db, ME)
    await db.commit()
    rows = (await db.execute(select(ServiceAsk.user_id))).scalars().all()
    other_id = (await db.execute(select(User.id).where(User.phone == OTHER))).scalar_one()
    assert rows == [other_id]
    assert (await db.execute(text("SELECT count(*) FROM service_ask_items"))).scalar_one() == 1
    assert (await db.execute(select(AppNotification.kind, AppNotification.user_id)
                             .where(AppNotification.kind.like("person\\_%", escape="\\")))).all() == []
    # The panthaky's own bookings are theirs and stay (D6; erasure's own rule makes the record "Erased").
    assert await db.get(Booking, done["items"][0]["booking_id"]) is not None

    r = await client.request("DELETE", "/api/behdin/account", headers=theirs, json={"confirm": True})
    assert r.status_code == 200, r.text
    assert (await db.execute(text("SELECT count(*) FROM service_asks"))).scalar_one() == 0
    assert (await db.execute(text("SELECT count(*) FROM service_ask_items"))).scalar_one() == 0
    assert (await panthaky_asks(client, pan)).json()["asks"] == []


# --- a confirmed request follows the fire temple's diary -----------------------------------------------
async def test_deleting_the_booking_cancels_a_one_prayer_request_by_the_fire_temple_and_tells_the_person(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    made = await ask(client, mine, request(item(await service_id(db, "Jashan"))))
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)).json()
    cal = (await client.get(f"/api/behdin/me/calendar?from={day(0)}&to={day(10)}", headers=mine)).json()["items"]
    assert [i["source"] for i in cal] == ["request"] and cal[0]["date"] == day() and cal[0]["time"] == "10:00"
    r = await client.delete(f"/api/mobed/agyaries/1/bookings/{done['items'][0]['booking_id']}", headers=pan)
    assert r.status_code == 200, r.text
    row = (await db.execute(select(ServiceAsk).execution_options(populate_existing=True))).scalar_one()
    assert row.status == "cancelled_by_fire_temple"
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert view["label"] == "Cancelled by the fire temple" and view["can_cancel"] is False
    assert view["can_ask_another"] is True and view["items"][0]["state"] == "cancelled_by_fire_temple"
    notes = (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"]
    assert notes[0]["kind"] == "person_ask_cancelled_by_temple"
    d = day()
    assert notes[0]["body"] == f"Cancelled by Goti Adarian: Jashan on {d[8:]}/{d[5:7]}/{d[:4]} 10:00"
    assert (await client.get(f"/api/behdin/me/calendar?from={day(0)}&to={day(10)}", headers=mine)).json()["items"] == []
    assert (await client.post(f"/api/behdin/me/asks/{made['id']}/cancel", headers=mine)).status_code == 409


async def test_one_prayer_removed_from_a_request_of_several_marks_it_changed_and_all_removed_cancels_it(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    jashan, afringan = await service_id(db, "Jashan"), await service_id(db, "Afringan")
    made = await ask(client, mine, request(item(jashan), item(afringan, date=day(5))))
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)).json()
    first, second = (e["booking_id"] for e in done["items"])
    assert (await client.delete(f"/api/mobed/agyaries/1/bookings/{first}", headers=pan)).status_code == 200
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    # Still confirmed, marked Changed, the removed prayer flagged, the other standing.
    assert view["status"] == "accepted" and view["label"] == "Changed" and view["changed"] is True
    assert [i["state"] for i in view["items"]] == ["cancelled_by_fire_temple", "accepted"]
    assert view["total"] == 200.0                                   # only what still stands
    note = (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"][0]
    assert note["kind"] == "person_ask_changed" and note["body"].startswith("Changed by Goti Adarian: Jashan on ")
    assert note["body"].endswith("cancelled")
    cal = (await client.get(f"/api/behdin/me/calendar?from={day(0)}&to={day(9)}", headers=mine)).json()["items"]
    assert [i["date"] for i in cal] == [day(5)]
    # Now the last one goes: the whole request is cancelled by the fire temple.
    assert (await client.delete(f"/api/mobed/agyaries/1/bookings/{second}", headers=pan)).status_code == 200
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert view["status"] == "cancelled_by_fire_temple" and all(i["state"] == "cancelled_by_fire_temple" for i in view["items"])
    assert (await client.get(f"/api/behdin/me/calendar?from={day(0)}&to={day(9)}", headers=mine)).json()["items"] == []


async def test_deleting_the_memorial_cancels_the_request_and_the_calendar_reads_the_memorials_dates_live(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    today = service_asks.today_ist()
    made = await ask(client, mine, {"agyary_id": 1, "items": [
        {"type": "memorial", "departed_name": "Dinshaw Rustom Mehta", "death_date": (today - timedelta(days=2)).isoformat(),
         "recurring": "monthly", "recurring_count": 3}]})
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)).json()
    memorial_id = done["items"][0]["memorial_id"]
    span = f"from={today.isoformat()}&to={(today + timedelta(days=399)).isoformat()}"
    cal = [i for i in (await client.get(f"/api/behdin/me/calendar?{span}", headers=mine)).json()["items"]
           if i["source"] == "request"]
    assert len(cal) >= 4 and cal[0]["title"].startswith("Memorial - Goti Adarian")

    # The panthaky moves one date: the request and the calendar follow, and the person is told.
    saved = (await client.get(f"/api/mobed/agyaries/1/memorials/{memorial_id}", headers=pan)).json()
    obs = next(o for o in saved["observances"] if o["date"] > today.isoformat())
    moved_to = (today + timedelta(days=200)).isoformat()
    r = await client.patch(f"/api/mobed/agyaries/1/memorials/{memorial_id}/observances/{obs['id']}", headers=pan,
                           json={"move_to": moved_to})
    assert r.status_code == 200, r.text
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert view["status"] == "accepted" and view["changed"] is True and view["label"] == "Changed"
    assert moved_to in [d["date"] for d in view["items"][0]["memorial"]["dates"]]
    note = (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"][0]
    assert note["kind"] == "person_ask_changed" and note["body"].startswith("Changed by Goti Adarian: Memorial, now ")
    assert moved_to in [i["date"] for i in (await client.get(f"/api/behdin/me/calendar?{span}", headers=mine)).json()["items"]]

    # The panthaky deletes the memorial: the request is cancelled by the fire temple, the calendar empties.
    assert (await client.delete(f"/api/mobed/agyaries/1/memorials/{memorial_id}", headers=pan)).status_code == 200
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    assert view["status"] == "cancelled_by_fire_temple" and view["label"] == "Cancelled by the fire temple"
    note = (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"][0]
    assert note["kind"] == "person_ask_cancelled_by_temple" and note["body"].startswith("Cancelled by Goti Adarian: Memorial on ")
    cal = (await client.get(f"/api/behdin/me/calendar?{span}", headers=mine)).json()["items"]
    assert [i for i in cal if i["source"] == "request"] == []


async def test_editing_the_time_or_the_geh_tells_the_person_and_the_request_shows_the_new_one(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    made = await ask(client, mine, request(item(await service_id(db, "Jashan"))))
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{made['id']}/accept", headers=pan)).json()
    booking = await db.get(Booking, done["items"][0]["booking_id"], populate_existing=True)
    edit = {"behdin_phone": ME, "behdin_name": "Farzin Meherzad Turel", "service_id": booking.service_id,
            "ceremony_datetime": f"{day(5)}T11:30:00", "purpose": "gujrela_nu"}
    same = {**edit, "ceremony_datetime": f"{day()}T10:00:00"}
    assert (await client.put(f"/api/mobed/agyaries/1/bookings/{booking.id}", headers=pan, json=same)).status_code == 200
    assert (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"][0]["kind"] == "person_ask_accepted"
    r = await client.put(f"/api/mobed/agyaries/1/bookings/{booking.id}", headers=pan, json=edit)
    assert r.status_code == 200, r.text
    view = (await client.get(f"/api/behdin/me/asks/{made['id']}", headers=mine)).json()
    item0 = view["items"][0]
    assert item0["date"] == day(5) and item0["time"] == "11:30" and item0["changed"] is True and view["changed"] is True
    note = (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"][0]
    d5 = day(5)
    assert note["kind"] == "person_ask_changed"
    assert note["body"] == f"Changed by Goti Adarian: Jashan, now {d5[8:]}/{d5[5:7]}/{d5[:4]} 11:30"
    cal = (await client.get(f"/api/behdin/me/calendar?from={day(0)}&to={day(10)}", headers=mine)).json()["items"]
    assert [(i["date"], i["time"]) for i in cal] == [(day(5), "11:30")]


async def test_deleting_the_machi_or_stopping_the_series_cancels_the_request(client, db, seeded):
    pan = await switch_on(client, db)
    mine = await person(client)
    machi = await service_id(db, "Machi")
    one = await ask(client, mine, request({"service_id": machi, "date": day(5), "geh": 2}))
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{one['id']}/accept", headers=pan)).json()
    held = await db.get(Machi, done["items"][0]["machi_id"], populate_existing=True)
    r = await client.put(f"/api/mobed/agyaries/1/machis/{held.id}", headers=pan, json={
        "behdin_phone": ME, "behdin_name": "Farzin Meherzad Turel", "roj": 1, "mah": 1, "year": 1400, "geh": 3,
        "gregorian": day(5), "purpose": "tandarosti"})
    assert r.status_code == 200 and r.json().get("confirmed", True), r.text
    view = (await client.get(f"/api/behdin/me/asks/{one['id']}", headers=mine)).json()
    assert view["items"][0]["geh"] == 3 and view["items"][0]["geh_name"] == "Uzirin" and view["changed"] is True
    assert (await client.get("/api/behdin/notifications", headers=mine)).json()["notifications"][0]["body"].endswith(", Uzirin")
    assert (await client.delete(f"/api/mobed/agyaries/1/machis/{held.id}", headers=pan)).status_code == 200
    assert (await client.get(f"/api/behdin/me/asks/{one['id']}", headers=mine)).json()["status"] == "cancelled_by_fire_temple"

    # A repeating series stopped from a later occurrence ends its item, though the first date stays.
    jashan = await service_id(db, "Jashan")
    series = await ask(client, mine, request(item(jashan, date=day(6), recurring="monthly", recurring_count=6)))
    done = (await client.post(f"/api/mobed/agyaries/1/asks/{series['id']}/accept", headers=pan)).json()
    first = await db.get(Booking, done["items"][0]["booking_id"], populate_existing=True)
    later = (await db.execute(select(Booking).where(Booking.recurrence_rule_id == first.recurrence_rule_id,
                                                     Booking.id != first.id).order_by(Booking.ceremony_datetime))).scalars().first()
    assert (await client.delete(f"/api/mobed/agyaries/1/bookings/{later.id}?future=true", headers=pan)).status_code == 200
    assert (await client.get(f"/api/behdin/me/asks/{series['id']}", headers=mine)).json()["status"] == "cancelled_by_fire_temple"
    assert (await client.get(f"/api/behdin/me/calendar?from={day(0)}&to={day(300)}", headers=mine)).json()["items"] == []


# --- setting up: prices first, then switch on -------------------------------------------------
async def test_requests_cannot_be_switched_on_until_every_offered_service_has_a_price(client, db, seeded):
    pan = await panthaky_headers(client)
    satum = await service_id(db, "Satum")
    await client.put(f"/api/mobed/agyaries/1/services/{satum}", headers=pan, json={"default_price": None})
    state = (await client.get("/api/mobed/agyaries/1/asks-setting", headers=pan)).json()
    assert state["ready"] is False and {s["name"]: s["price"] for s in state["services"]}["Satum"] is None
    refused = await client.put("/api/mobed/agyaries/1/asks-setting", headers=pan, json={"takes_asks": True})
    assert refused.status_code == 409 and refused.json()["detail"] == "Enter a price for every service first."
    # A service switched off is not offered, so it needs no price; zero is a price.
    await client.put(f"/api/mobed/agyaries/1/services/{satum}", headers=pan, json={"is_active": False})
    assert (await client.get("/api/mobed/agyaries/1/asks-setting", headers=pan)).json()["ready"] is True
    await client.put(f"/api/mobed/agyaries/1/services/{satum}", headers=pan, json={"default_price": 0, "is_active": True})
    assert (await client.put("/api/mobed/agyaries/1/asks-setting", headers=pan, json={"takes_asks": True})).status_code == 200

    # While it is on: no price cleared, no unpriced service switched on, the last service stays on.
    r = await client.put(f"/api/mobed/agyaries/1/services/{satum}", headers=pan, json={"default_price": None})
    assert r.status_code == 409
    listed = (await client.get("/api/mobed/agyaries/1/service-prices", headers=pan)).json()["services"]
    assert len(listed) == 10 and {s["name"] for s in listed} >= {"Machi", "Jashan", "Yazeshni"}   # the diary's catalog
    ids = [s["id"] for s in listed]
    for sid in ids[:-1]:
        assert (await client.put(f"/api/mobed/agyaries/1/services/{sid}", headers=pan, json={"is_active": False})).status_code == 200
    last = await client.put(f"/api/mobed/agyaries/1/services/{ids[-1]}", headers=pan, json={"is_active": False})
    assert last.status_code == 409 and "at least one" in last.json()["detail"]
    # Switching off is always allowed, and then the last one can go.
    assert (await client.put("/api/mobed/agyaries/1/asks-setting", headers=pan, json={"takes_asks": False})).status_code == 200
    assert (await client.put(f"/api/mobed/agyaries/1/services/{ids[-1]}", headers=pan, json={"is_active": False})).status_code == 200
    state = (await client.get("/api/mobed/agyaries/1/asks-setting", headers=pan)).json()
    assert state["ready"] is False and state["services"] == []
    again = await client.put("/api/mobed/agyaries/1/asks-setting", headers=pan, json={"takes_asks": True})
    assert again.status_code == 409


async def test_people_see_only_fire_temples_taking_requests_by_town_and_a_distance_only_for_a_pin(client, db, seeded):
    await switch_on(client, db)
    mine = await person(client)
    pune = await agyari(db, "Pune Atash Behram (test)", (18.52, 73.86), city="Pune")
    pune.kind, pune.takes_asks, pune.location_source = "atash_behram", True, "pin"
    thane = await agyari(db, "Thane Adaran (test)", (19.2, 72.97), city="Thane")
    thane.takes_asks, thane.location_source = True, "town"
    quiet = await agyari(db, "Not Taking (test)", None, city="Mumbai")        # a panthaky, but switched off
    nobody = await agyari(db, "No Panthaky (test)", None, city="Mumbai")
    nobody.takes_asks = True
    await member(db, pune, "+919822200201", "panthaky")
    await member(db, thane, "+919822200202", "panthaky")
    await member(db, quiet, "+919822200203", "panthaky")
    await member(db, nobody, "+919822200204", "mobed")
    await db.commit()

    rows = (await client.post("/api/behdin/agyaries/find", headers=mine, json={})).json()["agyaries"]
    names = [r["name"] for r in rows]
    assert names == ["Goti Adarian", "Pune Atash Behram (test)", "Thane Adaran (test)"]    # by town, then name; nothing else
    assert all(r["answers_in_app"] is True and r["distance_km"] is None for r in rows)
    assert set(rows[0]) == {"id", "name", "city", "kind", "distance_km", "answers_in_app"}
    # The person's town first.
    rows = (await client.post("/api/behdin/agyaries/find", headers=mine, json={"town": "thane"})).json()["agyaries"]
    assert [r["city"] for r in rows] == ["Thane", "Mumbai", "Pune"]
    # A distance only for an exact pin, and only when the position was sent; it is not given back.
    body = {"town": "Pune", "lat": 18.53, "lng": 73.85}
    raw = await client.post("/api/behdin/agyaries/find", headers=mine, json=body)
    by = {r["name"]: r for r in raw.json()["agyaries"]}
    assert by["Pune Atash Behram (test)"]["distance_km"] < 5
    assert by["Thane Adaran (test)"]["distance_km"] is None and by["Goti Adarian"]["distance_km"] is None
    assert "18.53" not in raw.text and "73.85" not in raw.text
    found = (await client.post("/api/behdin/agyaries/find", headers=mine, json={"q": "pun"})).json()["agyaries"]
    assert [r["name"] for r in found] == ["Pune Atash Behram (test)"]
    assert (await client.post("/api/behdin/agyaries/find", headers=mine, json={"lat": 18.9})).status_code == 400
    assert (await client.post("/api/behdin/agyaries/find", headers=mine, json={"lat": 99, "lng": 1})).status_code == 400
    assert (await client.get("/api/behdin/agyaries/towns", headers=mine)).json() == {"towns": ["Mumbai", "Pune", "Thane"]}
    assert (await client.post("/api/behdin/agyaries/find", json={})).status_code == 401
    assert (await client.get("/api/behdin/agyaries/towns")).status_code == 401
    # The old list by position is gone.
    assert (await client.post("/api/behdin/agyaries/nearby", headers=mine, json={})).status_code in (404, 405)
