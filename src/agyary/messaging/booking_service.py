"""Persistence layer used by the conversation flows.

Creates machis/bookings from accumulated conversation-state data, snapshots
names onto the ceremony (immutability of the prayer record), and maintains
the customer's saved name pool.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.calendar import CalendarSystem, gregorian_to_parsi
from agyary.messaging.availability import parsi_slot_fields
from agyary.messaging.geh_times import GEH_START_TIMES, IST, machi_ceremony_datetime
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
    local = ceremony_dt_local.astimezone(IST)
    # The Parsi day starts at sunrise: a pre-sunrise ceremony (e.g. an
    # overnight Vandidad ending at 2 AM) belongs to the PREVIOUS Parsi day.
    anchor = local.date()
    if local.time() < GEH_START_TIMES[1]:
        anchor -= timedelta(days=1)
    roj, mah, year = parsi_slot_fields(
        gregorian_to_parsi(anchor, CalendarSystem(agyary.calendar_system))
    )
    booking = Booking(
        agyary_id=agyary.id,
        service_id=service.id,
        customer_id=customer.id,
        date_time=ceremony_dt_local,
        ceremony_datetime=ceremony_dt_local,
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
