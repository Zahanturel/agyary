"""Mobed PWA business logic: agyari search, My Day, Machi Board, manual
add. Business logic lives here (not in api/routes/mobed.py) so it stays
testable without FastAPI, matching this repo's stated services/ layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.calendar import CalendarSystem, gregorian_to_parsi, parsi_to_gregorian
from agyary.messaging import booking_service
from agyary.messaging.availability import available_gehs, drop_elapsed_gehs, parsi_slot_fields
from agyary.messaging.booking_service import MachiBookingResult
from agyary.messaging.formatting import PURPOSE_SHORT, date_label, geh_label, names_block
from agyary.messaging.geh_times import to_ist
from agyary.messaging.mobed_calendar import has_calendar_conflict
from agyary.models import (
    Agyary,
    AgyaryUser,
    Booking,
    BookingMobed,
    CeremonyName,
    Customer,
    Machi,
    RecurrenceRule,
    Service,
    UserPreferences,
)
from agyary.models.enums import DEFAULT_SECONDARY_CALENDAR_SYSTEM, SLOT_RELEASING_STATUSES

MY_DAY_HORIZON = timedelta(hours=12)  # mirrors my_bookings.py's past-cutoff
AGYARI_SEARCH_MIN_SIMILARITY = 0.2


async def search_agyaries(db: AsyncSession, query: str, limit: int = 12) -> list[Agyary]:
    """Filter-as-you-type agyari search for onboarding / join-another-agyari.

    Progressive substring match: every whitespace-separated word the mobed has
    typed must appear somewhere in "name + city" (case-insensitive). This
    matches from the very first character and *narrows* as more is typed
    (unlike a trigram-similarity match, which re-broadens on a longer query by
    pulling in anything sharing letters). Word-based so order doesn't matter
    ("goti mumbai" and "mumbai goti" both find it). Ranked with trigram
    similarity, active (already set up) agyaries above unclaimed seed entries.

    Returns both 'unclaimed' and 'active': a mobed must be able to find their
    as-yet-unclaimed temple in order to claim it. The caller shows the address
    in small grey text so same-named temples in different cities (e.g. several
    'Anjuman Daremeher') can be told apart."""
    query = query.strip()
    if not query:
        return []
    haystack = func.concat(Agyary.name, " ", Agyary.city)
    conditions = [haystack.ilike(f"%{word}%") for word in query.split()]
    stmt = (
        select(Agyary)
        .where(Agyary.is_active.is_(True), *conditions)
        .order_by(
            (Agyary.status == "active").desc(),
            func.similarity(Agyary.name, query).desc(),
            Agyary.name,
        )
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars())


async def activate_agyary(
    db: AsyncSession,
    agyary: Agyary,
    *,
    name: str,
    city: str,
    address: str | None,
    contact_phone: str | None,
) -> Agyary:
    """First-mobed activation: the mobed confirms/corrects the (2012-era,
    possibly stale) seed details, and the agyari flips unclaimed -> active.
    This is the concrete replacement for audit gap F1 - an agyari can't be
    booked against until a real person has vouched for and set it up. Updating
    the seeded row in place means the corrected details replace the stale
    suggestion automatically. Also seeds the standard service catalog so the
    booking path works immediately."""
    agyary.name = name.strip()
    agyary.city = city.strip()
    agyary.address = address.strip() if address else None
    agyary.contact_phone = contact_phone.strip() if contact_phone else None
    agyary.status = "active"
    await db.flush()
    await booking_service.ensure_default_services(db, agyary.id)
    return agyary


async def create_agyary(
    db: AsyncSession,
    *,
    name: str,
    city: str,
    address: str | None,
    contact_phone: str | None,
    calendar_system: str = "shenshai",
) -> Agyary:
    """Creation fallback when search finds nothing (agyari not in the seed
    list). Same end state as activation - born 'active' because a real mobed
    is entering it from scratch - plus the standard service catalog."""
    agyary = Agyary(
        name=name.strip(),
        city=city.strip(),
        address=address.strip() if address else None,
        contact_phone=contact_phone.strip() if contact_phone else None,
        calendar_system=calendar_system,
        status="active",
    )
    db.add(agyary)
    await db.flush()
    await booking_service.ensure_default_services(db, agyary.id)
    return agyary


@dataclass(frozen=True)
class MyDayEntry:
    booking: Booking
    agyary_id: int
    agyary_name: str
    service_name: str
    behdin_name: str


def _my_day_entries(rows) -> list[MyDayEntry]:
    return [
        MyDayEntry(
            booking=booking,
            agyary_id=agyary.id,
            agyary_name=agyary.name,
            service_name=service.name if service else "Service",
            behdin_name=customer.name if customer else "",
        )
        for booking, agyary, service, customer in rows
    ]


def _my_day_select():
    return (
        select(Booking, Agyary, Service, Customer)
        .join(BookingMobed, BookingMobed.booking_id == Booking.id)
        .join(Agyary, Agyary.id == Booking.agyary_id)
        .outerjoin(Service, Service.id == Booking.service_id)
        .outerjoin(Customer, Customer.id == Booking.customer_id)
    )


async def list_my_day(db: AsyncSession, user_id: int) -> list[MyDayEntry]:
    """Merged across every agyari the mobed belongs to - their day doesn't
    care about tenant boundaries, only we do (doc 05). Never includes
    machi (no mobed assignment, ever, not even here). Confirmed
    (BookingMobed.status == "accepted") bookings only. Includes the service
    name and booked-by name for the calendar cards."""
    horizon = datetime.now(UTC) - MY_DAY_HORIZON
    stmt = (
        _my_day_select()
        .where(
            BookingMobed.user_id == user_id,
            BookingMobed.status == "accepted",
            Booking.ceremony_datetime >= horizon,
        )
        .order_by(Booking.ceremony_datetime)
    )
    return _my_day_entries((await db.execute(stmt)).all())


@dataclass(frozen=True)
class MachiBoardEntry:
    machi: Machi
    behdin_name: str


async def bookable_gehs(db: AsyncSession, agyary: Agyary, gregorian: date) -> list[int]:
    """The gehs a machi can still be booked into on `gregorian` at this agyari,
    via the SAME shared availability core the booking path uses (available_gehs
    + drop_elapsed_gehs).

    Past dates are allowed here on purpose, for now: this is the mobed's own
    manual entry (walk-ins logged after the fact, corrections to something
    already recorded), not the behdin self-service flow - "never book in the
    past" is a rule for that automatic flow once it exists, not for a mobed
    manually recording what already happened. drop_elapsed_gehs still
    correctly no-ops for any day that isn't literally today, so this doesn't
    change same-day elapsed-geh behaviour at all."""
    roj, mah, year = parsi_slot_fields(
        gregorian_to_parsi(gregorian, CalendarSystem(agyary.calendar_system))
    )
    return drop_elapsed_gehs(await available_gehs(db, agyary.id, roj, mah, year), gregorian)


MAX_BOARD_RANGE_DAYS = 366


async def list_machi_board(
    db: AsyncSession, agyary_id: int, start: date, end: date, created_by_user_id: int | None = None
) -> list[MachiBoardEntry]:
    """Machis at one agyari between two dates, inclusive.

    ``created_by_user_id`` narrows this to the machis that one mobed
    entered themselves. The mobed app always passes it: a mobed does not
    need - and should not be shown - every machi at their fire temple,
    and the unfiltered response carries other mobeds' behdin names, which
    is somebody else's business. Left as None it is the agyari-wide board,
    for the management surface that will come later.

    The window is required, not optional. This used to return every
    non-released machi at the agyari for all time and let the client filter
    by day, which was survivable only while it was fetched once for a board
    showing a single date. A calendar refetching on every month step turns
    that into "re-download the temple's entire history to render 30 days",
    growing without bound. Bounded on gregorian_date (the Parsi-day anchor
    the board is keyed by, and the indexed column) rather than
    ceremony_datetime, which for Ushahin lands on the following morning.
    """
    if end < start:
        raise ValueError("end must not be before start")
    if (end - start).days + 1 > MAX_BOARD_RANGE_DAYS:
        raise ValueError(f"Range too large (max {MAX_BOARD_RANGE_DAYS} days)")

    stmt = (
        select(Machi, Customer)
        .outerjoin(Customer, Customer.id == Machi.customer_id)
        .where(
            Machi.agyary_id == agyary_id,
            Machi.status.notin_(SLOT_RELEASING_STATUSES),
            Machi.gregorian_date >= start,
            Machi.gregorian_date <= end,
        )
        .order_by(Machi.ceremony_datetime)
    )
    if created_by_user_id is not None:
        stmt = stmt.where(Machi.created_by_user_id == created_by_user_id)
    return [
        MachiBoardEntry(machi=machi, behdin_name=customer.name if customer else "")
        for machi, customer in (await db.execute(stmt)).all()
    ]


async def is_active_member(db: AsyncSession, agyary_id: int, user_id: int) -> bool:
    result = await db.execute(
        select(AgyaryUser).where(
            AgyaryUser.agyary_id == agyary_id,
            AgyaryUser.user_id == user_id,
            AgyaryUser.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none() is not None


async def get_customer_history(db: AsyncSession, user_id: int, customer_id: int) -> dict | None:
    """A mobed's full history with one of his own behdins - every machi and
    service HE personally entered for them, most recent first. Same
    created_by_user_id scoping as the behdin register: this is the mobed's
    own record of the relationship, not the fire temple's shared board."""
    customer = await db.get(Customer, customer_id)
    if customer is None:
        return None

    machis = (
        await db.execute(
            select(Machi).where(Machi.customer_id == customer_id, Machi.created_by_user_id == user_id)
        )
    ).scalars()
    booking_rows = (
        await db.execute(
            select(Booking, Service)
            .outerjoin(Service, Service.id == Booking.service_id)
            .where(Booking.customer_id == customer_id, Booking.created_by_user_id == user_id)
        )
    ).all()

    entries = []
    for m in machis:
        entries.append(
            {
                "kind": "machi",
                "id": m.id,
                "event": f"Machi ({PURPOSE_SHORT.get(m.purpose, m.purpose)})",
                "when": f"{date_label(m.parsi_roj, m.parsi_mah, m.gregorian_date)}, {geh_label(m.geh)}",
                "sort_key": m.ceremony_datetime,
            }
        )
    for b, service in booking_rows:
        local = to_ist(b.date_time)
        entries.append(
            {
                "kind": "booking",
                "id": b.id,
                "event": service.name if service else "Service",
                "when": f"{date_label(b.parsi_roj, b.parsi_mah, local.date())}, {local.strftime('%I:%M %p').lstrip('0')}",
                "sort_key": b.ceremony_datetime,
            }
        )
    entries.sort(key=lambda e: e["sort_key"], reverse=True)
    for e in entries:
        del e["sort_key"]

    return {"customer_id": customer.id, "name": customer.name, "phone": customer.phone, "history": entries}


async def _resolve_customer(
    db: AsyncSession, phone: str, name: str, actor_user_id: int | None = None
) -> Customer:
    """Same shared lookup both surfaces hit (doc 05) - reuses exactly the
    customer pool the WhatsApp flows already use, not a second saved-name
    system for the mobed side.

    ``actor_user_id`` puts the behdin into that mobed's own book. Serving
    someone is how most behdins get there: without this, a walk-in entered
    through the event flow would never show up in the mobed's behdin list.
    """
    customer = await booking_service.get_customer_by_phone(db, phone)
    if customer is None:
        customer = await booking_service.create_customer(db, phone, name)
    if actor_user_id is not None:
        from agyary.services import behdin_directory

        await behdin_directory.claim(db, actor_user_id, customer.id)
    return customer


async def _auto_names(db: AsyncSession, customer_id: int, service_name: str) -> list[dict]:
    """Pull the behdin's saved names for auto-attach at booking time.

    Pairs first, then farmayeshne. If the service is tandarosti, only
    living names are included. Returns an empty list if the behdin has
    no saved names — events save fine without them.
    """
    from agyary.services.behdin_directory import list_saved_names

    all_names = await list_saved_names(db, customer_id)
    is_tandarosti = service_name.strip().lower() == "tandarosti"
    if is_tandarosti:
        all_names = [n for n in all_names if n.get("status") == "living"]
    else:
        pairs = [n for n in all_names if n.get("section") == "pair"]
        farm = [n for n in all_names if n.get("section") == "farmayeshne"]
        all_names = pairs + farm
    return all_names


async def manual_add_machi(
    db: AsyncSession,
    agyary: Agyary,
    actor_user_id: int,
    *,
    behdin_phone: str,
    behdin_name: str,
    roj: int,
    mah: int,
    year: int,
    geh: int,
    gregorian,
    purpose: str,
    names: list[dict],
    recurring: bool = False,
) -> MachiBookingResult:
    """Walk-ins/phone bookings, machi case. Routes through book_machi_slot -
    the exact same shared function the WhatsApp flow uses (module 1) -
    never a second slot-check implementation. created_by_user_id is set
    here, after the shared core hands back a real row, rather than
    threading it into book_machi_slot itself - that function is shared
    with the WhatsApp path and shouldn't grow a PWA-only parameter."""
    customer = await _resolve_customer(db, behdin_phone, behdin_name, actor_user_id)
    result = await booking_service.book_machi_slot(
        db, agyary, customer, roj=roj, mah=mah, year=year, geh=geh,
        gregorian=gregorian, purpose=purpose, names=names,
    )
    if result.machi is not None:
        result.machi.created_by_user_id = actor_user_id
        await db.flush()
        if recurring and mah <= 12:
            await _create_recurring_machis(
                db, agyary, customer, result.machi, actor_user_id,
                roj=roj, geh=geh, purpose=purpose, names=names,
            )
    return result


async def _create_recurring_machis(
    db: AsyncSession,
    agyary: Agyary,
    customer: Customer,
    source_machi: Machi,
    actor_user_id: int,
    *,
    roj: int,
    geh: int,
    purpose: str,
    names: list[dict],
    horizon_months: int = 3,
) -> None:
    """Generate recurring machi instances for the next N months on the same
    roj+geh. Creates a RecurrenceRule linking back to the source machi, then
    books each future slot that is still open (skips taken ones silently)."""
    system = CalendarSystem(agyary.calendar_system)
    rule = RecurrenceRule(
        agyary_id=agyary.id,
        source_machi_id=source_machi.id,
        pattern="same_roj_every_mah",
        end_type="indefinite",
        generation_horizon_months=horizon_months,
    )
    db.add(rule)
    await db.flush()

    source_machi.recurrence_rule_id = rule.id

    start_mah = source_machi.parsi_mah
    start_year = source_machi.parsi_year
    for i in range(1, horizon_months + 1):
        next_mah = start_mah + i
        next_year = start_year
        while next_mah > 12:
            next_mah -= 12
            next_year += 1
        try:
            greg = parsi_to_gregorian(next_year, system, mah=next_mah, roj=roj)
        except ValueError:
            continue
        result = await booking_service.book_machi_slot(
            db, agyary, customer, roj=roj, mah=next_mah, year=next_year,
            geh=geh, gregorian=greg, purpose=purpose, names=names,
        )
        if result.machi is not None:
            result.machi.created_by_user_id = actor_user_id
            result.machi.recurrence_rule_id = rule.id
            result.machi.is_recurring_instance = True

    rule.last_generated_until = greg
    await db.flush()


@dataclass(frozen=True)
class ManualBookingResult:
    booking: Booking
    calendar_conflict: bool


async def manual_add_booking(
    db: AsyncSession,
    agyary: Agyary,
    actor_user_id: int,
    *,
    behdin_phone: str,
    behdin_name: str,
    service_id: int,
    ceremony_dt_local: datetime,
    purpose: str,
    names: list[dict] | None,
    location: str | None,
    is_offsite: bool,
) -> ManualBookingResult | None:
    """Walk-ins/phone bookings, non-machi case. The mobed entered it
    themselves - already agreed, so BookingMobed starts "accepted", not
    "assigned" (no accept/decline round-trip needed). Calendar conflict is
    the same non-blocking flag as the WhatsApp services flow (module 4),
    just surfaced to the caller instead of via a WhatsApp notification."""
    service = await booking_service.get_service_by_id(db, agyary.id, service_id)
    if service is None:
        return None
    # Conflict must be checked BEFORE creating this booking's own
    # BookingMobed row, or it would find itself and always report a
    # conflict.
    conflict = await has_calendar_conflict(db, actor_user_id, ceremony_dt_local)
    customer = await _resolve_customer(db, behdin_phone, behdin_name, actor_user_id)
    if names is None:
        names = await _auto_names(db, customer.id, service.name)
    booking = await booking_service.create_booking_request(
        db, agyary, customer, service,
        ceremony_dt_local=ceremony_dt_local, purpose=purpose, names=names,
        location=location, is_offsite=is_offsite, amount=None,
    )
    booking.status = "approved"  # self-entered, already agreed - no gate
    booking.created_by_user_id = actor_user_id
    db.add(BookingMobed(booking_id=booking.id, user_id=actor_user_id, status="accepted"))
    await db.flush()
    return ManualBookingResult(booking=booking, calendar_conflict=conflict)


# ---------------------------------------------------------------------------
# Edit (re-uses the shared slot-check / conflict core, never a raw update)
# ---------------------------------------------------------------------------
async def get_machi_detail(db: AsyncSession, agyary_id: int, machi_id: int) -> dict | None:
    machi = await db.get(Machi, machi_id)
    if machi is None or machi.agyary_id != agyary_id:
        return None
    customer = await db.get(Customer, machi.customer_id)
    return {
        "id": machi.id,
        "behdin_name": customer.name if customer else "",
        "behdin_phone": customer.phone if customer else "",
        "purpose": machi.purpose,
        "roj": machi.parsi_roj,
        "mah": machi.parsi_mah,
        "year": machi.parsi_year,
        "geh": machi.geh,
        "gregorian": machi.gregorian_date.isoformat(),
        "names": await _names_as_dicts(db, machi_id=machi.id),
    }


async def get_booking_detail(db: AsyncSession, agyary_id: int, booking_id: int) -> dict | None:
    booking = await db.get(Booking, booking_id)
    if booking is None or booking.agyary_id != agyary_id:
        return None
    customer = await db.get(Customer, booking.customer_id)
    return {
        "id": booking.id,
        "behdin_name": customer.name if customer else "",
        "behdin_phone": customer.phone if customer else "",
        "service_id": booking.service_id,
        "purpose": booking.purpose,
        "ceremony_datetime": to_ist(booking.ceremony_datetime).isoformat(),
        "location": booking.location,
        "is_offsite": booking.is_offsite,
        "names": await _names_as_dicts(db, booking_id=booking.id),
    }


async def _apply_behdin_edit(
    db: AsyncSession, ceremony, behdin_phone: str, behdin_name: str,
    actor_user_id: int | None = None,
) -> None:
    """Re-point a ceremony to the customer identified by (possibly edited)
    phone, creating them if new and updating their display name - the PWA
    gives the mobed the flexibility to correct a walk-in's name/number."""
    phone, name = behdin_phone.strip(), behdin_name.strip()
    if not phone:
        return
    customer = await booking_service.get_customer_by_phone(db, phone)
    if customer is None:
        customer = await booking_service.create_customer(db, phone, name)
    elif name and customer.name != name:
        customer.name = name
    ceremony.customer_id = customer.id
    if actor_user_id is not None:
        from agyary.services import behdin_directory

        await behdin_directory.claim(db, actor_user_id, customer.id)
    await db.flush()


async def edit_machi(
    db: AsyncSession,
    agyary: Agyary,
    machi_id: int,
    actor_user_id: int,
    *,
    behdin_phone: str,
    behdin_name: str,
    roj: int,
    mah: int,
    year: int,
    geh: int,
    gregorian,
    purpose: str,
    names: list[dict],
) -> MachiBookingResult | None:
    """Edit a machi via the shared slot-check core (rebook_machi_slot). Returns
    None if the machi doesn't belong to this agyari; otherwise a
    MachiBookingResult whose .machi is None (with .alternatives set) when the
    new slot is taken - exactly the create contract."""
    machi = await db.get(Machi, machi_id)
    if machi is None or machi.agyary_id != agyary.id:
        return None
    await _apply_behdin_edit(db, machi, behdin_phone, behdin_name, actor_user_id)
    return await booking_service.rebook_machi_slot(
        db, agyary, machi, roj=roj, mah=mah, year=year, geh=geh,
        gregorian=gregorian, purpose=purpose, names=names,
    )


async def edit_booking(
    db: AsyncSession,
    agyary: Agyary,
    actor_user_id: int,
    booking_id: int,
    *,
    behdin_phone: str,
    behdin_name: str,
    service_id: int,
    ceremony_dt_local: datetime,
    purpose: str,
    names: list[dict] | None,
    location: str | None,
    is_offsite: bool,
) -> ManualBookingResult | None:
    booking = await db.get(Booking, booking_id)
    if booking is None or booking.agyary_id != agyary.id:
        return None
    service = await booking_service.get_service_by_id(db, agyary.id, service_id)
    if service is None:
        return None
    await _apply_behdin_edit(db, booking, behdin_phone, behdin_name, actor_user_id)
    if names is None:
        customer = await db.get(Customer, booking.customer_id)
        names = await _auto_names(db, customer.id, service.name) if customer else []
    await booking_service.update_booking(
        db, agyary, booking, service,
        ceremony_dt_local=ceremony_dt_local, purpose=purpose, names=names,
        location=location, is_offsite=is_offsite,
    )
    # Non-blocking flag, same as create; exclude this booking so it doesn't
    # find itself.
    conflict = await has_calendar_conflict(
        db, actor_user_id, booking.ceremony_datetime, exclude_booking_id=booking.id
    )
    return ManualBookingResult(booking=booking, calendar_conflict=conflict)


# ---------------------------------------------------------------------------
# Slip (module 7): five fields only - agyari name, behdin name + contact,
# event, roj/mah/geh-or-time, names. No price, anywhere.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SlipData:
    agyary_name: str
    behdin_name: str
    behdin_phone: str
    event: str
    when: str
    names_text: str


async def _names_as_dicts(db: AsyncSession, *, machi_id: int | None = None, booking_id: int | None = None) -> list[dict]:
    column = CeremonyName.machi_id if machi_id is not None else CeremonyName.booking_id
    value = machi_id if machi_id is not None else booking_id
    rows = (
        await db.execute(
            select(CeremonyName).where(column == value).order_by(CeremonyName.display_order)
        )
    ).scalars()
    return [
        {"section": r.section, "title": r.title, "name": r.name, "status": r.status, "pair_group": r.pair_group}
        for r in rows
    ]


async def reading_system(db: AsyncSession, user_id: int) -> CalendarSystem:
    """The calendar a given mobed reads in - their primary preference.

    Slips are rendered in this, NOT in the stored Roj/Mah. A mobed prints,
    tears off and uses these slips themselves, so the slip has to read the
    way they read. The stored values stay exactly as they are: they are the
    fire temple's own reckoning and the stable historical record. Only the
    rendering follows the reader.
    """
    prefs = await db.get(UserPreferences, user_id)
    chosen = prefs.default_secondary_system if prefs else DEFAULT_SECONDARY_CALENDAR_SYSTEM
    return CalendarSystem(chosen)


def _reading(gregorian: date, system: CalendarSystem) -> tuple[int, int]:
    """(roj, mah) for a Gregorian day in `system`, Gatha days as mah=13."""
    roj, mah, _year = parsi_slot_fields(gregorian_to_parsi(gregorian, system))
    return roj, mah


async def get_machi_slip(
    db: AsyncSession, agyary_id: int, machi_id: int, reader_user_id: int | None = None
) -> SlipData | None:
    machi = await db.get(Machi, machi_id)
    if machi is None or machi.agyary_id != agyary_id:
        return None
    agyary = await db.get(Agyary, agyary_id)
    customer = await db.get(Customer, machi.customer_id)
    names = await _names_as_dicts(db, machi_id=machi.id)
    if reader_user_id is None:
        roj, mah = machi.parsi_roj, machi.parsi_mah
    else:
        roj, mah = _reading(machi.gregorian_date, await reading_system(db, reader_user_id))
    return SlipData(
        agyary_name=agyary.name,
        behdin_name=customer.name,
        behdin_phone=customer.phone,
        event=f"Machi ({machi.purpose})",
        when=f"{date_label(roj, mah, machi.gregorian_date)}, {geh_label(machi.geh)}",
        names_text=names_block(names),
    )


async def get_booking_slip(
    db: AsyncSession, agyary_id: int, booking_id: int, reader_user_id: int | None = None
) -> SlipData | None:
    booking = await db.get(Booking, booking_id)
    if booking is None or booking.agyary_id != agyary_id:
        return None
    agyary = await db.get(Agyary, agyary_id)
    customer = await db.get(Customer, booking.customer_id)
    service = await db.get(Service, booking.service_id)
    names = await _names_as_dicts(db, booking_id=booking.id)
    local = to_ist(booking.date_time)
    if reader_user_id is None:
        roj, mah = booking.parsi_roj, booking.parsi_mah
    else:
        roj, mah = _reading(local.date(), await reading_system(db, reader_user_id))
    when = f"{date_label(roj, mah, local.date())}, {local.strftime('%I:%M %p').lstrip('0')}"
    return SlipData(
        agyary_name=agyary.name,
        behdin_name=customer.name,
        behdin_phone=customer.phone,
        event=service.name if service else "Service",
        when=when,
        names_text=names_block(names),
    )
