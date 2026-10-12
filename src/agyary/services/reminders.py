"""WhatsApp reminders to a family: who has agreed, and what a STOP does.

The agreement is made in person. A mobed asks the behdin and turns reminders
on for their own record of them (``Customer.reminders_enabled``); nothing is
ever sent to someone it has not been turned on for. A behdin can withdraw at
any time by replying STOP to a reminder. That is the person's, not any
mobed's: it is remembered against the number (``ReminderOptOut``), stops
every mobed's record of it (``Customer.reminders_stopped_at``), and tells
each mobed who had reminders on, in the app.

A STOP is final until a mobed says otherwise. Turning reminders back on for
someone who stopped needs an explicit confirmation, because the only honest
reason to do it is that they asked again.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import get_settings
from agyary.models import AppNotification, Customer, Memorial, MemorialObservance, ReminderOptOut

# How long a notification stays up. They are about what to do now, not a log.
NOTIFICATION_TTL = timedelta(hours=24)

KIND_REMINDER_STOPPED = "reminder_stopped"
KIND_MEMORIAL_CLOSING = "memorial_closing"

IST = ZoneInfo("Asia/Kolkata")

# What counts as a STOP (RM-4). The word on its own always does. So does a
# SHORT message that asks for the messages to stop in the family's own words -
# "please stop", "no more", "don't send", in Hindi or Gujarati - because a
# grieving family who writes that and keeps getting messages is the worse
# mistake: the mobed is shown what they wrote and can turn reminders back on.
# A long message, or one that asks for something NOT to stop ("please don't
# stop the Afringan"), is not a STOP; it is passed to the mobed instead.
_STOP = re.compile(r"^\s*(stop|unsubscribe)\s*[.!]*\s*$", re.IGNORECASE)
_STOP_SHORT = 60
_STOP_WORDS = re.compile(
    r"\b(stop|unsubscribe|unsub|no more|don\'?t send|do not send|band karo|bandh karo|band|bandh)\b"
    "|बंद"      # Hindi "band" (stop)
    "|બંધ",     # Gujarati "bandh" (stop)
    re.IGNORECASE,
)
_NOT_STOP = re.compile(r"\b(don\'?t|do not|never)\s+stop\b", re.IGNORECASE)


class ReminderError(Exception):
    """A refused change. ``code`` lets the caller tell the cases apart."""

    def __init__(self, message: str, code: str = "refused") -> None:
        super().__init__(message)
        self.code = code


def is_stop(text: str) -> bool:
    text = (text or "").replace("’", "'").strip()
    if _STOP.match(text):
        return True
    return len(text) <= _STOP_SHORT and bool(_STOP_WORDS.search(text)) and not _NOT_STOP.search(text)


def may_send_to(settings, phone: str) -> bool:
    """Whether REMINDERS_ALLOWLIST lets a live reminder go to ``phone``
    ("*" for everyone; empty for nobody)."""
    raw = settings.reminders_allowlist.strip()
    if raw == "*":
        return True
    return phone in {p.strip() for p in raw.split(",") if p.strip()}


def goes_automatically(
    settings, *, paused: bool, account_on: bool, customer: Customer, owner_user_id: int
) -> bool:
    """Whether the planner would send this family's reminder on its own - the
    one answer both the planner and the mobed's Reminders list use, so the list
    never promises a reminder that is not going to happen (RM-2)."""
    return (
        settings.reminders_send_mode == "live"
        and not paused
        and account_on
        and customer.owner_user_id == owner_user_id
        and customer.reminders_enabled
        and customer.reminders_stopped_at is None
        and customer.is_active
        and may_send_to(settings, customer.phone)
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def notify(
    db: AsyncSession,
    user_id: int,
    kind: str,
    title: str,
    body: str,
    *,
    link: str | None = None,
    agyary_id: int | None = None,
    now: datetime | None = None,
) -> AppNotification:
    """Leave something for a mobed to see the next time they open the app."""
    now = now or _now()
    note = AppNotification(
        user_id=user_id, agyary_id=agyary_id, kind=kind, title=title, body=body,
        link=link, created_at=now, expires_at=now + NOTIFICATION_TTL,
    )
    db.add(note)
    await db.flush()
    return note


async def reminder_state(db: AsyncSession, user_id: int, customer: Customer) -> dict:
    """Whether reminders are on for this behdin, and whether they ever said STOP."""
    return {
        "enabled": bool(customer.owner_user_id == user_id and customer.reminders_enabled),
        "stopped_at": customer.reminders_stopped_at.isoformat() if customer.reminders_stopped_at else None,
        # So the screen can say plainly whether anything is being sent yet.
        "delivery": get_settings().reminders_send_mode,
    }


async def set_reminders(
    db: AsyncSession,
    user_id: int,
    customer: Customer,
    enabled: bool,
    *,
    confirm_restart: bool = False,
    now: datetime | None = None,
) -> dict:
    """Turn reminders on or off for one of this mobed's behdins.

    Lifting a STOP ("they asked me to") lifts it for this mobed's record only:
    the person asked this mobed. Every other mobed's record of the number stays
    stopped, and so does the number itself for anyone who adds it later."""
    now = now or _now()
    if customer.owner_user_id != user_id:
        raise ReminderError("That behdin is not in your book.", "not_in_book")

    if enabled:
        if customer.reminders_stopped_at is not None:
            if not confirm_restart:
                raise ReminderError(
                    "This person replied STOP to a reminder. Turn reminders back on only "
                    "if they have asked you to.",
                    "stopped",
                )
            customer.reminders_stopped_at = None
        customer.reminders_enabled = True
        customer.reminders_enabled_at = now
    else:
        customer.reminders_enabled = False
        customer.reminders_enabled_at = None
    await db.flush()
    return await reminder_state(db, user_id, customer)


async def record_stop(db: AsyncSession, phone: str, *, said: str | None = None, now: datetime | None = None) -> int:
    """A person replied STOP from ``phone``. Returns how many mobeds were told.

    The STOP is the person's: it is remembered against the number (so a mobed
    who adds it later starts stopped), and it stops every mobed's record of it.
    Each mobed who had reminders on is told, about their own record.

    Idempotent: Meta redelivers webhooks, and people send STOP twice. The
    second one finds every record already stopped and tells nobody again.
    """
    now = now or _now()
    await db.execute(
        pg_insert(ReminderOptOut)
        .values(phone=phone, stopped_at=now)
        .on_conflict_do_update(index_elements=[ReminderOptOut.phone], set_={"stopped_at": now})
    )
    records = (
        await db.execute(
            select(Customer).where(Customer.phone == phone, Customer.reminders_stopped_at.is_(None))
        )
    ).scalars().all()

    told = 0
    for customer in records:
        customer.reminders_stopped_at = now
        if not customer.reminders_enabled:
            continue
        customer.reminders_enabled = False
        customer.reminders_enabled_at = None
        if customer.owner_user_id is None:
            continue
        await notify(
            db, customer.owner_user_id, KIND_REMINDER_STOPPED,
            f"{customer.name} stopped reminders",
            f"{customer.name} replied STOP, so WhatsApp reminders to them are now off. "
            + (f'They wrote: "{said[:200]}". ' if said and not _STOP.match(said) else "")
            + "Turn them back on only if they ask you to.",
            link=f"#/behdins/{customer.id}", now=now,
        )
        told += 1
    await db.flush()
    return told


KIND_BEHDIN_REPLY = "behdin_reply"
REPLY_WINDOW = timedelta(days=30)


async def forward_reply(
    db: AsyncSession, phone: str, text: str, *, context_id: str | None = None, now: datetime | None = None
) -> bool:
    """Pass what a family wrote back to the mobed whose reminder it answers
    (RM-4). Returns whether anyone was told.

    Whose: the reminder the message replies to, when WhatsApp says which; else
    the mobed who last reminded this number in the past month. Only that one
    mobed, about their own record (D2): another mobed who keeps the same family
    learns nothing. A number we never reminded reaches nobody - it is someone
    messaging the number, not a family answering."""
    from agyary.models import Notification

    now = now or _now()
    TYPE = "memorial_reminder"
    reminder = None
    if context_id:
        reminder = (
            await db.execute(
                select(Notification).where(Notification.notification_type == TYPE,
                                           Notification.wa_message_id == context_id)
            )
        ).scalar_one_or_none()
    if reminder is None:
        reminder = (
            await db.execute(
                select(Notification)
                .where(
                    Notification.notification_type == TYPE,
                    Notification.recipient_phone == phone,
                    Notification.status.in_(("sent", "delivered", "read")),
                    Notification.sent_at > now - REPLY_WINDOW,
                )
                .order_by(Notification.sent_at.desc(), Notification.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if reminder is None or reminder.recipient_phone != phone:
        return False
    customer = await db.get(Customer, reminder.recipient_id) if reminder.recipient_id else None
    if customer is None or customer.owner_user_id is None:
        return False
    await notify(
        db, customer.owner_user_id, KIND_BEHDIN_REPLY, f"{customer.name} replied on WhatsApp",
        f'"{text.strip()[:300]}"', link=f"#/behdins/{customer.id}", now=now,
    )
    await db.flush()
    return True


async def notify_closing_tomorrow(db: AsyncSession, now: datetime | None = None) -> int:
    """Tell each mobed whose memorial has its LAST prayer tomorrow, so the end
    of a family's observances is not something they find out on the day.

    Independent of WhatsApp: it only leaves a notice in the app, so it runs
    whether or not reminders are being sent. At most one notice per memorial
    (it is looked for before it is made, which is what lets the loop call this
    every minute of the evening). Returns how many were made.
    """
    now = now or _now()
    tomorrow = now.astimezone(IST).date() + timedelta(days=1)
    last = (
        select(MemorialObservance.memorial_id, func.max(MemorialObservance.gregorian_date).label("last_date"))
        .group_by(MemorialObservance.memorial_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(Memorial, Customer.name)
            .join(last, last.c.memorial_id == Memorial.id)
            .join(Customer, Customer.id == Memorial.customer_id)
            .where(last.c.last_date == tomorrow)
        )
    ).all()

    made = 0
    for memorial, behdin_name in rows:
        link = f"#/memorial/{memorial.id}"
        already = (
            await db.execute(
                select(AppNotification.id).where(
                    AppNotification.user_id == memorial.created_by_user_id,
                    AppNotification.kind == KIND_MEMORIAL_CLOSING,
                    AppNotification.link == link,
                    AppNotification.created_at > now - timedelta(days=2),
                )
            )
        ).first()
        if already:
            continue
        await notify(
            db, memorial.created_by_user_id, KIND_MEMORIAL_CLOSING,
            f"Last prayer for {memorial.departed_name} is tomorrow",
            f"After tomorrow there are no more prayers for {memorial.departed_name} "
            f"({behdin_name}). The memorial will close.",
            link=link, agyary_id=memorial.agyary_id, now=now,
        )
        made += 1
    await db.flush()
    return made
