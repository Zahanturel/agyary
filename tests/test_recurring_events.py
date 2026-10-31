"""An event (a booking) can repeat, like a machi: monthly on the same Roj, or
yearly on the same Roj and Mah (a Salgrah, an anniversary). The pattern and the
deleting of a series are shared with machis; what is checked here is what is
particular to events - a time of day instead of a geh, no exclusive slot, and the
calendar topping a repeat up as it is scrolled forward."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from agyary.models import Booking, BookingMobed, CeremonyName, RecurrenceRule
from tests.conftest import sign_in

PHONE = "+919911100077"
NAMES = [{"section": "farmayeshne", "title": "behdin", "name": "Zubin", "status": "living", "pair_group": None}]


async def _headers(client, seeded) -> dict:
    token = (await sign_in(client, PHONE, "Event Mobed"))["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)
    assert r.status_code == 200, r.text
    return headers


def _payload(when="2027-11-05T11:00:00+05:30", phone="+919922200301", **extra) -> dict:
    return {
        "behdin_phone": phone, "behdin_name": "Salgrah Family", "service_id": 2,
        "ceremony_datetime": when, "purpose": "khushali_nu", "names": NAMES,
        "location": None, "is_offsite": False, **extra,
    }


async def _add(client, aid, headers, **kw) -> int:
    r = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/booking", json=_payload(**kw), headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["booking_id"]


async def _series(db, rule_id) -> list[Booking]:
    return list((await db.execute(
        select(Booking).where(Booking.recurrence_rule_id == rule_id).order_by(Booking.ceremony_datetime)
    )).scalars())


async def test_a_yearly_event_repeats_on_the_same_roj_and_mah(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    source_id = await _add(client, aid, headers, recurring="yearly")

    rule = (await db.execute(select(RecurrenceRule).where(RecurrenceRule.source_booking_id == source_id))).scalar_one()
    assert rule.pattern == "same_roj_mah_every_year" and rule.source_machi_id is None
    rows = await _series(db, rule.id)
    assert len(rows) == 4   # the one booked, and the next three years
    source = rows[0]
    assert source.id == source_id and not source.is_recurring_instance
    for i, b in enumerate(rows[1:], start=1):
        assert b.is_recurring_instance and b.service_id == source.service_id and b.customer_id == source.customer_id
        assert (b.parsi_roj, b.parsi_mah) == (source.parsi_roj, source.parsi_mah)
        assert b.parsi_year == source.parsi_year + i
        assert b.ceremony_datetime.astimezone(source.ceremony_datetime.tzinfo).time() == source.ceremony_datetime.time()
        assert b.status == "approved" and b.created_by_user_id == source.created_by_user_id
        mobed = (await db.execute(select(BookingMobed).where(BookingMobed.booking_id == b.id))).scalar_one()
        assert mobed.status == "accepted"
        names = (await db.execute(select(CeremonyName).where(CeremonyName.booking_id == b.id))).scalars().all()
        assert [n.name for n in names] == ["Zubin"]


async def test_a_monthly_event_steps_through_the_months(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    source_id = await _add(client, aid, headers, recurring="monthly")
    rule = (await db.execute(select(RecurrenceRule).where(RecurrenceRule.source_booking_id == source_id))).scalar_one()
    assert rule.pattern == "same_roj_every_mah"
    rows = await _series(db, rule.id)
    assert len(rows) == 4
    assert len({b.parsi_roj for b in rows}) == 1
    gaps = {(b2.ceremony_datetime - b1.ceremony_datetime).days for b1, b2 in zip(rows, rows[1:])}
    assert gaps == {30}


async def test_a_pre_sunrise_event_keeps_its_parsi_day_every_time(db, client, seeded):
    """Before sunrise a ceremony belongs to the previous Parsi day; the repeats
    must land on the same Parsi day, not a day off."""
    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    source_id = await _add(client, aid, headers, when="2027-11-05T04:30:00+05:30", recurring="yearly")
    rule = (await db.execute(select(RecurrenceRule).where(RecurrenceRule.source_booking_id == source_id))).scalar_one()
    rows = await _series(db, rule.id)
    assert len(rows) == 4
    assert {(b.parsi_roj, b.parsi_mah) for b in rows} == {(rows[0].parsi_roj, rows[0].parsi_mah)}


async def test_the_calendar_tops_a_repeat_up_once_and_only_once(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    source_id = await _add(client, aid, headers, recurring="monthly")
    rule = (await db.execute(select(RecurrenceRule).where(RecurrenceRule.source_booking_id == source_id))).scalar_one()
    before = len(await _series(db, rule.id))

    far = date(2027, 11, 5) + timedelta(days=30 * 9)
    window = {"from": (far - timedelta(days=30)).isoformat(), "to": far.isoformat()}
    r = await client.get("/api/mobed/my-day", params=window, headers=headers)
    assert r.status_code == 200
    after = len(await _series(db, rule.id))
    assert after > before
    assert any(far - timedelta(days=30) <= date.fromisoformat(e["ceremony_datetime"][:10]) <= far for e in r.json())

    # Looking again writes nothing new.
    await client.get("/api/mobed/my-day", params=window, headers=headers)
    assert len(await _series(db, rule.id)) == after


async def test_a_single_event_is_not_a_repeat_and_the_slip_says_so(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    one = await _add(client, aid, headers, when="2027-12-05T10:00:00+05:30", phone="+919922200302")
    assert (await db.get(Booking, one)).recurrence_rule_id is None
    r = await client.get(f"/api/mobed/agyaries/{aid}/bookings/{one}/slip", headers=headers)
    assert r.json()["is_recurring"] is False

    rep = await _add(client, aid, headers, recurring="yearly")
    r = await client.get(f"/api/mobed/agyaries/{aid}/bookings/{rep}/slip", headers=headers)
    assert r.json()["is_recurring"] is True


async def test_an_unknown_repeat_is_refused(client, seeded):
    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    r = await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/booking", json=_payload(recurring="weekly"), headers=headers
    )
    assert r.status_code == 422


async def test_an_event_on_a_gatha_day_cannot_repeat_but_can_be_booked_once(db, client, seeded):
    from agyary.messaging.booking_service import slot_keys
    from agyary.models import Agyary

    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    agyary = await db.get(Agyary, aid)
    d = date(2027, 1, 1)
    while slot_keys(agyary, d)[1] <= 12:
        d += timedelta(days=1)
    when = f"{d.isoformat()}T11:00:00+05:30"

    for kind in ("monthly", "yearly"):
        r = await client.post(
            f"/api/mobed/agyaries/{aid}/manual-add/booking", json=_payload(when=when, recurring=kind), headers=headers
        )
        assert r.status_code == 400 and "Gatha" in r.json()["detail"]
        r = await client.post(
            f"/api/mobed/agyaries/{aid}/slip-preview/booking", json=_payload(when=when, recurring=kind), headers=headers
        )
        assert r.status_code == 400
    assert (await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/booking", json=_payload(when=when), headers=headers
    )).status_code == 200


async def test_deleting_one_occurrence_leaves_the_rest(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    source_id = await _add(client, aid, headers, recurring="monthly")
    rule = (await db.execute(select(RecurrenceRule).where(RecurrenceRule.source_booking_id == source_id))).scalar_one()
    rows = await _series(db, rule.id)
    middle = rows[2]
    r = await client.delete(f"/api/mobed/agyaries/{aid}/bookings/{middle.id}", headers=headers)
    assert r.status_code == 200
    assert {b.id for b in await _series(db, rule.id)} == {b.id for b in rows} - {middle.id}
    await db.refresh(rule)
    assert rule.is_active is True


async def test_deleting_the_source_alone_hands_the_repeat_to_the_next(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    source_id = await _add(client, aid, headers, recurring="monthly")
    rule = (await db.execute(select(RecurrenceRule).where(RecurrenceRule.source_booking_id == source_id))).scalar_one()
    rows = await _series(db, rule.id)
    r = await client.delete(f"/api/mobed/agyaries/{aid}/bookings/{source_id}", headers=headers)
    assert r.status_code == 200
    await db.refresh(rule)
    assert rule.source_booking_id == rows[1].id


async def test_deleting_this_and_future_stops_the_repeat_but_keeps_the_past(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    source_id = await _add(client, aid, headers, recurring="monthly")
    rule = (await db.execute(select(RecurrenceRule).where(RecurrenceRule.source_booking_id == source_id))).scalar_one()
    rows = await _series(db, rule.id)
    r = await client.delete(f"/api/mobed/agyaries/{aid}/bookings/{rows[2].id}?future=true", headers=headers)
    assert r.status_code == 200
    assert {b.id for b in await _series(db, rule.id)} == {rows[0].id, rows[1].id}
    await db.refresh(rule)
    assert rule.is_active is False


async def test_deleting_this_and_future_from_the_first_ends_the_repeat(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    source_id = await _add(client, aid, headers, recurring="yearly")
    rule_id = (await db.execute(
        select(RecurrenceRule.id).where(RecurrenceRule.source_booking_id == source_id)
    )).scalar_one()
    r = await client.delete(f"/api/mobed/agyaries/{aid}/bookings/{source_id}?future=true", headers=headers)
    assert r.status_code == 200
    assert await db.get(RecurrenceRule, rule_id) is None
    assert await _series(db, rule_id) == []


async def test_the_behdins_history_folds_a_repeat_into_one_line(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _headers(client, seeded)
    source_id = await _add(client, aid, headers, recurring="yearly")
    cid = (await db.get(Booking, source_id)).customer_id
    r = await client.get(f"/api/mobed/customers/{cid}/history", headers=headers)
    assert r.status_code == 200
    lines = [e["event"] for e in r.json()["history"] if e["kind"] == "booking"]
    assert len(lines) == 1 and "yearly" in lines[0] and "4 occurrences" in lines[0]
