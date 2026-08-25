"""Regression tests for the defects confirmed by the adversarial review."""

from datetime import date, time

from sqlalchemy import select

from agyary.messaging.date_parser import parse_date_input, parse_time_input
from agyary.messaging.flows.base import is_done_line
from agyary.messaging.name_parser import parse_names
from agyary.models import CustomerSavedName
from tests.test_chat_flow import CUSTOMER, book_patet_machi, onboard, send

TODAY = date(2026, 7, 21)


def test_bare_departed_marker_is_not_a_name():
    assert parse_names("Behdin (D)") == []
    assert parse_names("(d)") == []


def test_commas_inside_parentheses_do_not_split():
    names = parse_names("Behdin Roshan (nee Mehta, Surat)")
    assert len(names) == 1
    assert names[0].name == "Roshan (nee Mehta, Surat)"
    # Top-level commas still split.
    assert len(parse_names("Er. Zahan, Er. Meherzad")) == 2


def test_sept_abbreviation():
    p = parse_date_input("sept 5", TODAY)
    assert p.kind == "gregorian" and p.gregorian == date(2026, 9, 5)


def test_feb_29_resolves_to_next_leap_year():
    p = parse_date_input("29/2", TODAY)
    assert p.kind == "gregorian" and p.gregorian == date(2028, 2, 29)


def test_midnight_not_bumped_to_pm():
    assert parse_time_input("0:30") == time(0, 30)
    assert parse_time_input("6:30") == time(18, 30)  # 1-7 heuristic unchanged


def test_done_with_punctuation():
    assert is_done_line("done.")
    assert is_done_line("Done!")
    assert is_done_line(" DONE ")
    assert not is_done_line("well done job")


async def test_ist_display_in_my_bookings_and_approval(db, seeded):
    """Booking times must render in IST after the Postgres UTC round-trip."""
    await onboard(db, seeded)
    await send(db, seeded, "book_service")
    await send(db, seeded, "Jashan")
    await send(db, seeded, "purpose_khushali_nu")
    await send(db, seeded, "1 January")  # far future: past-time guard can't trip
    await send(db, seeded, "date_confirm")
    await send(db, seeded, "10:30 am")
    await send(db, seeded, "loc_agyary")
    await send(db, seeded, "Er. Zahan, Er. Meherzad\ndone")
    await send(db, seeded, "Behdin Jaidev\ndone")
    await send(db, seeded, "priest_1")  # book with the panthaky
    replies = await send(db, seeded, "confirm_booking")
    approve_id = next(r for r in replies if r.to == seeded["panthaky_phone"]).buttons[0].id

    replies = await send(db, seeded, "my_bookings")
    assert "10:30 AM" in replies[0].text  # was 5:00 AM (UTC) before the fix
    await send(db, seeded, "menu")

    replies = await send(db, seeded, approve_id, phone=seeded["panthaky_phone"])
    customer_msg = next(r for r in replies if r.to == CUSTOMER)
    assert "10:30 AM" in customer_msg.text


async def test_out_of_range_altslot_geh_does_not_crash(db, seeded):
    await onboard(db, seeded)
    await book_patet_machi(db, seeded)  # auto-confirms

    other = "+919900022222"
    await onboard(db, seeded, name="Roshan Mistry", phone=other)
    await send(db, seeded, "book_machi", other)
    await send(db, seeded, "purpose_patet", other)
    await send(db, seeded, "Roj Bahman Mah Fravardin", other)
    await send(db, seeded, "Havan", other)  # taken -> alternatives state
    replies = await send(db, seeded, "altslot_2026-08-20_7", other)
    assert "choose one of the options" in replies[0].text.casefold()


async def test_gujrela_saved_offer_only_complete_pairs(db, seeded):
    """Mixed hama-anjuman pairs must not surface half pairs to gujrela."""
    await onboard(db, seeded)
    # Hama Anjuman with one living pair + one departed pair.
    await send(db, seeded, "book_service")
    await send(db, seeded, "Jashan")
    await send(db, seeded, "purpose_hama_anjuman")
    await send(db, seeded, "1 January")
    await send(db, seeded, "date_confirm")
    await send(db, seeded, "11 am")
    await send(db, seeded, "loc_agyary")
    await send(db, seeded, "Behdin A, Behdin B\nEr. C (D), Er. D (D)\ndone")
    await send(db, seeded, "Behdin Jaidev\ndone")
    await send(db, seeded, "priest_1")
    await send(db, seeded, "confirm_booking")

    # Pair homogenization: every saved pair group is status-consistent.
    pool = (
        (
            await db.execute(
                select(CustomerSavedName).where(CustomerSavedName.section == "pair")
            )
        )
        .scalars()
        .all()
    )
    by_group: dict[int, set[str]] = {}
    for row in pool:
        by_group.setdefault(row.pair_group, set()).add(row.status)
    assert all(len(statuses) == 1 for statuses in by_group.values())

    # Gujrela booking: the saved offer must preview only the departed pair.
    await send(db, seeded, "book_service")
    await send(db, seeded, "Satum")
    await send(db, seeded, "purpose_gujrela_nu")
    await send(db, seeded, "2 January")
    await send(db, seeded, "date_confirm")
    replies = await send(db, seeded, "11 am")
    assert "Use your saved pairs?" in replies[0].text
    assert "C" in replies[0].text and "D" in replies[0].text
    assert "Behdin A" not in replies[0].text

    replies = await send(db, seeded, "names_saved_yes")
    assert "Farmayeshne" in replies[0].text


async def test_past_time_today_rejected(db, seeded):
    """'today' + a time that already passed must be rejected at time entry."""
    from datetime import datetime, timedelta

    from agyary.messaging.geh_times import IST

    now = datetime.now(IST)
    past_dt = now - timedelta(hours=1)
    past = past_dt.strftime("%H:%M")
    if now.hour < 2 or 1 <= past_dt.hour <= 7:
        # Too close to midnight for a same-day past time, or 'past' falls in
        # the bare-hour "1-7 means PM" heuristic (parse_time_input) which
        # would misread it as a future time instead of a past one; skip.
        return

    await onboard(db, seeded)
    await send(db, seeded, "book_service")
    await send(db, seeded, "Jashan")
    await send(db, seeded, "purpose_khushali_nu")
    await send(db, seeded, "today")
    await send(db, seeded, "date_confirm")
    replies = await send(db, seeded, past)
    assert "already passed" in replies[0].text


async def test_welcome_boilerplate_trimmed(db, seeded):
    """Greeting filler is gone, and name-ack + menu are a single message."""
    replies = await send(db, seeded, "hi")
    assert "Jai Sali" not in replies[0].text
    assert "may we have your name" in replies[0].text

    replies = await send(db, seeded, "Jaidev Patel")
    assert len(replies) == 1  # ack + menu merged into one outgoing message
    assert "Jai Sali" not in replies[0].text
    assert "Good to hear from you" not in replies[0].text
    assert "Thanks, Jaidev Patel" in replies[0].text
    assert "What would you like to do" in replies[0].text


async def test_auto_confirmation_has_no_pure_tone_filler(db, seeded):
    """Machi is auto-confirmed (redesign v3, no approval step) - the single
    confirmation message must still carry no gushing filler language."""
    await onboard(db, seeded)
    replies = await book_patet_machi(db, seeded)
    customer_msg = next(r for r in replies if r.to == CUSTOMER)
    assert "look forward" not in customer_msg.text.casefold()
    assert "confirmed" in customer_msg.text


async def test_roj_typo_falls_back_to_list(db, seeded):
    """A Roj typo must offer the Flow picker instead of a dead-end error.

    Roj/Mah fallbacks are WhatsApp Flows now, not list messages - but
    handle_message is transport-agnostic, so
    sending 'roj_2'/'mah_1' as raw text is exactly what a completed Flow's
    nfm_reply routes to."""
    await onboard(db, seeded)
    await send(db, seeded, "book_machi")
    await send(db, seeded, "purpose_patet")
    replies = await send(db, seeded, "Roj Bahmn")  # typo of Bahman
    assert "didn't recognize that Roj" in replies[0].text
    assert replies[0].flow is not None

    replies = await send(db, seeded, "roj_2")
    assert "Which Mah" in replies[0].text
    assert replies[0].flow is not None

    replies = await send(db, seeded, "mah_1")
    assert "Which Geh" in replies[0].text


async def test_mah_typo_falls_back_to_scoped_mah_list(db, seeded):
    """A Mah typo (with a valid Roj) reuses the existing Mah Flow, scoped."""
    await onboard(db, seeded)
    await send(db, seeded, "book_service")
    await send(db, seeded, "Jashan")
    await send(db, seeded, "purpose_khushali_nu")
    replies = await send(db, seeded, "Roj Bahman Mah Fravrdn")  # typo of Fravardin
    assert "Roj Bahman" in replies[0].text
    assert "didn't recognize that Mah" in replies[0].text
    assert replies[0].flow is not None

    replies = await send(db, seeded, "mah_1")  # Fravardin
    assert "What time?" in replies[0].text


async def test_roj_list_selection_by_typed_name_still_works(db, seeded):
    """The Roj list fallback also accepts a typed (now-correct) Roj name."""
    await onboard(db, seeded)
    await send(db, seeded, "book_machi")
    await send(db, seeded, "purpose_patet")
    await send(db, seeded, "Roj Xyz")  # nonsense -> Roj list
    replies = await send(db, seeded, "Bahman")
    assert "Which Mah" in replies[0].text
