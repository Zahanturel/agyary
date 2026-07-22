"""Free-text date/time parsing for the booking flows.

Accepted date inputs:
- Parsi: "Roj Bahman", "Roj Bahman Mah Fravardin" (the "roj" keyword is
  required: several names, e.g. Bahman, are both a Roj and a Mah)
- Gregorian: "July 23", "23 July", "23/7", "23-7-2026", "2026-07-23"
- Relative: "today", "tomorrow"

Parsi year inference (v2 audit fix #6): a Roj+Mah with no year means the
nearest occurrence that is today or later in the agyary's calendar system.
Gregorian day/month without a year resolves the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Literal

from agyary.calendar import CalendarSystem, MAH_NAMES, ROJ_NAMES, gregorian_to_parsi, parsi_to_gregorian

_GREG_MONTHS = {
    name: i + 1
    for i, name in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ]
    )
}
_GREG_MONTH_LOOKUP = {
    **_GREG_MONTHS,
    **{name[:3]: num for name, num in _GREG_MONTHS.items()},
    "sept": 9,  # common four-letter abbreviation
}

_ROJ_LOOKUP = {name.lower(): i + 1 for i, name in enumerate(ROJ_NAMES)}
_MAH_LOOKUP = {name.lower(): i + 1 for i, name in enumerate(MAH_NAMES)}


@dataclass(frozen=True)
class DateParse:
    kind: Literal[
        "parsi_full",
        "parsi_roj_only",
        "gregorian",
        "roj_invalid",
        "mah_invalid",
        "invalid",
    ]
    roj: int | None = None
    mah: int | None = None
    gregorian: date | None = None


def _match_calendar_name(token: str, lookup: dict[str, int]) -> int | None:
    """Exact match first, then unambiguous prefix match ("ardi" -> Ardibehesht)."""
    token = token.lower().strip(" ,.")
    if token in lookup:
        return lookup[token]
    if len(token) >= 3:
        candidates = {v for k, v in lookup.items() if k.startswith(token)}
        if len(candidates) == 1:
            return candidates.pop()
    return None


_PARSI_RE = re.compile(
    r"^\s*roj\s+(?P<roj>[a-z\-]+)\s*(?:[, ]\s*mah\s+(?P<mah>[a-z\-]+))?\s*$",
    re.IGNORECASE,
)
_DMY_RE = re.compile(
    r"^\s*(?P<d>\d{1,2})\s*[/\-.]\s*(?P<m>\d{1,2})(?:\s*[/\-.]\s*(?P<y>\d{2,4}))?\s*$"
)
_ISO_RE = re.compile(r"^\s*(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\s*$")
_MONTH_NAME_RE = re.compile(
    r"^\s*(?:(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s+(?P<mon1>[a-z]+)|(?P<mon2>[a-z]+)\s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?)(?:[, ]+(?P<y>\d{4}))?\s*$",
    re.IGNORECASE,
)


def _nearest_future_gregorian(day: int, month: int, today: date) -> date | None:
    # The long horizon only matters for Feb 29, which may be several years out.
    for year in range(today.year, today.year + 9):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None


def parse_date_input(text: str, today: date) -> DateParse:
    cleaned = text.strip().lower()

    if cleaned in ("today", "aaj"):
        return DateParse(kind="gregorian", gregorian=today)
    if cleaned == "tomorrow":
        return DateParse(kind="gregorian", gregorian=today + timedelta(days=1))

    parsi = _PARSI_RE.match(cleaned)
    if parsi:
        roj = _match_calendar_name(parsi.group("roj"), _ROJ_LOOKUP)
        if roj is None:
            return DateParse(kind="roj_invalid")
        if parsi.group("mah") is None:
            return DateParse(kind="parsi_roj_only", roj=roj)
        mah = _match_calendar_name(parsi.group("mah"), _MAH_LOOKUP)
        if mah is None:
            return DateParse(kind="mah_invalid", roj=roj)
        return DateParse(kind="parsi_full", roj=roj, mah=mah)

    iso = _ISO_RE.match(cleaned)
    if iso:
        try:
            return DateParse(
                kind="gregorian",
                gregorian=date(int(iso.group("y")), int(iso.group("m")), int(iso.group("d"))),
            )
        except ValueError:
            return DateParse(kind="invalid")

    dmy = _DMY_RE.match(cleaned)
    if dmy:
        day, month = int(dmy.group("d")), int(dmy.group("m"))
        year_raw = dmy.group("y")
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
            try:
                return DateParse(kind="gregorian", gregorian=date(year, month, day))
            except ValueError:
                return DateParse(kind="invalid")
        resolved = _nearest_future_gregorian(day, month, today)
        return (
            DateParse(kind="gregorian", gregorian=resolved)
            if resolved
            else DateParse(kind="invalid")
        )

    named = _MONTH_NAME_RE.match(cleaned)
    if named:
        day = int(named.group("d1") or named.group("d2"))
        month = _GREG_MONTH_LOOKUP.get((named.group("mon1") or named.group("mon2")).lower())
        if month is None:
            return DateParse(kind="invalid")
        year_raw = named.group("y")
        if year_raw:
            try:
                return DateParse(kind="gregorian", gregorian=date(int(year_raw), month, day))
            except ValueError:
                return DateParse(kind="invalid")
        resolved = _nearest_future_gregorian(day, month, today)
        return (
            DateParse(kind="gregorian", gregorian=resolved)
            if resolved
            else DateParse(kind="invalid")
        )

    return DateParse(kind="invalid")


def infer_parsi_year(roj: int, mah: int, system: CalendarSystem, today: date) -> tuple[int, date]:
    """Nearest occurrence of Roj/Mah that is today or later.

    Returns (parsi_year, gregorian_date).
    """
    current = gregorian_to_parsi(today, system)
    for year in (current.year, current.year + 1):
        gregorian = parsi_to_gregorian(year, system, mah=mah, roj=roj)
        if gregorian >= today:
            return year, gregorian
    raise ValueError(f"Could not infer year for roj={roj} mah={mah}")


_TIME_RE = re.compile(
    r"^\s*(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ampm>am|pm|a\.m\.|p\.m\.)?\s*$",
    re.IGNORECASE,
)


def parse_time_input(text: str) -> time | None:
    match = _TIME_RE.match(text.strip().lower())
    if not match:
        return None
    hour = int(match.group("h"))
    minute = int(match.group("m") or 0)
    ampm = (match.group("ampm") or "").replace(".", "")
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    elif not ampm and 1 <= hour <= 7:
        # Bare small hours ("4", "6:30") almost always mean afternoon/evening
        # ceremonies; treat 1-7 as PM when unqualified ("0:30" stays midnight).
        hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)
