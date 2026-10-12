"""Memorials: the observances a family keeps for one departed person.

The schedule itself is calendar.memorial.build_schedule (pure, tested). This
module is everything around it: validating what the mobed chose, saving the
memorial and its observances, and reading them back for the behdin's page and
for the calendar.

A memorial is private to the mobed who made it - same rule as the behdin
book. Every read here takes the user's id and filters on it; the API layer
only decides who is asking.

There is no scheduler, so nothing here "closes" a memorial. Whether one is
still running is derived from its dates each time it is read, and the
closing notice is generated on the last observance's day when the calendar
asks for that day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agyary.calendar import CalendarSystem, gregorian_to_parsi
from agyary.calendar.memorial import Observance, build_schedule
from agyary.messaging import booking_service
from agyary.messaging.availability import parsi_slot_fields
from agyary.models import (
    Agyary,
    Customer,
    Memorial,
    MemorialObservance,
    MemorialObservanceService,
    Notification,
    Service,
)
from agyary.models.enums import CALENDAR_SYSTEMS
from agyary.services import mobed_dashboard, reminder_message

IST = ZoneInfo("Asia/Kolkata")

# A schedule is always finite and shown whole before saving; these keep one
# request from writing an absurd number of rows.
MAX_MONTHLY_MONTHS = 120
MAX_YEARLY_YEARS = 50
MAX_PARAB_YEARS = 25
MAX_OBSERVANCES = 800


class MemorialError(Exception):
    """Rejected memorial - the message is safe to show the mobed."""


@dataclass(frozen=True)
class Choice:
    """What the mobed chose, before it becomes a schedule. A series that was
    not chosen is None; a series that was chosen has its length, always."""

    departed_name: str
    death_date: date
    opening: str
    day_counts: tuple[int, ...] = ()
    monthly_months: int | None = None
    yearly_years: int | None = None
    parabs: str | None = None
    parab_years: int | None = None
    # The calendar the family keeps, or None for the mobed's own primary. It
    # decides which day is a Parab and where the Gatha days fall, so it is
    # stored with the memorial rather than assumed later.
    calendar: str | None = None


def _validate_length(value: int | None, label: str, ceiling: int) -> None:
    if value is None:
        return
    if not 1 <= value <= ceiling:
        raise MemorialError(f"{label} must be between 1 and {ceiling}.")


async def calendar_for(db: AsyncSession, user_id: int, choice: Choice) -> CalendarSystem:
    """The calendar a memorial is counted in: the one the mobed chose for this
    family, else the one they read in. NOT the fire temple's - the temple's
    reckoning is for its own slots, while a family's Parabs and Gatha days
    follow the calendar they keep, and the mobed sees every date in theirs."""
    if choice.calendar:
        if choice.calendar not in CALENDAR_SYSTEMS:
            raise MemorialError("Choose Shenshai, Kadmi or Fasli.")
        return CalendarSystem(choice.calendar)
    return await mobed_dashboard.reading_system(db, user_id)


def plan(system: CalendarSystem, choice: Choice) -> tuple[list[Observance], tuple[int, int, int]]:
    """The schedule for a choice, without saving anything. Also returns the
    death as (roj, mah, year) in ``system`` - what the preview shows the
    mobed, and what gets stored."""
    name = choice.departed_name.strip()
    if not name:
        raise MemorialError("Please enter the departed person's name.")
    _validate_length(choice.monthly_months, "Monthly observances", MAX_MONTHLY_MONTHS)
    _validate_length(choice.yearly_years, "Yearly observances", MAX_YEARLY_YEARS)
    _validate_length(choice.parab_years, "Parab years", MAX_PARAB_YEARS)
    if (choice.parabs is None) != (choice.parab_years is None):
        raise MemorialError("Choose how many years the Parabs should run for.")

    # A Gatha death is stored the way machis store one: Mah 13, with the
    # Gatha number in the Roj slot.
    roj, mah, year = parsi_slot_fields(gregorian_to_parsi(choice.death_date, system))

    try:
        schedule = build_schedule(
            death_roj=roj, death_mah=mah, death_year=year,
            system=system, opening=choice.opening,
            day_counts=tuple(choice.day_counts),
            monthly_months=choice.monthly_months or 0,
            yearly_years=choice.yearly_years or 0,
            parabs=choice.parabs, parab_years=choice.parab_years or 0,
        )
    except ValueError as exc:
        raise MemorialError(str(exc)) from exc
    if len(schedule) > MAX_OBSERVANCES:
        raise MemorialError(
            f"That makes {len(schedule)} observances, more than the {MAX_OBSERVANCES} allowed. "
            "Shorten the series."
        )
    return schedule, (roj, mah, year)


async def _validated_services(db: AsyncSession, agyary_id: int, service_ids: list[int]) -> list[Service]:
    wanted = list(dict.fromkeys(service_ids))  # order kept, duplicates gone
    if not wanted:
        raise MemorialError("Choose at least one service: Afringan, Farokshi or Baaj.")
    found = []
    for sid in wanted:
        service = await booking_service.get_service_by_id(db, agyary_id, sid)
        if service is None:
            raise MemorialError("One of those services isn't offered here.")
        found.append(service)
    return found


async def create_memorial(
    db: AsyncSession,
    agyary: Agyary,
    user_id: int,
    customer: Customer,
    choice: Choice,
    service_ids: list[int],
) -> Memorial:
    """Save a memorial. Every observance starts with the same services - the
    set chosen here - and each can be changed on its own afterwards."""
    system = await calendar_for(db, user_id, choice)
    schedule, (roj, mah, year) = plan(system, choice)
    services = await _validated_services(db, agyary.id, service_ids)

    memorial = Memorial(
        agyary_id=agyary.id,
        customer_id=customer.id,
        created_by_user_id=user_id,
        departed_name=choice.departed_name.strip(),
        death_gregorian=choice.death_date,
        death_roj=roj, death_mah=mah, death_year=year,
        calendar_system=system.value,
        opening=choice.opening,
        day_counts=sorted(set(choice.day_counts)),
        monthly_months=choice.monthly_months,
        yearly_years=choice.yearly_years,
        parabs=choice.parabs,
        parab_years=choice.parab_years,
    )
    memorial.observances = [
        MemorialObservance(
            code=o.code, label=o.label, day_number=o.day_number,
            gregorian_date=o.gregorian_date,
            parsi_roj=o.roj, parsi_mah=o.mah, parsi_year=o.year, gatha_index=o.gatha_index,
            services=[MemorialObservanceService(service_id=s.id) for s in services],
        )
        for o in schedule
    ]
    db.add(memorial)
    await db.flush()
    return memorial


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _with_children():
    return selectinload(Memorial.observances).selectinload(MemorialObservance.services)


async def get_for_user(db: AsyncSession, user_id: int, memorial_id: int) -> Memorial | None:
    """A memorial, but only the caller's own."""
    result = await db.execute(
        select(Memorial)
        .options(_with_children())
        .where(Memorial.id == memorial_id, Memorial.created_by_user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_for_behdin(
    db: AsyncSession, user_id: int, agyary_id: int, customer_id: int
) -> list[Memorial]:
    result = await db.execute(
        select(Memorial)
        .options(_with_children())
        .where(
            Memorial.created_by_user_id == user_id,
            Memorial.agyary_id == agyary_id,
            Memorial.customer_id == customer_id,
        )
        .order_by(Memorial.death_gregorian.desc(), Memorial.id.desc())
    )
    return list(result.scalars())


def today_ist() -> date:
    return datetime.now(IST).date()


def progress(memorial: Memorial, today: date) -> dict:
    """Where a memorial has got to. Running means something is still ahead
    of today; completed means the last observance has passed."""
    dates = [o.gregorian_date for o in memorial.observances]
    upcoming = sorted((o for o in memorial.observances if o.gregorian_date >= today),
                      key=lambda o: (o.gregorian_date, o.day_number))
    last = max(dates) if dates else None
    return {
        "total": len(dates),
        "done": sum(1 for d in dates if d < today),
        "next": serialize_observance(upcoming[0]) if upcoming else None,
        "last_date": last.isoformat() if last else None,
        "status": "running" if upcoming else "completed",
    }


def _hhmm(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t else None


def serialize_observance(o: MemorialObservance, names: dict[int, str] | None = None) -> dict:
    return {
        "id": o.id,
        "memorial_id": o.memorial_id,
        "code": o.code,
        "label": o.label,
        "day_number": o.day_number,
        "date": o.gregorian_date.isoformat(),
        "roj": o.parsi_roj, "mah": o.parsi_mah, "year": o.parsi_year,
        "gatha_index": o.gatha_index,
        "time": _hhmm(o.time_of_day),
        "notes": o.notes,
        "service_ids": sorted(s.service_id for s in o.services),
        "services": [
            {"id": s.service_id, "name": (names or {}).get(s.service_id, "")}
            for s in sorted(o.services, key=lambda s: s.service_id)
        ],
    }


async def _service_names(db: AsyncSession, agyary_id: int) -> dict[int, str]:
    rows = await db.execute(select(Service.id, Service.name).where(Service.agyary_id == agyary_id))
    return {sid: name for sid, name in rows.all()}


def serialize_memorial(
    memorial: Memorial, names: dict[int, str], today: date, *, with_observances: bool
) -> dict:
    out = {
        "id": memorial.id,
        "customer_id": memorial.customer_id,
        "departed_name": memorial.departed_name,
        "death_date": memorial.death_gregorian.isoformat(),
        "death": {"roj": memorial.death_roj, "mah": memorial.death_mah, "year": memorial.death_year},
        "calendar": memorial.calendar_system,
        "opening": memorial.opening,
        "day_counts": memorial.day_counts,
        "monthly_months": memorial.monthly_months,
        "yearly_years": memorial.yearly_years,
        "parabs": memorial.parabs,
        "parab_years": memorial.parab_years,
        **progress(memorial, today),
    }
    if with_observances:
        out["observances"] = [
            serialize_observance(o, names)
            for o in sorted(memorial.observances, key=lambda o: (o.gregorian_date, o.day_number))
        ]
    return out


async def summaries(db: AsyncSession, agyary_id: int, memorials: list[Memorial], *, detailed: bool) -> list[dict]:
    names = await _service_names(db, agyary_id)
    today = today_ist()
    return [serialize_memorial(m, names, today, with_observances=detailed) for m in memorials]


# ---------------------------------------------------------------------------
# Editing one observance
# ---------------------------------------------------------------------------
async def get_observance_for_user(
    db: AsyncSession, user_id: int, memorial_id: int, observance_id: int
) -> tuple[Memorial, MemorialObservance] | None:
    memorial = await get_for_user(db, user_id, memorial_id)
    if memorial is None:
        return None
    for o in memorial.observances:
        if o.id == observance_id:
            return memorial, o
    return None


async def update_observance(
    db: AsyncSession,
    memorial: Memorial,
    observance: MemorialObservance,
    *,
    service_ids: list[int] | None,
    time_of_day: time | None,
    clear_time: bool,
    notes: str | None,
    clear_notes: bool,
) -> None:
    """Change one observance without touching the others. Services must stay
    non-empty - an observance with nothing to do is a mistake, not a state."""
    if service_ids is not None:
        services = await _validated_services(db, memorial.agyary_id, service_ids)
        observance.services = [MemorialObservanceService(service_id=s.id) for s in services]
    if clear_time:
        observance.time_of_day = None
    elif time_of_day is not None:
        observance.time_of_day = time_of_day
    if clear_notes:
        observance.notes = None
    elif notes is not None:
        observance.notes = notes.strip() or None
    await db.flush()


async def delete_memorial(db: AsyncSession, memorial: Memorial) -> None:
    await db.delete(memorial)
    await db.flush()


# ---------------------------------------------------------------------------
# The calendar
# ---------------------------------------------------------------------------
CLOSING_TEXT = (
    "Last observance for {departed}. After today there are no more upcoming "
    "bookings for this memorial, and it will be closed."
)


async def calendar_feed(
    db: AsyncSession, user_id: int, agyary_id: int, start: date, end: date
) -> list[dict]:
    """Everything of this mobed's memorials that falls in [start, end]:
    the observances, plus a separate closing notice on the day of each
    memorial's last one. The notice is its own kind so the calendar can pin
    and colour it apart from ordinary events."""
    if end < start:
        raise MemorialError("end must not be before start")

    rows = (
        await db.execute(
            select(MemorialObservance, Memorial, Customer.name)
            .join(Memorial, Memorial.id == MemorialObservance.memorial_id)
            .join(Customer, Customer.id == Memorial.customer_id)
            .options(selectinload(MemorialObservance.services))
            .where(
                Memorial.created_by_user_id == user_id,
                Memorial.agyary_id == agyary_id,
                MemorialObservance.gregorian_date >= start,
                MemorialObservance.gregorian_date <= end,
            )
            .order_by(MemorialObservance.gregorian_date, MemorialObservance.day_number)
        )
    ).all()
    if not rows:
        return []

    # The last date of each memorial in the window - taken over ALL of its
    # observances, not just those in range, or a memorial viewed mid-way
    # would think its last visible day was its last.
    memorial_ids = {m.id for _, m, _ in rows}
    last_dates = dict(
        (
            await db.execute(
                select(MemorialObservance.memorial_id, func.max(MemorialObservance.gregorian_date))
                .where(MemorialObservance.memorial_id.in_(memorial_ids))
                .group_by(MemorialObservance.memorial_id)
            )
        ).all()
    )

    names = await _service_names(db, agyary_id)
    items: list[dict] = []
    closing_done: set[int] = set()
    for obs, memorial, behdin_name in rows:
        is_last = obs.gregorian_date == last_dates[memorial.id]
        items.append({
            "kind": "memorial",
            **serialize_observance(obs, names),
            "behdin_name": behdin_name,
            "departed_name": memorial.departed_name,
            "is_last": is_last,
        })
        if is_last and memorial.id not in closing_done:
            closing_done.add(memorial.id)
            items.append({
                "kind": "memorial_closing",
                "memorial_id": memorial.id,
                "date": obs.gregorian_date.isoformat(),
                "behdin_name": behdin_name,
                "departed_name": memorial.departed_name,
                "text": CLOSING_TEXT.format(departed=memorial.departed_name),
            })
    return items



# ---------------------------------------------------------------------------
# Reminders due
# ---------------------------------------------------------------------------
# A family is reminded the day before. The same number will drive the
# automatic sender, so what the mobed sees as "due" here is exactly what would
# go out.
REMINDER_LEAD_DAYS = 1

# The opening days (1-10) are never reminded. The family is at the fire
# temple with the mobed every day of them, in mourning; a text would be
# useless at best and an intrusion at worst. Reminders start with what comes
# after: the 29th/30th day on, the monthly and yearly series, the Parabs.
OPENING_DAYS = 10


def whatsapp_link(phone: str, text: str) -> str:
    """A wa.me link that opens a chat with ``phone`` with ``text`` ready to
    send. Sent from the mobed's own WhatsApp: nothing goes out until they
    tap Send."""
    return f"https://wa.me/{phone.lstrip('+')}?text={quote(text, safe='')}"


async def reminders_due(
    db: AsyncSession, user_id: int, agyary_id: int, today: date, horizon_days: int
) -> list[dict]:
    """This mobed's observances from today to ``horizon_days`` ahead, soonest
    first, each marked ``due`` once it is within the reminder lead time.

    Scoped to the caller like every memorial read: a family's departed are
    not a colleague's to see, so the list is the mobed's own, not the
    fire temple's.
    """
    if horizon_days < 0:
        raise MemorialError("horizon must not be negative")
    end = today + timedelta(days=horizon_days)
    rows = (
        await db.execute(
            select(
                MemorialObservance, Memorial, Customer.name, Customer.phone,
                Customer.reminders_enabled & (Customer.owner_user_id == user_id),
                Customer.reminders_stopped_at,
            )
            .join(Memorial, Memorial.id == MemorialObservance.memorial_id)
            .join(Customer, Customer.id == Memorial.customer_id)
            .options(selectinload(MemorialObservance.services))
            .where(
                Memorial.created_by_user_id == user_id,
                Memorial.agyary_id == agyary_id,
                MemorialObservance.gregorian_date >= today,
                MemorialObservance.gregorian_date <= end,
                MemorialObservance.day_number > OPENING_DAYS,
            )
            .order_by(MemorialObservance.gregorian_date, MemorialObservance.day_number)
        )
    ).all()
    names = await _service_names(db, agyary_id)
    agyary_name = (await db.execute(select(Agyary.name).where(Agyary.id == agyary_id))).scalar_one()
    # What has already been sent automatically, by observance.
    sent = dict(
        (
            await db.execute(
                select(Notification.memorial_observance_id, Notification.status).where(
                    Notification.notification_type == "memorial_reminder",
                    Notification.memorial_observance_id.in_([o.id for o, *_ in rows]),
                )
            )
        ).all()
    )
    items = []
    for obs, memorial, behdin_name, behdin_phone, auto_on, stopped_at in rows:
        days_away = (obs.gregorian_date - today).days
        serialized = serialize_observance(obs, names)
        text = reminder_message.manual_text(reminder_message.build_parts(
            agyary_name, obs, memorial.departed_name,
            [s["name"] for s in serialized["services"]], today,
        ))
        items.append({
            **serialized,
            "memorial_id": memorial.id,
            "customer_id": memorial.customer_id,
            "behdin_name": behdin_name,
            "behdin_phone": behdin_phone,
            "message": text,
            "wa_link": whatsapp_link(behdin_phone, text),
            "departed_name": memorial.departed_name,
            # The observance's Roj/Mah/year are in THIS memorial's calendar.
            "calendar": memorial.calendar_system,
            "days_away": days_away,
            "due": days_away <= REMINDER_LEAD_DAYS,
            # Will it go on its own (the behdin agreed and has not said STOP),
            # and if it has been tried, how that went.
            "auto": bool(auto_on) and stopped_at is None,
            "sent_status": sent.get(obs.id),
        })
    return items
