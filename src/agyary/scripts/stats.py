"""Who is actually using this. Read-only, run on the server.

    docker compose exec app uv run python -m agyary.scripts.stats

Deliberately a script and not a page. An admin page needs a role to gate
it on, and every membership this app creates is a plain 'mobed' - there
is nothing to check against, so an admin route would either be open to
every signed-in mobed or guarded by something invented for the purpose.
A script needs neither, adds no HTTP surface, and cannot be reached from
the internet at all.

Phone numbers are masked unless you pass --full. They are the one piece
of directly identifying data here and terminal scrollback outlives the
question you opened this to answer.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from agyary.core.database import async_session_factory, engine
from agyary.models import (
    Agyary,
    AgyaryUser,
    Booking,
    Customer,
    Machi,
    User,
    WaLoginAttempt,
)


# The shared engine echoes every statement when app_debug is on, which
# buries the report under its own SQL. This is a human-readable report, so
# it turns that off for itself regardless of how the server is configured.
engine.echo = False


def mask(phone: str | None, full: bool) -> str:
    """+919812345678 -> +9198****5678. Enough to recognise a number you
    already know, not enough to dial one you don't."""
    if not phone:
        return "-"
    if full or len(phone) < 9:
        return phone
    return f"{phone[:5]}{'*' * (len(phone) - 9)}{phone[-4:]}"


def ago(ts: datetime | None) -> str:
    if ts is None:
        return "never"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    seconds = (datetime.now(UTC) - ts).total_seconds()
    if seconds < 90:
        return "just now"
    for cutoff, div, unit in ((5400, 60, "min"), (172800, 3600, "hr")):
        if seconds < cutoff:
            return f"{int(seconds // div)} {unit} ago"
    return f"{int(seconds // 86400)} days ago"


def rule(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m\n{'-' * max(len(title), 40)}")


async def report(full: bool) -> None:
    async with async_session_factory() as db:
        async def scalar(stmt) -> int:
            return (await db.execute(stmt)).scalar_one() or 0

        users = await scalar(select(func.count()).select_from(User))
        temples_total = await scalar(select(func.count()).select_from(Agyary))
        claimed = await scalar(
            select(func.count()).select_from(Agyary).where(Agyary.status != "unclaimed")
        )
        machis = await scalar(select(func.count()).select_from(Machi))
        bookings = await scalar(select(func.count()).select_from(Booking))
        behdins = await scalar(select(func.count()).select_from(Customer))

        rule("Totals")
        print(f"  mobeds signed up      {users}")
        print(f"  fire temples claimed  {claimed} (of {temples_total} seeded)")
        print(f"  machis               {machis}")
        print(f"  bookings             {bookings}")
        print(f"  behdins on file      {behdins}")

        if users == 0:
            print("\n  Nobody has signed up yet.")

        # --- Who signed up -------------------------------------------------
        rows = (
            await db.execute(
                select(User).order_by(User.created_at.desc()).limit(40)
            )
        ).scalars().all()
        if rows:
            rule(f"Mobeds ({len(rows)} most recent)")
            print(f"  {'name':<28}{'phone':<18}{'joined':<16}{'temple'}")
            for u in rows:
                membership = (
                    await db.execute(
                        select(Agyary.name, AgyaryUser.role)
                        .join(AgyaryUser, AgyaryUser.agyary_id == Agyary.id)
                        .where(AgyaryUser.user_id == u.id, AgyaryUser.is_active.is_(True))
                        .order_by(AgyaryUser.joined_at)
                        .limit(1)
                    )
                ).first()
                where = f"{membership[0]} ({membership[1]})" if membership else "\033[33mno temple yet\033[0m"
                print(f"  {u.name[:27]:<28}{mask(u.phone, full):<18}{ago(u.created_at):<16}{where}")

        # --- Which temples are live ---------------------------------------
        temples = (
            await db.execute(
                select(Agyary, func.count(AgyaryUser.user_id))
                .join(AgyaryUser, AgyaryUser.agyary_id == Agyary.id)
                .where(AgyaryUser.is_active.is_(True))
                .group_by(Agyary.id)
                .order_by(func.count(AgyaryUser.user_id).desc())
            )
        ).all()
        if temples:
            rule("Fire temples with members")
            print(f"  {'name':<38}{'city':<20}{'status':<12}{'mobeds'}")
            for t, n in temples:
                print(f"  {t.name[:37]:<38}{(t.city or '-')[:19]:<20}{t.status:<12}{n}")

        # --- Is anything being entered ------------------------------------
        week = datetime.now(UTC) - timedelta(days=7)
        rule("Activity, last 7 days")
        for label, model in (("machis entered", Machi), ("bookings entered", Booking)):
            n = await scalar(
                select(func.count()).select_from(model).where(model.created_at >= week)
            )
            print(f"  {label:<22}{n}")
        last_machi = (
            await db.execute(select(func.max(Machi.created_at)))
        ).scalar_one_or_none()
        print(f"  {'last machi entered':<22}{ago(last_machi)}")

        # --- Sign-in funnel ------------------------------------------------
        # The one that answers "did somebody try and fail". An attempt is
        # created the moment the button is tapped and claimed only when
        # their WhatsApp message reaches the webhook, so unclaimed rows are
        # people who tapped and never arrived - a broken webhook, a number
        # that is not registered, or a mobed who gave up.
        attempts = await scalar(select(func.count()).select_from(WaLoginAttempt))
        unclaimed = await scalar(
            select(func.count()).select_from(WaLoginAttempt).where(
                WaLoginAttempt.claimed_at.is_(None)
            )
        )
        rule("Sign-in attempts in flight")
        print(f"  live attempts         {attempts}")
        print(f"  of those, unclaimed   {unclaimed}")
        if unclaimed and unclaimed == attempts and attempts > 2:
            print(
                "\n  \033[33mEvery live attempt is unclaimed.\033[0m If that persists, the"
                "\n  webhook is not delivering: check the number is REGISTERED (not"
                "\n  merely verified), that the Meta app is published, and that"
                "\n  WHATSAPP_APP_SECRET is set."
            )
        print(
            "\n  Note: these rows are swept on expiry, so this is a live gauge,"
            "\n  not a history. A quiet zero here is normal."
        )
        print()


def main() -> None:
    full = "--full" in sys.argv
    if not full:
        print("\n(phone numbers masked; pass --full to show them)")
    asyncio.run(report(full))


if __name__ == "__main__":
    main()
