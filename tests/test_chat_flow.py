"""End-to-end conversation tests through handle_message (the abstract
messaging interface), against a real Postgres test database."""

from __future__ import annotations

from sqlalchemy import select

from agyary.messaging import handle_message
from agyary.models import (
    Booking,
    BookingMobed,
    CeremonyName,
    ConversationState,
    CustomerSavedName,
    Machi,
)

CUSTOMER = "+919900011111"


async def send(db, seeded, text, phone=CUSTOMER):
    return await handle_message(db, seeded["agyary_id"], phone, text)


async def onboard(db, seeded, name="Jaidev Patel", phone=CUSTOMER):
    """First contact + name collection; ends at the welcome menu."""
    replies = await send(db, seeded, "hi", phone)
    assert "may we have your name" in replies[0].text
    replies = await send(db, seeded, name, phone)
    assert any("What would you like to do" in r.text for r in replies)
    return replies


def all_row_ids(message):
    return [row.id for section in message.sections for row in section.rows]


async def book_patet_machi(db, seeded, phone=CUSTOMER):
    """Menu -> patet machi on Roj Bahman Mah Fravardin, Havan geh -> confirm.

    'Which Geh' is now a WhatsApp Flow prompt, not a list message - but
    handle_message is transport-agnostic, so sending 'geh_1' as raw text is
    exactly what a completed Flow's nfm_reply routes to (see
    _extract_flow_reply in api/routes/whatsapp.py), and this helper is
    unaffected by the module 3 rewrite.
    """
    await send(db, seeded, "book_machi", phone)
    await send(db, seeded, "purpose_patet", phone)
    replies = await send(db, seeded, "Roj Bahman Mah Fravardin", phone)
    assert "Which Geh" in replies[0].text
    assert replies[0].flow is not None  # static Geh Flow, not a list message
    replies = await send(db, seeded, "geh_1", phone)
    assert "departed pair" in replies[0].text
    replies = await send(db, seeded, "Er. Kaikhushru, Er. Hormazd", phone)
    assert "booking summary" in replies[0].text
    return await send(db, seeded, "confirm_booking", phone)


async def test_full_patet_flow_auto_confirms(db, seeded):
    """Machi is fully automatic (redesign v3): no approval gate, no money,
    a single confirmation message, and an FYI (not action-required) message
    to every active agyary member - not just ADMIN_ROLES, since a
    peer-mobed agyari has none."""
    await onboard(db, seeded)
    replies = await book_patet_machi(db, seeded)

    customer_msgs = [r for r in replies if r.to == CUSTOMER]
    assert len(customer_msgs) == 1
    assert "confirmed" in customer_msgs[0].text
    assert "hear back" not in customer_msgs[0].text
    assert "upi" not in customer_msgs[0].text.casefold()
    assert not customer_msgs[0].buttons  # no approve/decline gate

    fyi_msgs = [r for r in replies if r.to != CUSTOMER]
    assert {r.to for r in fyi_msgs} == {seeded["panthaky_phone"], seeded["mobed_phone"]}
    assert all(not r.buttons for r in fyi_msgs)  # informational only, no action

    machi = (await db.execute(select(Machi))).scalar_one()
    assert machi.status == "confirmed"
    assert machi.purpose == "patet"
    assert (machi.parsi_roj, machi.parsi_mah) == (2, 1)
    assert machi.geh == 1
    assert machi.ceremony_datetime is not None
    assert machi.amount is None  # no money in this pass

    # Names snapshotted: one departed pair in the 'pair' section.
    names = (await db.execute(select(CeremonyName))).scalars().all()
    assert len(names) == 2
    assert all(
        n.section == "pair" and n.status == "departed" and n.pair_group == 1 for n in names
    )

    # Saved pool updated with the typed pair.
    pool = (await db.execute(select(CustomerSavedName))).scalars().all()
    assert len(pool) == 2 and all(r.section == "pair" for r in pool)


async def test_slot_conflict_offers_alternatives(db, seeded):
    await onboard(db, seeded)
    await book_patet_machi(db, seeded)  # auto-confirms Havan/geh_1, no approval step

    # Second customer, same date, insists on the now-taken geh directly
    # (the Geh picker is a static Flow now - always all 5 options, not
    # filtered to what's free - so the re-check that matters happens after
    # selection, same as it always has for a Roj/Mah combo with zero free
    # gehs left).
    other = "+919900022222"
    await onboard(db, seeded, name="Roshan Mistry", phone=other)
    await send(db, seeded, "book_machi", other)
    await send(db, seeded, "purpose_tandarosti", other)
    replies = await send(db, seeded, "Roj Bahman Mah Fravardin", other)
    assert replies[0].flow is not None

    replies = await send(db, seeded, "geh_1", other)
    assert "is booked" in replies[0].text
    alt_ids = all_row_ids(replies[0])
    assert any(i.startswith("altslot_") for i in alt_ids)


async def test_tandarosti_accumulation_and_done(db, seeded):
    await onboard(db, seeded)
    await send(db, seeded, "book_machi")
    await send(db, seeded, "purpose_tandarosti")
    await send(db, seeded, "tomorrow")
    await send(db, seeded, "date_confirm")
    await send(db, seeded, "geh_2")
    replies = await send(db, seeded, "Er. Zahan\nOsti Farzin")
    assert "Got 2 names" in replies[0].text
    replies = await send(db, seeded, "Khud Zhian")
    assert "Got 3 names" in replies[0].text
    replies = await send(db, seeded, "done")
    assert "booking summary" in replies[0].text
    await send(db, seeded, "confirm_booking")

    machi = (await db.execute(select(Machi))).scalar_one()
    assert machi.purpose == "tandarosti"
    names = (await db.execute(select(CeremonyName))).scalars().all()
    assert len(names) == 3
    assert all(n.status == "living" and n.pair_group is None for n in names)
    # Tandarosti names saved to the pool as farmayeshne (living singles).
    pool = (await db.execute(select(CustomerSavedName))).scalars().all()
    assert all(r.section == "farmayeshne" for r in pool)


async def test_saved_names_reused_on_second_booking(db, seeded):
    await onboard(db, seeded)
    await book_patet_machi(db, seeded)  # auto-confirms

    # Second patet booking: saved pair should be offered, and reusing it
    # must snapshot onto the new machi.
    await send(db, seeded, "book_machi")
    await send(db, seeded, "purpose_patet")
    await send(db, seeded, "Roj Ardibehesht Mah Fravardin")
    replies = await send(db, seeded, "geh_1")
    assert "saved departed pair" in replies[0].text
    assert "Kaikhushru" in replies[0].text
    replies = await send(db, seeded, "names_saved_yes")
    assert "booking summary" in replies[0].text
    await send(db, seeded, "confirm_booking")

    machis = (await db.execute(select(Machi))).scalars().all()
    assert len(machis) == 2
    names = (await db.execute(select(CeremonyName))).scalars().all()
    assert len(names) == 4  # 2 per machi - snapshot copied, not shared


async def test_service_booking_full_flow(db, seeded):
    """Services keep a human gate (unlike machi) - but it's now the
    specifically-chosen priest, not any admin: 'choose who to book with'
    (a dynamic Flow, seeded has 2 active members so it isn't auto-picked),
    immediate two-way contact exchange, and only the chosen priest can
    accept/decline."""
    await onboard(db, seeded)
    replies = await send(db, seeded, "book_service")
    assert replies[0].flow is not None  # services list is a dynamic Flow now
    await send(db, seeded, "Jashan")  # services also match by typed name
    replies = await send(db, seeded, "purpose_khushali_nu")
    assert "When would you like the Jashan" in replies[0].text
    await send(db, seeded, "tomorrow")
    await send(db, seeded, "date_confirm")
    replies = await send(db, seeded, "10:30 am")
    assert "Where will the ceremony" in replies[0].text
    replies = await send(db, seeded, "loc_offsite")
    assert "address" in replies[0].text
    replies = await send(db, seeded, "123 Marine Drive, Flat 4B")
    assert "pair names" in replies[0].text.casefold()
    replies = await send(db, seeded, "Er. Zahan, Er. Meherzad\ndone")
    assert "Farmayeshne" in replies[0].text
    replies = await send(db, seeded, "Behdin Jaidev\ndone")
    assert "book with" in replies[0].text.casefold()
    assert replies[0].flow is not None  # priest picker is a dynamic Flow

    replies = await send(db, seeded, "priest_2")  # the seeded mobed
    assert "booking summary" in replies[0].text
    assert "Er. Pervez Kias" in replies[0].text  # contact shown at choice time

    replies = await send(db, seeded, "confirm_booking")
    assert "has been sent" in replies[0].text
    assert seeded["mobed_phone"] in replies[0].text  # two-way contact exchange

    booking = (await db.execute(select(Booking))).scalar_one()
    assert booking.purpose == "khushali_nu"
    assert booking.is_offsite and "Marine Drive" in booking.location
    assert booking.ceremony_datetime == booking.date_time
    assert booking.status == "requested"
    assert booking.amount is None  # no money in this pass

    names = (await db.execute(select(CeremonyName))).scalars().all()
    pair = [n for n in names if n.section == "pair"]
    farm = [n for n in names if n.section == "farmayeshne"]
    assert len(pair) == 2 and all(n.pair_group == 1 for n in pair)
    assert len(farm) == 1 and farm[0].status == "living"

    # Only the chosen priest (the mobed) can accept - not the panthaky,
    # even though panthaky is still an ADMIN_ROLES member at this agyari.
    request_msg = next(r for r in replies if r.to == seeded["mobed_phone"])
    accept_id = next(b.id for b in request_msg.buttons if b.id.startswith("approve_booking_"))

    rejected = await send(db, seeded, accept_id, phone=seeded["panthaky_phone"])
    assert "not able to take that action" in rejected[0].text
    await db.refresh(booking)
    assert booking.status == "requested"

    accept_replies = await send(db, seeded, accept_id, phone=seeded["mobed_phone"])
    assert any("confirmed" in r.text for r in accept_replies if r.to == CUSTOMER)
    await db.refresh(booking)
    assert booking.status == "approved"

    booking_mobed = (await db.execute(select(BookingMobed))).scalar_one()
    assert booking_mobed.user_id == 2 and booking_mobed.status == "accepted"


async def test_gujrela_pair_line_validation(db, seeded):
    await onboard(db, seeded)
    await send(db, seeded, "book_service")
    await send(db, seeded, "Satum")
    await send(db, seeded, "purpose_gujrela_nu")
    await send(db, seeded, "tomorrow")
    await send(db, seeded, "date_confirm")
    replies = await send(db, seeded, "11 am")
    # Satum is not offsite-capable: goes straight to pair names.
    assert "departed names" in replies[0].text

    # A lone name doesn't resolve as a pair on its own - rejected, not
    # silently merged into whatever comes next.
    replies = await send(db, seeded, "Er. Kaikhushru")
    assert "Couldn't read this line as a pair" in replies[0].text
    assert "Er. Kaikhushru" in replies[0].text

    # A comma-pair and a no-comma double-title pair, both in one message.
    replies = await send(db, seeded, "Er. Kaikhushru, Er. Hormazd\nBehdin Roshan Behdin Dinshaw")
    assert "Pairs added" in replies[0].text
    assert "Kaikhushru" in replies[0].text and "Dinshaw" in replies[0].text
    assert "2 pairs so far" in replies[0].text

    replies = await send(db, seeded, "done")
    assert "Farmayeshne" in replies[0].text
    replies = await send(db, seeded, "Behdin Jaidev\ndone")
    assert "book with" in replies[0].text.casefold()
    replies = await send(db, seeded, "priest_1")
    assert "booking summary" in replies[0].text


async def test_pair_names_accumulate_across_messages(db, seeded):
    """Pairs accumulate across separate messages, mirroring farmayeshne."""
    await onboard(db, seeded)
    await send(db, seeded, "book_service")
    await send(db, seeded, "Satum")
    await send(db, seeded, "purpose_gujrela_nu")
    await send(db, seeded, "tomorrow")
    await send(db, seeded, "date_confirm")
    await send(db, seeded, "11 am")

    replies = await send(db, seeded, "Ervad Kaikhushru, Ervad Hormazd")
    assert "Pair added" in replies[0].text
    assert "Kaikhushru" in replies[0].text and "Hormazd" in replies[0].text
    assert "1 pair so far" in replies[0].text

    replies = await send(db, seeded, "Behdin Roshan Behdin Dinshaw")
    assert "2 pairs so far" in replies[0].text

    replies = await send(db, seeded, "done")
    assert "Farmayeshne" in replies[0].text
    replies = await send(db, seeded, "Behdin Jaidev\ndone")
    assert "book with" in replies[0].text.casefold()
    replies = await send(db, seeded, "priest_1")
    assert "booking summary" in replies[0].text
    await send(db, seeded, "confirm_booking")

    names = (await db.execute(select(CeremonyName))).scalars().all()
    pair_names = [n for n in names if n.section == "pair"]
    assert len(pair_names) == 4
    by_group: dict[int, list] = {}
    for n in pair_names:
        by_group.setdefault(n.pair_group, []).append(n)
    assert len(by_group) == 2
    assert all(n.status == "departed" for n in pair_names)  # gujrela_nu: always departed


async def test_hama_anjuman_skip_preserved(db, seeded):
    await onboard(db, seeded)
    await send(db, seeded, "book_service")
    await send(db, seeded, "Jashan")
    await send(db, seeded, "purpose_hama_anjuman")
    await send(db, seeded, "tomorrow")
    await send(db, seeded, "date_confirm")
    await send(db, seeded, "11 am")
    replies = await send(db, seeded, "loc_agyary")
    assert "skip" in replies[0].text.casefold()
    replies = await send(db, seeded, "skip")
    assert "Farmayeshne" in replies[0].text


async def test_my_bookings_cancel_frees_slot(db, seeded):
    await onboard(db, seeded)
    await book_patet_machi(db, seeded)  # auto-confirms, status="confirmed"

    replies = await send(db, seeded, "my_bookings")
    assert "1. Machi (Patet)" in replies[0].text
    await send(db, seeded, "1")
    await send(db, seeded, "cancel_item")
    replies = await send(db, seeded, "confirm_cancel")
    assert "has been cancelled" in replies[0].text
    # FYI to every active agyary member, not just ADMIN_ROLES.
    assert {seeded["panthaky_phone"], seeded["mobed_phone"]} <= {r.to for r in replies}

    machi = (await db.execute(select(Machi))).scalar_one()
    assert machi.status == "cancelled"

    # Slot is bookable again (partial unique index releases it): a second
    # customer can now actually complete a booking on the same geh, not
    # just see it offered (the Geh Flow always shows all 5 options
    # regardless of availability - the real check happens on selection).
    other = "+919900022222"
    await onboard(db, seeded, name="Roshan Mistry", phone=other)
    await send(db, seeded, "book_machi", other)
    await send(db, seeded, "purpose_patet", other)
    await send(db, seeded, "Roj Bahman Mah Fravardin", other)
    replies = await send(db, seeded, "geh_1", other)
    assert "departed pair" in replies[0].text  # proceeded to names, not "is booked"


async def test_menu_reset_keyword(db, seeded):
    await onboard(db, seeded)
    await send(db, seeded, "book_machi")
    replies = await send(db, seeded, "menu")
    assert any("What would you like to do" in r.text for r in replies)
    state = (await db.execute(select(ConversationState))).scalar_one()
    assert state.flow == "menu"


async def test_state_expiry_returns_menu(db, seeded):
    from datetime import UTC, datetime, timedelta

    await onboard(db, seeded)
    await send(db, seeded, "book_machi")
    state = (await db.execute(select(ConversationState))).scalar_one()
    state.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    # Expired mid-flow: silently back to the welcome menu (no 'session expired').
    replies = await send(db, seeded, "purpose_patet")
    assert any("What would you like to do" in r.text for r in replies)
    assert not any("expired" in r.text.casefold() for r in replies)
