"""Seed the worldwide fire-temple reference list as UNCLAIMED agyaries.

Source: audit-flowcharts/list_fire_temples.xls (2012 vintage), converted once
to data/fire_temples.json so runtime needs no .xls reader. 167 distinct
temples - names that repeat across different cities (e.g. several 'Anjuman
Daremeher', three 'Atash Kadeh') are genuinely different temples and are all
kept; they're disambiguated by address in search.

Each row is inserted as status='unclaimed' with no wa_phone_number_id: it's
findable in search so a mobed can claim it, but it isn't a set-up agyari until
the first mobed activates it (see mobed_dashboard.activate_agyary). The seed
details may be stale; activation is where they get corrected.

Run with:  uv run python -m agyary.scripts.seed_fire_temples
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.database import async_session_factory
from agyary.models import Agyary

_DATA = Path(__file__).parent / "data" / "fire_temples.json"


def _address(row: dict) -> str | None:
    parts = [p for p in (row.get("address", ""), row.get("state", "")) if p]
    return ", ".join(parts) or None


async def seed(db: AsyncSession) -> int:
    temples = json.loads(_DATA.read_text(encoding="utf-8"))
    added = 0
    for row in temples:
        name, city = row["name"], row["city"]
        exists = (
            await db.execute(
                select(Agyary.id).where(Agyary.name == name, Agyary.city == city)
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue
        db.add(
            Agyary(
                name=name,
                city=city,
                address=_address(row),
                calendar_system=row.get("calendar_system", "shenshai"),
                status="unclaimed",
                is_active=True,
            )
        )
        added += 1
    await db.commit()
    print(f"fire-temple seed: {added} added, {len(temples) - added} already present")
    return added


async def main() -> None:
    async with async_session_factory() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
