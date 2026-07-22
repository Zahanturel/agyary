"""Geh -> physical ceremony time mapping.

Geh boundaries track the sun, so exact times vary by season; these are the
fixed approximations used for reminders and dashboards (all agyaries are in
India -> IST).

The critical case (v2 audit fix #1): the Parsi day starts at sunrise, and the
Ushahin geh (midnight to sunrise) of, say, Roj Bahman falls in the early
morning of the NEXT Gregorian day. The panthaky prays the Ushahin machi at
~4 AM the following civil date, so ceremony_datetime = gregorian_date + 1 day
at 04:00 IST for geh 5.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Approximate local start time of each geh.
GEH_START_TIMES: dict[int, time] = {
    1: time(7, 0),  # Havan: sunrise -> noon
    2: time(13, 0),  # Rapithwin: noon -> ~3 pm
    3: time(15, 30),  # Uziran: ~3 pm -> sunset
    4: time(19, 0),  # Aiwisruthrem: sunset -> midnight
    5: time(4, 0),  # Ushahin: midnight -> sunrise (next Gregorian day)
}


def to_ist(dt: datetime) -> datetime:
    """For display: timestamptz round-trips from Postgres come back UTC."""
    return dt.astimezone(IST)


def machi_ceremony_datetime(gregorian_date: date, geh: int) -> datetime:
    """Physical start time of a machi anchored on the given Parsi-day date."""
    if geh not in GEH_START_TIMES:
        raise ValueError(f"geh must be 1-5, got {geh}")
    civil_date = gregorian_date + timedelta(days=1) if geh == 5 else gregorian_date
    return datetime.combine(civil_date, GEH_START_TIMES[geh], tzinfo=IST)
