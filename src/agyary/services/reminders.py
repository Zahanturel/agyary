"""WhatsApp reminders to a family: who has agreed, and what a STOP does.

The agreement is made in person. A mobed asks the behdin and turns reminders
on for them (``UserCustomer.reminders_enabled``); nothing is ever sent to
someone it has not been turned on for. A behdin can withdraw at any time by
replying STOP to a reminder, which is recorded on the person
(``Customer.reminders_stopped_at``), switches reminders off for every mobed
who had them on, and tells each of those mobeds in the app.

A STOP is final until a mobed says otherwise. Turning reminders back on for
someone who stopped needs an explicit confirmation, because the only honest
reason to do it is that they asked again.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import get_settings
from agyary.models import AppNotification, Customer, UserCustomer

# How long a notification stays up. They are about what to do now, not a log.
NOTIFICATION_TTL = timedelta(hours=24)

KIND_REMINDER_STOPPED = "reminder_stopped"

# What counts as a STOP: the word on its own, in any case, with the odd
# bit of punctuation. "Stop" inside a longer sentence is not one - someone
# writing "please don't stop the Afringan" must not be unsubscribed.
_STOP = re.compile(r"^\s*(stop|unsubscribe)\s*[.!]*\s*$", re.IGNORECASE)


class ReminderError(Exception):
    """A refused change. ``code`` lets the caller tell the cases apart."""

    def __init__(self, message: str, code: str = "refused") -> None:
        super().__init__(message)
        self.code = code


def is_stop(text: str) -> bool:
    return bool(_STOP.match(text or ""))


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
    row = await db.get(UserCustomer, (user_id, customer.id))
    return {
        "enabled": bool(row and row.reminders_enabled),
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
    """Turn reminders on or off for one of this mobed's behdins."""
    now = now or _now()
    row = await db.get(UserCustomer, (user_id, customer.id))
    if row is None:
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
        row.reminders_enabled = True
        row.reminders_enabled_at = now
    else:
        row.reminders_enabled = False
        row.reminders_enabled_at = None
    await db.flush()
    return await reminder_state(db, user_id, customer)


async def record_stop(db: AsyncSession, phone: str, *, now: datetime | None = None) -> int:
    """A person replied STOP from ``phone``. Returns how many mobeds were told.

    Idempotent: Meta redelivers webhooks, and people send STOP twice. The
    second one finds them already stopped and does nothing, so no mobed is
    told twice.
    """
    now = now or _now()
    customer = (
        await db.execute(select(Customer).where(Customer.phone == phone))
    ).scalar_one_or_none()
    if customer is None or customer.reminders_stopped_at is not None:
        return 0

    customer.reminders_stopped_at = now
    rows = (
        await db.execute(
            select(UserCustomer).where(
                UserCustomer.customer_id == customer.id, UserCustomer.reminders_enabled.is_(True)
            )
        )
    ).scalars().all()
    for row in rows:
        row.reminders_enabled = False
        row.reminders_enabled_at = None
        await notify(
            db, row.user_id, KIND_REMINDER_STOPPED,
            f"{customer.name} stopped reminders",
            f"{customer.name} replied STOP, so WhatsApp reminders to them are now off. "
            "Turn them back on only if they ask you to.",
            link=f"#/behdins/{customer.id}", now=now,
        )
    await db.flush()
    return len(rows)
