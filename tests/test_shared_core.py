"""Module 1: the shared slot-check/claim/alternatives function used by both
the WhatsApp machi flow and (later) the PWA manual-add path, and the shared
priest-personal-calendar-conflict check used by the services flow."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from agyary.messaging import booking_service
from agyary.messaging.geh_times import IST
from agyary.messaging.mobed_calendar import has_calendar_conflict
from agyary.models import Agyary, BookingMobed


async def _customer(db, phone="+919900033333", name="Test Customer"):
    return await booking_service.create_customer(db, phone, name)


async def test_book_machi_slot_confirms_free_slot(db, seeded):
    agyary = await db.get(Agyary, seeded["agyary_id"])
    customer = await _customer(db)

    result = await booking_service.book_machi_slot(
        db,
        agyary,
        customer,
        roj=2,
        mah=1,
        year=1396,
        geh=1,
        gregorian=date(2027, 8, 20),
        purpose="patet",
        names=[
            {"section": "pair", "title": "ervad", "name": "Kaikhushru", "status": "departed", "pair_group": 1},
            {"section": "pair", "title": "ervad", "name": "Hormazd", "status": "departed", "pair_group": 1},
        ],
    )

    assert result.alternatives is None
    assert result.machi is not None
    assert result.machi.status == "confirmed"
    assert result.machi.amount is None  # no money in this pass


async def test_book_machi_slot_offers_alternatives_when_taken(db, seeded):
    agyary = await db.get(Agyary, seeded["agyary_id"])
    first_customer = await _customer(db, phone="+919900033334", name="First Customer")
    second_customer = await _customer(db, phone="+919900033335", name="Second Customer")

    names = [
        {"section": "pair", "title": "ervad", "name": "A", "status": "departed", "pair_group": 1},
        {"section": "pair", "title": "ervad", "name": "B", "status": "departed", "pair_group": 1},
    ]
    gregorian = date(2027, 8, 21)

    first = await booking_service.book_machi_slot(
        db, agyary, first_customer, roj=3, mah=1, year=1396, geh=2,
        gregorian=gregorian, purpose="patet", names=names,
    )
    assert first.machi is not None

    second = await booking_service.book_machi_slot(
        db, agyary, second_customer, roj=3, mah=1, year=1396, geh=2,
        gregorian=gregorian, purpose="patet", names=names,
    )
    assert second.machi is None
    assert second.alternatives is not None
    assert 2 not in second.alternatives.same_day_gehs
    assert 1 in second.alternatives.same_day_gehs


async def test_book_machi_slot_never_books_the_past(db, seeded):
    """An elapsed geh today must fall through to alternatives, not book."""
    agyary = await db.get(Agyary, seeded["agyary_id"])
    customer = await _customer(db, phone="+919900033336")
    now = datetime.now(IST)
    today = now.date()

    # geh 1 (Havan, starts 07:00) has already elapsed if it's past 07:00 IST;
    # geh 5 (Ushahin, starts 04:00 the *next* Gregorian day) covers the
    # early-morning case instead. Pick whichever has actually elapsed "today"
    # per the shared same-day logic, so this test is time-of-day independent.
    from agyary.messaging.availability import drop_elapsed_gehs

    all_gehs = [1, 2, 3, 4, 5]
    still_free = drop_elapsed_gehs(all_gehs, today)
    elapsed = [g for g in all_gehs if g not in still_free]
    if not elapsed:
        return  # nothing elapsed yet today (e.g. just after midnight) - skip

    geh = elapsed[0]
    result = await booking_service.book_machi_slot(
        db, agyary, customer, roj=1, mah=1, year=1396, geh=geh,
        gregorian=today, purpose="tandarosti",
        names=[{"section": "pair", "title": "khud", "name": "X", "status": "living", "pair_group": None}],
    )
    assert result.machi is None
    assert geh not in result.alternatives.same_day_gehs


async def test_has_calendar_conflict_true_for_overlapping_accepted_booking(db, seeded):
    agyary_id = seeded["agyary_id"]
    mobed_user_id = 2  # seeded mobed
    customer = await _customer(db, phone="+919900033337")

    service = await booking_service.list_services(db, agyary_id, exclude_machi=False)
    jashan = next(s for s in service if s.name == "Jashan")

    dt = datetime(2027, 9, 1, 10, 30, tzinfo=IST)
    booking = await booking_service.create_booking_request(
        db, agyary=await db.get(Agyary, agyary_id), customer=customer, service=jashan,
        ceremony_dt_local=dt, purpose="khushali_nu",
        names=[{"section": "farmayeshne", "title": "behdin", "name": "X", "status": "living", "pair_group": None}],
        location=None, is_offsite=False, amount=None,
    )
    db.add(BookingMobed(booking_id=booking.id, user_id=mobed_user_id, status="accepted"))
    await db.flush()

    assert await has_calendar_conflict(db, mobed_user_id, dt) is True
    assert await has_calendar_conflict(db, mobed_user_id, dt + timedelta(hours=5)) is False


async def test_has_calendar_conflict_ignores_declined_bookings(db, seeded):
    agyary_id = seeded["agyary_id"]
    mobed_user_id = 2
    customer = await _customer(db, phone="+919900033338")

    services = await booking_service.list_services(db, agyary_id, exclude_machi=False)
    jashan = next(s for s in services if s.name == "Jashan")

    dt = datetime(2027, 9, 2, 10, 30, tzinfo=IST)
    booking = await booking_service.create_booking_request(
        db, agyary=await db.get(Agyary, agyary_id), customer=customer, service=jashan,
        ceremony_dt_local=dt, purpose="khushali_nu",
        names=[{"section": "farmayeshne", "title": "behdin", "name": "X", "status": "living", "pair_group": None}],
        location=None, is_offsite=False, amount=None,
    )
    db.add(BookingMobed(booking_id=booking.id, user_id=mobed_user_id, status="accepted"))
    await db.flush()
    booking.status = "declined"
    await db.flush()

    assert await has_calendar_conflict(db, mobed_user_id, dt) is False
