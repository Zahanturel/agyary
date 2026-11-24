"""What a person keeps for themselves in the behdin app (R4.1, 25 Nov 2026).

Which agyari is "mine", the memorials of the person's own departed and their
own events, and the calendar that holds them. Private to the one account (D2,
D6): every read and write here takes the user's id and filters on it, and
nothing else in the system imports ``models/person_own.py``.

The schedule of a memorial is the mobed side's engine, called as it is
(``services.memorials.plan``): nothing here counts a day itself.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agyary.calendar import CalendarSystem, gregorian_to_parsi, parsi_to_gregorian
from agyary.core.config import Settings
from agyary.messaging.availability import parsi_slot_fields
from agyary.models import Agyary, PersonAgyari, PersonEvent, PersonMemorial, PersonMemorialObservance
from agyary.models.enums import EVENT_KINDS, EVENT_REPEATS
from agyary.services import funeral_requests, memorials, mobed_dashboard, panthaky
from agyary.services.funeral_records import NAME_NOT_KNOWN

IST = ZoneInfo("Asia/Kolkata")

NEARBY_LIMIT = 50
MAX_MEMORIALS = 100
MAX_EVENTS = 500
MAX_CALENDAR_DAYS = 400
TITLE_MAX, NOTES_MAX = 120, 500
EARLIEST_EVENT_YEAR = 1850
LATEST_EVENT_YEARS_AHEAD = 100


class PersonError(Exception):
    """A rejected choice; the message is plain words, safe to show the person."""


# ---------------------------------------------------------------------------
# Agyaries to choose from
# ---------------------------------------------------------------------------
async def nearby(
    db: AsyncSession, settings: Settings, *, lat: float | None, lng: float | None, q: str | None
) -> list[dict]:
    """Active agyaries, Atash Behrams first and then nearest first (by name when
    the person gave no position). ``lat`` and ``lng`` are used here, to sort and
    to measure, and never stored or logged. Nothing private is returned: no
    phone, no names of mobeds."""
    q = (q or "").strip()
    if q:
        rows = await mobed_dashboard.search_agyaries(db, q, limit=500)
    else:
        rows = list((await db.execute(select(Agyary).where(Agyary.is_active.is_(True)))).scalars())
    located = lat is not None and lng is not None

    def distance(a: Agyary) -> float | None:
        if not located or a.latitude is None or a.longitude is None:
            return None
        return funeral_requests.km(lat, lng, a.latitude, a.longitude)

    measured = [(a, distance(a)) for a in rows]
    measured.sort(key=lambda pair: (
        pair[0].kind != "atash_behram",
        pair[1] is None,
        pair[1] if pair[1] is not None else 0.0,
        pair[0].name.lower(),
        pair[0].id,
    ))
    chosen = measured[:NEARBY_LIMIT]
    reach = await panthaky.reach_of(db, settings, [a.id for a, _d in chosen])
    return [
        {
            "id": a.id, "name": a.name, "city": a.city, "kind": a.kind,
            "distance_km": None if d is None else round(d, 1),
            "answers_in_app": reach.get(a.id) == panthaky.REACH_PANTHAKY,
        }
        for a, d in chosen
    ]


async def my_agyari(db: AsyncSession, settings: Settings, user_id: int) -> dict | None:
    row = await db.get(PersonAgyari, user_id)
    if row is None:
        return None
    agyary = await db.get(Agyary, row.agyary_id)
    if agyary is None:
        return None
    reach = await panthaky.reach_of(db, settings, [agyary.id])
    return {
        "id": agyary.id, "name": agyary.name, "city": agyary.city, "kind": agyary.kind,
        "answers_in_app": reach.get(agyary.id) == panthaky.REACH_PANTHAKY,
        "chosen_at": row.chosen_at.isoformat() if row.chosen_at else None,
        "closed": not agyary.is_active,
    }


async def choose_agyari(db: AsyncSession, user_id: int, agyary_id: int) -> None:
    agyary = await db.get(Agyary, agyary_id)
    if agyary is None or not agyary.is_active:
        raise PersonError("That fire temple could not be found.")
    row = await db.get(PersonAgyari, user_id)
    if row is None:
        db.add(PersonAgyari(user_id=user_id, agyary_id=agyary_id))
    else:
        row.agyary_id = agyary_id
        row.chosen_at = func.now()
    await db.flush()


async def forget_agyari(db: AsyncSession, user_id: int) -> None:
    row = await db.get(PersonAgyari, user_id)
    if row is not None:
        await db.delete(row)
        await db.flush()


# ---------------------------------------------------------------------------
# Dates: the Parsi reading of a day
# ---------------------------------------------------------------------------
def today_ist() -> date:
    return datetime.now(IST).date()


def parsi_of(when: date, system: CalendarSystem) -> dict | None:
    """The day in the Parsi calendar, as the calendar screens give it (names and all)."""
    from agyary.api.routes.calendar import _serialize   # the one place the shape is written

    try:
        return _serialize(gregorian_to_parsi(when, system))
    except (ValueError, OverflowError):
        return None


def _roj_mah(parsi: dict | None) -> tuple[int | None, int | None]:
    if parsi is None:
        return None, None
    if parsi["is_gatha"]:
        return parsi["gatha_index"], 13
    return parsi["roj"], parsi["mah"]


# ---------------------------------------------------------------------------
# Memorials
# ---------------------------------------------------------------------------
def _clean_choice(choice: memorials.Choice) -> tuple[memorials.Choice, bool]:
    """A missing name reads "(name not known)", as on the Doongerwadi side (D12); a name
    given follows the rules for a name in a message. Returns the choice and whether
    the name still has to be checked."""
    name = (choice.departed_name or "").strip()
    if not name:
        return replace(choice, departed_name=NAME_NOT_KNOWN), False
    return replace(choice, departed_name=name), True


async def _count(db: AsyncSession, model, user_id: int) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(model.user_id == user_id))).scalar_one()


def _fill(row: PersonMemorial, choice: memorials.Choice, system: CalendarSystem, death: tuple[int, int, int],
          death_date: date, birthday: tuple[int, int] | None, start_from: date | None) -> None:
    roj, mah, year = death
    row.departed_name = choice.departed_name
    row.death_gregorian, row.death_roj, row.death_mah, row.death_year = death_date, roj, mah, year
    row.died_over_a_year_ago = choice.long_ago
    row.calendar_system = system.value
    row.opening = choice.opening
    row.day_counts = sorted(set(choice.day_counts))
    row.monthly_months = choice.monthly_months
    row.yearly_years = choice.yearly_years
    row.fravardin_roj_months = choice.fravardin_roj_months
    row.parabs = choice.parabs
    row.parab_years = choice.parab_years
    row.parab_count = choice.parab_count
    row.birthday_roj = birthday[0] if birthday else None
    row.birthday_mah = birthday[1] if birthday else None
    row.birthday_years = choice.birthday_years if birthday else None
    row.start_from = start_from


def _observances(user_id: int, schedule) -> list[PersonMemorialObservance]:
    return [
        PersonMemorialObservance(
            user_id=user_id, code=o.code, label=o.label, day_number=o.day_number,
            gregorian_date=o.gregorian_date, parsi_roj=o.roj, parsi_mah=o.mah, parsi_year=o.year,
            gatha_index=o.gatha_index,
        )
        for o in schedule
    ]


async def create_memorial(db: AsyncSession, user_id: int, choice: memorials.Choice) -> PersonMemorial:
    """Work out the schedule with the engine and save it, for this person alone."""
    if await _count(db, PersonMemorial, user_id) >= MAX_MEMORIALS:
        raise PersonError(f"You can keep up to {MAX_MEMORIALS} memorials. Please delete one first.")
    choice, check_name = _clean_choice(choice)
    try:
        system = await memorials.calendar_for(db, user_id, choice)
        today = today_ist()
        schedule, death, death_date = memorials.plan(system, choice, today, check_name=check_name)
        birthday = memorials.resolve_birthday(system, choice)
    except memorials.MemorialError as exc:
        raise PersonError(str(exc)) from exc
    row = PersonMemorial(user_id=user_id)
    _fill(row, choice, system, death, death_date, birthday, choice.start_from or (today if choice.long_ago else None))
    row.observances = _observances(user_id, schedule)
    db.add(row)
    await db.flush()
    return row


async def rework_memorial(db: AsyncSession, row: PersonMemorial, choice: memorials.Choice) -> PersonMemorial:
    """Count the whole memorial again from the new choices (nothing on a person's
    own memorial is set by hand, so nothing needs carrying over)."""
    choice, check_name = _clean_choice(choice)
    made_on = row.created_at.astimezone(IST).date() if row.created_at else today_ist()
    if choice.long_ago and choice.start_from is None:
        choice = replace(choice, start_from=row.start_from)
    try:
        system = await memorials.calendar_for(db, row.user_id, choice)
        schedule, death, death_date = memorials.plan(system, choice, made_on, check_name=check_name)
        birthday = memorials.resolve_birthday(system, choice)
    except memorials.MemorialError as exc:
        raise PersonError(str(exc)) from exc
    _fill(row, choice, system, death, death_date, birthday, choice.start_from or (made_on if choice.long_ago else None))
    row.observances.clear()
    await db.flush()
    row.observances.extend(_observances(row.user_id, schedule))
    await db.flush()
    return row


def _with_dates():
    return selectinload(PersonMemorial.observances)


async def get_memorial(db: AsyncSession, user_id: int, memorial_id: int) -> PersonMemorial | None:
    """Only the person's own: someone else's id is simply not found."""
    return (await db.execute(
        select(PersonMemorial).options(_with_dates()).where(
            PersonMemorial.id == memorial_id, PersonMemorial.user_id == user_id)
    )).scalar_one_or_none()


async def list_memorials(db: AsyncSession, user_id: int) -> list[PersonMemorial]:
    return list((await db.execute(
        select(PersonMemorial).options(_with_dates()).where(PersonMemorial.user_id == user_id)
        .order_by(PersonMemorial.id)
    )).scalars())


def _observance(o: PersonMemorialObservance, system: CalendarSystem) -> dict:
    parsi = parsi_of(o.gregorian_date, system)
    return {
        "id": o.id, "code": o.code, "label": o.label, "day_number": o.day_number,
        "date": o.gregorian_date.isoformat(), "parsi_roj": o.gatha_index if o.parsi_mah == 13 else o.parsi_roj,
        "parsi_mah": o.parsi_mah, "parsi_year": o.parsi_year, "parsi": parsi,
    }


def _system_of(row: PersonMemorial) -> CalendarSystem:
    return CalendarSystem(row.calendar_system)


def memorial_choices(row: PersonMemorial) -> dict:
    """The choices as they were made, for the form to show again."""
    return {
        "opening": row.opening, "day_counts": list(row.day_counts or []),
        "monthly": {"count": row.monthly_months} if row.monthly_months else None,
        "yearly": {"count": row.yearly_years} if row.yearly_years else None,
        "fravardin_roj": {"count": row.fravardin_roj_months} if row.fravardin_roj_months else None,
        "parabs": {"which": row.parabs, "years": row.parab_years, "count": row.parab_count} if row.parabs else None,
        "birthday": ({"roj": row.birthday_roj, "mah": row.birthday_mah, "years": row.birthday_years}
                     if row.birthday_roj else None),
        "calendar": row.calendar_system, "long_ago": row.died_over_a_year_ago,
        "start_from": row.start_from.isoformat() if row.start_from else None,
    }


def serialize_memorial(row: PersonMemorial, *, detailed: bool, today: date | None = None) -> dict:
    today = today or today_ist()
    system = _system_of(row)
    dates = list(row.observances)
    ahead = [o for o in dates if o.gregorian_date >= today]
    nxt = ahead[0] if ahead else None
    out = {
        "id": row.id,
        "departed_name": row.departed_name,
        "name_known": row.departed_name != NAME_NOT_KNOWN,
        "calendar": row.calendar_system,
        "long_ago": row.died_over_a_year_ago,
        # A death given by Roj and Mah alone has no date or year to show (as on the other side).
        "death_date": None if row.died_over_a_year_ago else row.death_gregorian.isoformat(),
        "death_roj": row.death_roj, "death_mah": row.death_mah,
        "death_year": None if row.died_over_a_year_ago else row.death_year,
        "count": len(dates), "remaining": len(ahead), "running": bool(ahead),
        "next": _observance(nxt, system) if nxt else None,
    }
    if detailed:
        out["observances"] = [_observance(o, system) for o in dates]
        out["choices"] = memorial_choices(row)
    return out


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def _check_text(value: str | None, what: str, limit: int, *, required: bool) -> str | None:
    text = (value or "").strip()
    if not text:
        if required:
            raise PersonError(f"Please enter {what}.")
        return None
    if len(text) > limit:
        raise PersonError(f"Please keep {what} to {limit} letters or fewer.")
    return text


def _check_date(when: date) -> None:
    if not (EARLIEST_EVENT_YEAR <= when.year <= today_ist().year + LATEST_EVENT_YEARS_AHEAD):
        raise PersonError("Please check the year of that date.")


async def _parsi_day(db: AsyncSession, user_id: int, when: date) -> tuple[int, int, str]:
    """The day's Roj and Mah in the calendar the person reads in (Mah 13 is a Gatha day,
    the Gatha number in the Roj)."""
    system = await mobed_dashboard.reading_system(db, user_id)
    try:
        roj, mah, _year = parsi_slot_fields(gregorian_to_parsi(when, system))
    except (ValueError, OverflowError) as exc:
        raise PersonError("That is not a day in the Parsi calendar.") from exc
    return roj, mah, system.value


async def save_event(
    db: AsyncSession, user_id: int, row: PersonEvent | None, *, title: str, kind: str, when: date,
    repeats: str, notes: str | None,
) -> PersonEvent:
    title_ok = _check_text(title, "a title", TITLE_MAX, required=True)
    notes_ok = _check_text(notes, "the note", NOTES_MAX, required=False)
    if kind not in EVENT_KINDS:
        raise PersonError("Please choose birthday, navjote, anniversary or other.")
    if repeats not in EVENT_REPEATS:
        raise PersonError("Please choose how it repeats.")
    _check_date(when)
    parsi = await _parsi_day(db, user_id, when) if repeats == "yearly_parsi" else (None, None, None)
    if row is None:
        if await _count(db, PersonEvent, user_id) >= MAX_EVENTS:
            raise PersonError(f"You can keep up to {MAX_EVENTS} events. Please delete one first.")
        row = PersonEvent(user_id=user_id)
        db.add(row)
    row.title, row.kind, row.gregorian_date, row.repeats, row.notes = title_ok, kind, when, repeats, notes_ok
    row.parsi_roj, row.parsi_mah, row.parsi_calendar = parsi
    await db.flush()
    return row


async def get_event(db: AsyncSession, user_id: int, event_id: int) -> PersonEvent | None:
    return (await db.execute(
        select(PersonEvent).where(PersonEvent.id == event_id, PersonEvent.user_id == user_id)
    )).scalar_one_or_none()


async def list_events(db: AsyncSession, user_id: int) -> list[PersonEvent]:
    return list((await db.execute(
        select(PersonEvent).where(PersonEvent.user_id == user_id).order_by(PersonEvent.gregorian_date, PersonEvent.id)
    )).scalars())


def serialize_event(row: PersonEvent, system: CalendarSystem) -> dict:
    parsi = parsi_of(row.gregorian_date, system)
    return {
        "id": row.id, "title": row.title, "kind": row.kind, "date": row.gregorian_date.isoformat(),
        "repeats": row.repeats, "notes": row.notes,
        "parsi_roj": row.parsi_roj if row.repeats == "yearly_parsi" else _roj_mah(parsi)[0],
        "parsi_mah": row.parsi_mah if row.repeats == "yearly_parsi" else _roj_mah(parsi)[1],
        "parsi": parsi,
    }


def event_dates(row: PersonEvent, start: date, end: date) -> list[date]:
    """The days in [start, end] this event falls on: its own day, and for a yearly one
    each time it comes round (never before its first day). A 29 Feb is kept on 28 Feb
    in a year without one."""
    first = row.gregorian_date
    out: list[date] = []
    if row.repeats == "none":
        out = [first]
    elif row.repeats == "yearly_english":
        for year in range(max(start.year, first.year), end.year + 1):
            try:
                out.append(date(year, first.month, first.day))
            except ValueError:
                out.append(date(year, 2, 28))
    elif row.repeats == "yearly_parsi":
        system = CalendarSystem(row.parsi_calendar)
        try:
            lo, hi = gregorian_to_parsi(start, system).year, gregorian_to_parsi(end, system).year
        except (ValueError, OverflowError):
            return []
        for year in range(lo - 1, hi + 2):
            try:
                if row.parsi_mah == 13:
                    out.append(parsi_to_gregorian(year, system, gatha_index=row.parsi_roj))
                else:
                    out.append(parsi_to_gregorian(year, system, mah=row.parsi_mah, roj=row.parsi_roj))
            except (ValueError, OverflowError):
                continue   # that Gatha day does not exist that year
    return sorted(d for d in out if start <= d <= end and d >= first)


# ---------------------------------------------------------------------------
# The calendar: the person's own things in a range of days
# ---------------------------------------------------------------------------
async def calendar(db: AsyncSession, user_id: int, start: date, end: date) -> list[dict]:
    if end < start:
        raise PersonError("The end date is before the start date.")
    if (end - start).days + 1 > MAX_CALENDAR_DAYS:
        raise PersonError(f"Please choose a shorter time, up to {MAX_CALENDAR_DAYS} days.")
    system = await mobed_dashboard.reading_system(db, user_id)
    items: list[dict] = []
    rows = (await db.execute(
        select(PersonMemorialObservance, PersonMemorial.departed_name, PersonMemorial.calendar_system)
        .join(PersonMemorial, PersonMemorial.id == PersonMemorialObservance.memorial_id)
        .where(PersonMemorialObservance.user_id == user_id,
               PersonMemorialObservance.gregorian_date.between(start, end))
    )).all()
    for o, name, calendar_system in rows:
        parsi = parsi_of(o.gregorian_date, CalendarSystem(calendar_system))
        roj, mah = _roj_mah(parsi)
        items.append({
            "kind": "memorial", "source": "memorial", "id": o.id, "memorial_id": o.memorial_id,
            "title": f"{o.label} - {name}", "label": o.label, "date": o.gregorian_date.isoformat(),
            "parsi_roj": roj, "parsi_mah": mah, "parsi": parsi,
        })
    for e in await list_events(db, user_id):
        for when in event_dates(e, start, end):
            own = CalendarSystem(e.parsi_calendar) if e.repeats == "yearly_parsi" else system
            parsi = parsi_of(when, own)
            roj, mah = _roj_mah(parsi)
            items.append({
                "kind": e.kind, "source": "event", "id": e.id, "title": e.title, "date": when.isoformat(),
                "repeats": e.repeats, "parsi_roj": roj, "parsi_mah": mah, "parsi": parsi,
            })
    items.sort(key=lambda i: (i["date"], i["source"] != "memorial", i["title"].lower(), i["id"]))
    return items

