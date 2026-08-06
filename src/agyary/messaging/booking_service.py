"""Persistence layer used by the conversation flows.

Creates machis/bookings from accumulated conversation-state data, snapshots
names onto the ceremony (immutability of the prayer record), and maintains
the customer's saved name pool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.calendar import CalendarSystem, gregorian_to_parsi
from agyary.messaging.availability import (
    SlotOption,
    available_gehs,
    drop_elapsed_gehs,
    next_days_with_geh,
    parsi_slot_fields,
)
from agyary.messaging.geh_times import GEH_START_TIMES, ensure_ist, machi_ceremony_datetime
from agyary.models import (
    Agyary,
    AgyaryCustomer,
    AgyaryUser,
    Booking,
    CeremonyName,
    Customer,
    CustomerSavedName,
    Machi,
    Payment,
    Service,
    User,
)
from agyary.models.enums import ADMIN_ROLES


class SlotTakenError(Exception):
    """The requested machi slot was booked concurrently."""


async def get_customer_by_phone(db: AsyncSession, phone: str) -> Customer | None:
    result = await db.execute(select(Customer).where(Customer.phone == phone))
    return result.scalar_one_or_none()


async def create_customer(db: AsyncSession, phone: str, name: str = "") -> Customer:
    customer = Customer(phone=phone, name=name)
    db.add(customer)
    await db.flush()
    return customer


async def ensure_agyary_customer(db: AsyncSession, agyary_id: int, customer_id: int) -> None:
    result = await db.execute(
        select(AgyaryCustomer).where(
            AgyaryCustomer.agyary_id == agyary_id,
            AgyaryCustomer.customer_id == customer_id,
        )
    )
    junction = result.scalar_one_or_none()
    if junction is None:
        db.add(
            AgyaryCustomer(
                agyary_id=agyary_id,
                customer_id=customer_id,
                first_booking_at=datetime.now(UTC),
            )
        )
    elif junction.first_booking_at is None:
        junction.first_booking_at = datetime.now(UTC)


async def get_admins(db: AsyncSession, agyary_id: int) -> list[User]:
    result = await db.execute(
        select(User)
        .join(AgyaryUser, AgyaryUser.user_id == User.id)
        .where(
            AgyaryUser.agyary_id == agyary_id,
            AgyaryUser.role.in_(ADMIN_ROLES),
            AgyaryUser.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    return list(result.scalars())


async def is_admin_phone(db: AsyncSession, agyary_id: int, phone: str) -> bool:
    return any(admin.phone == phone for admin in await get_admins(db, agyary_id))


async def get_active_agyary_users(db: AsyncSession, agyary_id: int) -> list[User]:
    """Every active member at an agyary, any role - not just ADMIN_ROLES.

    Machi's FYI notification (module 3) goes to everyone, since a
    peer-mobed agyari has no ADMIN_ROLES member at all and get_admins()
    would silently return an empty list there - the exact bug this
    redesign exists to fix.
    """
    result = await db.execute(
        select(User)
        .join(AgyaryUser, AgyaryUser.user_id == User.id)
        .where(
            AgyaryUser.agyary_id == agyary_id,
            AgyaryUser.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    return list(result.scalars())


# The standard service catalog a freshly set-up agyari starts with, so the
# manual-add booking path works the moment a mobed activates it. Name +
# min_mobeds + offsite_capable only - NO default price (money is parked this
# pass, doc 05). Machi is included so it exists as a Service row, but the
# booking flows exclude it by name (it has its own slot-based path).
DEFAULT_SERVICE_SPECS = [
    ("Machi", 1, False),
    ("Jashan", 1, True),
    ("Afringan", 1, True),
    ("Farokshi", 1, True),
    ("Satum", 1, False),
    ("Navjote", 1, True),
    ("Wedding", 1, True),
    ("Vandidad", 1, False),
    ("Yazeshni", 2, False),
]


async def ensure_default_services(db: AsyncSession, agyary_id: int) -> None:
    """Idempotently give an agyari the standard service list (used when a
    mobed activates or creates one). Only adds names not already present, so
    it's safe to call more than once and never clobbers a mobed's edits."""
    existing = {
        name.strip().lower()
        for name in (
            await db.execute(select(Service.name).where(Service.agyary_id == agyary_id))
        ).scalars()
    }
    for order, (name, min_mobeds, offsite) in enumerate(DEFAULT_SERVICE_SPECS):
        if name.strip().lower() in existing:
            continue
        db.add(
            Service(
                agyary_id=agyary_id,
                name=name,
                default_price=None,
                min_mobeds=min_mobeds,
                offsite_capable=offsite,
                display_order=order,
            )
        )
    await db.flush()


async def get_service_by_id(db: AsyncSession, agyary_id: int, service_id: int) -> Service | None:
    result = await db.execute(
        select(Service).where(
            Service.id == service_id,
            Service.agyary_id == agyary_id,
            Service.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def list_services(db: AsyncSession, agyary_id: int, exclude_machi: bool = True) -> list[Service]:
    stmt = (
        select(Service)
        .where(Service.agyary_id == agyary_id, Service.is_active.is_(True))
        .order_by(Service.display_order, Service.id)
    )
    services = list((await db.execute(stmt)).scalars())
    if exclude_machi:
        services = [s for s in services if s.name.strip().lower() != "machi"]
    return services


async def machi_price(db: AsyncSession, agyary_id: int) -> Decimal | None:
    result = await db.execute(
        select(Service.default_price).where(
            Service.agyary_id == agyary_id,
            func.lower(Service.name) == "machi",
            Service.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Saved name pool
# ---------------------------------------------------------------------------
async def saved_pairs(db: AsyncSession, customer_id: int, departed_only: bool = False) -> list[CustomerSavedName]:
    stmt = (
        select(CustomerSavedName)
        .where(CustomerSavedName.customer_id == customer_id, CustomerSavedName.section == "pair")
        .order_by(CustomerSavedName.pair_group, CustomerSavedName.display_order)
    )
    rows = list((await db.execute(stmt)).scalars())
    if departed_only:
        rows = [r for r in rows if r.status == "departed"]
    return rows


def complete_pairs(rows: list[CustomerSavedName]) -> list[CustomerSavedName]:
    """Only rows belonging to complete, status-consistent pairs.

    A departed-only (or otherwise filtered) view of the pool can leave lone
    survivors of mixed pairs; offering those would book a one-name 'pair'.
    """
    grouped: dict[int, list[CustomerSavedName]] = {}
    for row in rows:
        if row.pair_group is not None:
            grouped.setdefault(row.pair_group, []).append(row)
    result: list[CustomerSavedName] = []
    for group in sorted(grouped):
        members = grouped[group]
        if len(members) == 2 and members[0].status == members[1].status:
            result.extend(members)
    return result


async def saved_farmayeshne(db: AsyncSession, customer_id: int) -> list[CustomerSavedName]:
    stmt = (
        select(CustomerSavedName)
        .where(
            CustomerSavedName.customer_id == customer_id,
            CustomerSavedName.section == "farmayeshne",
        )
        .order_by(CustomerSavedName.display_order)
    )
    return list((await db.execute(stmt)).scalars())


async def replace_saved_section(
    db: AsyncSession, customer_id: int, section: str, names: list[dict]
) -> None:
    """Replace one section of the customer's saved pool ('New set' semantics)."""
    await db.execute(
        delete(CustomerSavedName).where(
            CustomerSavedName.customer_id == customer_id,
            CustomerSavedName.section == section,
        )
    )
    for i, n in enumerate(names):
        db.add(
            CustomerSavedName(
                customer_id=customer_id,
                section=section,
                title=n["title"],
                name=n["name"],
                status=n["status"],
                pair_group=n.get("pair_group"),
                display_order=i,
            )
        )


def saved_rows_to_dicts(rows: list[CustomerSavedName], section: str) -> list[dict]:
    return [
        {
            "section": section,
            "title": r.title,
            "name": r.name,
            "status": r.status,
            "pair_group": r.pair_group,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Ceremony creation (snapshot-on-booking)
# ---------------------------------------------------------------------------
def normalize_machi_names(purpose: str, names: list[dict]) -> list[dict]:
    """Put Tandarosti names in the section they belong to.

    Tandarosti names are the living family the machi is being done for -
    which is what 'farmayeshne' means. They were being written as
    section='pair' with pair_group=NULL, i.e. as pair-section rows that
    aren't in a pair, on the reasoning that machis have no farmayeshne
    section. That was inconsistent two ways: the saved-name pool has always
    stored the very same names as 'farmayeshne'
    (flows/machi.py's replace_saved_section call), so a name changed
    sections on its way from the pool onto the ceremony; and any consumer
    grouping pair rows had to special-case a NULL group.

    Applied at the two shared slot functions below, so it holds for the
    WhatsApp flow and the PWA alike no matter what either sends, and for
    anything added later. Patet is untouched - it genuinely is one departed
    pair.
    """
    if purpose != "tandarosti":
        return names
    return [
        {**n, "section": "farmayeshne", "pair_group": None} if n.get("section") == "pair" else n
        for n in names
    ]


def _attach_names(names: list[dict], *, machi_id: int | None = None, booking_id: int | None = None):
    for i, n in enumerate(names):
        yield CeremonyName(
            machi_id=machi_id,
            booking_id=booking_id,
            section=n["section"],
            title=n["title"],
            name=n["name"],
            status=n["status"],
            pair_group=n.get("pair_group"),
            display_order=i,
        )


async def create_machi_request(
    db: AsyncSession,
    agyary: Agyary,
    customer: Customer,
    *,
    roj: int,
    mah: int,
    year: int,
    geh: int,
    gregorian: date,
    purpose: str,
    names: list[dict],
    amount: Decimal | None,
) -> Machi:
    """Create a requested machi; raises SlotTakenError on a slot race.

    Uses a SAVEPOINT so the partial-unique-index violation doesn't poison the
    outer transaction (the caller still needs to send alternative messages).
    """
    machi = Machi(
        agyary_id=agyary.id,
        customer_id=customer.id,
        parsi_roj=roj,
        parsi_mah=mah,
        parsi_year=year,
        calendar_system=agyary.calendar_system,
        geh=geh,
        gregorian_date=gregorian,
        ceremony_datetime=machi_ceremony_datetime(gregorian, geh),
        purpose=purpose,
        amount=amount,
    )
    try:
        async with db.begin_nested():
            db.add(machi)
            await db.flush()
    except IntegrityError as exc:
        raise SlotTakenError from exc

    for row in _attach_names(names, machi_id=machi.id):
        db.add(row)
    await ensure_agyary_customer(db, agyary.id, customer.id)
    await db.flush()
    return machi


@dataclass(frozen=True)
class MachiSlotAlternatives:
    """Structured, unrendered alternative data for a taken machi slot.

    Deliberately plain data, not pre-built WhatsApp messages - each caller
    (the WhatsApp flow, the PWA manual-add path) renders this into its own
    shape. Mirrors what ``next_any_day`` deliberately excludes: that option
    is a 90-day scan, expensive enough that today's flow only computes it
    when the customer explicitly asks for it (the "next available day"
    button) rather than eagerly on every taken-slot response - callers that
    want it call ``next_days_with_any_geh`` themselves.
    """

    same_day_gehs: list[int]
    same_geh_next_days: list[SlotOption]


@dataclass(frozen=True)
class MachiBookingResult:
    """Outcome of ``book_machi_slot``: exactly one of the two is set."""

    machi: Machi | None
    alternatives: MachiSlotAlternatives | None


async def compute_machi_alternatives(
    db: AsyncSession, agyary: Agyary, roj: int, mah: int, year: int, geh: int, gregorian: date
) -> MachiSlotAlternatives:
    same_day = drop_elapsed_gehs(
        await available_gehs(db, agyary.id, roj, mah, year), gregorian
    )
    same_geh_next = await next_days_with_geh(
        db, agyary.id, CalendarSystem(agyary.calendar_system), gregorian, geh
    )
    return MachiSlotAlternatives(same_day_gehs=same_day, same_geh_next_days=same_geh_next)


async def book_machi_slot(
    db: AsyncSession,
    agyary: Agyary,
    customer: Customer,
    *,
    roj: int,
    mah: int,
    year: int,
    geh: int,
    gregorian: date,
    purpose: str,
    names: list[dict],
) -> MachiBookingResult:
    """The one function that owns "is this slot valid, is it free, claim it,
    what are the alternatives if not" for machi bookings.

    Both the WhatsApp flow (auto-confirm) and the PWA's manual walk-in entry
    call into this - neither talks to persistence directly for this
    decision, and neither re-implements the past-elapsed-geh check or the
    alternatives computation independently. No money/payment: machi is
    booked with no amount recorded in this redesign.
    """
    names = normalize_machi_names(purpose, names)
    free = drop_elapsed_gehs(await available_gehs(db, agyary.id, roj, mah, year), gregorian)
    if geh in free:
        try:
            machi = await create_machi_request(
                db,
                agyary,
                customer,
                roj=roj,
                mah=mah,
                year=year,
                geh=geh,
                gregorian=gregorian,
                purpose=purpose,
                names=names,
                amount=None,
            )
            # This function IS the auto-confirm decision - no approval gate
            # follows, so the machi is booked, not merely requested.
            machi.status = "confirmed"
            await db.flush()
            return MachiBookingResult(machi=machi, alternatives=None)
        except SlotTakenError:
            pass  # raced between the pre-check and the insert - fall through

    alternatives = await compute_machi_alternatives(db, agyary, roj, mah, year, geh, gregorian)
    return MachiBookingResult(machi=None, alternatives=alternatives)


def _booking_parsi_anchor(agyary: Agyary, ceremony_dt_local: datetime) -> tuple[datetime, int, int, int]:
    """Anchor a local ceremony datetime to IST and derive its Parsi day.

    Shared by create and edit so the (sunrise-anchored) date derivation and
    the IST coercion (audit finding G1) live in exactly one place. A naive
    datetime (the PWA sends one) means IST local time, not server-local; a
    pre-sunrise ceremony belongs to the PREVIOUS Parsi day.
    """
    local = ensure_ist(ceremony_dt_local)
    anchor = local.date()
    if local.time() < GEH_START_TIMES[1]:
        anchor -= timedelta(days=1)
    roj, mah, year = parsi_slot_fields(
        gregorian_to_parsi(anchor, CalendarSystem(agyary.calendar_system))
    )
    return local, roj, mah, year


async def replace_ceremony_names(
    db: AsyncSession, names: list[dict], *, machi_id: int | None = None, booking_id: int | None = None
) -> None:
    """Snapshot a fresh set of names onto a ceremony, dropping the old set.
    Used by the edit path (create attaches directly)."""
    column = CeremonyName.machi_id if machi_id is not None else CeremonyName.booking_id
    value = machi_id if machi_id is not None else booking_id
    await db.execute(delete(CeremonyName).where(column == value))
    for row in _attach_names(names, machi_id=machi_id, booking_id=booking_id):
        db.add(row)
    await db.flush()


async def create_booking_request(
    db: AsyncSession,
    agyary: Agyary,
    customer: Customer,
    service: Service,
    *,
    ceremony_dt_local: datetime,
    purpose: str,
    names: list[dict],
    location: str | None,
    is_offsite: bool,
    amount: Decimal | None,
) -> Booking:
    local, roj, mah, year = _booking_parsi_anchor(agyary, ceremony_dt_local)
    booking = Booking(
        agyary_id=agyary.id,
        service_id=service.id,
        customer_id=customer.id,
        date_time=local,
        ceremony_datetime=local,
        parsi_roj=roj,
        parsi_mah=mah,
        parsi_year=year,
        calendar_system=agyary.calendar_system,
        purpose=purpose,
        location=location,
        is_offsite=is_offsite,
        amount=amount,
    )
    db.add(booking)
    await db.flush()
    for row in _attach_names(names, booking_id=booking.id):
        db.add(row)
    await ensure_agyary_customer(db, agyary.id, customer.id)
    await db.flush()
    return booking


async def rebook_machi_slot(
    db: AsyncSession,
    agyary: Agyary,
    machi: Machi,
    *,
    roj: int,
    mah: int,
    year: int,
    geh: int,
    gregorian: date,
    purpose: str,
    names: list[dict],
) -> MachiBookingResult:
    """Edit an existing machi, re-validating the slot through the SAME core
    primitives create uses (available_gehs + drop_elapsed_gehs + the partial
    unique index) - never a second slot-check path. If the day/geh actually
    changed and the new slot is taken (or elapsed), returns alternatives and
    leaves the machi untouched; an unchanged slot (name/purpose-only edit)
    skips the re-check entirely so it can't collide with itself."""
    names = normalize_machi_names(purpose, names)
    if (roj, mah, year, geh) != (machi.parsi_roj, machi.parsi_mah, machi.parsi_year, machi.geh):
        free = drop_elapsed_gehs(await available_gehs(db, agyary.id, roj, mah, year), gregorian)
        if geh not in free:
            return MachiBookingResult(
                machi=None,
                alternatives=await compute_machi_alternatives(db, agyary, roj, mah, year, geh, gregorian),
            )
        try:
            async with db.begin_nested():
                machi.parsi_roj, machi.parsi_mah, machi.parsi_year = roj, mah, year
                machi.geh = geh
                machi.gregorian_date = gregorian
                machi.ceremony_datetime = machi_ceremony_datetime(gregorian, geh)
                await db.flush()
        except IntegrityError:  # raced onto a slot taken between check and write
            return MachiBookingResult(
                machi=None,
                alternatives=await compute_machi_alternatives(db, agyary, roj, mah, year, geh, gregorian),
            )
    machi.purpose = purpose
    await replace_ceremony_names(db, names, machi_id=machi.id)
    return MachiBookingResult(machi=machi, alternatives=None)


async def update_booking(
    db: AsyncSession,
    agyary: Agyary,
    booking: Booking,
    service: Service,
    *,
    ceremony_dt_local: datetime,
    purpose: str,
    names: list[dict],
    location: str | None,
    is_offsite: bool,
) -> Booking:
    """Edit a booking's details in place (time-based, no slot uniqueness).
    Re-derives the Parsi day via the shared anchor helper and re-snapshots
    names. The caller recomputes the (non-blocking) calendar-conflict flag."""
    local, roj, mah, year = _booking_parsi_anchor(agyary, ceremony_dt_local)
    booking.service_id = service.id
    booking.date_time = local
    booking.ceremony_datetime = local
    booking.parsi_roj, booking.parsi_mah, booking.parsi_year = roj, mah, year
    booking.purpose = purpose
    booking.location = location
    booking.is_offsite = is_offsite
    await db.flush()
    await replace_ceremony_names(db, names, booking_id=booking.id)
    return booking


# ---------------------------------------------------------------------------
# Approval / decline / cancellation
# ---------------------------------------------------------------------------
def generate_upi_link(upi_id: str, payee_name: str, amount: Decimal, note: str) -> str:
    params = {"pa": upi_id, "pn": payee_name, "am": str(amount), "cu": "INR", "tn": note}
    return "upi://pay?" + urlencode(params)


async def create_pending_payment(
    db: AsyncSession, ceremony: Machi | Booking, upi_link: str | None
) -> Payment:
    payment = Payment(
        agyary_id=ceremony.agyary_id,
        customer_id=ceremony.customer_id,
        machi_id=ceremony.id if isinstance(ceremony, Machi) else None,
        booking_id=ceremony.id if isinstance(ceremony, Booking) else None,
        amount=ceremony.amount,
        method="upi" if upi_link else "cash",
        upi_intent_link=upi_link,
    )
    db.add(payment)
    await db.flush()
    return payment
