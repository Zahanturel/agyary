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
import unicodedata
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

# The words a mobed says to the family before turning reminders on (RM-6). They
# name the business that will message them and say how to stop, which is what
# Meta's opt-in rules expect. Change the words, change the version: each
# agreement keeps the version that was read out.
CONSENT_VERSION = "2026-10-a"
CONSENT_TEXT = (
    "May Mobed Diary send you a short WhatsApp message the evening before each of "
    "these prayers? It comes from the Mobed Diary number, not from me. You can stop "
    "them at any time by replying STOP."
)
KIND_MEMORIAL_CLOSING = "memorial_closing"

IST = ZoneInfo("Asia/Kolkata")

# What counts as a STOP (RM-4): the whole message is one of these phrases, in
# any case, with any spacing, trailing punctuation or emoji, and "please" or
# "thanks" around it - "STOP", " stop. ", "Stop reminders please", "Cancel",
# "Unsubscribe me", "बंद करो". Only the whole message: a sentence that merely
# contains the word ("please stop by the agyary tomorrow", "please don't stop
# the Afringan") is not a STOP; it is passed to the mobed, who sees what was
# written. The usual SMS keywords (STOP, STOPALL, UNSUBSCRIBE, CANCEL, END, QUIT)
# are all here.
_STOP = re.compile(r"^\s*(stop|unsubscribe)\s*[.!]*\s*$", re.IGNORECASE)
_STOP_PHRASES = frozenset({
    "stop", "stopall", "stop all", "stop it", "stop this", "stop these", "end", "quit",
    "stop reminder", "stop reminders", "stop the reminders", "stop all reminders",
    "stop message", "stop messages", "stop the messages", "stop all messages", "stop these messages",
    "stop sending", "stop sending these", "stop sending messages", "stop sending reminders",
    "unsubscribe", "unsub", "cancel", "cancel reminders", "cancel the reminders", "cancel all reminders",
    "opt out", "opt-out", "optout",
    "no more", "no more messages", "no more reminders",
    "don't send", "dont send", "do not send", "don't send these", "dont send these", "do not send these",
    "don't send messages", "do not send messages",
    "band", "bandh", "band karo", "bandh karo", "band kar do", "bandh kar do", "mat bhejo",
    "बंद", "बंद करो", "बंद कर दो", "मत भेजो",           # Hindi
    "બંધ", "બંધ કરો", "બંધ કરી દો",                    # Gujarati
})
_POLITE_BEFORE = ("please ", "pls ", "plz ", "kindly ")
_POLITE_AFTER = (" please", " pls", " plz", " thanks", " thank you", " me", " now")


def _trim(text: str) -> str:
    """Drop spaces, punctuation and symbols (emoji included) from both ends -
    but not the vowel signs Hindi and Gujarati words end in."""
    def edge(c: str) -> bool:
        return c.isspace() or unicodedata.category(c)[0] in "PS"

    start, end = 0, len(text)
    while start < end and edge(text[start]):
        start += 1
    while end > start and edge(text[end - 1]):
        end -= 1
    return text[start:end]


class ReminderError(Exception):
    """A refused change. ``code`` lets the caller tell the cases apart."""

    def __init__(self, message: str, code: str = "refused") -> None:
        super().__init__(message)
        self.code = code


def is_stop(text: str) -> bool:
    text = _trim(" ".join((text or "").replace("’", "'").casefold().split()))
    while True:
        before = text
        for word in _POLITE_BEFORE:
            if text.startswith(word):
                text = _trim(text[len(word):])
        for word in _POLITE_AFTER:
            if text.endswith(word):
                text = _trim(text[: -len(word)])
        if text == before:
            return text in _STOP_PHRASES


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
    consent_version: str | None = None,
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
        if consent_version is not None and consent_version != CONSENT_VERSION:
            raise ReminderError(
                "The words to read to the family have changed. Please open this page again "
                "and read them the new words first.",
                "stale_consent",
            )
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
        customer.reminders_consent_version = CONSENT_VERSION
    else:
        customer.reminders_enabled = False
        customer.reminders_enabled_at = None
        customer.reminders_consent_version = None
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

# The one reply a STOP gets (once per number, ever). Plain text inside the
# window the STOP opened; since 1 Oct 2026 Meta charges it at about the utility
# rate, so it has its own daily cap.
STOP_ACK_TEXT = "You will not receive any more reminders from {mobed}. May you and your family be in peace."


async def _answered_record(
    db: AsyncSession, phone: str, context_id: str | None, now: datetime
) -> Customer | None:
    """The record (and so the mobed) whose reminder a message from ``phone``
    answers: the reminder it replies to, when WhatsApp says which; else the one
    last sent to that number in the past month. None for a number we never
    reminded."""
    from agyary.models import Notification

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
        return None
    customer = await db.get(Customer, reminder.recipient_id) if reminder.recipient_id else None
    if customer is None or customer.owner_user_id is None:
        return None
    return customer


async def already_stopped(db: AsyncSession, phone: str) -> bool:
    """Whether this number had replied STOP before (a STOP is never forgotten)."""
    return await db.get(ReminderOptOut, phone) is not None


async def acknowledge_stop(
    db: AsyncSession, settings, phone: str, *, context_id: str | None = None,
    now: datetime | None = None, client=None,
) -> str:
    """Answer a family's first STOP with one short, kind line naming their
    mobed. Call it only for a number that had not stopped before - the caller
    checks, before recording the STOP - so a second STOP, or Meta delivering
    the same one twice, gets nothing.

    Sent only while reminders are live, not paused, under its own daily cap,
    and only to a number we actually reminded. Returns what happened."""
    from agyary.models import User
    from agyary.services import guardrails, wa_send

    now = now or _now()
    if settings.reminders_send_mode != "live" or not wa_send.can_send(settings):
        return "not sending"
    if await guardrails.paused_reason(db):
        return "paused"
    customer = await _answered_record(db, phone, context_id, now)
    if customer is None:
        return "never reminded"
    start, end = guardrails.day_bounds(now)
    today = (
        await db.execute(
            select(func.count()).select_from(ReminderOptOut).where(
                ReminderOptOut.acknowledged_at >= start, ReminderOptOut.acknowledged_at < end)
        )
    ).scalar_one()
    if today >= settings.reminders_stop_ack_daily_cap:
        return "over the daily limit"
    mobed = await db.get(User, customer.owner_user_id)
    name = (mobed.name or "").strip() if mobed else ""
    text = STOP_ACK_TEXT.format(mobed=name or "your mobed")
    if not await wa_send.send_text(settings, phone, text, client=client):
        return "failed"
    row = await db.get(ReminderOptOut, phone)
    if row is not None:
        row.acknowledged_at = now
    await db.flush()
    return "sent"


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
    now = now or _now()
    customer = await _answered_record(db, phone, context_id, now)
    if customer is None:
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
