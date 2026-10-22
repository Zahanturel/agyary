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


def test_a_gatha_death_has_no_roj_and_mah_for_day_one():
    with pytest.raises(ValueError):
        count_from(1, 13, YEAR, 1)
    with pytest.raises(ValueError):
        count_from(7, 13, YEAR, 2)   # there is no 7th Gatha day


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


@pytest.mark.parametrize("system", SYSTEMS)
def test_masiso_bamsi_chamsi_varsi_are_months_on_at_the_same_roj(system):
    # Masiso is the monthly, Bamsi two months, Chamsi six, Varsi a year.
    sched = build_schedule(
        death_roj=9, death_mah=3, death_year=YEAR, system=system,
        opening=OPENING_TENTH, day_counts=(30, 60, 180, 360),
    )
    named = {o.label: o for o in sched if o.label != "Dasmi"}
    assert {k: (v.roj, v.mah, v.year) for k, v in named.items()} == {
        "Masiso": (9, 4, YEAR), "Bamsi": (9, 5, YEAR),
        "Chamsi": (9, 9, YEAR), "Varsi": (9, 3, YEAR + 1),
    }
    for o in named.values():
        assert o.gregorian_date == parsi_to_gregorian(o.year, system, mah=o.mah, roj=o.roj)


def test_deci_is_the_day_before_each():
    sched = build_schedule(
        death_roj=9, death_mah=3, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, day_counts=(29, 30, 59, 60, 179, 180, 359, 360),
    )
    named = [o for o in sched if o.label != "Dasmi"]
    assert [o.label for o in named] == [
        "Deci", "Masiso", "Deci", "Bamsi", "Deci", "Chamsi", "Deci", "Varsi"]
    for deci, day in zip(named[0::2], named[1::2]):
        assert day.gregorian_date - deci.gregorian_date == timedelta(days=1)
        assert (deci.roj, day.roj) == (8, 9)


def test_masiso_is_the_first_monthly_so_the_date_is_listed_once_under_its_name():
    sched = build_schedule(
        death_roj=9, death_mah=3, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, day_counts=(30,), monthly_months=3,
    )
    labels = [o.label for o in sched if o.label != "Dasmi"]
    assert labels == ["Masiso", "Month 2", "Month 3"]
    assert len({o.gregorian_date for o in sched}) == len(sched)


def test_varsi_is_the_first_yearly_and_keeps_its_own_name():
    kw = dict(death_roj=9, death_mah=3, death_year=YEAR, system=CalendarSystem.SHENSHAI,
              opening=OPENING_TENTH, yearly_years=2)
    with_varsi = build_schedule(**kw, day_counts=(360,))
    assert [o.label for o in with_varsi if o.label != "Dasmi"] == ["Varsi", "Year 2"]
    without = build_schedule(**kw)
    assert [o.label for o in without if o.label != "Dasmi"] == ["Year 1", "Year 2"]
    # And with monthly running through the year, the year still wins that day.
    labels = [o.label for o in build_schedule(**kw, monthly_months=12)]
    assert "Year 1" in labels and "Month 12" not in labels


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


def test_masiso_skips_the_gathas_unlike_the_tenth():
    sched = build_schedule(
        death_roj=30, death_mah=12, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, day_counts=(30,),
    )
    masiso = next(o for o in sched if o.label == "Masiso")
    # By Roj and Mah: the same Roj (30), one Mah on -> Mah 1 of the next year...
    assert (masiso.roj, masiso.mah, masiso.year) == (30, 1, YEAR + 1)
    # ...which is 5 Gatha days later in real time than 30 days after the death.
    death = parsi_to_gregorian(YEAR, CalendarSystem.SHENSHAI, mah=12, roj=30)
    assert (masiso.gregorian_date - death).days == 30 + 5


# --- Parabs ------------------------------------------------------------------

def _parabs(sched):
    return [o for o in sched if o.code.startswith("parab_")]


def test_parab_rojs_are_the_roj_named_like_the_mah():
    from agyary.calendar import MAH_NAMES, ROJ_NAMES
    from agyary.calendar.memorial import PARAB_ROJ_FOR_MAH

    assert sorted(PARAB_ROJ_FOR_MAH) == list(range(1, 13))
    for mah, roj in PARAB_ROJ_FOR_MAH.items():
        if mah == 10:   # Dae-Dadar: Roj Hormazd is the Roj that is also called Dae-Dadar
            assert roj == 1
            continue
        assert ROJ_NAMES[roj - 1] == MAH_NAMES[mah - 1]
    assert PARAB_ROJ_FOR_MAH[1] == 19 and PARAB_ROJ_FOR_MAH[4] == 13


def test_dae_parab_is_dae_dadar_on_roj_hormazd():
    from agyary.calendar import MAH_NAMES, ROJ_NAMES
    from agyary.calendar.memorial import PARAB_ROJ_FOR_MAH

    # Month 10 is Dae-Dadar; the Roj that shares that name is Roj 1 (Hormazd). The other
    # Dae days (Roj 8 Dae-Pa-Adar, 15 Dae-Pa-Meher, 23 Dae-Pa-Din) are not Parabs.
    assert MAH_NAMES[9] == "Dae-Dadar" and ROJ_NAMES[7] == "Dae-Pa-Adar"
    assert PARAB_ROJ_FOR_MAH[10] == 1
    assert len(PARAB_ROJ_FOR_MAH) == 12


def test_fravardin_and_tir_parabs_only():
    from agyary.calendar.memorial import PARAB_FRAVARDIN_TIR

    sched = build_schedule(
        death_roj=9, death_mah=6, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, parabs=PARAB_FRAVARDIN_TIR, parab_years=2,
    )
    parabs = _parabs(sched)
    assert {(o.mah, o.roj) for o in parabs} == {(1, 19), (4, 13)}
    # Two years after a Mah-6 death: Fravardin and Tir of each of the next two years.
    assert [(o.mah, o.year) for o in parabs] == [
        (1, YEAR + 1), (4, YEAR + 1), (1, YEAR + 2), (4, YEAR + 2)]


def test_each_parab_comes_round_once_a_year_for_the_years_asked():
    from agyary.calendar.memorial import PARAB_ALL

    for years in (1, 2, 3):
        sched = build_schedule(
            death_roj=9, death_mah=6, death_year=YEAR, system=CalendarSystem.SHENSHAI,
            opening=OPENING_TENTH, parabs=PARAB_ALL, parab_years=years,
        )
        parabs = _parabs(sched)
        death = parsi_to_gregorian(YEAR, CalendarSystem.SHENSHAI, mah=6, roj=9)
        assert len(parabs) == 12 * years
        assert all(2 <= o.day_number <= 360 * years + 1 for o in parabs)
        assert all(o.gregorian_date > death for o in parabs)
        for mah in range(1, 13):
            assert sum(o.mah == mah for o in parabs) == years
    assert any(o.label == "Dae-Dadar Parab" and o.roj == 1 and o.mah == 10 for o in parabs)


def test_a_parab_on_the_death_day_is_not_an_observance_but_next_years_is():
    from agyary.calendar.memorial import PARAB_FRAVARDIN_TIR

    # Death on the Fravardin Parab itself: that day is day 1; Tir follows this
    # year and the next Fravardin Parab is the anniversary, day 361.
    sched = build_schedule(
        death_roj=19, death_mah=1, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, parabs=PARAB_FRAVARDIN_TIR, parab_years=1,
    )
    assert [(o.mah, o.year) for o in _parabs(sched)] == [(4, YEAR), (1, YEAR + 1)]


# --- When observances share a date, one wins: opening > yearly > monthly > Deci > Parab

KW = dict(system=CalendarSystem.SHENSHAI)


def test_yearly_beats_a_parab_on_the_same_day():
    from agyary.calendar.memorial import PARAB_FRAVARDIN_TIR

    # Death on the Fravardin Parab: the next one is the anniversary, day 361.
    sched = build_schedule(
        death_roj=19, death_mah=1, death_year=YEAR, opening=OPENING_TENTH,
        yearly_years=1, parabs=PARAB_FRAVARDIN_TIR, parab_years=1, **KW,
    )
    on_361 = [o for o in sched if o.day_number == 361]
    assert [o.code for o in on_361] == ["year_1"]
    assert len({o.gregorian_date for o in sched}) == len(sched)


def test_monthly_beats_a_parab_on_the_same_day():
    from agyary.calendar.memorial import PARAB_ALL

    # Death on Roj 6 of Mah 1: the monthly on Roj 6 of Mah 3 is the Khordad Parab's day.
    sched = build_schedule(
        death_roj=6, death_mah=1, death_year=YEAR, opening=OPENING_TENTH,
        monthly_months=2, parabs=PARAB_ALL, parab_years=1, **KW,
    )
    on_that_day = [o for o in sched if (o.mah, o.roj) == (3, 6)]
    assert [o.code for o in on_that_day] == ["month_2"]


def test_the_opening_beats_a_parab_on_the_same_day():
    from agyary.calendar.memorial import PARAB_FRAVARDIN_TIR

    # Death on Roj 10 of Mah 1: the 10th day is Roj 19 of Mah 1, the Fravardin Parab.
    sched = build_schedule(
        death_roj=10, death_mah=1, death_year=YEAR, opening=OPENING_TENTH,
        parabs=PARAB_FRAVARDIN_TIR, parab_years=1, **KW,
    )
    on_that_day = [o for o in sched if (o.mah, o.roj) == (1, 19)]
    assert [o.label for o in on_that_day] == ["Dasmi"]


def test_a_deci_beats_a_parab_on_the_same_day():
    from agyary.calendar.memorial import PARAB_ALL

    # The Deci is the day before Masiso, so for a death on Roj 7 it is Roj 6 of the
    # next Mah - the Parab of any Mah whose Parab Roj is 6 (Khordad).
    sched = build_schedule(
        death_roj=7, death_mah=2, death_year=YEAR, opening=OPENING_TENTH,
        day_counts=(29, 30), parabs=PARAB_ALL, parab_years=1, **KW,
    )
    deci = next(o for o in sched if o.label == "Deci")
    assert (deci.roj, deci.mah) == (6, 3)
    assert [o.label for o in sched if o.gregorian_date == deci.gregorian_date] == ["Deci"]


def test_a_named_day_keeps_its_name_over_the_plain_series():
    sched = build_schedule(
        death_roj=9, death_mah=3, death_year=YEAR, opening=OPENING_TENTH,
        day_counts=(30, 360), monthly_months=12, yearly_years=1, **KW,
    )
    labels = [o.label for o in sched]
    assert "Masiso" in labels and "Varsi" in labels
    assert "Month 1" not in labels and "Year 1" not in labels and "Month 12" not in labels


def test_parabs_need_an_explicit_length():
    from agyary.calendar.memorial import PARAB_ALL

    with pytest.raises(ValueError):
        build_schedule(
            death_roj=9, death_mah=3, death_year=YEAR, system=CalendarSystem.SHENSHAI,
            opening=OPENING_TENTH, parabs=PARAB_ALL,
        )


# --- A death on a Gatha day ---------------------------------------------------
# The Gatha day is day 1 and the opening carries straight on. Counting by Roj
# and Mah has no Roj to start from, so the Gatha sits just before Mah 1 Roj 1
# of the next year: day 2 is Mah 1 Roj 1.

def test_roj_and_mah_counting_from_a_gatha_death():
    assert count_from(3, 13, YEAR, 2) == (1, 1, YEAR + 1)
    assert count_from(3, 13, YEAR, 30) == (29, 1, YEAR + 1)
    assert count_from(3, 13, YEAR, 31) == (30, 1, YEAR + 1)
    assert count_from(3, 13, YEAR, 32) == (1, 2, YEAR + 1)
    # Day 361 is 360 Roj-days on: the last Roj of the last Mah.
    assert count_from(3, 13, YEAR, 361) == (30, 12, YEAR + 1)


@pytest.mark.parametrize("system", SYSTEMS)
def test_opening_from_a_gatha_death_is_literal_days_from_that_day(system):
    sched = build_schedule(
        death_roj=3, death_mah=13, death_year=YEAR, system=system, opening=OPENING_ALL,
    )
    death = parsi_to_gregorian(YEAR, system, gatha_index=3)
    assert [o.day_number for o in sched] == list(range(1, 11))
    assert sched[0].gregorian_date == death and sched[0].gatha_index == 3
    assert [o.gregorian_date for o in sched] == [death + timedelta(days=n) for n in range(10)]
    # Gatha 3 is followed by Gatha 4, Gatha 5, then Mah 1 Roj 1 of the next year.
    assert [o.gatha_index for o in sched[:3]] == [3, 4, 5]
    assert (sched[3].mah, sched[3].roj, sched[3].year) == (1, 1, YEAR + 1)


def test_the_tenth_day_from_a_gatha_death_is_literal():
    sched = build_schedule(
        death_roj=3, death_mah=13, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH,
    )
    death = parsi_to_gregorian(YEAR, CalendarSystem.SHENSHAI, gatha_index=3)
    assert sched[0].gregorian_date == death + timedelta(days=9)


@pytest.mark.parametrize("system", SYSTEMS)
def test_after_a_gatha_death_monthly_is_roj_hormazd_and_yearly_is_the_gatha(system):
    from agyary.calendar.memorial import PARAB_FRAVARDIN_TIR

    sched = build_schedule(
        death_roj=3, death_mah=13, death_year=YEAR, system=system,
        opening=OPENING_TENTH, day_counts=(29, 30, 60, 360), monthly_months=3, yearly_years=2,
        parabs=PARAB_FRAVARDIN_TIR, parab_years=1,
    )
    by_label = {o.label: o for o in sched}
    # Monthly: Roj Hormazd (Roj 1) of each Mah, from Mah 2 of the next year.
    assert (by_label["Masiso"].roj, by_label["Masiso"].mah, by_label["Masiso"].year) == (1, 2, YEAR + 1)
    assert (by_label["Bamsi"].roj, by_label["Bamsi"].mah) == (1, 3)
    assert (by_label["Month 3"].roj, by_label["Month 3"].mah) == (1, 4)
    # Yearly: the same Gatha day each year. Varsi is the first of them.
    assert by_label["Varsi"].gatha_index == 3 and by_label["Varsi"].year == YEAR + 1
    assert by_label["Varsi"].gregorian_date == parsi_to_gregorian(YEAR + 1, system, gatha_index=3)
    assert by_label["Year 2"].gatha_index == 3 and by_label["Year 2"].year == YEAR + 2
    assert "Year 1" not in by_label   # that day is Varsi
    # The Deci is the actual day before Masiso: the last Roj of Mah 1.
    assert by_label["Deci"].gregorian_date == by_label["Masiso"].gregorian_date - timedelta(days=1)
    assert (by_label["Deci"].roj, by_label["Deci"].mah) == (30, 1)
    # And a month is about a month: Masiso is not days after the death.
    assert (by_label["Masiso"].gregorian_date - parsi_to_gregorian(YEAR, system, gatha_index=3)).days > 25
    # Fravardin Parab is Roj 19 of Mah 1: day 20; Tir Parab is Roj 13 of Mah 4: day 104.
    parabs = {o.mah: o for o in _parabs(sched)}
    assert (parabs[1].day_number, parabs[1].year) == (20, YEAR + 1)
    assert (parabs[4].day_number, parabs[4].year) == (104, YEAR + 1)


def test_after_a_gatha_death_the_twelfth_monthly_and_the_first_yearly_are_different_days():
    sched = build_schedule(
        death_roj=3, death_mah=13, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_TENTH, monthly_months=13, yearly_years=1,
    )
    by_code = {o.code: o for o in sched}
    assert (by_code["month_11"].mah, by_code["month_11"].roj, by_code["month_11"].year) == (12, 1, YEAR + 1)
    assert by_code["year_1"].gatha_index == 3
    # The 12th and 13th monthly wrap into the following year.
    assert (by_code["month_12"].mah, by_code["month_12"].roj, by_code["month_12"].year) == (1, 1, YEAR + 2)
    assert (by_code["month_13"].mah, by_code["month_13"].roj, by_code["month_13"].year) == (2, 1, YEAR + 2)


def test_a_yearly_gatha_in_a_year_without_that_gatha_keeps_the_last_one():
    # Fasli's sixth Gatha exists only in leap cycles; the year after one has five.
    for year in range(1390, 1410):
        try:
            parsi_to_gregorian(year, CalendarSystem.FASLI, gatha_index=6)
            parsi_to_gregorian(year + 1, CalendarSystem.FASLI, gatha_index=6)
        except ValueError:
            try:
                parsi_to_gregorian(year, CalendarSystem.FASLI, gatha_index=6)
            except ValueError:
                continue
            sched = build_schedule(
                death_roj=6, death_mah=13, death_year=year, system=CalendarSystem.FASLI,
                opening=OPENING_TENTH, yearly_years=1,
            )
            year_one = next(o for o in sched if o.code == "year_1")
            assert year_one.gatha_index == 5 and year_one.year == year + 1
            return
    raise AssertionError("no leap Fasli year found")


def test_a_gatha_death_in_the_sixth_gatha_of_a_fasli_leap_cycle():
    # Fasli adds a sixth Gatha in leap cycles; find one and die on it.
    for year in range(1390, 1410):
        try:
            died = parsi_to_gregorian(year, CalendarSystem.FASLI, gatha_index=6)
        except ValueError:
            continue
        sched = build_schedule(
            death_roj=6, death_mah=13, death_year=year, system=CalendarSystem.FASLI,
            opening=OPENING_ALL,
        )
        assert sched[0].gregorian_date == died and sched[0].gatha_index == 6
        assert (sched[1].mah, sched[1].roj, sched[1].year) == (1, 1, year + 1)
        return
    raise AssertionError("no leap Fasli year found")


def test_dasmi_is_chosen_like_any_named_day_with_no_opening():
    from agyary.calendar.memorial import OPENING_NONE
    kw = dict(death_roj=2, death_mah=1, death_year=YEAR, system=CalendarSystem.SHENSHAI,
              opening=OPENING_NONE)
    assert build_schedule(**kw) == []
    only = build_schedule(**kw, day_counts=(10, 30))
    assert [o.day_number for o in only] == [10, 31]
    assert only[0].label == "Dasmi"


def test_birthday_repeats_on_its_roj_and_mah_after_the_death():
    from agyary.calendar.memorial import OPENING_NONE
    sched = build_schedule(
        death_roj=2, death_mah=1, death_year=YEAR, system=CalendarSystem.SHENSHAI,
        opening=OPENING_NONE, birthday=(9, 5), birthday_years=3,
    )
    assert [o.label for o in sched] == ["Birthday"] * 3
    assert [(o.roj, o.mah) for o in sched] == [(9, 5)] * 3
    assert [o.year for o in sched] == [YEAR, YEAR + 1, YEAR + 2]


def test_a_birthday_needs_years_and_a_real_roj_and_mah():
    from agyary.calendar.memorial import OPENING_NONE
    kw = dict(death_roj=2, death_mah=1, death_year=YEAR, system=CalendarSystem.SHENSHAI,
              opening=OPENING_NONE)
    with pytest.raises(ValueError):
        build_schedule(**kw, birthday=(9, 5), birthday_years=0)
    with pytest.raises(ValueError):
        build_schedule(**kw, birthday=(9, 13), birthday_years=2)


def _late(**over):
    from agyary.calendar.memorial import OPENING_NONE
    kw = dict(death_roj=2, death_mah=1, death_year=YEAR, system=CalendarSystem.SHENSHAI,
              opening=OPENING_NONE)
    kw.update(over)
    return build_schedule(**kw)


def test_starting_late_leaves_out_passed_days_and_counts_series_from_the_next_one():
    whole = _late(day_counts=(10, 29, 30), monthly_months=12)
    start = whole[4].gregorian_date          # a few months in
    late = _late(day_counts=(10, 29, 30), monthly_months=6, start_from=start)
    assert all(o.gregorian_date >= start for o in late)
    assert not any(o.code in ("day_10", "day_29", "day_30") for o in late)
    months = [o for o in late if o.code.startswith(("month_", "year_"))]
    assert len(months) == 6                    # six MORE months, not six from the death
    # and they are the consecutive monthlies that follow the start
    assert [o.day_number for o in months] == [months[0].day_number + 30 * i for i in range(6)]


def test_starting_late_keeps_named_days_still_to_come():
    whole = _late(day_counts=(10, 30, 60))
    start = whole[0].gregorian_date          # Dasmi itself is not before the start
    late = _late(day_counts=(10, 30, 60), start_from=start)
    assert [o.code for o in late] == [o.code for o in whole]


def test_starting_late_birthday_and_parabs_run_from_the_start():
    whole = _late(birthday=(9, 5), birthday_years=1, parabs="fravardin_tir", parab_years=1)
    start = whole[-1].gregorian_date
    late = _late(birthday=(9, 5), birthday_years=2, parabs="fravardin_tir", parab_years=1, start_from=start)
    assert all(o.gregorian_date >= start for o in late)
    assert sum(o.label == "Birthday" for o in late) == 2
    assert sum(o.label.endswith("Parab") for o in late) == 2   # each Parab once


def test_roj_fravardin_every_month_for_n_months():
    from agyary.calendar.memorial import FRAVARDIN_ROJ
    sched = _late(fravardin_roj_months=14)
    assert len(sched) == 14 and all(o.label == "Roj Fravardin" for o in sched)
    assert {o.roj for o in sched} == {FRAVARDIN_ROJ} == {19}
    mahs = [o.mah for o in sched]
    assert all((b - a) % 12 == 1 for a, b in zip(mahs, mahs[1:]))   # one per Mah, in order
    dates = [o.gregorian_date for o in sched]
    assert dates == sorted(dates) and len(set(dates)) == 14


def test_roj_fravardin_starting_late_counts_from_the_next_one():
    whole = _late(fravardin_roj_months=12)
    start = whole[5].gregorian_date
    late = _late(fravardin_roj_months=4, start_from=start)
    assert [o.gregorian_date for o in late] == [o.gregorian_date for o in whole[5:9]]


def test_roj_fravardin_in_the_mah_of_fravardin_is_a_parab_only_once():
    sched = _late(fravardin_roj_months=12, parabs="fravardin_tir", parab_years=1)
    dates = [o.gregorian_date for o in sched]
    assert len(dates) == len(set(dates))


def test_parabs_by_count_are_the_next_n_in_date_order():
    from agyary.calendar.memorial import OPENING_NONE
    sched = _late(parabs="all", parab_count=6)
    assert len(sched) == 6 and all(o.label.endswith("Parab") for o in sched)
    dates = [o.gregorian_date for o in sched]
    assert dates == sorted(dates)
    # 24 Parabs is the same as two years of them
    two_years = _late(parabs="all", parab_years=2)
    assert [o.gregorian_date for o in _late(parabs="all", parab_count=len(two_years))] == \
           [o.gregorian_date for o in two_years]


def test_parabs_by_count_starting_late_count_from_the_next_one():
    whole = _late(parabs="all", parab_count=20)
    start = whole[7].gregorian_date
    late = _late(parabs="all", parab_count=5, start_from=start)
    assert [o.gregorian_date for o in late] == [o.gregorian_date for o in whole[7:12]]


def test_parabs_need_one_length_only():
    with pytest.raises(ValueError):
        _late(parabs="all")
    with pytest.raises(ValueError):
        _late(parabs="all", parab_years=1, parab_count=3)


def test_days_5_to_9_are_literal_days_and_leave_the_dasmi_to_its_own_choice():
    sched = _late(opening="days_5_to_9", day_counts=(10,))
    assert [o.day_number for o in sched] == [5, 6, 7, 8, 9, 10]
    assert [o.label for o in sched] == ["Day 5", "Day 6", "Day 7", "Day 8", "Day 9", "Dasmi"]
    assert [o.day_number for o in _late(opening="days_5_to_9")] == [5, 6, 7, 8, 9]
