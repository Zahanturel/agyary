"""Idempotent demo seed: one agyary, a panthaky, a mobed, standard services.

Lives under tests/ because that is what it is for. Every test fixture is
built from it (see conftest.seeded), and it is not production data - the
people and services in here are invented. The fire-temple directory, which
IS real reference data the app needs, is seeded separately by
agyary.scripts.seed_fire_temples.

Run with:  uv run python -m tests.seed_demo
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.database import async_session_factory
from agyary.models import Agyary, AgyaryUser, Service, User

DEMO_AGYARY = {
    "name": "Goti Adarian",
    "city": "Mumbai",
    "address": "Gamadia Colony, Tardeo",
    "calendar_system": "shenshai",
    "contact_phone": "+919800000001",
    "upi_id": "gotiadarian@sbi",
}

DEMO_USERS = [
    {"name": "Er. Hormuz Dadachanji", "phone": "+919800000001", "role": "panthaky"},
    {"name": "Er. Pervez Kias", "phone": "+919800000002", "role": "mobed"},
]

# name, price, min_mobeds, offsite_capable  (doc 1 seed list)
SEED_SERVICES = [
    ("Machi", Decimal("300"), 1, False),
    ("Jashan", Decimal("1500"), 1, True),
    ("Afringan", Decimal("200"), 1, True),
    ("Farokshi", Decimal("200"), 1, True),
    ("Satum", Decimal("300"), 1, False),
    ("Navjote", Decimal("5000"), 1, True),
    ("Wedding", Decimal("10000"), 1, True),
    ("Vandidad", Decimal("3000"), 1, False),
    ("Yazeshni", Decimal("3000"), 2, False),
]


async def seed(db: AsyncSession) -> None:
    agyary = (
        await db.execute(select(Agyary).where(Agyary.name == DEMO_AGYARY["name"]))
    ).scalar_one_or_none()
    if agyary is None:
        agyary = Agyary(**DEMO_AGYARY)
        db.add(agyary)
        await db.flush()
        print(f"created agyary: {agyary.name} (id={agyary.id})")
    else:
        print(f"agyary exists: {agyary.name} (id={agyary.id})")

    for spec in DEMO_USERS:
        user = (
            await db.execute(select(User).where(User.phone == spec["phone"]))
        ).scalar_one_or_none()
        if user is None:
            user = User(name=spec["name"], phone=spec["phone"])
            db.add(user)
            await db.flush()
            print(f"created user: {user.name}")
        junction = (
            await db.execute(
                select(AgyaryUser).where(
                    AgyaryUser.agyary_id == agyary.id, AgyaryUser.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if junction is None:
            db.add(AgyaryUser(agyary_id=agyary.id, user_id=user.id, role=spec["role"]))
            print(f"  -> {spec['role']} at {agyary.name}")

    for order, (name, price, min_mobeds, offsite) in enumerate(SEED_SERVICES):
        service = (
            await db.execute(
                select(Service).where(Service.agyary_id == agyary.id, Service.name == name)
            )
        ).scalar_one_or_none()
        if service is None:
            db.add(
                Service(
                    agyary_id=agyary.id,
                    name=name,
                    default_price=price,
                    min_mobeds=min_mobeds,
                    offsite_capable=offsite,
                    display_order=order,
                )
            )
            print(f"created service: {name}")

    await db.commit()
    print("seed complete")


async def main() -> None:
    async with async_session_factory() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
