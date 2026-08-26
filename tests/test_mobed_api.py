"""Mobed PWA API: sign-in, agyari search/join/activate/create, My Day,
Machi Board, manual add, and edit - the last through the shared slot-check
/ conflict core."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from agyary.messaging.geh_times import to_ist
from agyary.models import Agyary, Booking, BookingMobed, Machi, Service, User
from tests.conftest import sign_in

NEW_MOBED_PHONE = "+919911100001"


async def _login(client, name="New Mobed", phone=NEW_MOBED_PHONE) -> dict:
    """Full sign-in through the real inbound path - see conftest.sign_in."""
    return await sign_in(client, phone, name)


async def _headers(client, name="New Mobed", phone=NEW_MOBED_PHONE) -> dict:
    return {"Authorization": f"Bearer {(await _login(client, name, phone))['access_token']}"}


async def _member_headers(client, seeded, name="New Mobed", phone=NEW_MOBED_PHONE) -> dict:
    """Login + join the seeded agyari (login no longer auto-joins)."""
    headers = await _headers(client, name, phone)
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)
    assert r.status_code == 200, r.text
    return headers


# ---------------------------------------------------------------------------
# Auth (see test_wa_login.py for the sign-in mechanics themselves)
# ---------------------------------------------------------------------------
async def test_login_creates_user_and_returns_session(db, client, seeded):
    body = await _login(client)
    assert body["user"]["name"] == "New Mobed"
    assert body["user"]["phone"] == NEW_MOBED_PHONE
    assert body["user"]["agyaries"] == []  # login alone joins nothing

    user = (await db.execute(select(User).where(User.phone == NEW_MOBED_PHONE))).scalar_one()
    assert user.name == "New Mobed"

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    r = await client.get("/api/mobed/auth/me", headers=headers)
    assert r.status_code == 200 and r.json()["phone"] == NEW_MOBED_PHONE

    r = await client.post("/api/mobed/auth/refresh")
    assert r.status_code == 200 and r.json()["access_token"]


async def test_login_returning_visit_reuses_the_user_and_keeps_the_name(db, client, seeded):
    """A second sign-in from the same number is the same mobed, not a new
    one - and it does not rename them. The name step only runs on a phone's
    first ever sign-in; changing it afterwards is PATCH /auth/me, so a
    returning visit cannot overwrite the name on their slips by accident."""
    first = await _login(client, name="Old Name")
    again = await _login(client, name="Ignored On A Return Visit")
    assert again["user"]["id"] == first["user"]["id"]
    assert again["user"]["name"] == "Old Name"

    users = (
        await db.execute(select(User).where(User.phone == NEW_MOBED_PHONE))
    ).scalars().all()
    assert len(users) == 1 and users[0].name == "Old Name"


async def test_join_reports_membership(client, seeded):
    headers = await _headers(client)
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["agyary"]["status"] == "active"
    assert body["user"]["agyaries"][0]["id"] == seeded["agyary_id"]


async def test_me_requires_bearer_token(client):
    r = await client.get("/api/mobed/auth/me")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Search / activate / create
# ---------------------------------------------------------------------------
async def test_agyari_search_fuzzy(client, seeded):
    r = await client.get("/api/mobed/agyaries/search", params={"q": "Goti"})
    assert r.status_code == 200
    rows = r.json()
    assert "Goti Adarian" in [a["name"] for a in rows]
    assert all("address" in a and "status" in a for a in rows)


async def test_activate_unclaimed_agyari_sets_up_and_seeds_services(db, client, seeded):
    unclaimed = Agyary(name="Vatcha Gandhi Agiary", city="Mumbai", status="unclaimed")
    db.add(unclaimed)
    await db.commit()

    headers = await _headers(client)
    # A mobed can find the unclaimed temple and claim it.
    r = await client.get("/api/mobed/agyaries/search", params={"q": "Vatcha"})
    assert any(a["status"] == "unclaimed" for a in r.json())

    await client.post(f"/api/mobed/agyaries/{unclaimed.id}/join", headers=headers)
    r = await client.post(
        f"/api/mobed/agyaries/{unclaimed.id}/activate",
        json={"name": "Vatcha Gandhi Agiary", "city": "Mumbai", "address": "Cumballa Hill", "contact_phone": "+919122000001"},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["agyary"]["status"] == "active"

    await db.refresh(unclaimed)
    assert unclaimed.status == "active" and unclaimed.address == "Cumballa Hill"
    svc_count = (
        await db.execute(select(func.count()).select_from(Service).where(Service.agyary_id == unclaimed.id))
    ).scalar()
    assert svc_count > 0  # standard catalog seeded on activation


async def test_create_agyari_fallback(db, client, seeded):
    headers = await _headers(client)
    r = await client.post(
        "/api/mobed/agyaries",
        json={"name": "Brand New Agiary", "city": "Pune", "address": "Camp"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["agyary"]["status"] == "active"
    assert any(a["name"] == "Brand New Agiary" for a in body["user"]["agyaries"])
    new_id = body["agyary"]["id"]
    svc_count = (
        await db.execute(select(func.count()).select_from(Service).where(Service.agyary_id == new_id))
    ).scalar()
    assert svc_count > 0


# ---------------------------------------------------------------------------
# Manual add (shared slot-check core)
# ---------------------------------------------------------------------------
async def test_manual_add_machi_confirms_and_detects_taken_slot(db, client, seeded):
    headers = await _member_headers(client, seeded)
    payload = {
        "behdin_phone": "+919922200001",
        "behdin_name": "Walk-in Behdin",
        "roj": 5, "mah": 2, "year": 1396, "geh": 1,
        "gregorian": "2027-10-10",
        "purpose": "patet",
        "names": [
            {"section": "pair", "title": "ervad", "name": "A", "status": "departed", "pair_group": 1},
            {"section": "pair", "title": "ervad", "name": "B", "status": "departed", "pair_group": 1},
        ],
    }
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/manual-add/machi", json=payload, headers=headers)
    assert r.status_code == 200 and r.json()["confirmed"] is True
    machi = await db.get(Machi, r.json()["machi_id"])
    assert machi.status == "confirmed" and machi.amount is None

    r2 = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/manual-add/machi", json=payload, headers=headers)
    assert r2.status_code == 200 and r2.json()["confirmed"] is False
    assert 1 not in r2.json()["alternatives"]["same_day_gehs"]


async def test_manual_add_machi_requires_membership(client, seeded):
    payload = {
        "behdin_phone": "+919922200002", "behdin_name": "X",
        "roj": 1, "mah": 1, "year": 1396, "geh": 2, "gregorian": "2027-10-11",
        "purpose": "patet", "names": [],
    }
    r = await client.post(
        f"/api/mobed/agyaries/{seeded['agyary_id']}/manual-add/machi",
        json=payload, headers={"Authorization": "Bearer not-even-valid"},
    )
    assert r.status_code == 401


async def test_manual_add_booking_and_my_day_and_machi_board(db, client, seeded):
    headers = await _member_headers(client, seeded)
    booking_payload = {
        "behdin_phone": "+919922200003", "behdin_name": "Walk-in Family",
        "service_id": 2,  # Jashan, per seed_demo order
        "ceremony_datetime": "2027-11-05T11:00:00+05:30",
        "purpose": "khushali_nu",
        "names": [{"section": "farmayeshne", "title": "behdin", "name": "X", "status": "living", "pair_group": None}],
        "location": None, "is_offsite": False,
    }
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/manual-add/booking", json=booking_payload, headers=headers)
    assert r.status_code == 200 and r.json()["calendar_conflict"] is False

    booking = (await db.execute(select(Booking))).scalar_one()
    assert booking.status == "approved"
    assert (await db.execute(select(BookingMobed))).scalar_one().status == "accepted"

    r = await client.get("/api/mobed/my-day", headers=headers)
    assert r.status_code == 200
    my_day = r.json()
    assert len(my_day) == 1 and my_day[0]["agyary_name"] == "Goti Adarian"

    machi_payload = {
        "behdin_phone": "+919922200004", "behdin_name": "Another Walk-in",
        "roj": 10, "mah": 3, "year": 1396, "geh": 3, "gregorian": "2027-11-06",
        "purpose": "tandarosti",
        "names": [{"section": "pair", "title": "khud", "name": "Z", "status": "living", "pair_group": None}],
    }
    await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/manual-add/machi", json=machi_payload, headers=headers)

    assert len((await client.get("/api/mobed/my-day", headers=headers)).json()) == 1  # machi never on My Day
    board = (
        await client.get(
            f"/api/mobed/agyaries/{seeded['agyary_id']}/machi-board",
            params={"from": "2027-11-01", "to": "2027-11-30"},
            headers=headers,
        )
    ).json()
    assert len(board) == 1 and board[0]["status"] == "confirmed"


async def test_manual_add_booking_ist_time_and_no_conflict_crash(db, seeded):
    """Audit finding G1 regression: a naive datetime means IST (not
    server-local), and a second overlapping booking must flag a conflict
    without raising on a tz-aware-vs-naive comparison. expire_all() forces
    the first booking to reload from Postgres tz-aware, the shape a real
    second HTTP request sees."""
    from agyary.services import mobed_dashboard

    agyary = await db.get(Agyary, seeded["agyary_id"])
    dt = datetime.fromisoformat("2027-08-01T10:00:00")  # naive == 10:00 IST intended
    names = [{"section": "farmayeshne", "title": "behdin", "name": "A", "status": "living", "pair_group": None}]
    r1 = await mobed_dashboard.manual_add_booking(
        db, agyary, 2, behdin_phone="+915551", behdin_name="A", service_id=2,
        ceremony_dt_local=dt, purpose="khushali_nu", names=names, location=None, is_offsite=False,
    )
    await db.commit()
    await db.refresh(r1.booking)
    assert to_ist(r1.booking.ceremony_datetime).strftime("%H:%M") == "10:00"  # G1 part b

    db.expire(r1.booking)  # force the conflict query to reload it tz-aware from DB
    r2 = await mobed_dashboard.manual_add_booking(
        db, agyary, 2, behdin_phone="+915552", behdin_name="B", service_id=2,
        ceremony_dt_local=dt, purpose="khushali_nu", names=names, location=None, is_offsite=False,
    )
    assert r2.calendar_conflict is True  # G1 part a: flagged, not crashed


# ---------------------------------------------------------------------------
# Edit (shared slot-check on reschedule)
# ---------------------------------------------------------------------------
async def test_edit_machi_reschedule_and_collision(db, client, seeded):
    headers = await _member_headers(client, seeded)
    aid = seeded["agyary_id"]

    def machi_body(geh, gregorian="2027-12-01"):
        return {
            "behdin_phone": "+919933300001", "behdin_name": "Edit Behdin",
            "roj": 7, "mah": 4, "year": 1397, "geh": geh, "gregorian": gregorian,
            "purpose": "patet",
            "names": [
                {"section": "pair", "title": "ervad", "name": "A", "status": "departed", "pair_group": 1},
                {"section": "pair", "title": "ervad", "name": "B", "status": "departed", "pair_group": 1},
            ],
        }

    m1 = (await client.post(f"/api/mobed/agyaries/{aid}/manual-add/machi", json=machi_body(1), headers=headers)).json()["machi_id"]
    # Second machi exists only to occupy geh 2 for the collision check below.
    await client.post(f"/api/mobed/agyaries/{aid}/manual-add/machi", json=machi_body(2), headers=headers)

    # detail pre-fills the edit form
    detail = (await client.get(f"/api/mobed/agyaries/{aid}/machis/{m1}/detail", headers=headers)).json()
    assert detail["geh"] == 1 and detail["roj"] == 7

    # Reschedule m1 from geh 1 -> geh 3 (free): succeeds and moves the slot.
    edit = {"behdin_phone": detail["behdin_phone"], "behdin_name": detail["behdin_name"],
            "roj": 7, "mah": 4, "year": 1397, "geh": 3, "gregorian": "2027-12-01", "purpose": "patet", "names": detail["names"]}
    r = await client.put(f"/api/mobed/agyaries/{aid}/machis/{m1}", json=edit, headers=headers)
    assert r.status_code == 200 and r.json()["confirmed"] is True
    await db.refresh(await db.get(Machi, m1))
    assert (await db.get(Machi, m1)).geh == 3

    # Reschedule m1 onto geh 2 (taken by m2): rejected with alternatives, unchanged.
    edit_collide = {**edit, "geh": 2}
    r = await client.put(f"/api/mobed/agyaries/{aid}/machis/{m1}", json=edit_collide, headers=headers)
    assert r.status_code == 200 and r.json()["confirmed"] is False
    assert 2 not in r.json()["alternatives"]["same_day_gehs"]
    assert (await db.get(Machi, m1)).geh == 3  # still 3, not silently overwritten


async def test_edit_booking_updates_time(db, client, seeded):
    headers = await _member_headers(client, seeded)
    aid = seeded["agyary_id"]
    create = {
        "behdin_phone": "+919933300002", "behdin_name": "Edit Family",
        "service_id": 2, "ceremony_datetime": "2027-12-10T09:00:00",
        "purpose": "khushali_nu",
        "names": [{"section": "farmayeshne", "title": "behdin", "name": "X", "status": "living", "pair_group": None}],
        "location": None, "is_offsite": False,
    }
    bid = (await client.post(f"/api/mobed/agyaries/{aid}/manual-add/booking", json=create, headers=headers)).json()["booking_id"]

    detail = (await client.get(f"/api/mobed/agyaries/{aid}/bookings/{bid}/detail", headers=headers)).json()
    assert to_ist(datetime.fromisoformat(detail["ceremony_datetime"])).strftime("%H:%M") == "09:00"

    assert detail["behdin_name"] == "Edit Family"  # detail returns behdin for the form
    edit = {
        "behdin_phone": detail["behdin_phone"], "behdin_name": "Edited Family Name",
        "service_id": 2, "ceremony_datetime": "2027-12-10T16:30:00",
        "purpose": "khushali_nu", "names": detail["names"], "location": None, "is_offsite": False,
    }
    r = await client.put(f"/api/mobed/agyaries/{aid}/bookings/{bid}", json=edit, headers=headers)
    assert r.status_code == 200
    booking = await db.get(Booking, bid)
    await db.refresh(booking)
    assert to_ist(booking.ceremony_datetime).strftime("%H:%M") == "16:30"
    # Behdin is editable from the PWA - the rename persists on the customer.
    from agyary.models import Customer
    customer = await db.get(Customer, booking.customer_id)
    await db.refresh(customer)
    assert customer.name == "Edited Family Name"


async def test_edit_booking_round_trips_location_and_offsite(db, client, seeded):
    """The contract the form's edit path depends on: whatever detail hands
    back for location/is_offsite, sending it straight back on the PUT must
    preserve it. The form has no control for either field, so it can only
    carry them through - it used to send a flat null/false instead, wiping
    an offsite booking's location on any unrelated edit."""
    headers = await _member_headers(client, seeded)
    aid = seeded["agyary_id"]
    create = {
        "behdin_phone": "+919933300009", "behdin_name": "Offsite Family",
        "service_id": 2, "ceremony_datetime": "2028-01-12T09:00:00",
        "purpose": "khushali_nu",
        "names": [{"section": "farmayeshne", "title": "behdin", "name": "X", "status": "living", "pair_group": None}],
        "location": "14 Cusrow Baug, Colaba", "is_offsite": True,
    }
    bid = (await client.post(f"/api/mobed/agyaries/{aid}/manual-add/booking", json=create, headers=headers)).json()["booking_id"]

    detail = (await client.get(f"/api/mobed/agyaries/{aid}/bookings/{bid}/detail", headers=headers)).json()
    assert detail["location"] == "14 Cusrow Baug, Colaba" and detail["is_offsite"] is True

    # An edit that changes only the time, carrying detail's values through.
    edit = {
        "behdin_phone": detail["behdin_phone"], "behdin_name": detail["behdin_name"],
        "service_id": 2, "ceremony_datetime": "2028-01-12T17:00:00",
        "purpose": "khushali_nu", "names": detail["names"],
        "location": detail["location"], "is_offsite": detail["is_offsite"],
    }
    assert (await client.put(f"/api/mobed/agyaries/{aid}/bookings/{bid}", json=edit, headers=headers)).status_code == 200

    booking = await db.get(Booking, bid)
    await db.refresh(booking)
    assert booking.location == "14 Cusrow Baug, Colaba" and booking.is_offsite is True
    assert to_ist(booking.ceremony_datetime).strftime("%H:%M") == "17:00"

    # My Day still shows the offsite tag afterwards.
    entry = [e for e in (await client.get("/api/mobed/my-day", headers=headers)).json() if e["booking_id"] == bid][0]
    assert entry["is_offsite"] is True and entry["location"] == "14 Cusrow Baug, Colaba"
