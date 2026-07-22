from datetime import date, timedelta

import pytest

from agyary.calendar.engine import (
    GATHA_NAMES,
    MAH_NAMES,
    ROJ_NAMES,
    CalendarSystem,
    get_navroze,
    gregorian_to_parsi,
    parsi_to_gregorian,
)

SHENSHAI = CalendarSystem.SHENSHAI
KADMI = CalendarSystem.KADMI
FASLI = CalendarSystem.FASLI


# ---------------------------------------------------------------------------
# Verified anchor point
# ---------------------------------------------------------------------------
class TestAnchorPoint:
    def test_shenshai_anchor(self):
        result = gregorian_to_parsi(date(2026, 7, 19), SHENSHAI)
        assert result.roj == 9
        assert result.roj_name == "Adar"
        assert result.mah == 12
        assert result.mah_name == "Aspandard"
        assert not result.is_gatha

    def test_kadmi_anchor(self):
        result = gregorian_to_parsi(date(2026, 7, 19), KADMI)
        assert result.roj == 4
        assert result.roj_name == "Shahrevar"
        assert result.mah == 1
        assert result.mah_name == "Fravardin"
        assert not result.is_gatha


# ---------------------------------------------------------------------------
# Navroze
# ---------------------------------------------------------------------------
class TestNavroze:
    def test_shenshai_navroze_2026(self):
        assert get_navroze(2026, SHENSHAI) == date(2026, 8, 15)

    def test_kadmi_navroze_2026(self):
        assert get_navroze(2026, KADMI) == date(2026, 7, 16)

    @pytest.mark.parametrize("year", [2020, 2024, 2025, 2026, 2030, 2050])
    def test_fasli_navroze_always_march_21(self, year):
        assert get_navroze(year, FASLI) == date(year, 3, 21)


# ---------------------------------------------------------------------------
# Gatha days
# ---------------------------------------------------------------------------
class TestGathaDays:
    @pytest.mark.parametrize(
        ("day", "expected_index"),
        [
            (10, 1),
            (11, 2),
            (12, 3),
            (13, 4),
            (14, 5),
        ],
    )
    def test_shenshai_gatha_days_august_2026(self, day, expected_index):
        result = gregorian_to_parsi(date(2026, 8, day), SHENSHAI)
        assert result.is_gatha
        assert result.gatha_index == expected_index
        assert result.gatha_name == GATHA_NAMES[expected_index - 1]
        assert result.mah is None
        assert result.roj is None

    def test_day_before_gatha_is_last_roj_of_last_mah(self):
        result = gregorian_to_parsi(date(2026, 8, 9), SHENSHAI)
        assert not result.is_gatha
        assert result.mah == 12
        assert result.roj == 30

    def test_day_after_gatha_is_new_year_navroze(self):
        result = gregorian_to_parsi(date(2026, 8, 15), SHENSHAI)
        assert not result.is_gatha
        assert result.mah == 1
        assert result.roj == 1


# ---------------------------------------------------------------------------
# Month boundaries: verify one date per Mah, roundtripped through the engine
# ---------------------------------------------------------------------------
class TestMonthBoundaries:
    @pytest.mark.parametrize("mah", range(1, 13))
    def test_first_roj_of_each_mah(self, mah):
        yz_year = 1395
        g_date = parsi_to_gregorian(yz_year, SHENSHAI, mah=mah, roj=1)
        result = gregorian_to_parsi(g_date, SHENSHAI)
        assert result.mah == mah
        assert result.roj == 1
        assert result.mah_name == MAH_NAMES[mah - 1]

    @pytest.mark.parametrize("mah", range(1, 13))
    def test_last_roj_of_each_mah(self, mah):
        yz_year = 1395
        g_date = parsi_to_gregorian(yz_year, SHENSHAI, mah=mah, roj=30)
        result = gregorian_to_parsi(g_date, SHENSHAI)
        assert result.mah == mah
        assert result.roj == 30

    def test_consecutive_mahs_are_30_days_apart_at_roj_1(self):
        yz_year = 1395
        first = parsi_to_gregorian(yz_year, SHENSHAI, mah=1, roj=1)
        second = parsi_to_gregorian(yz_year, SHENSHAI, mah=2, roj=1)
        assert (second - first).days == 30


# ---------------------------------------------------------------------------
# Roundtrip: Gregorian -> Parsi -> Gregorian
# ---------------------------------------------------------------------------
class TestRoundtrip:
    @pytest.mark.parametrize("system", [SHENSHAI, KADMI, FASLI])
    @pytest.mark.parametrize(
        "g_date",
        [
            date(2026, 7, 19),
            date(2026, 1, 1),
            date(2026, 12, 31),
            date(2024, 2, 29),  # Gregorian leap day
            date(2025, 3, 21),
            date(2030, 6, 15),
            date(2000, 1, 1),
        ],
    )
    def test_roundtrip(self, system, g_date):
        parsi_date = gregorian_to_parsi(g_date, system)
        if parsi_date.is_gatha:
            reconstructed = parsi_to_gregorian(
                parsi_date.year, system, gatha_index=parsi_date.gatha_index
            )
        else:
            reconstructed = parsi_to_gregorian(
                parsi_date.year, system, mah=parsi_date.mah, roj=parsi_date.roj
            )
        assert reconstructed == g_date

    @pytest.mark.parametrize("system", [SHENSHAI, KADMI, FASLI])
    def test_roundtrip_across_a_full_year(self, system):
        start = date(2026, 1, 1)
        for offset in range(0, 400, 17):  # sparse sample, ~24 dates
            g_date = start + timedelta(days=offset)
            parsi_date = gregorian_to_parsi(g_date, system)
            if parsi_date.is_gatha:
                reconstructed = parsi_to_gregorian(
                    parsi_date.year, system, gatha_index=parsi_date.gatha_index
                )
            else:
                reconstructed = parsi_to_gregorian(
                    parsi_date.year, system, mah=parsi_date.mah, roj=parsi_date.roj
                )
            assert reconstructed == g_date


# ---------------------------------------------------------------------------
# Fasli leap-year handling
# ---------------------------------------------------------------------------
class TestFasliLeapYear:
    def test_six_gatha_days_when_cycle_contains_a_leap_february(self):
        # The Fasli cycle 2023-03-21 .. 2024-03-20 contains Feb 29, 2024.
        cycle_start_yz_year = 2023 - 630
        sixth_gatha_date = parsi_to_gregorian(
            cycle_start_yz_year, FASLI, gatha_index=6
        )
        result = gregorian_to_parsi(sixth_gatha_date, FASLI)
        assert result.is_gatha
        assert result.gatha_index == 6
        # The 6th leap-year Gatha has no traditional name (only 5 are named).
        assert result.gatha_name is None

        # And the cycle is exactly 366 days long, keeping Navroze pinned.
        next_navroze = sixth_gatha_date + timedelta(days=1)
        assert next_navroze == date(2024, 3, 21)

    def test_five_gatha_days_when_cycle_has_no_leap_february(self):
        # 2025-03-21 .. 2026-03-20 contains Feb 2026, not a leap year.
        cycle_start_yz_year = 2025 - 630
        with pytest.raises(ValueError):
            parsi_to_gregorian(cycle_start_yz_year, FASLI, gatha_index=6)

        fifth_gatha_date = parsi_to_gregorian(cycle_start_yz_year, FASLI, gatha_index=5)
        next_navroze = fifth_gatha_date + timedelta(days=1)
        assert next_navroze == date(2026, 3, 21)

    def test_fasli_gatha_day_count_matches_gregorian_leap_status(self):
        for cycle_start_year, expect_leap in [(2019, True), (2020, False), (2023, True)]:
            cycle_start_yz_year = cycle_start_year - 630
            is_leap_next_feb = (cycle_start_year + 1) % 4 == 0 and (
                (cycle_start_year + 1) % 100 != 0 or (cycle_start_year + 1) % 400 == 0
            )
            assert is_leap_next_feb == expect_leap
            if expect_leap:
                parsi_to_gregorian(cycle_start_yz_year, FASLI, gatha_index=6)
            else:
                with pytest.raises(ValueError):
                    parsi_to_gregorian(cycle_start_yz_year, FASLI, gatha_index=6)


# ---------------------------------------------------------------------------
# Misc validation
# ---------------------------------------------------------------------------
class TestValidation:
    def test_roj_names_count(self):
        assert len(ROJ_NAMES) == 30

    def test_mah_names_count(self):
        assert len(MAH_NAMES) == 12

    def test_gatha_names_count(self):
        assert len(GATHA_NAMES) == 5

    def test_parsi_to_gregorian_requires_exactly_one_mode(self):
        with pytest.raises(ValueError):
            parsi_to_gregorian(1395, SHENSHAI)
        with pytest.raises(ValueError):
            parsi_to_gregorian(1395, SHENSHAI, mah=1, roj=1, gatha_index=1)

    def test_invalid_mah_raises(self):
        with pytest.raises(ValueError):
            parsi_to_gregorian(1395, SHENSHAI, mah=13, roj=1)

    def test_invalid_roj_raises(self):
        with pytest.raises(ValueError):
            parsi_to_gregorian(1395, SHENSHAI, mah=1, roj=31)
