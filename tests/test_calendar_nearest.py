"""Resolving a Roj/Mah with no year attached.

The thing this exists to prevent: clients deriving the Yazdegerdi year as
`Gregorian year - 630`. Shenshai and Kadmi Navroze falls in mid-August, so
that subtraction is off by a whole year for every date between January 1st
and Navroze - and a machi filed under the wrong Parsi year is booked into
the wrong slot, not merely displayed oddly.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from agyary.calendar import (
    CalendarSystem,
    gregorian_to_parsi,
    nearest_occurrence,
    parsi_to_gregorian,
)

SYSTEMS = [CalendarSystem.SHENSHAI, CalendarSystem.KADMI, CalendarSystem.FASLI]


@pytest.mark.parametrize("system", SYSTEMS)
@pytest.mark.parametrize("reference", [date(2026, 1, 15), date(2026, 7, 1), date(2026, 11, 30)])
def test_result_is_that_roj_mah_and_is_not_in_the_past(system, reference):
    for mah, roj in [(1, 1), (4, 17), (12, 30), (7, 5)]:
        result = nearest_occurrence(system, mah=mah, roj=roj, on_or_after=reference)
        parsi = gregorian_to_parsi(result, system)
        assert (parsi.mah, parsi.roj) == (mah, roj)
        assert result >= reference


@pytest.mark.parametrize("system", SYSTEMS)
def test_it_is_the_nearest_one_not_merely_a_valid_one(system):
    """A year earlier must be in the past, and a year later must be further
    away - that pins it to the soonest occurrence rather than any match."""
    reference = date(2026, 5, 20)
    result = nearest_occurrence(system, mah=6, roj=12, on_or_after=reference)
    year = gregorian_to_parsi(result, system).year

    previous = parsi_to_gregorian(year - 1, system, mah=6, roj=12)
    following = parsi_to_gregorian(year + 1, system, mah=6, roj=12)
    assert previous < reference <= result < following


@pytest.mark.parametrize("system", SYSTEMS)
def test_todays_own_roj_mah_resolves_to_today(system):
    """"Next occurrence" counts today itself - picking today's Roj/Mah out
    of a dropdown must not jump a year forward."""
    today = date(2026, 9, 9)
    parsi = gregorian_to_parsi(today, system)
    assert nearest_occurrence(system, mah=parsi.mah, roj=parsi.roj, on_or_after=today) == today


def test_the_naive_yz_formula_is_wrong_and_this_is_not():
    """The concrete bug being designed out. In January, Shenshai's YZ year
    is still the one that began at the previous August's Navroze, so
    `Gregorian year - 630` names the wrong year."""
    reference = date(2026, 1, 20)
    naive_year = reference.year - 630
    real_year = gregorian_to_parsi(reference, CalendarSystem.SHENSHAI).year
    assert naive_year != real_year  # the trap

    resolved = nearest_occurrence(CalendarSystem.SHENSHAI, mah=11, roj=3, on_or_after=reference)
    assert gregorian_to_parsi(resolved, CalendarSystem.SHENSHAI).mah == 11
    # Using the naive year would have landed a year off.
    assert parsi_to_gregorian(naive_year, CalendarSystem.SHENSHAI, mah=11, roj=3) != resolved


@pytest.mark.parametrize("system", SYSTEMS)
def test_gatha_days_resolve_by_index(system):
    reference = date(2026, 6, 1)
    result = nearest_occurrence(system, gatha_index=3, on_or_after=reference)
    parsi = gregorian_to_parsi(result, system)
    assert parsi.is_gatha and parsi.gatha_index == 3 and result >= reference


def test_sixth_gatha_only_resolves_where_it_exists():
    """Fasli grows a sixth Gatha in leap cycles; Shenshai and Kadmi never
    have one, so asking must fail rather than silently return something."""
    reference = date(2026, 1, 1)
    result = nearest_occurrence(CalendarSystem.FASLI, gatha_index=6, on_or_after=reference)
    parsi = gregorian_to_parsi(result, CalendarSystem.FASLI)
    assert parsi.is_gatha and parsi.gatha_index == 6

    for system in (CalendarSystem.SHENSHAI, CalendarSystem.KADMI):
        with pytest.raises(ValueError):
            nearest_occurrence(system, gatha_index=6, on_or_after=reference)


def test_every_roj_mah_of_a_year_resolves_within_a_year():
    """Sweep the whole year: no combination may be unresolvable, and none
    may land more than a year out."""
    reference = date(2026, 3, 3)
    for mah in range(1, 13):
        for roj in range(1, 31):
            result = nearest_occurrence(
                CalendarSystem.SHENSHAI, mah=mah, roj=roj, on_or_after=reference
            )
            assert reference <= result < reference + timedelta(days=366)


# ---------------------------------------------------------------------------
# The endpoint clients are expected to use
# ---------------------------------------------------------------------------
async def test_from_parsi_without_year_resolves_server_side(client):
    r = await client.get("/api/calendar/from-parsi", params={"roj": 5, "mah": 6})
    assert r.status_code == 200
    body = r.json()
    assert body["roj"] == 5 and body["mah"] == 6
    assert date.fromisoformat(body["gregorian_date"]) >= date.today()


async def test_from_parsi_with_year_still_converts_exactly(client):
    """The pre-existing two-way navigation must keep working unchanged."""
    r = await client.get(
        "/api/calendar/from-parsi", params={"roj": 5, "mah": 6, "year": 1396, "system": "shenshai"}
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["roj"], body["mah"], body["year"]) == (5, 6, 1396)
    assert body["gregorian_date"] == parsi_to_gregorian(
        1396, CalendarSystem.SHENSHAI, mah=6, roj=5
    ).isoformat()


async def test_from_parsi_handles_gatha_month(client):
    r = await client.get("/api/calendar/from-parsi", params={"roj": 2, "mah": 13})
    assert r.status_code == 200
    body = r.json()
    assert body["is_gatha"] is True and body["gatha_index"] == 2


async def test_from_parsi_rejects_impossible_gatha_index(client):
    r = await client.get("/api/calendar/from-parsi", params={"roj": 7, "mah": 13})
    assert r.status_code == 400


async def test_from_parsi_round_trips_against_convert(client):
    """Date -> Roj/Mah -> Date is the loop a synced pair of input fields
    runs on every keystroke; it must be stable."""
    for ymd in ("2026-08-06", "2027-01-02", "2026-12-31"):
        forward = (await client.get("/api/calendar/convert", params={"date": ymd})).json()
        back = (
            await client.get(
                "/api/calendar/from-parsi",
                params={"roj": forward["roj"], "mah": forward["mah"], "year": forward["year"]},
            )
        ).json()
        assert back["gregorian_date"] == ymd
