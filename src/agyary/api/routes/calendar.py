from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from agyary.calendar import (
    CalendarSystem,
    ParsiDate,
    gregorian_to_parsi,
    nearest_occurrence,
    parsi_to_gregorian,
)

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

# A month grid view needs at most 6 weeks (42 days); this is a guard against
# abuse, not a real product constraint.
_MAX_RANGE_DAYS = 62


def _serialize(parsi_date: ParsiDate) -> dict:
    return {
        "calendar": parsi_date.calendar.value,
        "year": parsi_date.year,
        "gregorian_date": parsi_date.gregorian_date.isoformat(),
        "is_gatha": parsi_date.is_gatha,
        "mah": parsi_date.mah,
        "mah_name": parsi_date.mah_name,
        "roj": parsi_date.roj,
        "roj_name": parsi_date.roj_name,
        "gatha_index": parsi_date.gatha_index,
        "gatha_name": parsi_date.gatha_name,
        "display": str(parsi_date),
    }


@router.get("/today")
def today(system: CalendarSystem = Query(default=CalendarSystem.SHENSHAI)) -> dict:
    return _serialize(gregorian_to_parsi(date.today(), system))


@router.get("/convert")
def convert(
    date_: date = Query(alias="date"),
    system: CalendarSystem = Query(default=CalendarSystem.SHENSHAI),
) -> dict:
    try:
        return _serialize(gregorian_to_parsi(date_, system))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/range")
def range_(
    start: date = Query(),
    end: date = Query(),
    system: CalendarSystem = Query(default=CalendarSystem.SHENSHAI),
) -> list[dict]:
    """Parsi date for every Gregorian day in [start, end] inclusive, in one
    call - the month-grid calendar view needs ~42 days' worth of Roj/Mah and
    doing that as 42 separate /convert round trips would be slow and chatty
    on a mobile connection."""
    if end < start:
        raise HTTPException(status_code=400, detail="end must not be before start")
    if (end - start).days + 1 > _MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"Range too large (max {_MAX_RANGE_DAYS} days)")
    days = []
    current = start
    while current <= end:
        days.append(_serialize(gregorian_to_parsi(current, system)))
        current += timedelta(days=1)
    return days


@router.get("/parsi-month")
def parsi_month(
    mah: int = Query(ge=1, le=13),
    year: int = Query(),
    system: CalendarSystem = Query(default=CalendarSystem.SHENSHAI),
) -> list[dict]:
    """Every day of one Parsi month - Roj 1..30 for mah 1-12, or the Gatha
    days for mah=13 (5 days normally, 6 in a Fasli leap cycle) - each with
    its Gregorian equivalent, in one call. The Parsi-native month grid needs
    this in one batch rather than 30 separate /from-parsi round trips."""
    days = []
    if mah == 13:
        for gatha_index in range(1, 7):
            try:
                gregorian = parsi_to_gregorian(year, system, gatha_index=gatha_index)
            except ValueError:
                break
            days.append(_serialize(gregorian_to_parsi(gregorian, system)))
    else:
        for roj in range(1, 31):
            try:
                gregorian = parsi_to_gregorian(year, system, mah=mah, roj=roj)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            days.append(_serialize(gregorian_to_parsi(gregorian, system)))
    return days


@router.get("/from-parsi")
def from_parsi(
    roj: int = Query(ge=1, le=30),
    mah: int = Query(ge=1, le=13),
    year: int | None = Query(default=None),
    system: CalendarSystem = Query(default=CalendarSystem.SHENSHAI),
) -> dict:
    """Roj/Mah (+ optional Year) -> Gregorian.

    With ``year``, this is a plain conversion. Without it, the server
    resolves the soonest occurrence on or after today, because a Roj/Mah
    pair on its own repeats every year and doesn't name a date.

    **Clients must never compute the YZ year themselves.** It is not
    ``Gregorian year - 630``: Shenshai and Kadmi Navroze falls in
    mid-August and drifts a day every four years, so that subtraction is
    wrong for every day between January 1st and Navroze. Any UI that keeps
    a Date field and a Roj/Mah field in sync belongs on this endpoint in
    both directions - call it with no ``year`` and use what comes back.

    (The current PWA gets exactly this wrong in two places, both to be
    fixed in the frontend pass: mobed.html:991 seeds the jump panel's year
    input from `getUTCFullYear() - 630`, and mobed.html:1523 uses the same
    expression as the year actually SAVED onto a machi when no prefill is
    available - which mis-files the ceremony by a whole Parsi year for any
    machi entered between January and Navroze.)

    ``mah=13`` addresses the Gatha days, where ``roj`` is the Gatha index
    (1-5, or 1-6 inside a Fasli leap cycle).
    """
    is_gatha = mah == 13
    if is_gatha and roj > 6:
        raise HTTPException(status_code=400, detail="Gatha index must be between 1 and 6")
    kwargs = {"gatha_index": roj} if is_gatha else {"mah": mah, "roj": roj}

    try:
        if year is None:
            gregorian = nearest_occurrence(system, **kwargs)
        else:
            gregorian = parsi_to_gregorian(year, system, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize(gregorian_to_parsi(gregorian, system))
