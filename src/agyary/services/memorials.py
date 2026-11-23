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

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agyary.calendar import CalendarSystem, gregorian_to_parsi, parsi_to_gregorian
from agyary.calendar.memorial import (
    NAMED_DAYS,
    OPENING_5_TO_9,
    OPENING_NONE,
    PARAB_FRAVARDIN_TIR,
    PARAB_ROJ_FOR_MAH,
    Observance,
    build_schedule,
)
from agyary.core.config import get_settings
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
    User,
)
from agyary.models.enums import OFFERED_CALENDARS
from agyary.services import guardrails, mobed_dashboard, reminder_message, reminders, template_text

IST = ZoneInfo("Asia/Kolkata")

# A schedule is always finite and shown whole before saving; these keep one
# request from writing an absurd number of rows.
# Old people's prayers can run for decades, so these allow up to 100 years:
# 1200 monthly, 100 yearly, 1200 Parabs.
MAX_MONTHLY_MONTHS = 1200
MAX_YEARLY_YEARS = 100
MAX_PARAB_YEARS = 100
MAX_BIRTHDAY_YEARS = 100
MAX_PARAB_COUNT = 1200
MAX_OBSERVANCES = 2500

# "More than a year ago" means the stand-in death is at least this many days back,
# so every opening and named day (the last is the 360th) is already behind it.
OLD_DEATH_DAYS = 361


class MemorialError(Exception):
    """Rejected memorial - the message is safe to show the mobed."""


@dataclass(frozen=True)
class Choice:
    """What the mobed chose, before it becomes a schedule. A series that was
    not chosen is None; a series that was chosen has its length, always."""

    departed_name: str
    # The death, either as a Gregorian date or as Roj and Mah (and Parsi year)
    # in the family's calendar (D5) - a death before sunrise belongs to the
    # previous Parsi day, and the mobed knows which it was. Mah 13 is a Gatha
    # day, with the Gatha number as the Roj.
    death_date: date | None
    opening: str = OPENING_NONE
    day_counts: tuple[int, ...] = ()
    monthly_months: int | None = None
    yearly_years: int | None = None
    fravardin_roj_months: int | None = None   # Roj Fravardin every month, for this many months
    parabs: str | None = None
    parab_years: int | None = None
    parab_count: int | None = None   # alternatively: how many Parabs, not how many years
    # The deceased's birthday, as a date or as Roj and Mah (one or the other),
    # repeated for birthday_years years.
    birthday_date: date | None = None
    birthday_roj: int | None = None
    birthday_mah: int | None = None
    birthday_years: int | None = None
    # A family arriving late: count from the death as always, but book nothing
    # before this date (see build_schedule). None books the whole schedule.
    start_from: date | None = None
    # The calendar the family keeps, or None for the mobed's own primary. It
    # decides which day is a Parab and where the Gatha days fall, so it is
    # stored with the memorial rather than assumed later.
    calendar: str | None = None
    death_roj: int | None = None
    death_mah: int | None = None
    death_year: int | None = None
    # The person passed away more than a year ago and the family wants the
    # monthly and yearly prayers carried on. The death is then given by Roj and
    # Mah alone (nobody needs the year), the opening and named days have gone,
    # and everything runs from today. See resolve_death and plan.
    long_ago: bool = False
    # The death's date as already worked out, used as it is: re-working a saved
    # memorial whose death did not change (for a death long ago this is the
    # stand-in, which must not drift a year as time goes by). Never from the API.
    death_known: date | None = None


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
        if choice.calendar not in OFFERED_CALENDARS:
            raise MemorialError("Choose Shenshai or Kadmi.")
        return CalendarSystem(choice.calendar)
    return await mobed_dashboard.reading_system(db, user_id)


def _on_parsi_day(year: int, system: CalendarSystem, roj: int, mah: int) -> date:
    if mah == 13:
        return parsi_to_gregorian(year, system, gatha_index=roj)
    return parsi_to_gregorian(year, system, mah=mah, roj=roj)


def resolve_death(system: CalendarSystem, choice: Choice, today: date | None = None) -> date:
    """The Gregorian date of the death, from whichever way it was given (D5).
    Roj and Mah without a year mean the most recent such day, today included.

    For a death more than a year ago (``long_ago``) only the Roj and Mah are
    known, and the date returned is a stand-in: the latest such day at least
    OLD_DEATH_DAYS back. It is never shown to anyone; it only places the
    monthly and yearly days on the right Roj and Mah."""
    if choice.death_known is not None:
        return choice.death_known
    if choice.long_ago and (choice.death_date is not None or choice.death_year is not None):
        raise MemorialError("For a death more than a year ago, give only the Roj and Mah.")
    by_date = choice.death_date is not None
    by_parsi = choice.death_roj is not None or choice.death_mah is not None or choice.death_year is not None
    if by_date == by_parsi:
        raise MemorialError("Give the date of death either as a date or as Roj and Mah, not both.")
    if by_date:
        return choice.death_date
    roj, mah = choice.death_roj, choice.death_mah
    if roj is None or mah is None:
        raise MemorialError("Give both the Roj and the Mah of the death.")
    if not 1 <= mah <= 13 or not 1 <= roj <= (6 if mah == 13 else 30):
        raise MemorialError("That is not a Roj and Mah.")
    try:
        if choice.death_year is not None:
            return _on_parsi_day(choice.death_year, system, roj, mah)
        today = today or today_ist()
        latest = today - timedelta(days=OLD_DEATH_DAYS) if choice.long_ago else today
        current = gregorian_to_parsi(today, system).year
        candidates = []
        for year in range(current - 4, current + 1):   # four back: Fasli's sixth Gatha
            try:
                when = _on_parsi_day(year, system, roj, mah)
            except ValueError:
                continue
            if when <= latest:
                candidates.append(when)
        if not candidates:
            raise MemorialError("That day has not come round in the last few years.")
        return max(candidates)
    except (ValueError, OverflowError) as exc:
        raise MemorialError("That is not a day in this calendar.") from exc


def resolve_birthday(system: CalendarSystem, choice: Choice) -> tuple[int, int] | None:
    """The birthday as (roj, mah), from a date or from Roj and Mah; None when
    no birthday was chosen. A date is read in the family's calendar."""
    given = [choice.birthday_date, choice.birthday_roj, choice.birthday_mah]
    if all(g is None for g in given):
        if choice.birthday_years is not None:
            raise MemorialError("Give the birthday as a date or as Roj and Mah.")
        return None
    if choice.birthday_years is None:
        raise MemorialError("Choose how many years the birthday should repeat for.")
    if choice.birthday_date is not None:
        if choice.birthday_roj is not None or choice.birthday_mah is not None:
            raise MemorialError("Give the birthday either as a date or as Roj and Mah, not both.")
        try:
            p = gregorian_to_parsi(choice.birthday_date, system)
        except (ValueError, OverflowError) as exc:
            raise MemorialError("That is not a day in this calendar.") from exc
        if p.mah == 13 or p.mah is None:
            raise MemorialError("That birthday falls on a Gatha day; give it as a different date.")
        return p.roj, p.mah
    roj, mah = choice.birthday_roj, choice.birthday_mah
    if roj is None or mah is None:
        raise MemorialError("Give both the Roj and the Mah of the birthday.")
    if not (1 <= mah <= 12 and 1 <= roj <= 30):
        raise MemorialError("A birthday is a Roj and a Mah (not a Gatha day).")
    return roj, mah


def named_days_passed(system: CalendarSystem, choice: Choice, today: date | None = None) -> dict[str, bool]:
    """Which of the days a family can pick on top of the repeating ones have
    already gone by, so the form can show them lighter and not let them be ticked.
    Keys: "5_to_9" (passed once the 9th is behind), and each named day by number.
    For a death more than a year ago, all of them. Today itself has not passed."""
    today = today or today_ist()
    keys = ["5_to_9"] + [str(n) for n in NAMED_DAYS]
    if choice.long_ago:
        return {k: True for k in keys}
    death = resolve_death(system, choice, today)
    roj, mah, year = parsi_slot_fields(gregorian_to_parsi(death, system))
    try:
        schedule = build_schedule(
            death_roj=roj, death_mah=mah, death_year=year, system=system,
            opening=OPENING_5_TO_9, day_counts=tuple(NAMED_DAYS),
        )
    except ValueError as exc:
        raise MemorialError(str(exc)) from exc
    when = {o.code: o.gregorian_date for o in schedule}
    out = {str(n): when[f"day_{n}"] < today for n in NAMED_DAYS if f"day_{n}" in when}
    out["5_to_9"] = when["day_9"] < today
    return out


def passed_before_start(system: CalendarSystem, choice: Choice) -> int:
    """How many dates of the whole schedule fall before ``start_from`` and so
    are not booked - for the review to say so. 0 when there is no start date."""
    if choice.start_from is None:
        return 0
    whole = Choice(**{**choice.__dict__, "start_from": None})
    try:
        schedule, _, _ = plan(system, whole)
    except MemorialError:
        return 0
    return sum(1 for o in schedule if o.gregorian_date < choice.start_from)


def plan(
    system: CalendarSystem, choice: Choice, today: date | None = None, *, check_name: bool = True,
) -> tuple[list[Observance], tuple[int, int, int], date]:
    """The schedule for a choice, without saving anything. Also returns the
    death as (roj, mah, year) in ``system`` and as a Gregorian date - what the
    preview shows the mobed, and what gets stored.

    ``today`` is the day the schedule is worked out as of: normally today, but
    for a re-work the day the memorial was first made, so a death given by Roj
    and Mah alone lands where it did then. ``check_name`` is off only when a
    saved memorial's own schedule is worked out again (its name was checked when
    it was saved, possibly under older rules)."""
    name = choice.departed_name.strip()
    if check_name:
        if not name:
            raise MemorialError("Please enter the departed person's name.")
        # The name is read out in each reminder, so it follows the rules for text
        # in a paid message (services/template_text.py).
        try:
            template_text.check(name, "departed person's name", max_len=template_text.DEPARTED_MAX)
        except ValueError as exc:
            raise MemorialError(str(exc)) from exc
    _validate_length(choice.monthly_months, "Monthly observances", MAX_MONTHLY_MONTHS)
    _validate_length(choice.yearly_years, "Yearly observances", MAX_YEARLY_YEARS)
    _validate_length(choice.fravardin_roj_months, "Roj Fravardin months", MAX_MONTHLY_MONTHS)
    _validate_length(choice.parab_years, "Parab years", MAX_PARAB_YEARS)
    _validate_length(choice.parab_count, "Parabs", MAX_PARAB_COUNT)
    has_length = choice.parab_years is not None or choice.parab_count is not None
    if choice.parabs is None and has_length:
        raise MemorialError("Choose which Parabs: all of them, or Fravardin and Tir only.")
    if choice.parabs is not None and not has_length:
        raise MemorialError("Choose how many Parabs to keep.")
    if choice.parab_years is not None and choice.parab_count is not None:
        raise MemorialError("Give the Parabs as years or as a number of Parabs, not both.")

    birthday = resolve_birthday(system, choice)
    _validate_length(choice.birthday_years, "Birthdays", MAX_BIRTHDAY_YEARS)

    if choice.long_ago:
        if choice.opening != OPENING_NONE or choice.day_counts:
            raise MemorialError(
                "The opening days and the named days (Dasmi, Masiso, Varsi...) have passed for someone who "
                "died more than a year ago. Choose what repeats instead.")
        # Everything runs from today: the monthly and yearly days still to come.
        choice = replace(choice, start_from=choice.start_from or today or today_ist())

    # A Gatha death is stored the way machis store one: Mah 13, with the
    # Gatha number in the Roj slot.
    death_date = resolve_death(system, choice, today)
    roj, mah, year = parsi_slot_fields(gregorian_to_parsi(death_date, system))

    try:
        schedule = build_schedule(
            death_roj=roj, death_mah=mah, death_year=year,
            system=system, opening=choice.opening,
            day_counts=tuple(choice.day_counts),
            monthly_months=choice.monthly_months or 0,
            yearly_years=choice.yearly_years or 0,
            parabs=choice.parabs, parab_years=choice.parab_years or 0,
            parab_count=choice.parab_count or 0,
            birthday=birthday, birthday_years=choice.birthday_years or 0,
            start_from=choice.start_from,
            fravardin_roj_months=choice.fravardin_roj_months or 0,
            plain_labels=choice.long_ago,
        )
    except ValueError as exc:
        raise MemorialError(str(exc)) from exc
    if not schedule:
        raise MemorialError(
            "Nothing is left to book from that date - everything chosen has already passed."
            if choice.start_from else "Choose at least one day, or something that repeats.")
    if len(schedule) > MAX_OBSERVANCES:
        raise MemorialError(
            f"That makes {len(schedule)} observances, more than the {MAX_OBSERVANCES} allowed. "
            "Shorten the series."
        )
    return schedule, (roj, mah, year), death_date


async def _validated_services(db: AsyncSession, agyary_id: int, service_ids: list[int]) -> list[Service]:
    wanted = list(dict.fromkeys(service_ids))  # order kept, duplicates gone
    if not wanted:
        raise MemorialError("Choose at least one prayer.")
    found = []
    for sid in wanted:
        service = await booking_service.get_service_by_id(db, agyary_id, sid)
        if service is None:
            raise MemorialError("One of those services isn't offered here.")
        found.append(service)
    return found


# The codes (see calendar.memorial) of the anniversaries: Masiso / Bamsi / Chamsi
# / Varsi, the monthly and the yearly series.
_ANNIVERSARY_DAYS = {"day_30", "day_60", "day_180", "day_360"}


def is_anniversary(code: str) -> bool:
    return code in _ANNIVERSARY_DAYS or code.startswith(("month_", "year_"))


def _is_jashan(service: Service) -> bool:
    return service.name.strip().lower() == "jashan"


async def create_memorial(
    db: AsyncSession,
    agyary: Agyary,
    user_id: int,
    customer: Customer,
    choice: Choice,
    service_ids: list[int],
    exclude_codes: tuple[str, ...] = (),
    service_overrides: dict[str, list[int]] | None = None,
    all_paid: bool = False,
) -> Memorial:
    """Save a memorial. Every observance starts with the same services - the
    set chosen here - and each can be changed on its own afterwards."""
    system = await calendar_for(db, user_id, choice)
    today = today_ist()
    schedule, (roj, mah, year), death_date = plan(system, choice, today)
    # Dates the mobed removed on the review screen: left out of what is saved,
    # and remembered, so that re-working the memorial later leaves them out too.
    removed = sorted(set(exclude_codes) & {o.code for o in schedule})
    if removed:
        schedule = [o for o in schedule if o.code not in set(removed)]
        if not schedule:
            raise MemorialError("Every observance was removed - keep at least one.")
    services = await _validated_services(db, agyary.id, service_ids)
    # Prayers the mobed set for single dates on the review screen.
    overrides: dict[str, list[Service]] = {}
    for code, ids in (service_overrides or {}).items():
        if code not in {o.code for o in schedule}:
            continue   # a date that was removed, or never existed
        if not ids:
            raise MemorialError("Every date needs at least one prayer.")
        overrides[code] = await _validated_services(db, agyary.id, ids)
    birthday = resolve_birthday(system, choice)

    memorial = Memorial(
        agyary_id=agyary.id,
        customer_id=customer.id,
        created_by_user_id=user_id,
        departed_name=choice.departed_name.strip(),
        death_gregorian=death_date,
        death_roj=roj, death_mah=mah, death_year=year,
        died_over_a_year_ago=choice.long_ago,
        calendar_system=system.value,
        opening=choice.opening,
        day_counts=sorted(set(choice.day_counts)),
        monthly_months=choice.monthly_months,
        yearly_years=choice.yearly_years,
        fravardin_roj_months=choice.fravardin_roj_months,
        parabs=choice.parabs,
        parab_years=choice.parab_years,
        parab_count=choice.parab_count,
        birthday_roj=birthday[0] if birthday else None,
        birthday_mah=birthday[1] if birthday else None,
        birthday_years=choice.birthday_years if birthday else None,
        # A death long ago runs from today (see plan); a late family from the
        # day they chose. Kept so a re-work books from the same day.
        start_from=choice.start_from or (today if choice.long_ago else None),
        removed_codes=removed,
    )
    memorial.observances = []
    for o in schedule:
        # Jashan is kept on the anniversaries only (monthly, yearly and their named
        # days); the mobed turns it on for any other day on its own page.
        chosen = overrides.get(o.code) or [s for s in services if not _is_jashan(s) or is_anniversary(o.code)]
        if not chosen:
            raise MemorialError(
                "Jashan is only put on the monthly and yearly days. Choose another prayer too, "
                "for the other days.")
        memorial.observances.append(MemorialObservance(
            paid_at=datetime.now(timezone.utc) if all_paid else None,
            moved_by_hand=False,
            code=o.code, label=o.label, day_number=o.day_number,
            gregorian_date=o.gregorian_date,
            parsi_roj=o.roj, parsi_mah=o.mah, parsi_year=o.year, gatha_index=o.gatha_index,
            services=[MemorialObservanceService(service_id=s.id) for s in chosen],
        ))
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
        "paid_count": sum(1 for o in memorial.observances if o.paid_at is not None),
    }


def _hhmm(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t else None


def serialize_observance(o: MemorialObservance, names: dict[int, str] | None = None) -> dict:
    return {
        "id": o.id,
        "paid": o.paid_at is not None,
        "memorial_id": o.memorial_id,
        "code": o.code,
        "label": o.label,
        "day_number": o.day_number,
        "date": o.gregorian_date.isoformat(),
        "roj": o.parsi_roj, "mah": o.parsi_mah, "year": o.parsi_year,
        "gatha_index": o.gatha_index,
        # The mobed put this date on another day themselves.
        "moved_by_hand": bool(o.moved_by_hand),
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
        # A death more than a year ago was given by Roj and Mah alone: the stored
        # date and year are stand-ins and are never handed out.
        "long_ago": memorial.died_over_a_year_ago,
        "death_date": None if memorial.died_over_a_year_ago else memorial.death_gregorian.isoformat(),
        "death": {"roj": memorial.death_roj, "mah": memorial.death_mah,
                  "year": None if memorial.died_over_a_year_ago else memorial.death_year},
        "calendar": memorial.calendar_system,
        "opening": memorial.opening,
        "day_counts": memorial.day_counts,
        "monthly_months": memorial.monthly_months,
        "yearly_years": memorial.yearly_years,
        "fravardin_roj_months": memorial.fravardin_roj_months,
        "parabs": memorial.parabs,
        "parab_years": memorial.parab_years,
        "parab_count": memorial.parab_count,
        "birthday": ({"roj": memorial.birthday_roj, "mah": memorial.birthday_mah,
                      "years": memorial.birthday_years} if memorial.birthday_roj else None),
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
    new_date: date | None = None,
    back_to_usual: bool = False,
) -> None:
    """Change one observance without touching the others. Services must stay
    non-empty - an observance with nothing to do is a mistake, not a state.

    ``new_date`` moves it to another day (marked as moved by hand, so a re-work
    of the whole memorial leaves it there); ``back_to_usual`` puts it back on
    the day its schedule gives it."""
    if back_to_usual:
        usual = usual_observance(memorial, observance.code)
        if usual is None:
            raise MemorialError(
                "This date is no longer part of the memorial's schedule, so it has no usual day to go back to.")
        _clash(memorial, observance, usual.gregorian_date)
        if _place(observance, usual.gregorian_date, CalendarSystem(memorial.calendar_system), by_hand=False):
            await _forget_reminders(db, [observance.id])
    elif new_date is not None and new_date != observance.gregorian_date:
        _clash(memorial, observance, new_date)
        _place(observance, new_date, CalendarSystem(memorial.calendar_system), by_hand=True)
        await _forget_reminders(db, [observance.id])
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


async def set_paid(
    db: AsyncSession, memorial: Memorial, paid: bool, observance_id: int | None = None
) -> int:
    """Tick (or untick) the paid mark on one date of a memorial, or on every date
    when ``observance_id`` is None. Returns how many dates changed."""
    now = datetime.now(timezone.utc)
    changed = 0
    for o in memorial.observances:
        if observance_id is not None and o.id != observance_id:
            continue
        if paid and o.paid_at is None:
            o.paid_at, changed = now, changed + 1
        elif not paid and o.paid_at is not None:
            o.paid_at, changed = None, changed + 1
    await db.flush()
    return changed


async def delete_memorial(db: AsyncSession, memorial: Memorial) -> None:
    await db.delete(memorial)
    await db.flush()


# ---------------------------------------------------------------------------
# Editing: one date moved or removed, or the whole memorial re-worked
# ---------------------------------------------------------------------------
# A re-work counts every date again from the death (past dates too - the
# owner's call, 17 Nov 2026) and then carries over what the mobed did to each
# date by its code: Masiso stays Masiso, with its prayers, time, note and paid
# tick, even when a corrected Roj puts it on another day. Dates the mobed took
# out stay out, and a date they moved by hand stays where they put it.

@dataclass(frozen=True)
class EditBasis:
    """What a re-work starts from besides the choices: where the schedule was
    booked from, and the codes of the dates the mobed took out."""

    start_from: date | None
    removed: frozenset[str]


def created_day(memorial: Memorial) -> date:
    """The day (in India) the memorial was made. A death given by Roj and Mah
    alone is placed relative to it, then and on every re-work."""
    made = memorial.created_at or datetime.now(timezone.utc)
    return made.astimezone(IST).date()


def stored_choice(memorial: Memorial, start_from: date | None) -> Choice:
    """The memorial's saved choices, to work its schedule out again exactly as
    it was saved (its death included, as stored)."""
    long_ago = memorial.died_over_a_year_ago
    return Choice(
        departed_name=memorial.departed_name,
        death_date=None if long_ago else memorial.death_gregorian,
        death_roj=memorial.death_roj if long_ago else None,
        death_mah=memorial.death_mah if long_ago else None,
        death_known=memorial.death_gregorian,
        long_ago=long_ago,
        calendar=memorial.calendar_system,
        opening=memorial.opening,
        day_counts=tuple(memorial.day_counts or ()),
        monthly_months=memorial.monthly_months,
        yearly_years=memorial.yearly_years,
        fravardin_roj_months=memorial.fravardin_roj_months,
        parabs=memorial.parabs,
        parab_years=memorial.parab_years,
        parab_count=memorial.parab_count,
        birthday_roj=memorial.birthday_roj,
        birthday_mah=memorial.birthday_mah,
        birthday_years=memorial.birthday_years,
        start_from=start_from,
    )


def _saved_schedule(memorial: Memorial, start_from: date | None) -> list[Observance]:
    try:
        schedule, _, _ = plan(
            CalendarSystem(memorial.calendar_system), stored_choice(memorial, start_from),
            created_day(memorial), check_name=False,
        )
    except MemorialError:
        return []
    return schedule


def edit_basis(memorial: Memorial) -> EditBasis:
    """Where the memorial's schedule was booked from, and which dates the mobed
    took out. Stored since memorials became editable; for one saved before that
    (``removed_codes`` NULL) it is worked out from its dates - nothing could
    take a single date out then except the review screen."""
    if memorial.removed_codes is not None:
        return EditBasis(memorial.start_from, frozenset(memorial.removed_codes))
    made = created_day(memorial)
    if memorial.died_over_a_year_ago:
        start = made   # it ran from the day it was made
    elif any(o.gregorian_date < made for o in memorial.observances):
        start = None   # dates before that day were booked: the whole schedule
    else:
        # Nothing before the day it was made is on file. Either the family came
        # late ("from today") or there was nothing before then anyway; booking
        # from that day gives the same schedule in the second case.
        whole = _saved_schedule(memorial, None)
        start = made if any(o.gregorian_date < made for o in whole) else None
    have = {o.code for o in memorial.observances}
    return EditBasis(start, frozenset({o.code for o in _saved_schedule(memorial, start)} - have))


def usual_observance(memorial: Memorial, code: str) -> Observance | None:
    """Where the memorial's own schedule puts the date with this code, or None
    when the schedule no longer has it."""
    basis = edit_basis(memorial)
    return next((o for o in _saved_schedule(memorial, basis.start_from) if o.code == code), None)


def usual_service_ids(memorial: Memorial) -> list[int]:
    """The prayers a date added by a re-work starts with: the set most of the
    memorial's ordinary dates have, plus whatever most of its monthly and yearly
    days have on top (Jashan, usually)."""
    def most_common(sets: list[frozenset[int]]) -> frozenset[int]:
        return max(sets, key=sets.count) if sets else frozenset()

    plain, anniv = [], []
    for o in memorial.observances:
        ids = frozenset(s.service_id for s in o.services)
        (anniv if is_anniversary(o.code) else plain).append(ids)
    base = most_common(plain) or most_common(anniv)
    extra = {sid for sid in frozenset().union(*anniv) if 2 * sum(sid in s for s in anniv) > len(anniv)} if anniv else set()
    return sorted(base | extra)


def edit_form(memorial: Memorial) -> dict:
    """The memorial's choices as the form shows them, to be changed."""
    basis = edit_basis(memorial)
    per_year = 2 if memorial.parabs == PARAB_FRAVARDIN_TIR else len(PARAB_ROJ_FOR_MAH)
    long_ago = memorial.died_over_a_year_ago
    return {
        "id": memorial.id,
        "customer_id": memorial.customer_id,
        "departed_name": memorial.departed_name,
        "long_ago": long_ago,
        "death_date": None if long_ago else memorial.death_gregorian.isoformat(),
        "death": {"roj": memorial.death_roj, "mah": memorial.death_mah},
        "calendar": memorial.calendar_system,
        "opening": memorial.opening,
        "day_counts": list(memorial.day_counts or []),
        "monthly_months": memorial.monthly_months,
        "yearly_years": memorial.yearly_years,
        "fravardin_roj_months": memorial.fravardin_roj_months,
        "parabs": memorial.parabs,
        # The form asks for a number of Parabs. N years of them is the same
        # dates as N years' worth of Parabs, so older memorials read the same.
        "parab_count": memorial.parab_count or (memorial.parab_years * per_year if memorial.parab_years else None),
        "birthday": ({"roj": memorial.birthday_roj, "mah": memorial.birthday_mah,
                      "years": memorial.birthday_years} if memorial.birthday_roj else None),
        "start_from": basis.start_from.isoformat() if basis.start_from else None,
        "service_ids": usual_service_ids(memorial),
        "removed_count": len(basis.removed),
    }


def _parsi_fields(when: date, system: CalendarSystem) -> tuple[int | None, int | None, int, int | None]:
    try:
        p = gregorian_to_parsi(when, system)
    except (ValueError, OverflowError) as exc:
        raise MemorialError("That is not a day in this calendar.") from exc
    return p.roj, p.mah, p.year, p.gatha_index


def _place(row: MemorialObservance, when: date, system: CalendarSystem, *, by_hand: bool) -> bool:
    """Put one date on ``when``, read in the memorial's calendar. True when the
    day changed - the family has then not been reminded of the new one."""
    row.parsi_roj, row.parsi_mah, row.parsi_year, row.gatha_index = _parsi_fields(when, system)
    row.moved_by_hand = by_hand
    changed = when != row.gregorian_date
    row.gregorian_date = when
    if changed:
        row.reminded_by_hand_at = None
    return changed


def _clash(memorial: Memorial, row: MemorialObservance, when: date) -> None:
    """One date per day: moving onto a day the memorial already has is refused."""
    other = next((o for o in memorial.observances if o.id != row.id and o.gregorian_date == when), None)
    if other is not None:
        raise MemorialError(
            f"{other.label} is already on that day. Choose another day, or remove one of the two.")


async def _forget_reminders(db: AsyncSession, observance_ids: list[int]) -> None:
    """These dates moved, so any reminder about them was about the old day:
    unhook it, so the new day is reminded afresh and one still waiting for the
    old day is not sent (reminder_sender._withdrawn)."""
    if not observance_ids:
        return
    await db.execute(
        update(Notification)
        .where(
            Notification.notification_type == "memorial_reminder",
            Notification.memorial_observance_id.in_(observance_ids),
        )
        .values(memorial_observance_id=None)
    )


async def remove_observance(db: AsyncSession, memorial: Memorial, observance: MemorialObservance) -> None:
    """Take one date out of a memorial, for good: a later re-work does not
    bring it back (it can be put back from the Edit screen)."""
    if len(memorial.observances) <= 1:
        raise MemorialError("This is the memorial's only date. To take it off, delete the memorial instead.")
    basis = edit_basis(memorial)   # before the date goes: an older memorial is read from its dates
    memorial.start_from = basis.start_from
    memorial.removed_codes = sorted(basis.removed | {observance.code})
    memorial.observances.remove(observance)
    await db.flush()


@dataclass
class Replan:
    """A memorial's schedule worked out again from changed choices, set against
    what is saved. Nothing is written."""

    system: CalendarSystem
    death: tuple[int, int, int]
    death_date: date
    start_from: date | None
    # In date order; the row is None for a date the re-work adds.
    kept: list[tuple[Observance, MemorialObservance | None]]
    # In the schedule, but taken out by the mobed (they can be put back).
    left_out: list[Observance]
    # Saved dates that will go: no longer in the schedule, or taken out now.
    dropped: list[MemorialObservance]


async def replan(
    db: AsyncSession, user_id: int, memorial: Memorial, choice: Choice, removed: set[str],
) -> Replan:
    system = await calendar_for(db, user_id, choice)
    made = created_day(memorial)
    basis = edit_basis(memorial)
    # A death long ago runs from the day the memorial was made, as it did then;
    # otherwise the form says (the whole schedule, or from the day it gives).
    start = (basis.start_from or made) if choice.long_ago else choice.start_from
    # A death long ago given by the same Roj and Mah keeps its stand-in date, or
    # the monthly and yearly days would be counted from a year later.
    same_death = (
        choice.long_ago and memorial.died_over_a_year_ago and system.value == memorial.calendar_system
        and (choice.death_roj, choice.death_mah) == (memorial.death_roj, memorial.death_mah)
    )
    choice = replace(choice, start_from=start, death_known=memorial.death_gregorian if same_death else None)
    schedule, death, death_date = plan(system, choice, made)

    rows = {o.code: o for o in memorial.observances}
    kept: list[tuple[Observance, MemorialObservance | None]] = []
    left_out: list[Observance] = []
    dropped: list[MemorialObservance] = []
    for o in schedule:
        row = rows.get(o.code)
        if o.code in removed:
            left_out.append(o)
            if row is not None:
                dropped.append(row)
        else:
            kept.append((o, row))
    planned = {o.code for o in schedule}
    dropped += [row for code, row in rows.items() if code not in planned]
    # A date moved by hand stays on its own day.
    kept.sort(key=lambda pair: (pair[1].gregorian_date if pair[1] is not None and pair[1].moved_by_hand
                                else pair[0].gregorian_date, pair[0].day_number))
    return Replan(system, death, death_date, start, kept, left_out, dropped)


def _parsi_dict(when: date, system: CalendarSystem) -> dict:
    roj, mah, year, gatha = _parsi_fields(when, system)
    return {"roj": roj, "mah": mah, "year": year, "gatha_index": gatha}


async def preview_edit(db: AsyncSession, user_id: int, memorial: Memorial, choice: Choice) -> dict:
    """What re-working the memorial with these choices would do, date by date:
    which stay, which move (and from where), which are new, which go."""
    basis = edit_basis(memorial)
    rp = await replan(db, user_id, memorial, choice, set(basis.removed))
    observances = []
    for o, row in rp.kept:
        item = {
            "code": o.code, "label": o.label, "day_number": o.day_number,
            "anniversary": is_anniversary(o.code),
            "date": o.gregorian_date.isoformat(),
            "roj": o.roj, "mah": o.mah, "year": o.year, "gatha_index": o.gatha_index,
            "status": "new", "old_date": None, "observance_id": None, "service_ids": None,
            "paid": False, "time": None, "notes": None, "moved_by_hand": False,
        }
        if row is not None:
            item.update({
                "observance_id": row.id,
                "service_ids": sorted(s.service_id for s in row.services),
                "paid": row.paid_at is not None, "time": _hhmm(row.time_of_day), "notes": row.notes,
                "moved_by_hand": bool(row.moved_by_hand),
            })
            if row.moved_by_hand:
                item.update({"status": "moved_by_hand", "date": row.gregorian_date.isoformat(),
                             **_parsi_dict(row.gregorian_date, rp.system)})
            elif row.gregorian_date != o.gregorian_date:
                item.update({"status": "moved", "old_date": row.gregorian_date.isoformat()})
            else:
                item["status"] = "same"
        observances.append(item)
    roj, mah, year = rp.death
    return {
        "calendar": rp.system.value,
        "long_ago": choice.long_ago,
        "death": {"roj": roj, "mah": mah, "year": None if choice.long_ago else year},
        "death_date": None if choice.long_ago else rp.death_date.isoformat(),
        "start_from": rp.start_from.isoformat() if rp.start_from else None,
        "count": len(observances),
        "observances": observances,
        "dropped": [
            {"code": r.code, "label": r.label, "date": r.gregorian_date.isoformat(),
             "roj": r.parsi_roj, "mah": r.parsi_mah, "gatha_index": r.gatha_index,
             "paid": r.paid_at is not None, "notes": r.notes, "moved_by_hand": bool(r.moved_by_hand)}
            for r in sorted(rp.dropped, key=lambda r: r.gregorian_date)
        ],
        "left_out": [
            {"code": o.code, "label": o.label, "date": o.gregorian_date.isoformat(),
             "roj": o.roj, "mah": o.mah, "year": o.year, "gatha_index": o.gatha_index,
             "anniversary": is_anniversary(o.code)}
            for o in rp.left_out
        ],
    }


async def edit_memorial(
    db: AsyncSession,
    user_id: int,
    memorial: Memorial,
    choice: Choice,
    service_ids: list[int],
    exclude_codes: tuple[str, ...] = (),
    restore_codes: tuple[str, ...] = (),
    service_overrides: dict[str, list[int]] | None = None,
) -> None:
    """Re-work a memorial with changed choices. Every date is counted again from
    the death; a date that is still there keeps its prayers, time, note and
    paid tick (and its day, if the mobed moved it by hand); new dates get
    ``service_ids`` (Jashan on the monthly and yearly days only, as when made);
    dates no longer chosen go. ``exclude_codes`` are taken out now and
    ``restore_codes`` - dates taken out earlier - put back."""
    basis = edit_basis(memorial)
    removed = (set(basis.removed) - set(restore_codes)) | set(exclude_codes)
    rp = await replan(db, user_id, memorial, choice, removed)
    if not rp.kept:
        raise MemorialError("Every date was taken out - keep at least one.")
    services = await _validated_services(db, memorial.agyary_id, service_ids)
    kept_codes = {o.code for o, _ in rp.kept}
    overrides: dict[str, list[Service]] = {}
    for code, ids in (service_overrides or {}).items():
        if code not in kept_codes:
            continue
        if not ids:
            raise MemorialError("Every date needs at least one prayer.")
        overrides[code] = await _validated_services(db, memorial.agyary_id, ids)
    birthday = resolve_birthday(rp.system, choice)

    moved: list[int] = []
    for o, row in rp.kept:
        if row is None:
            chosen = overrides.get(o.code) or [s for s in services if not _is_jashan(s) or is_anniversary(o.code)]
            if not chosen:
                raise MemorialError(
                    "Jashan is only put on the monthly and yearly days. Choose another prayer too, "
                    "for the other days.")
            memorial.observances.append(MemorialObservance(
                code=o.code, label=o.label, day_number=o.day_number, moved_by_hand=False,
                gregorian_date=o.gregorian_date,
                parsi_roj=o.roj, parsi_mah=o.mah, parsi_year=o.year, gatha_index=o.gatha_index,
                services=[MemorialObservanceService(service_id=s.id) for s in chosen],
            ))
            continue
        row.label, row.day_number = o.label, o.day_number
        if row.moved_by_hand:
            _place(row, row.gregorian_date, rp.system, by_hand=True)   # re-read in the calendar
        elif _place(row, o.gregorian_date, rp.system, by_hand=False):
            moved.append(row.id)
        if o.code in overrides:
            row.services = [MemorialObservanceService(service_id=s.id) for s in overrides[o.code]]
    for row in rp.dropped:
        memorial.observances.remove(row)
    await _forget_reminders(db, moved)

    roj, mah, year = rp.death
    memorial.departed_name = choice.departed_name.strip()
    memorial.death_gregorian = rp.death_date
    memorial.death_roj, memorial.death_mah, memorial.death_year = roj, mah, year
    memorial.died_over_a_year_ago = choice.long_ago
    memorial.calendar_system = rp.system.value
    memorial.opening = choice.opening
    memorial.day_counts = sorted(set(choice.day_counts))
    memorial.monthly_months = choice.monthly_months
    memorial.yearly_years = choice.yearly_years
    memorial.fravardin_roj_months = choice.fravardin_roj_months
    memorial.parabs = choice.parabs
    memorial.parab_years = choice.parab_years
    memorial.parab_count = choice.parab_count
    memorial.birthday_roj = birthday[0] if birthday else None
    memorial.birthday_mah = birthday[1] if birthday else None
    memorial.birthday_years = choice.birthday_years if birthday else None
    memorial.start_from = rp.start_from
    memorial.removed_codes = sorted(removed)
    await db.flush()


# ---------------------------------------------------------------------------
# The calendar
# ---------------------------------------------------------------------------
CLOSING_TEXT = (
    "Last prayer for {departed}. After today there are no more prayers for this memorial."
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


async def mark_reminded(
    db: AsyncSession, user_id: int, agyary_id: int, observance_id: int, reminded: bool,
    now: datetime | None = None,
) -> MemorialObservance | None:
    """Record (or take back) that the mobed told the family about this
    observance themselves. Only on the mobed's own memorials; None otherwise."""
    obs = (
        await db.execute(
            select(MemorialObservance)
            .join(Memorial, Memorial.id == MemorialObservance.memorial_id)
            .where(
                MemorialObservance.id == observance_id,
                Memorial.created_by_user_id == user_id,
                Memorial.agyary_id == agyary_id,
            )
        )
    ).scalar_one_or_none()
    if obs is None:
        return None
    obs.reminded_by_hand_at = (now or datetime.now(timezone.utc)) if reminded else None
    await db.flush()
    return obs


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
            select(MemorialObservance, Memorial, Customer)
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
    # Whether each would go on its own is the planner's own rule (RM-2): sending
    # live, not paused, this account's switch on (D4), consent, no STOP, allowlist.
    settings = get_settings()
    paused = await guardrails.paused_reason(db) is not None
    me = await db.get(User, user_id)
    account_on = bool(me and me.automatic_reminders)
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
    for obs, memorial, customer in rows:
        behdin_name, behdin_phone = customer.name, customer.phone
        days_away = (obs.gregorian_date - today).days
        serialized = serialize_observance(obs, names)
        text = reminder_message.manual_text(reminder_message.build_parts(
            agyary_name, obs, memorial.departed_name,
            [s["name"] for s in serialized["services"]], today,
            family=behdin_name, mobed=me.name if me is not None else "",
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
            # Will it go on its own, and if it has been tried, how that went.
            "auto": obs.reminded_by_hand_at is None and reminders.goes_automatically(
                settings, paused=paused, account_on=account_on, customer=customer, owner_user_id=user_id,
            ),
            "sent_status": sent.get(obs.id),
            # The mobed told the family themselves.
            "reminded_by_hand_at": obs.reminded_by_hand_at.isoformat() if obs.reminded_by_hand_at else None,
        })
    return items
