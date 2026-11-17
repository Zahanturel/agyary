"""Give the seeded fire temples their town-level starting positions (D10).

The Doongerwadi side shows a funeral place's manager the fire temples nearest
first, so every fire temple needs a position. The 167 that seed_fire_temples
put in the app start from the town (or neighbourhood) they are in, looked up on
OpenStreetMap for the Phase 2 research: data/fire_temple_positions.csv, a copy of
docs/phase2-doongerwadi/fire-temple-positions.csv kept here because the server's
image has no docs/ folder. A mobed of the temple, or an admin, then moves the
pin onto the temple itself; that makes it a "pin".

Matched exactly as seed_fire_temples stored them: the same name and the same
city. Only a fire temple with no position at all is filled, and it is filled as
"town" - a position someone has put on the map is never touched, and nor is a
town position already there, so running it twice changes nothing. A temple
whose name or city a mobed corrected when setting it up no longer matches and
is listed instead, as is a name and city that more than one fire temple has.

Dry run unless --write is given: it says what it would fill and what it could
not match, and changes nothing.

Run with:  python -m agyary.scripts.seed_fire_temple_locations            (dry run)
           python -m agyary.scripts.seed_fire_temple_locations --write    (fill them)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.models import Agyary
from agyary.models.enums import LOCATION_TOWN

DATA = Path(__file__).parent / "data" / "fire_temple_positions.csv"


@dataclass(frozen=True)
class Row:
    name: str
    city: str
    latitude: float
    longitude: float


@dataclass
class Report:
    filled: list[tuple[int, str, str]] = field(default_factory=list)      # (id, name, city)
    already_pin: list[tuple[int, str, str]] = field(default_factory=list)
    already_town: list[tuple[int, str, str]] = field(default_factory=list)
    not_found: list[tuple[str, str]] = field(default_factory=list)
    ambiguous: list[tuple[str, str, int]] = field(default_factory=list)   # (name, city, how many)
    bad_rows: list[str] = field(default_factory=list)


def _position(raw: str, low: float, high: float) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and low <= value <= high else None


def load_rows(path: Path = DATA, report: Report | None = None) -> list[Row]:
    """The positions in the list. A row with no usable position is left out
    and named in ``report.bad_rows``."""
    rows: list[Row] = []
    with path.open(encoding="utf-8", newline="") as f:
        for line_no, rec in enumerate(csv.DictReader(f), start=2):
            name, city = rec.get("name") or "", rec.get("city") or ""
            lat = _position(rec.get("latitude", ""), -90, 90)
            lon = _position(rec.get("longitude", ""), -180, 180)
            if not name or not city or lat is None or lon is None or (lat == 0 and lon == 0):
                if report is not None:
                    report.bad_rows.append(f"line {line_no}: {name or '?'}, {city or '?'}")
                continue
            rows.append(Row(name, city, lat, lon))
    return rows


async def fill(db: AsyncSession, rows: list[Row], *, write: bool, report: Report | None = None,
               now: datetime | None = None) -> Report:
    """Fill the fire temples in ``rows`` that have no position. Commits only
    with ``write``; a dry run leaves the session as it found it."""
    report = report or Report()
    now = now or datetime.now(timezone.utc)
    for row in rows:
        found = (
            await db.execute(
                select(Agyary).where(Agyary.name == row.name, Agyary.city == row.city)
                # What the database holds now, not what this session read earlier.
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
        if not found:
            report.not_found.append((row.name, row.city))
            continue
        if len(found) > 1:
            report.ambiguous.append((row.name, row.city, len(found)))
            continue
        agyary = found[0]
        key = (agyary.id, agyary.name, agyary.city)
        if agyary.latitude is not None or agyary.location_source is not None:
            (report.already_pin if agyary.location_source != LOCATION_TOWN else report.already_town).append(key)
            continue
        if write:
            # Only while it is still empty, in the same statement: a mobed who
            # drops a pin while this runs keeps their pin.
            done = await db.execute(
                update(Agyary)
                .where(Agyary.id == agyary.id, Agyary.latitude.is_(None), Agyary.location_source.is_(None))
                .values(latitude=row.latitude, longitude=row.longitude, location_source=LOCATION_TOWN,
                        location_set_by_user_id=None, location_set_at=now)
            )
            if done.rowcount != 1:
                report.already_pin.append(key)
                continue
        report.filled.append(key)
    if write:
        await db.commit()
    else:
        await db.rollback()
    return report


def print_report(report: Report, *, write: bool, total: int) -> None:
    verb = "Filled" if write else "Would fill"
    print(f"{verb} {len(report.filled)} of {total} fire temples with their town's position.")
    for _, name, city in report.filled:
        print(f"  {'filled' if write else 'would fill'}: {name}, {city}")
    if report.already_pin:
        print(f"Left alone, already pinned on the map by a person: {len(report.already_pin)}")
        for _, name, city in report.already_pin:
            print(f"  pinned: {name}, {city}")
    if report.already_town:
        print(f"Left alone, already has its town position: {len(report.already_town)}")
    if report.not_found:
        print(f"Not found in the app (renamed when set up, or not seeded): {len(report.not_found)}")
        for name, city in report.not_found:
            print(f"  not found: {name}, {city}")
    if report.ambiguous:
        print(f"Not filled, more than one fire temple has this name and city: {len(report.ambiguous)}")
        for name, city, n in report.ambiguous:
            print(f"  {n} fire temples: {name}, {city}")
    if report.bad_rows:
        print(f"Rows in the list with no usable position: {len(report.bad_rows)}")
        for line in report.bad_rows:
            print(f"  {line}")
    if not write:
        print("Dry run: nothing was changed. Run again with --write to fill them.")


async def main(write: bool) -> Report:
    from agyary.core.database import async_session_factory

    report = Report()
    rows = load_rows(DATA, report)
    async with async_session_factory() as db:
        await fill(db, rows, write=write, report=report)
    print_report(report, write=write, total=len(rows))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="fill them (without it, a dry run)")
    asyncio.run(main(parser.parse_args().write))
