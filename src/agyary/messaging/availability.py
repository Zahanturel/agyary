"""Machi slot availability queries and alternative-slot suggestions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.calendar import CalendarSystem, ParsiDate, gregorian_to_parsi
from agyary.messaging.geh_times import IST, machi_ceremony_datetime
from agyary.models import Machi
from agyary.models.enums import SLOT_RELEASING_STATUSES

ALL_GEHS = (1, 2, 3, 4, 5)
_SCAN_LIMIT_DAYS = 90


def drop_elapsed_gehs(gehs: list[int], gregorian: date) -> list[int]:
    """For same-day bookings, hide gehs whose start time already passed.

    The one shared past-check both the WhatsApp flow and the PWA manual-add
    path must call - never reimplement a naive date-only comparison, since
    the Ushahin geh crosses midnight into the next Gregorian morning.
    """
    now = datetime.now(IST)
    if gregorian != now.date():
        return gehs
    return [g for g in gehs if machi_ceremony_datetime(gregorian, g) > now]


def parsi_slot_fields(parsi: ParsiDate) -> tuple[int, int, int]:
    """(roj, mah, year) as stored on machi rows; Gatha days map to mah=13."""
    if parsi.is_gatha:
        return parsi.gatha_index, 13, parsi.year
    return parsi.roj, parsi.mah, parsi.year


@dataclass(frozen=True)
class SlotOption:
    roj: int
    mah: int
    year: int
    geh: int
    gregorian: date


async def booked_gehs(
    db: AsyncSession, agyary_id: int, roj: int, mah: int, year: int
) -> set[int]:
    result = await db.execute(
        select(Machi.geh).where(
            Machi.agyary_id == agyary_id,
            Machi.parsi_roj == roj,
            Machi.parsi_mah == mah,
            Machi.parsi_year == year,
            Machi.status.notin_(SLOT_RELEASING_STATUSES),
        )
    )
    return set(result.scalars())


async def available_gehs(
    db: AsyncSession, agyary_id: int, roj: int, mah: int, year: int
) -> list[int]:
    booked = await booked_gehs(db, agyary_id, roj, mah, year)
    return [geh for geh in ALL_GEHS if geh not in booked]


async def next_days_with_geh(
    db: AsyncSession,
    agyary_id: int,
    system: CalendarSystem,
    after: date,
    geh: int,
    count: int = 3,
) -> list[SlotOption]:
    """The next `count` days after `after` where `geh` is free."""
    options: list[SlotOption] = []
    for offset in range(1, _SCAN_LIMIT_DAYS + 1):
        day = after + timedelta(days=offset)
        roj, mah, year = parsi_slot_fields(gregorian_to_parsi(day, system))
        if geh not in await booked_gehs(db, agyary_id, roj, mah, year):
            options.append(SlotOption(roj=roj, mah=mah, year=year, geh=geh, gregorian=day))
            if len(options) >= count:
                break
    return options


async def next_days_with_any_geh(
    db: AsyncSession,
    agyary_id: int,
    system: CalendarSystem,
    after: date,
    count: int = 3,
) -> list[SlotOption]:
    """The next `count` days after `after` with at least one free geh
    (represented by the first free geh of that day)."""
    options: list[SlotOption] = []
    for offset in range(1, _SCAN_LIMIT_DAYS + 1):
        day = after + timedelta(days=offset)
        roj, mah, year = parsi_slot_fields(gregorian_to_parsi(day, system))
        free = await available_gehs(db, agyary_id, roj, mah, year)
        if free:
            options.append(SlotOption(roj=roj, mah=mah, year=year, geh=free[0], gregorian=day))
            if len(options) >= count:
                break
    return options
