"""Parsi (Zoroastrian) calendar engine.

Pure functions converting between the Gregorian calendar and the three Parsi
calendar systems in use today: Shenshai, Kadmi and Fasli.

Structure shared by all three systems: 12 months ("Mah") of 30 days ("Roj")
each, plus 5 (or, for Fasli in a Gregorian leap year, 6) intercalary Gatha
days at the end of the year.

Shenshai and Kadmi never apply a leap-year correction, so they drift against
the Gregorian calendar by roughly one day every four years. Kadmi is, by
definition, exactly 30 days ("one month") ahead of Shenshai: whatever
Shenshai will be in 30 days, Kadmi is today. That relationship is used
directly in this implementation rather than tracked via a second epoch.

Fasli is a solar-corrected calendar whose Navroze (new year) is pinned to
March 21st every Gregorian year; the extra Gatha day in leap years is what
keeps that pin in place.

Year numbers are expressed in the Yazdegerdi (YZ) era, using the common
approximation ``YZ = <Gregorian year of that cycle's Navroze> - 630``. This
is a display convention, not an astronomically precise epoch, and does not
affect Roj/Mah/Gatha calculations.
"""

from __future__ import annotations

import calendar as _pycalendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

ROJ_NAMES: tuple[str, ...] = (
    "Hormazd", "Bahman", "Ardibehesht", "Shahrevar", "Aspandard", "Khordad",
    "Amardad", "Daepadar", "Adar", "Avan", "Khorshed", "Mohor", "Tir", "Gosh",
    "Dae-Pa-Meher", "Meher", "Sarosh", "Rashne", "Fravardin", "Behram", "Ram",
    "Govad", "Dae-Pa-Din", "Din", "Ashishvangh", "Ashtad", "Asman", "Zamyad",
    "Mareshpand", "Aneran",
)

MAH_NAMES: tuple[str, ...] = (
    "Fravardin", "Ardibehesht", "Khordad", "Tir", "Amardad", "Shahrevar",
    "Meher", "Avan", "Adar", "Dae", "Bahman", "Aspandard",
)

GATHA_NAMES: tuple[str, ...] = (
    "Ahunavad", "Ushtavad", "Spentamad", "Vohukhshathra", "Vahishtoisht",
)

DAYS_PER_MONTH = 30
MONTHS_PER_YEAR = 12
DAYS_BEFORE_GATHA = DAYS_PER_MONTH * MONTHS_PER_YEAR  # 360
BASE_GATHA_COUNT = 5
YEAR_LENGTH = DAYS_BEFORE_GATHA + BASE_GATHA_COUNT  # 365

YZ_ERA_OFFSET = 630

KADMI_SHENSHAI_OFFSET_DAYS = 30

# How many years ahead nearest_occurrence() looks. Five covers a full Fasli
# leap cycle, which is the only case needing more than one (see that
# function's docstring).
_OCCURRENCE_SCAN_YEARS = 5


class CalendarSystem(str, Enum):
    SHENSHAI = "shenshai"
    KADMI = "kadmi"
    FASLI = "fasli"


@dataclass(frozen=True)
class ParsiDate:
    calendar: CalendarSystem
    year: int  # Yazdegerdi era year
    gregorian_date: date
    is_gatha: bool
    mah: int | None = None
    mah_name: str | None = None
    roj: int | None = None
    roj_name: str | None = None
    gatha_index: int | None = None
    gatha_name: str | None = None

    def __str__(self) -> str:
        if self.is_gatha:
            return f"{self.gatha_name} (Gatha {self.gatha_index}), Y{self.year} [{self.calendar.value}]"
        return f"Roj {self.roj} {self.roj_name}, Mah {self.mah} {self.mah_name}, Y{self.year} [{self.calendar.value}]"


# ---------------------------------------------------------------------------
# Verified anchor point: 2026-07-19 Gregorian = Roj 9 (Adar), Mah 12
# (Aspandard) in Shenshai. That is day-of-year 339 of the Shenshai year whose
# Navroze fell on 2025-08-15.
# ---------------------------------------------------------------------------
_SHENSHAI_ANCHOR_NAVROZE = date(2025, 8, 15)
_SHENSHAI_ANCHOR_YZ_YEAR = 2025 - YZ_ERA_OFFSET


def _day_of_year_from_mah_roj(mah: int, roj: int) -> int:
    if not 1 <= mah <= MONTHS_PER_YEAR:
        raise ValueError(f"mah must be between 1 and {MONTHS_PER_YEAR}, got {mah}")
    if not 1 <= roj <= DAYS_PER_MONTH:
        raise ValueError(f"roj must be between 1 and {DAYS_PER_MONTH}, got {roj}")
    return (mah - 1) * DAYS_PER_MONTH + roj


def _day_of_year_from_gatha(gatha_index: int, max_gatha: int) -> int:
    if not 1 <= gatha_index <= max_gatha:
        raise ValueError(f"gatha_index must be between 1 and {max_gatha}, got {gatha_index}")
    return DAYS_BEFORE_GATHA + gatha_index


def _decompose_day_of_year(
    day_of_year: int, max_gatha: int
) -> tuple[int | None, int | None, int | None]:
    total_days = DAYS_BEFORE_GATHA + max_gatha
    if not 1 <= day_of_year <= total_days:
        raise ValueError(f"day_of_year must be between 1 and {total_days}, got {day_of_year}")
    if day_of_year <= DAYS_BEFORE_GATHA:
        mah = (day_of_year - 1) // DAYS_PER_MONTH + 1
        roj = (day_of_year - 1) % DAYS_PER_MONTH + 1
        return mah, roj, None
    return None, None, day_of_year - DAYS_BEFORE_GATHA


def _build_parsi_date(
    system: CalendarSystem,
    yz_year: int,
    day_of_year: int,
    gregorian_date: date,
    max_gatha: int = BASE_GATHA_COUNT,
) -> ParsiDate:
    mah, roj, gatha_index = _decompose_day_of_year(day_of_year, max_gatha)
    if gatha_index is not None:
        # The 6th Fasli leap-year Gatha has no name among the traditional
        # five; it's an intercalary day inserted purely to keep Navroze
        # pinned to March 21st.
        gatha_name = GATHA_NAMES[gatha_index - 1] if gatha_index <= len(GATHA_NAMES) else None
        return ParsiDate(
            calendar=system,
            year=yz_year,
            gregorian_date=gregorian_date,
            is_gatha=True,
            gatha_index=gatha_index,
            gatha_name=gatha_name,
        )
    return ParsiDate(
        calendar=system,
        year=yz_year,
        gregorian_date=gregorian_date,
        is_gatha=False,
        mah=mah,
        mah_name=MAH_NAMES[mah - 1],
        roj=roj,
        roj_name=ROJ_NAMES[roj - 1],
    )


# ---------------------------------------------------------------------------
# Shenshai — the reference calendar; Kadmi and (partially) Fasli build on it.
# ---------------------------------------------------------------------------
def _shenshai_from_gregorian(g_date: date) -> ParsiDate:
    delta = g_date.toordinal() - _SHENSHAI_ANCHOR_NAVROZE.toordinal()
    year_offset = delta // YEAR_LENGTH
    day_of_year = delta % YEAR_LENGTH + 1
    yz_year = _SHENSHAI_ANCHOR_YZ_YEAR + year_offset
    return _build_parsi_date(CalendarSystem.SHENSHAI, yz_year, day_of_year, g_date)


def _shenshai_to_gregorian(yz_year: int, day_of_year: int) -> date:
    if not 1 <= day_of_year <= YEAR_LENGTH:
        raise ValueError(f"day_of_year must be between 1 and {YEAR_LENGTH}, got {day_of_year}")
    year_offset = yz_year - _SHENSHAI_ANCHOR_YZ_YEAR
    delta = year_offset * YEAR_LENGTH + (day_of_year - 1)
    return date.fromordinal(_SHENSHAI_ANCHOR_NAVROZE.toordinal() + delta)


# ---------------------------------------------------------------------------
# Kadmi — always exactly 30 days ahead of Shenshai.
# ---------------------------------------------------------------------------
def _kadmi_from_gregorian(g_date: date) -> ParsiDate:
    shifted = g_date + timedelta(days=KADMI_SHENSHAI_OFFSET_DAYS)
    shenshai_equivalent = _shenshai_from_gregorian(shifted)
    return ParsiDate(
        calendar=CalendarSystem.KADMI,
        year=shenshai_equivalent.year,
        gregorian_date=g_date,
        is_gatha=shenshai_equivalent.is_gatha,
        mah=shenshai_equivalent.mah,
        mah_name=shenshai_equivalent.mah_name,
        roj=shenshai_equivalent.roj,
        roj_name=shenshai_equivalent.roj_name,
        gatha_index=shenshai_equivalent.gatha_index,
        gatha_name=shenshai_equivalent.gatha_name,
    )


def _kadmi_to_gregorian(yz_year: int, day_of_year: int) -> date:
    shenshai_equivalent_date = _shenshai_to_gregorian(yz_year, day_of_year)
    return shenshai_equivalent_date - timedelta(days=KADMI_SHENSHAI_OFFSET_DAYS)


# ---------------------------------------------------------------------------
# Fasli — Navroze fixed at March 21; a 6th Gatha day appears whenever the
# February that falls inside the current cycle belongs to a Gregorian leap
# year, which is exactly what keeps Navroze pinned to March 21 every year.
# ---------------------------------------------------------------------------
def _fasli_cycle_start_year(g_date: date) -> int:
    if (g_date.month, g_date.day) >= (3, 21):
        return g_date.year
    return g_date.year - 1


def _fasli_max_gatha(cycle_start_year: int) -> int:
    return 6 if _pycalendar.isleap(cycle_start_year + 1) else 5


def _fasli_from_gregorian(g_date: date) -> ParsiDate:
    cycle_start_year = _fasli_cycle_start_year(g_date)
    cycle_start = date(cycle_start_year, 3, 21)
    day_of_year = (g_date - cycle_start).days + 1
    max_gatha = _fasli_max_gatha(cycle_start_year)
    yz_year = cycle_start_year - YZ_ERA_OFFSET
    return _build_parsi_date(CalendarSystem.FASLI, yz_year, day_of_year, g_date, max_gatha=max_gatha)


def _fasli_to_gregorian(yz_year: int, day_of_year: int) -> date:
    cycle_start_year = yz_year + YZ_ERA_OFFSET
    max_gatha = _fasli_max_gatha(cycle_start_year)
    total_days = DAYS_BEFORE_GATHA + max_gatha
    if not 1 <= day_of_year <= total_days:
        raise ValueError(f"day_of_year must be between 1 and {total_days}, got {day_of_year}")
    cycle_start = date(cycle_start_year, 3, 21)
    return cycle_start + timedelta(days=day_of_year - 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def gregorian_to_parsi(g_date: date, system: CalendarSystem) -> ParsiDate:
    """Convert a Gregorian date to its Parsi date in the given calendar system."""
    if system == CalendarSystem.SHENSHAI:
        return _shenshai_from_gregorian(g_date)
    if system == CalendarSystem.KADMI:
        return _kadmi_from_gregorian(g_date)
    if system == CalendarSystem.FASLI:
        return _fasli_from_gregorian(g_date)
    raise ValueError(f"Unknown calendar system: {system}")


def parsi_to_gregorian(
    year: int,
    system: CalendarSystem,
    mah: int | None = None,
    roj: int | None = None,
    gatha_index: int | None = None,
) -> date:
    """Convert a Parsi date (YZ year + either Mah/Roj or a Gatha index) to Gregorian.

    Exactly one of ``(mah, roj)`` or ``gatha_index`` must be provided.
    """
    is_gatha_request = gatha_index is not None
    is_mah_roj_request = mah is not None and roj is not None
    if is_gatha_request == is_mah_roj_request:
        raise ValueError("Provide exactly one of (mah, roj) or gatha_index")

    if system == CalendarSystem.FASLI:
        cycle_start_year = year + YZ_ERA_OFFSET
        max_gatha = _fasli_max_gatha(cycle_start_year)
    else:
        max_gatha = BASE_GATHA_COUNT

    if is_gatha_request:
        day_of_year = _day_of_year_from_gatha(gatha_index, max_gatha)
    else:
        day_of_year = _day_of_year_from_mah_roj(mah, roj)

    if system == CalendarSystem.SHENSHAI:
        return _shenshai_to_gregorian(year, day_of_year)
    if system == CalendarSystem.KADMI:
        return _kadmi_to_gregorian(year, day_of_year)
    if system == CalendarSystem.FASLI:
        return _fasli_to_gregorian(year, day_of_year)
    raise ValueError(f"Unknown calendar system: {system}")


def nearest_occurrence(
    system: CalendarSystem,
    mah: int | None = None,
    roj: int | None = None,
    gatha_index: int | None = None,
    on_or_after: date | None = None,
) -> date:
    """The soonest Gregorian date matching a Roj/Mah (or Gatha day), no year given.

    A Roj/Mah pair names a day within *some* year and repeats annually, so
    on its own it does not identify a date. This resolves that the way a
    person naturally would: the next time that day comes round, counting
    today itself as "next".

    The year cannot be guessed as ``gregorian_year - 630``. Shenshai and
    Kadmi Navroze falls in mid-August and drifts a day every four years, so
    that subtraction is wrong for the whole stretch between January 1st and
    Navroze. The current year is therefore *derived* by converting the
    reference date, then the neighbours on either side are evaluated and the
    soonest non-past one wins - the same candidate-scan shape as
    ``get_navroze`` below, and for the same reason.

    Gatha days are addressed by ``gatha_index``, not by mah/roj. Fasli grows
    a sixth Gatha in leap cycles, so a year that has no such day simply
    fails to produce a candidate rather than being assumed away.

    The scan runs a few years out rather than just to the next one. For an
    ordinary Roj/Mah that is free - the following year always answers, and
    the nearer candidate wins anyway - but Fasli's sixth Gatha comes round
    every four years, not annually, so a one-year window would declare a
    perfectly real day nonexistent for three years out of four.
    """
    reference = on_or_after or date.today()
    current_year = gregorian_to_parsi(reference, system).year

    candidates = []
    for year in range(current_year - 1, current_year + _OCCURRENCE_SCAN_YEARS + 1):
        try:
            candidate = parsi_to_gregorian(
                year, system, mah=mah, roj=roj, gatha_index=gatha_index
            )
        except ValueError:
            continue  # e.g. the 6th Gatha in a non-leap Fasli cycle
        if candidate >= reference:
            candidates.append(candidate)

    if not candidates:
        raise ValueError(
            f"No occurrence of that date found on or after {reference.isoformat()} "
            f"in the {system.value} calendar"
        )
    return min(candidates)


def get_navroze(gregorian_year: int, system: CalendarSystem) -> date:
    """The Gregorian date of Navroze (Parsi new year) that falls within ``gregorian_year``."""
    if system == CalendarSystem.FASLI:
        return date(gregorian_year, 3, 21)

    to_gregorian = _shenshai_to_gregorian if system == CalendarSystem.SHENSHAI else _kadmi_to_gregorian
    estimate_yz_year = gregorian_year - YZ_ERA_OFFSET
    for offset in range(-3, 4):
        candidate_yz_year = estimate_yz_year + offset
        candidate_date = to_gregorian(candidate_yz_year, 1)
        if candidate_date.year == gregorian_year:
            return candidate_date
    raise ValueError(f"Could not determine {system.value} Navroze for {gregorian_year}")
