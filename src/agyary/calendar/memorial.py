"""Memorial schedule: the observances that follow a death.

Pure functions, no DB - like the rest of this package.

Two ways of counting, settled with the mobed. In both, the day of death is
day 1.

LITERAL days - the opening (days 1-10, and the 10th on its own). Day N is
simply the Nth calendar day from the death, Gatha days included. A death on
Roj Aneran, the day before the Gathas, has its 10th day a few Rojs into the
next year, after the Gathas have each used up a day.

ROJ-AND-MAH days - everything else. These depend only on Roj and Mah, so the
five Gatha days are NOT counted and each is a plain walk around a 360-day
cycle (12 Mah x 30 Roj), identical in all three calendar systems. The system
only decides which Gregorian date a given Roj and Mah lands on.

The named days are month multiples, which is what their names mean: Masiso
is the monthly (the 30th day), Bamsi is two months (60th), Chamsi six months
(180th) and Varsi a year (360th). Each lands on the SAME Roj, that many Mahs
on. The Deci is the day before: the 29th before Masiso, and so on.

So, for a death on Roj R of Mah M, with the day of death as day 1:

    day 1    = R, M                     (the day of death)
    day 30   = the Roj before R, next Mah      (the Deci before Masiso)
    day 31   = R, next Mah              (Masiso, and the first monthly)
    day 361  = R, M, next year          (Varsi, and the first yearly)

A death on a Gatha day (Mah 13, with the Gatha number in the Roj slot, as
machis store it) has no Roj and Mah of its own. That Gatha day is day 1 and
the literal opening carries on from it. After that, as the mobed has it:

    monthly  = Roj Hormazd (the first Roj) of each Mah, from Mah 2 of the
               next year - so Masiso is Mah 2 Roj 1, a month or so on, and
               Bamsi Mah 3 Roj 1, ...
    yearly   = the same Gatha day, each year - so Varsi is that Gatha day
               a year on

The Deci is always the actual day before the day it precedes.
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
# No opening at all: the family picks the Dasmi (10th day) like any other
# named day. The two above are kept so memorials saved earlier still read.
OPENING_NONE = "none"
OPENINGS = (OPENING_ALL, OPENING_TENTH, OPENING_NONE)

# The named observances, in the mobed's own words, keyed by the family's name
# for the day ("the 30th"). 10 is the Dasmi, a literal day. 30/60/180/360 are
# Masiso, Bamsi, Chamsi and Varsi - one, two, six and twelve months on, on the
# same Roj - and 29/59/179/359 are the Deci, the day before each. The labels
# are spellings and live ONLY here, so changing one is a one-line change.
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
# Mah 10 is Dae-Pa-Adar, and so is Roj 8, so every Mah has its Parab by name.
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


GATHA_MAH = 13  # how machis (and memorials) store a Gatha day: Roj slot = its number


def _start(death_roj: int, death_mah: int, death_year: int) -> tuple[int, int]:
    """Where counting by Roj and Mah starts: (position in the 360-day cycle,
    the Parsi year that cycle belongs to). A Gatha death sits at -1 of the
    NEXT year - the slot just before Mah 1, Roj 1."""
    if death_mah == GATHA_MAH:
        if not 1 <= death_roj <= 6:
            raise ValueError(f"A Gatha day is 1 to 6, got {death_roj}")
        return -1, death_year + 1
    if not 1 <= death_mah <= MONTHS_PER_YEAR:
        raise ValueError(f"mah must be between 1 and {GATHA_MAH}, got {death_mah}")
    if not 1 <= death_roj <= DAYS_PER_MONTH:
        raise ValueError(f"roj must be between 1 and {DAYS_PER_MONTH}, got {death_roj}")
    return _ordinal(death_mah, death_roj), death_year


def count_from(
    death_roj: int, death_mah: int, death_year: int, day_number: int
) -> tuple[int, int, int]:
    """(roj, mah, year) of day ``day_number`` counted by Roj and Mah, where
    day 1 is the death day and Gatha days are skipped. For a death on a Gatha
    day, day 1 is that Gatha day itself, which has no Roj and Mah to return."""
    if day_number < 1:
        raise ValueError(f"day_number must be 1 or more, got {day_number}")
    start, base_year = _start(death_roj, death_mah, death_year)
    if death_mah == GATHA_MAH and day_number == 1:
        raise ValueError("Day 1 is the Gatha day itself")
    steps = start + (day_number - 1)
    year = base_year + steps // CYCLE_DAYS
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
    """Every Parab from day 2 through the ``years``-th anniversary (day
    360 * years + 1), so each Parab comes round once a year for ``years``
    years. Counted by Roj and Mah, like the monthly ones. The death day itself
    is not a Parab observance."""
    start, base_year = _start(*death)
    mahs = _FRAVARDIN_TIR_MAHS if which == PARAB_FRAVARDIN_TIR else tuple(PARAB_ROJ_FOR_MAH)
    out = []
    for year_offset in range(years + 1):
        for mah in mahs:
            roj = PARAB_ROJ_FOR_MAH[mah]
            day_number = _ordinal(mah, roj) - start + CYCLE_DAYS * year_offset + 1
            if not 2 <= day_number <= CYCLE_DAYS * years + 1:
                continue
            year = base_year + year_offset
            out.append(Observance(
                code=f"parab_{mah}_{year}", label=f"{MAH_NAMES[mah - 1]} Parab",
                day_number=day_number, roj=roj, mah=mah, year=year,
                gregorian_date=parsi_to_gregorian(year, system, mah=mah, roj=roj),
            ))
    return out


def _fravardin_roj_observances(
    death: tuple[int, int, int], death_date: date, system: CalendarSystem,
    months: int, not_before: date | None = None, extra_years: int = 0,
) -> list[Observance]:
    """Roj Fravardin of each Mah after the death, ``months`` of them (from
    ``not_before`` on, when given). The day of death itself is not repeated."""
    start, base_year = _start(*death)
    out: list[Observance] = []
    for year in range(death[2], death[2] + months // MONTHS_PER_YEAR + 3 + extra_years):
        for mah in range(1, MONTHS_PER_YEAR + 1):
            try:
                when = parsi_to_gregorian(year, system, mah=mah, roj=FRAVARDIN_ROJ)
            except ValueError:
                continue
            if when <= death_date or (not_before and when < not_before):
                continue
            out.append(Observance(
                code=f"fravroj_{year}_{mah}", label="Roj Fravardin",
                day_number=_position(FRAVARDIN_ROJ, mah, year, start, base_year),
                roj=FRAVARDIN_ROJ, mah=mah, year=year, gregorian_date=when,
            ))
            if len(out) == months:
                return out
    return out


def _birthday_observances(
    death: tuple[int, int, int], death_date: date, system: CalendarSystem,
    birthday: tuple[int, int], years: int,
    not_before: date | None = None, extra_years: int = 0,
) -> list[Observance]:
    """The deceased's birthday on its Roj and Mah, the next ``years`` times it
    comes round after the death. A birthday that falls on the day of death
    itself is not repeated."""
    roj, mah = birthday
    start, base_year = _start(*death)
    out: list[Observance] = []
    for year in range(death[2], death[2] + years + 2 + extra_years):
        try:
            when = parsi_to_gregorian(year, system, mah=mah, roj=roj)
        except ValueError:
            continue
        if when <= death_date or (not_before and when < not_before):
            continue
        out.append(Observance(
            code=f"birthday_{year}", label="Birthday",
            day_number=_position(roj, mah, year, start, base_year),
            roj=roj, mah=mah, year=year, gregorian_date=when,
        ))
        if len(out) == years:
            break
    return out


# The named days that are month multiples, as ("m", months) / ("y", years):
# Masiso is the monthly, Bamsi two months, Chamsi six, Varsi a year. Each Deci
# is the day before its named day.
_NAMED_SPAN = {30: ("m", 1), 60: ("m", 2), 180: ("m", 6), 360: ("y", 1)}
_DECI_OF = {29: 30, 59: 60, 179: 180, 359: 360}

# Which wins when two observances land on one date (lower wins).
_RANK = {"lit": 0, "y": 1, "m": 2, "deci": 3, "parab": 4, "fravardin_roj": 5, "birthday": 6}

# Roj Fravardin is the 19th Roj. Some families keep it every month.
FRAVARDIN_ROJ = ROJ_NAMES.index("Fravardin") + 1


def _position(roj: int, mah: int, year: int, start: int, base_year: int) -> int:
    """Which day since the death (the death day being day 1) a Roj and Mah
    is, counting by Roj and Mah."""
    return (year - base_year) * CYCLE_DAYS + _ordinal(mah, roj) - start + 1


def _gatha_day(year: int, system: CalendarSystem, gatha: int) -> date:
    """That Gatha day in ``year``. Fasli has a sixth Gatha only in leap
    cycles, so a year without one keeps the last Gatha it does have."""
    for g in range(gatha, 0, -1):
        try:
            return parsi_to_gregorian(year, system, gatha_index=g)
        except ValueError:
            continue
    raise ValueError(f"No Gatha day found in year {year}")


def _on_date(
    code: str, label: str, day_number: int, when: date, system: CalendarSystem,
) -> Observance:
    """An observance on a given date, read back in the calendar."""
    p = gregorian_to_parsi(when, system)
    return Observance(
        code=code, label=label, day_number=day_number, roj=p.roj, mah=p.mah,
        year=p.year, gregorian_date=when, gatha_index=p.gatha_index,
    )


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
    birthday: tuple[int, int] | None = None,
    birthday_years: int = 0,
    start_from: date | None = None,
    fravardin_roj_months: int = 0,
) -> list[Observance]:
    """Every observance the family chose, soonest first. Dates already past
    are included: this is a diary, and a family arriving late still wants
    the whole picture.

    ``opening`` is OPENING_ALL (days 1-10) or OPENING_TENTH. ``day_counts``
    picks from DAY_COUNT_CHOICES; the 10th is already covered by the opening
    and is never listed twice. Masiso, Bamsi, Chamsi and Varsi are the same
    days as the monthly and yearly observances, so when both are chosen each
    date appears once, under its own name. ``monthly_months`` is how many monthly
    observances follow the death (day 31, 61, ...), and ``yearly_years`` how
    many yearly ones (day 361, 721, ...); 0 means none.

    There is no "forever" here, so a schedule is always finite and can always
    be shown whole. There are no default end points either: a series without
    a length is for the caller to refuse (``parabs`` without ``parab_years`` is
    refused here), not for this to fill in.

    ``start_from`` is for a family that arrives late: the schedule is still
    counted from the death, but nothing before that date is booked. A named day
    that has already passed (Dasmi, a Deci, Masiso...) is simply left out, and
    each repeating series (monthly, yearly, Parabs, birthday) runs for its
    chosen length starting from the first date that is still to come - "6
    months" is six months of observances ahead, not six counted from the death.

    ``fravardin_roj_months`` is how many months Roj Fravardin is kept: that Roj of
    each Mah after the death, from the next one still to come when ``start_from``
    is given.

    ``birthday`` is the deceased's (roj, mah); it repeats for ``birthday_years``
    years after the death and is the lowest-ranked observance on a shared date.

    ``parabs`` is PARAB_ALL or PARAB_FRAVARDIN_TIR, for ``parab_years`` years
    after the death - each Parab once a year, like the yearly observance.

    Only one observance is kept per date. When several land on the same day
    the highest wins: the opening days, then the yearly (Varsi included), then
    the monthly (Masiso, Bamsi and Chamsi included), then a Deci, then a Parab.

    ``death_mah`` 13 means a Gatha day, with the Gatha number in ``death_roj``.
    """
    if opening not in OPENINGS:
        raise ValueError(f"opening must be one of {OPENINGS}, got {opening!r}")
    unknown = [d for d in day_counts if d not in NAMED_DAYS]
    if unknown:
        raise ValueError(f"Not an observance day: {unknown}")
    if monthly_months < 0 or yearly_years < 0 or parab_years < 0 or fravardin_roj_months < 0:
        raise ValueError("Counts cannot be negative")
    if parabs is not None and parabs not in PARABS:
        raise ValueError(f"parabs must be one of {PARABS}, got {parabs!r}")
    if parabs is not None and parab_years < 1:
        raise ValueError("Say how many years the Parabs should run for")
    if birthday is not None:
        if not (1 <= birthday[1] <= MONTHS_PER_YEAR and 1 <= birthday[0] <= DAYS_PER_MONTH):
            raise ValueError("A birthday is given as a Roj and a Mah (not a Gatha day)")
        if birthday_years < 1:
            raise ValueError("Say how many years the birthday should repeat for")

    death = (death_roj, death_mah, death_year)
    _start(*death)  # validates the death date
    if death_mah == GATHA_MAH:
        death_date = parsi_to_gregorian(death_year, system, gatha_index=death_roj)
    else:
        death_date = parsi_to_gregorian(death_year, system, mah=death_mah, roj=death_roj)

    start, base_year = _start(*death)
    gatha = death_mah == GATHA_MAH

    # What each choice IS, so that two names for one day are one entry. The
    # first to claim a day keeps it: the family's own word (Masiso) beats
    # "Year 1", which beats "Month 12". Keys: ("lit", n) a literal day,
    # ("m", k) the k-th monthly, ("y", k) the k-th yearly, ("deci", n).
    def canon(kind: str, k: int) -> tuple[str, int]:
        # By Roj and Mah, the 12th monthly IS the first yearly. After a death on
        # a Gatha day it is not: the monthly is on Roj 1, the yearly on the Gatha.
        if not gatha and kind == "m" and k % 12 == 0:
            return ("y", k // 12)
        return (kind, k)

    def resolve(key, code, label) -> Observance:
        kind, k = key
        if kind == "lit":
            return _literal(code, label, k, death_date, system)
        if kind == "deci":
            target = resolve(canon(*_NAMED_SPAN[_DECI_OF[k]]), "", "")
            return _on_date(code, label, target.day_number - 1,
                            target.gregorian_date - timedelta(days=1), system)
        if kind == "m":
            if gatha:
                mah, year = k % 12 + 1, base_year + k // 12
                return Observance(
                    code=code, label=label, roj=1, mah=mah, year=year,
                    day_number=_position(1, mah, year, start, base_year),
                    gregorian_date=parsi_to_gregorian(year, system, mah=mah, roj=1),
                )
            return _by_roj_and_mah(code, label, 1 + DAYS_PER_MONTH * k, death, system)
        # kind == "y"
        if gatha:
            return _on_date(code, label, 1 + CYCLE_DAYS * k,
                            _gatha_day(death_year + k, system, death_roj), system)
        return _by_roj_and_mah(code, label, 1 + CYCLE_DAYS * k, death, system)

    def first_valid(kind: str) -> int:
        """The first k whose date is not before ``start_from``."""
        k = 1
        while resolve(canon(kind, k), "", "").gregorian_date < start_from:
            k += 1
            if k > 100000:
                raise ValueError("start_from is too far from the death")
        return k

    wanted: dict[tuple[str, int], tuple[str, str]] = {}
    series_keys: set[tuple[str, int]] = set()

    def claim(key, code, label):
        wanted.setdefault(key, (code, label))

    if opening == OPENING_ALL:
        for n in range(1, 11):
            claim(("lit", n), f"day_{n}", f"Day {n}")
    # The 10th is always the mobed's own word for it, however it was reached.
    if opening != OPENING_NONE or 10 in day_counts:
        wanted[("lit", 10)] = ("day_10", NAMED_DAYS[10])
    for n in day_counts:
        if n == 10:
            continue
        if n in _NAMED_SPAN:
            claim(canon(*_NAMED_SPAN[n]), f"day_{n}", NAMED_DAYS[n])
        else:
            claim(("deci", n), f"day_{n}", NAMED_DAYS[n])
    named_keys = set(wanted)
    y0 = first_valid("y") if start_from and yearly_years else 1
    m0 = first_valid("m") if start_from and monthly_months else 1
    for k in range(y0, y0 + yearly_years):
        claim(("y", k), f"year_{k}", f"Year {k}")
        series_keys.add(("y", k))
    for k in range(m0, m0 + monthly_months):
        claim(canon("m", k), f"month_{k}", f"Month {k}")
        series_keys.add(canon("m", k))

    ranked = []
    for key, (code, label) in wanted.items():
        o = resolve(key, code, label)
        # A named day that has already passed is not booked when starting late.
        if (start_from and key in named_keys and key not in series_keys
                and o.gregorian_date < start_from):
            continue
        ranked.append((_RANK[key[0]], o))
    gone = max(0, ((start_from - death_date).days // CYCLE_DAYS) + 1) if start_from else 0
    if parabs is not None:
        found = _parab_observances(death, system, parabs, parab_years + gone)
        if start_from:
            per_year = 2 if parabs == PARAB_FRAVARDIN_TIR else len(PARAB_ROJ_FOR_MAH)
            found = [o for o in found if o.gregorian_date >= start_from]
            found = sorted(found, key=lambda o: o.gregorian_date)[: parab_years * per_year]
        ranked += [(_RANK["parab"], o) for o in found]
    if fravardin_roj_months:
        ranked += [(_RANK["fravardin_roj"], o) for o in _fravardin_roj_observances(
            death, death_date, system, fravardin_roj_months, start_from, gone)]
    if birthday is not None:
        ranked += [(_RANK["birthday"], o)
                   for o in _birthday_observances(death, death_date, system, birthday,
                                                  birthday_years, start_from, gone)]
    best: dict[date, tuple[int, Observance]] = {}
    for rank, o in ranked:
        if o.gregorian_date not in best or rank < best[o.gregorian_date][0]:
            best[o.gregorian_date] = (rank, o)
    return sorted((o for _, o in best.values()), key=lambda o: (o.gregorian_date, o.day_number))
