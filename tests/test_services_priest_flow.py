"""Module 4: the new 'choose who to book with' step for services - the
chosen-priest accept/decline gate, the non-blocking calendar-conflict flag,
immediate two-way contact exchange, and the terminology audit (never
'mobed' in customer-facing text)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from agyary.messaging import booking_service
from agyary.messaging.geh_times import IST
from agyary.models import AgyaryUser, Booking, BookingMobed
from tests.test_chat_flow import CUSTOMER, onboard, send


async def _book_jashan_up_to_priest_choice(db, seeded, phone=CUSTOMER):
    await send(db, seeded, "book_service", phone)
    await send(db, seeded, "Jashan", phone)
    await send(db, seeded, "purpose_khushali_nu", phone)
    await send(db, seeded, "1 January", phone)
    await send(db, seeded, "date_confirm", phone)
    await send(db, seeded, "10:30 am", phone)
    await send(db, seeded, "loc_agyary", phone)
    await send(db, seeded, "Er. Zahan, Er. Meherzad\ndone", phone)
    return await send(db, seeded, "Behdin Jaidev\ndone", phone)


async def test_calendar_conflict_never_blocks_but_flags_priest_only(db, seeded):
    await onboard(db, seeded)

    # Give the panthaky (priest_1) an existing accepted booking at the
    # exact time the new request will target.
    other_customer = await booking_service.create_customer(db, "+919900099999", "Other Customer")
    conflict_dt = datetime(2027, 1, 1, 10, 30, tzinfo=IST)
    other_booking = Booking(
        agyary_id=seeded["agyary_id"],
        service_id=1,
        customer_id=other_customer.id,
        date_time=conflict_dt,
        ceremony_datetime=conflict_dt,
        parsi_roj=1,
        parsi_mah=1,
        parsi_year=1396,
        calendar_system="shenshai",
        purpose="khushali_nu",
        status="approved",
    )
    db.add(other_booking)
    await db.flush()
    db.add(BookingMobed(booking_id=other_booking.id, user_id=1, status="accepted"))
    await db.flush()

    replies = await _book_jashan_up_to_priest_choice(db, seeded)
    assert "book with" in replies[0].text.casefold()

    replies = await send(db, seeded, "priest_1")
    assert "booking summary" in replies[0].text
    replies = await send(db, seeded, "confirm_booking")

    customer_msg = next(r for r in replies if r.to == CUSTOMER)
    priest_msg = next(r for r in replies if r.to == seeded["panthaky_phone"])

    # Never blocks: the booking exists regardless of the conflict.
    assert "has been sent" in customer_msg.text
    assert "already have something" not in customer_msg.text.casefold()
    # Flags the priest only.
    assert "already have something" in priest_msg.text.casefold()

    booking = (
        (await db.execute(select(Booking).where(Booking.id != other_booking.id)))
    ).scalar_one()
    assert booking.status == "requested"


async def test_chosen_priest_can_decline_customer_notified(db, seeded):
    await onboard(db, seeded)
    await _book_jashan_up_to_priest_choice(db, seeded)
    await send(db, seeded, "priest_1")
    replies = await send(db, seeded, "confirm_booking")
    decline_id = next(
        b.id
        for r in replies
        if r.to == seeded["panthaky_phone"]
        for b in r.buttons
        if b.id.startswith("decline_booking_")
    )

    replies = await send(db, seeded, decline_id, phone=seeded["panthaky_phone"])
    assert any("could not be accommodated" in r.text for r in replies if r.to == CUSTOMER)

    booking = (await db.execute(select(Booking))).scalar_one()
    assert booking.status == "declined"
    booking_mobed = (await db.execute(select(BookingMobed))).scalar_one()
    assert booking_mobed.status == "declined"


async def test_accept_is_idempotent(db, seeded):
    await onboard(db, seeded)
    await _book_jashan_up_to_priest_choice(db, seeded)
    await send(db, seeded, "priest_1")
    replies = await send(db, seeded, "confirm_booking")
    accept_id = next(
        b.id
        for r in replies
        if r.to == seeded["panthaky_phone"]
        for b in r.buttons
        if b.id.startswith("approve_booking_")
    )

    first = await send(db, seeded, accept_id, phone=seeded["panthaky_phone"])
    assert any("Accepted" in r.text for r in first if r.to == seeded["panthaky_phone"])

    second = await send(db, seeded, accept_id, phone=seeded["panthaky_phone"])
    assert "already approved" in second[0].text


async def test_sole_active_priest_is_auto_selected_no_picker_shown(db, seeded):
    """Don't make a single-priest agyari pick from a list of one."""
    await onboard(db, seeded)
    mobed_membership = (
        await db.execute(
            select(AgyaryUser).where(
                AgyaryUser.agyary_id == seeded["agyary_id"], AgyaryUser.user_id == 2
            )
        )
    ).scalar_one()
    mobed_membership.is_active = False
    await db.commit()

    replies = await _book_jashan_up_to_priest_choice(db, seeded)
    # No picker step - straight to the booking summary, with the sole
    # active priest (the panthaky) already chosen.
    assert "booking summary" in replies[0].text
    assert "Er. Hormuz Dadachanji" in replies[0].text

    replies = await send(db, seeded, "confirm_booking")
    assert seeded["panthaky_phone"] in {r.to for r in replies}


async def test_no_customer_facing_string_says_mobed(db, seeded):
    """Doc 05 non-negotiable: never say 'mobed' in customer-facing text -
    show names, not roles. Sweeps every message a behdin receives across a
    full services booking."""
    await onboard(db, seeded)
    replies = await _book_jashan_up_to_priest_choice(db, seeded)
    replies += await send(db, seeded, "priest_1")
    replies += await send(db, seeded, "confirm_booking")
    replies += await send(db, seeded, "contact")

    customer_texts = [r.text for r in replies if r.to == CUSTOMER]
    assert customer_texts
    assert not any("mobed" in text.casefold() for text in customer_texts)
