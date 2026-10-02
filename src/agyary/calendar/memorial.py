"""Memorial schedule: the observances that follow a death.

Pure functions, no DB - like the rest of this package.

Two ways of counting, settled with the mobed. In both, the day of death is
day 1.

LITERAL days - the opening (days 1-10, and the 10th on its own). Day N is
simply the Nth calendar day from the death, Gatha days included. A death on
Roj Aneran, the day before the Gathas, has its 10th day a few Rojs into the
next year, after the Gathas have each used up a day.

ROJ-AND-MAH days - everything else (29th and 30th, 59th and 60th, ..., the
monthly and yearly observances, the Parabs). These depend only on Roj and
Mah, so the five Gatha days are NOT counted and each is a plain walk around
a 360-day cycle (12 Mah x 30 Roj), identical in all three calendar systems.
The system only decides which Gregorian date a given Roj and Mah lands on.

So, for a death on Roj R of Mah M, counting by Roj and Mah:

    day 1    = R, M                     (the day of death)
    day 30   = the Roj before R, next Mah
    day 31   = R, next Mah              (the monthly observance)
    day 360  = the Roj before R, M, next year   (Varsi)
    day 361  = R, M, next year          (the yearly observance)

A death during the Gatha days (Mah 13) has no Roj and Mah to count from, so
it is refused rather than guessed at. It has special rules the mobed has yet
to confirm - see docs/memorial-plan.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from agyary.calendar.engine import (
    DAYS_PER_MONTH,
    MAH_NAMES,
    MONTHS_PER_YEAR,
    ROJ_NAMES,
    CalendarSystem,
    gregorian_to_parsi,
    parsi_to_gregorian,
)

CYCLE_DAYS = DAYS_PER_MONTH * MONTHS_PER_YEAR  # 360

# Which opening the family chose: every day from the 1st to the 10th, or the
# 10th alone. Days 1-4 are not a separate option - they are part of "all".
OPENING_ALL = "days_1_to_10"
OPENING_TENTH = "tenth_only"
OPENINGS = (OPENING_ALL, OPENING_TENTH)

# The named day-count observances, in the mobed's own words. The labels are
# provisional spellings and live ONLY here, so settling one is a one-line
# change. The 29/59/179/359 ones are the day before the 30/60/180/360.
NAMED_DAYS: dict[int, str] = {
    10: "Dasmi",
    29: "Deci",
    30: "Masiso",
    59: "Deci",
    60: "Bamsi",
    179: "Deci",
    180: "Chamsi",
    359: "Deci",
    360: "Varsi",
}
DAY_COUNT_CHOICES = tuple(NAMED_DAYS)  # what the picker offers, in order

# A Parab is the day whose Roj shares its name with the Mah. Fravardin and
# Tir are the two special ones, which some families book on their own.
# Keyed by Mah number -> Roj number.
#
# Dae (Mah 10) is deliberately absent: no Roj is called plain "Dae"
# (Dae-Pa-Adar, Dae-Pa-Meher and Dae-Pa-Din are different days), and which
# Roj is its Parab is not settled. See docs/memorial-plan.md.
PARAB_ROJ_FOR_MAH: dict[int, int] = {
    mah: ROJ_NAMES.index(name) + 1
    for mah, name in enumerate(MAH_NAMES, start=1)
    if name in ROJ_NAMES
}
PARAB_ALL = "all"
PARAB_FRAVARDIN_TIR = "fravardin_tir"
PARABS = (PARAB_ALL, PARAB_FRAVARDIN_TIR)
_FRAVARDIN_TIR_MAHS = (1, 4)


@dataclass(frozen=True)
class Observance:
    """One dated observance. ``code`` is stable and is what gets stored;
    ``label`` is for display only.

    A literal day can fall in the Gatha days, in which case ``roj`` and
    ``mah`` are None and ``gatha_index`` says which one."""

    code: str
    label: str
    day_number: int
    roj: int | None
    mah: int | None
    year: int
    gregorian_date: date
    gatha_index: int | None = None


def _ordinal(mah: int, roj: int) -> int:
    return (mah - 1) * DAYS_PER_MONTH + (roj - 1)


def count_from(
    death_roj: int, death_mah: int, death_year: int, day_number: int
) -> tuple[int, int, int]:
    """(roj, mah, year) of day ``day_number`` counted by Roj and Mah, where
    day 1 is the death day and Gatha days are skipped."""
    if day_number < 1:
        raise ValueError(f"day_number must be 1 or more, got {day_number}")
    if not 1 <= death_mah <= MONTHS_PER_YEAR:
        raise ValueError("A death during the Gatha days cannot be counted from")
    if not 1 <= death_roj <= DAYS_PER_MONTH:
        raise ValueError(f"roj must be between 1 and {DAYS_PER_MONTH}, got {death_roj}")
    steps = _ordinal(death_mah, death_roj) + (day_number - 1)
    year = death_year + steps // CYCLE_DAYS
    within = steps % CYCLE_DAYS
    return within % DAYS_PER_MONTH + 1, within // DAYS_PER_MONTH + 1, year


def _by_roj_and_mah(
    code: str, label: str, day_number: int,
    death: tuple[int, int, int], system: CalendarSystem,
) -> Observance:
    roj, mah, year = count_from(*death, day_number)
    return Observance(
        code=code, label=label, day_number=day_number, roj=roj, mah=mah, year=year,
        gregorian_date=parsi_to_gregorian(year, system, mah=mah, roj=roj),
    )


def _literal(
    code: str, label: str, day_number: int, death_date: date, system: CalendarSystem,
) -> Observance:
    when = death_date + timedelta(days=day_number - 1)
    p = gregorian_to_parsi(when, system)
    return Observance(
        code=code, label=label, day_number=day_number, roj=p.roj, mah=p.mah,
        year=p.year, gregorian_date=when, gatha_index=p.gatha_index,
    )


def _parab_observances(
    death: tuple[int, int, int], system: CalendarSystem, which: str, years: int,
) -> list[Observance]:
    """Every Parab strictly after the death, through the ``years``-th
    anniversary. Counted by Roj and Mah, like the monthly ones."""
    death_roj, death_mah, death_year = death
    start = _ordinal(death_mah, death_roj)
    mahs = _FRAVARDIN_TIR_MAHS if which == PARAB_FRAVARDIN_TIR else tuple(PARAB_ROJ_FOR_MAH)
    out = []
    for year_offset in range(years + 1):
        for mah in mahs:
            roj = PARAB_ROJ_FOR_MAH[mah]
            day_number = _ordinal(mah, roj) - start + CYCLE_DAYS * year_offset + 1
            if day_number <= 1 or day_number > CYCLE_DAYS * years + 1:
                continue
            year = death_year + year_offset
            out.append(Observance(
                code=f"parab_{mah}_{year}", label=f"{MAH_NAMES[mah - 1]} Parab",
                day_number=day_number, roj=roj, mah=mah, year=year,
                gregorian_date=parsi_to_gregorian(year, system, mah=mah, roj=roj),
            ))
    return out


def build_schedule(
    *,
    death_roj: int,
    death_mah: int,
    death_year: int,
    system: CalendarSystem,
    opening: str,
    day_counts: tuple[int, ...] = (),
    monthly_months: int = 0,
    yearly_years: int = 0,
    parabs: str | None = None,
    parab_years: int = 0,
) -> list[Observance]:
    """Every observance the family chose, soonest first. Dates already past
    are included: this is a diary, and a family arriving late still wants
    the whole picture.

    ``opening`` is OPENING_ALL (days 1-10) or OPENING_TENTH. ``day_counts``
    picks from DAY_COUNT_CHOICES; the 10th is already covered by the opening
    and is never listed twice. ``monthly_months`` is how many monthly
    observances follow the death (day 31, 61, ...), and ``yearly_years`` how
    many yearly ones (day 361, 721, ...); 0 means none.

    There is no "forever" here, so a schedule is always finite and can always
    be shown whole. There are no default end points either: choosing a
    repeating series without saying how long is for the caller to refuse
    (``parabs`` without ``parab_years`` is refused here), not for this to
    fill in.

    ``parabs`` is PARAB_ALL or PARAB_FRAVARDIN_TIR, for ``parab_years`` years
    after the death. A Parab that lands on the same day as another
    observance stays its own entry.
    """
    if opening not in OPENINGS:
        raise ValueError(f"opening must be one of {OPENINGS}, got {opening!r}")
    unknown = [d for d in day_counts if d not in NAMED_DAYS]
    if unknown:
        raise ValueError(f"Not an observance day: {unknown}")
    if monthly_months < 0 or yearly_years < 0 or parab_years < 0:
        raise ValueError("Counts cannot be negative")
    if parabs is not None and parabs not in PARABS:
        raise ValueError(f"parabs must be one of {PARABS}, got {parabs!r}")
    if parabs is not None and parab_years < 1:
        raise ValueError("Say how many years the Parabs should run for")

    death = (death_roj, death_mah, death_year)
    # Validates the death date as a side effect (Gatha deaths are refused).
    count_from(*death, 1)
    death_date = parsi_to_gregorian(death_year, system, mah=death_mah, roj=death_roj)

    wanted: dict[int, tuple[str, str]] = {}  # day_number -> (code, label)
    if opening == OPENING_ALL:
        for n in range(1, 11):
            wanted[n] = (f"day_{n}", f"Day {n}")
    for n in day_counts:
        wanted.setdefault(n, (f"day_{n}", NAMED_DAYS[n]))
    # The 10th is always the mobed's own word for it, however it was reached.
    wanted[10] = ("day_10", NAMED_DAYS[10])

    for k in range(1, monthly_months + 1):
        wanted.setdefault(1 + DAYS_PER_MONTH * k, (f"month_{k}", f"Month {k}"))
    for k in range(1, yearly_years + 1):
        # Month 12 and Year 1 are the same day (361); the family knows it
        # as the year.
        wanted[1 + CYCLE_DAYS * k] = (f"year_{k}", f"Year {k}")

    # The opening is counted in literal days; everything else by Roj and Mah.
    # With "tenth only" the 10th is still the literal 10th day.
    found = [
        _literal(code, label, n, death_date, system) if n <= 10
        else _by_roj_and_mah(code, label, n, death, system)
        for n, (code, label) in sorted(wanted.items())
    ]
    if parabs is not None:
        found += _parab_observances(death, system, parabs, parab_years)
    return sorted(found, key=lambda o: (o.gregorian_date, o.day_number))
