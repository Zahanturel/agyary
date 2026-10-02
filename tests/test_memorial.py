"""Memorial schedule: counting from the day of death.

Day of death is day 1 and Gatha days are not counted, so every milestone is
a walk around a 360-day Roj/Mah cycle, whatever the calendar system.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from agyary.calendar import CalendarSystem, parsi_to_gregorian
from agyary.calendar.memorial import (
    OPENING_ALL,
    OPENING_TENTH,
    build_schedule,
    count_from,
)

SYSTEMS = [CalendarSystem.SHENSHAI, CalendarSystem.KADMI, CalendarSystem.FASLI]
YEAR = 1395


def test_day_one_is_the_day_of_death():
    assert count_from(2, 1, YEAR, 1) == (2, 1, YEAR)


def test_day_ten_is_nine_rojs_later():
    assert count_from(2, 1, YEAR, 10) == (11, 1, YEAR)


def test_day_thirty_is_the_roj_before_the_same_roj_next_mah():
    assert count_from(2, 1, YEAR, 30) == (1, 2, YEAR)
    assert count_from(2, 1, YEAR, 31) == (2, 2, YEAR)


def test_first_roj_wraps_to_the_last_roj_of_the_previous_cycle_position():
    # Death on Roj 1: day 30 is Roj 30 of the SAME Mah, day 31 is Roj 1 next Mah.
    assert count_from(1, 5, YEAR, 30) == (30, 5, YEAR)
    assert count_from(1, 5, YEAR, 31) == (1, 6, YEAR)


def test_varsi_is_the_roj_before_the_anniversary_and_yearly_is_the_anniversary():
    assert count_from(2, 1, YEAR, 360) == (1, 1, YEAR + 1)
    assert count_from(2, 1, YEAR, 361) == (2, 1, YEAR + 1)


def test_counting_rolls_over_the_year_from_the_last_mah():
    # Death in Mah 12: day 31 is Mah 1 of the next Parsi year.
    assert count_from(10, 12, YEAR, 31) == (10, 1, YEAR + 1)


def test_gatha_days_are_not_counted():
    # Mah 12 Roj 30 -> day 2 is Mah 1 Roj 1 of the next year, not a Gatha day.
    assert count_from(30, 12, YEAR, 2) == (1, 1, YEAR + 1)


def test_a_gatha_death_cannot_be_counted_from():
    with pytest.raises(ValueError):
        count_from(1, 13, YEAR, 10)


def test_day_number_must_be_positive():
    with pytest.raises(ValueError):
        count_from(2, 1, YEAR, 0)


@pytest.mark.parametrize("system", SYSTEMS)
def test_monthly_observances_land_on_the_same_roj_every_mah(system):
    sched = build_schedule(
        death_roj=7, death_mah=3, death_year=YEAR, system=system,
        opening=OPENING_TENTH, monthly_months=14,
    )
    monthly = [o for o in sched if o.code.startswith("month_")]
    assert len(monthly) == 14
    assert all(o.roj == 7 for o in monthly)
    assert [o.mah for o in monthly[:3]] == [4, 5, 6]


@pytest.mark.parametrize("system", SYSTEMS)
def test_gregorian_dates_match_the_engine(system):
    sched = build_schedule(
        death_roj=9, death_mah=12, death_year=YEAR, system=system,
        opening=OPENING_ALL, day_counts=(30, 360), yearly_years=2,
    )
    for o in sched:
        assert o.gregorian_date == parsi_to_gregorian(o.year, system, mah=o.mah, roj=o.roj)
    # Soonest first, and strictly increasing.
    dates = [o.gregorian_date for o in sched]
    assert dates == sorted(dates) and len(set(dates)) == len(dates)


def test_all_opening_gives_ten_consecutive_days():
    sched = build_schedule(
        death_roj=9, death_mah=3, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_ALL,
    )
    assert [o.day_number for o in sched] == list(range(1, 11))
    assert sched[-1].label == "Dasmi"
    assert all(b.gregorian_date - a.gregorian_date == timedelta(days=1)
               for a, b in zip(sched, sched[1:]))


def test_tenth_only_gives_just_the_tenth():
    sched = build_schedule(
        death_roj=9, death_mah=3, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH,
    )
    assert [o.day_number for o in sched] == [10]


def test_tenth_is_not_listed_twice_when_also_picked():
    sched = build_schedule(
        death_roj=9, death_mah=3, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_ALL, day_counts=(10, 30),
    )
    assert [o.day_number for o in sched].count(10) == 1


def test_month_twelve_and_year_one_are_the_same_day_named_as_the_year():
    sched = build_schedule(
        death_roj=9, death_mah=3, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, monthly_months=12, yearly_years=1,
    )
    day361 = [o for o in sched if o.day_number == 361]
    assert [o.code for o in day361] == ["year_1"]


def test_named_days_in_order_with_the_before_days_one_day_earlier():
    sched = build_schedule(
        death_roj=9, death_mah=3, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, day_counts=(29, 30, 59, 60, 179, 180, 359, 360),
    )
    by_day = {o.day_number: o for o in sched}
    for before in (29, 59, 179, 359):
        assert by_day[before + 1].gregorian_date - by_day[before].gregorian_date == timedelta(days=1)
    assert [o.day_number for o in sched] == sorted(by_day)


def test_rejects_bad_input():
    kw = dict(death_roj=9, death_mah=3, death_year=YEAR, system=CalendarSystem.SHENSHAI)
    with pytest.raises(ValueError):
        build_schedule(**kw, opening="nonsense")
    with pytest.raises(ValueError):
        build_schedule(**kw, opening=OPENING_ALL, day_counts=(11,))
    with pytest.raises(ValueError):
        build_schedule(**kw, opening=OPENING_ALL, monthly_months=-1)


# --- Literal opening vs Roj-and-Mah counting across the Gatha days ----------

@pytest.mark.parametrize("system", SYSTEMS)
def test_tenth_day_is_literal_so_gatha_days_count(system):
    # Death on the last Roj of the last Mah, the day before the Gathas.
    kw = dict(death_roj=30, death_mah=12, death_year=YEAR, system=system)
    sched = build_schedule(**kw, opening=OPENING_TENTH)
    death = parsi_to_gregorian(YEAR, system, mah=12, roj=30)
    assert sched[0].gregorian_date == death + timedelta(days=9)


def test_literal_opening_can_land_in_the_gatha_days():
    sched = build_schedule(
        death_roj=30, death_mah=12, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_ALL,
    )
    by_day = {o.day_number: o for o in sched}
    assert by_day[1].mah == 12 and by_day[1].roj == 30
    assert by_day[2].mah is None and by_day[2].gatha_index == 1
    assert by_day[6].gatha_index == 5
    assert (by_day[7].mah, by_day[7].roj, by_day[7].year) == (1, 1, YEAR + 1)
    assert (by_day[10].mah, by_day[10].roj) == (1, 4)


def test_thirtieth_day_skips_the_gathas_unlike_the_tenth():
    sched = build_schedule(
        death_roj=30, death_mah=12, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, day_counts=(30,),
    )
    thirtieth = next(o for o in sched if o.day_number == 30)
    # By Roj and Mah: the Roj before the same Roj (30) next Mah -> Mah 1, Roj 29...
    assert (thirtieth.roj, thirtieth.mah, thirtieth.year) == (29, 1, YEAR + 1)
    # ...which is 5 Gatha days later in real time than 29 days after the death.
    death = parsi_to_gregorian(YEAR, CalendarSystem.SHENSHAI, mah=12, roj=30)
    assert (thirtieth.gregorian_date - death).days == 29 + 5


# --- Parabs ------------------------------------------------------------------

def test_parab_rojs_are_the_roj_named_like_the_mah():
    from agyary.calendar import MAH_NAMES, ROJ_NAMES
    from agyary.calendar.memorial import PARAB_ROJ_FOR_MAH

    for mah, roj in PARAB_ROJ_FOR_MAH.items():
        assert ROJ_NAMES[roj - 1] == MAH_NAMES[mah - 1]
    assert PARAB_ROJ_FOR_MAH[1] == 19 and PARAB_ROJ_FOR_MAH[4] == 13
    # Dae has no Roj of its own name; held until the mobed confirms it.
    assert 10 not in PARAB_ROJ_FOR_MAH


def test_fravardin_and_tir_parabs_only():
    from agyary.calendar.memorial import PARAB_FRAVARDIN_TIR

    sched = build_schedule(
        death_roj=9, death_mah=6, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, parabs=PARAB_FRAVARDIN_TIR, parab_years=2,
    )
    parabs = [o for o in sched if o.code.startswith("parab_")]
    assert {(o.mah, o.roj) for o in parabs} == {(1, 19), (4, 13)}
    # Two years after a Mah-6 death: Tir and Fravardin of the next two years.
    assert [(o.mah, o.year) for o in parabs] == [
        (1, YEAR + 1), (4, YEAR + 1), (1, YEAR + 2), (4, YEAR + 2)]


def test_parabs_are_after_the_death_and_within_the_years_asked():
    from agyary.calendar.memorial import PARAB_ALL, PARAB_ROJ_FOR_MAH

    sched = build_schedule(
        death_roj=9, death_mah=6, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, parabs=PARAB_ALL, parab_years=1,
    )
    parabs = [o for o in sched if o.code.startswith("parab_")]
    death = parsi_to_gregorian(YEAR, CalendarSystem.SHENSHAI, mah=6, roj=9)
    assert all(1 < o.day_number <= 361 for o in parabs)
    assert all(o.gregorian_date > death for o in parabs)
    # One year after a Mah-6 death: every Parab with a Roj, exactly once.
    assert len(parabs) == len(PARAB_ROJ_FOR_MAH)


def test_a_parab_death_day_is_not_its_own_observance():
    from agyary.calendar.memorial import PARAB_FRAVARDIN_TIR

    sched = build_schedule(
        death_roj=19, death_mah=1, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, parabs=PARAB_FRAVARDIN_TIR, parab_years=1,
    )
    parabs = [o for o in sched if o.code.startswith("parab_")]
    # Tir this year, and Fravardin again on the anniversary (day 361).
    assert [(o.mah, o.year) for o in parabs] == [(4, YEAR), (1, YEAR + 1)]


def test_parabs_need_an_explicit_length():
    from agyary.calendar.memorial import PARAB_ALL

    with pytest.raises(ValueError):
        build_schedule(
            death_roj=9, death_mah=3, death_year=YEAR, system=CalendarSystem.SHENSHAI,
            opening=OPENING_TENTH, parabs=PARAB_ALL,
        )
