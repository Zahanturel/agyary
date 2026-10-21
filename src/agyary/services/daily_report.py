"""The daily report: the evening before, what is on a mobed's day tomorrow.

A mobed who turns it on (users.daily_report) is told every evening, from about
8 pm IST, what they have tomorrow - the services, machis and memorial prayers they
are down for, with the behdins' names - so they can prepare the day before (buy the
fruit, set things out). It always goes in the app (the bell and the popup on open);
and, when DAILY_REPORT_SEND_MODE=live, on WhatsApp from the shared number too,
through an approved template. Whether anything is paid is NOT in it: that stays in
the app.

Nothing is sent when tomorrow is empty, and nothing twice: each target day is left
as an app notification, which is also how a second pass knows it has already run.
A failed WhatsApp message is recorded and not retried, so a mobed is never sent
the same list twice; the in-app one is there either way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agyary.core.config import Settings
from agyary.messaging.formatting import PURPOSE_SHORT, geh_label
from agyary.messaging.geh_times import IST
from agyary.models import (
    AgyaryUser, AppNotification, Customer, Machi, Memorial, MemorialObservance, Notification, Service, User,
)
from agyary.models.enums import SLOT_RELEASING_STATUSES
from agyary.services import guardrails, mobed_dashboard, reminders, wa_send

logger = logging.getLogger(__name__)

KIND = "daily_report"
WA_LIST_MAX = 700          # characters of list in a WhatsApp message (the body limit is 1024)
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Item:
    sort: datetime
    kind: str          # "booking" | "machi" | "memorial"
    text: str


def day_label(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def _clock(dt: datetime) -> str:
    local = dt.astimezone(IST)
    return local.strftime("%I:%M %p").lstrip("0")


async def tomorrows_items(db: AsyncSession, user_id: int, day: date) -> list[Item]:
    """Everything this mobed is down for on ``day``, in the order the day runs."""
    items: list[Item] = []
    start = datetime.combine(day, time.min, IST)

    # Services they have accepted.
    for e in await mobed_dashboard.list_my_day(db, user_id, day, day):
        b = e.booking
        if b.status in SLOT_RELEASING_STATUSES:
            continue
        where = " (offsite)" if b.is_offsite else ""
        items.append(Item(b.ceremony_datetime, "booking",
                          f"{_clock(b.ceremony_datetime)} {e.service_name}{where} - {e.behdin_name or 'a behdin'}"))

    # Machis they are responsible for.
    machis = (await db.execute(
        select(Machi, Customer.name)
        .join(Customer, Customer.id == Machi.customer_id)
        .where(Machi.gregorian_date == day,
               (Machi.created_by_user_id == user_id) | (Machi.assigned_mobed_id == user_id),
               Machi.status.notin_(SLOT_RELEASING_STATUSES))
    )).all()
    for m, name in machis:
        items.append(Item(m.ceremony_datetime, "machi",
                          f"Machi ({PURPOSE_SHORT.get(m.purpose, m.purpose)}), {geh_label(m.geh)} - {name or 'a behdin'}"))

    # Memorial prayer days of the families they look after.
    rows = (await db.execute(
        select(MemorialObservance, Memorial, Customer.name)
        .join(Memorial, Memorial.id == MemorialObservance.memorial_id)
        .join(Customer, Customer.id == Memorial.customer_id)
        .options(selectinload(MemorialObservance.services))
        .where(MemorialObservance.gregorian_date == day, Memorial.created_by_user_id == user_id)
    )).all()
    names_by_agyary: dict[int, dict[int, str]] = {}
    for obs, memorial, behdin in rows:
        if memorial.agyary_id not in names_by_agyary:
            found = await db.execute(select(Service.id, Service.name).where(Service.agyary_id == memorial.agyary_id))
            names_by_agyary[memorial.agyary_id] = dict(found.all())
        names = names_by_agyary[memorial.agyary_id]
        prayers = ", ".join(names[s.service_id] for s in sorted(obs.services, key=lambda s: s.service_id)
                            if s.service_id in names)
        # A prayer day with no time goes after the timed things of the day.
        when = datetime.combine(day, obs.time_of_day or time(23, 59), IST)
        at = f"{obs.time_of_day.strftime('%I:%M %p').lstrip('0')} " if obs.time_of_day else ""
        items.append(Item(when, "memorial",
                          f"{at}{obs.label} for the late {memorial.departed_name}"
                          f"{f' ({prayers})' if prayers else ''} - {behdin or 'a behdin'}"))

    items.sort(key=lambda i: (i.sort, i.text))
    return items


def summary_line(items: list[Item]) -> str:
    """"5 things: 3 services, 1 machi, 1 memorial prayer"."""
    n = {k: sum(1 for i in items if i.kind == k) for k in ("booking", "machi", "memorial")}
    parts = []
    if n["booking"]:
        parts.append(f"{n['booking']} service{'s' if n['booking'] != 1 else ''}")
    if n["machi"]:
        parts.append(f"{n['machi']} machi{'s' if n['machi'] != 1 else ''}")
    if n["memorial"]:
        parts.append(f"{n['memorial']} memorial prayer{'s' if n['memorial'] != 1 else ''}")
    total = len(items)
    return f"{total} thing{'s' if total != 1 else ''} on your day: " + ", ".join(parts)


def app_body(items: list[Item]) -> str:
    return summary_line(items) + "\n\n" + "\n".join(f"- {i.text}" for i in items)


def whatsapp_params(day: date, items: list[Item]) -> dict[str, str]:
    """The three variables of the template: the day, the count, and the list on one
    line (a template variable may not hold a line break)."""
    shown, used = [], 0
    for idx, i in enumerate(items):
        if used + len(i.text) + 2 > WA_LIST_MAX and shown:
            shown.append(f"and {len(items) - idx} more, see the app")
            break
        shown.append(i.text)
        used += len(i.text) + 2
    flat = "; ".join(shown).replace("\n", " ")
    return {"1": day_label(day), "2": summary_line(items).split(":")[0], "3": flat}


async def _already(db: AsyncSession, user_id: int, link: str) -> bool:
    found = await db.execute(
        select(AppNotification.id).where(
            AppNotification.user_id == user_id, AppNotification.kind == KIND, AppNotification.link == link,
        ).limit(1)
    )
    return found.first() is not None


def _why_not_whatsapp(settings: Settings, user: User, paused: str | None) -> str | None:
    if settings.daily_report_send_mode != "live":
        return "off"
    if not wa_send.can_send(settings):
        return "WhatsApp is not set up"
    if paused:
        return "sending is paused"
    if not reminders.may_send_to(settings, user.phone):
        return "number not on the allowlist"
    return None


async def _send_whatsapp(
    db: AsyncSession, settings: Settings, client: httpx.AsyncClient, user: User, day: date, items: list[Item], now: datetime,
) -> None:
    params = whatsapp_params(day, items)
    # The log wants a fire temple; the report is the mobed's own, so their first.
    agyary_id = (await db.execute(
        select(AgyaryUser.agyary_id).where(AgyaryUser.user_id == user.id, AgyaryUser.is_active.is_(True))
        .order_by(AgyaryUser.joined_at).limit(1)
    )).scalar_one_or_none()
    if agyary_id is None:
        return
    n = Notification(
        agyary_id=agyary_id, recipient_phone=user.phone, recipient_type="user", recipient_id=user.id,
        notification_type=KIND, template_name=settings.whatsapp_daily_report_template,
        template_params=params, scheduled_at=now, status="sending",
    )
    db.add(n)
    await db.flush()
    try:
        resp = await client.post(
            f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            json={
                "messaging_product": "whatsapp", "to": wa_send.to_number(user.phone), "type": "template",
                "template": {
                    "name": settings.whatsapp_daily_report_template,
                    "language": {"code": settings.whatsapp_template_language},
                    "components": [{"type": "body", "parameters": [
                        {"type": "text", "text": params[k]} for k in ("1", "2", "3")]}],
                },
            },
        )
        if resp.status_code == 200:
            try:
                n.wa_message_id = resp.json()["messages"][0]["id"]
            except (KeyError, IndexError, ValueError):
                pass
            n.status, n.sent_at = "sent", now
        else:
            try:
                why = str(resp.json()["error"]["message"])
            except (KeyError, ValueError, TypeError):
                why = f"HTTP {resp.status_code}"
            n.status, n.error_message = "failed", why[:500]
            logger.warning("Daily report to a mobed was not accepted (HTTP %s)", resp.status_code)
    except httpx.HTTPError as exc:
        n.status, n.error_message = "failed", f"no answer: {exc.__class__.__name__}"
    await db.flush()


async def run(
    db: AsyncSession, now: datetime, settings: Settings, client: httpx.AsyncClient | None = None,
) -> int:
    """One pass: leave tomorrow's report for each mobed who has asked for it and has
    not had it yet. Returns how many were made."""
    today = now.astimezone(IST).date()
    tomorrow = today + timedelta(days=1)
    link = f"#/calendar/day/{tomorrow.isoformat()}"

    users = (await db.execute(
        select(User).where(User.daily_report.is_(True), User.is_active.is_(True)).order_by(User.id)
    )).scalars().all()
    made = 0
    paused = await guardrails.paused_reason(db) if users else None
    own = None
    try:
        for user in users:
            if await _already(db, user.id, link):
                continue
            items = await tomorrows_items(db, user.id, tomorrow)
            if not items:
                continue
            await reminders.notify(
                db, user.id, KIND, f"Tomorrow: {len(items)} on your day", app_body(items), link=link, now=now,
            )
            made += 1
            if _why_not_whatsapp(settings, user, paused) is None:
                if client is None:
                    client = own = httpx.AsyncClient(timeout=20)
                await _send_whatsapp(db, settings, client, user, tomorrow, items, now)
            await db.flush()
    finally:
        if own is not None:
            await own.aclose()
    return made
