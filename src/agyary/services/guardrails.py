"""Keeping reminder sending from costing more than it should.

Every reminder is a paid WhatsApp message to a real family, so the loop that
sends them is the one place a bug, a bad actor or a billing surprise could turn
into a real bill. Four things stand between that and us:

  caps      a ceiling on messages per day and month overall, and per mobed and
            per fire temple per day. A reminder over a cap is not sent; the mobed
            is told so they can send it by hand, and the admins are alerted.
  pause     one switch that stops all sending at once. An admin flips it from
            their phone; it survives a restart.
  breaker   the loop pauses itself on the first sign of an account-level problem
            from Meta (an invalid token, a payment problem, throttling) and after
            several failures in a row, rather than keep trying.
  alerts    when a cap or the breaker trips, the admins find out in the app, and
            in the server log at ERROR.

Meta's prepaid balance is a fifth, outermost limit: with no auto top-up, spending
cannot exceed what was put in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import AppNotification, AppSetting, Memorial, MemorialObservance, Notification, User

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
TYPE = "memorial_reminder"

KEY_PAUSED = "reminders_paused"
KIND_ALERT = "alert"
ALERT_DEDUPE = timedelta(hours=6)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Who is an admin
# ---------------------------------------------------------------------------
def admin_phones(settings: Settings) -> set[str]:
    return {p.strip() for p in settings.admin_phones.split(",") if p.strip()}


def is_admin(settings: Settings, phone: str) -> bool:
    return phone in admin_phones(settings)


# ---------------------------------------------------------------------------
# The pause switch
# ---------------------------------------------------------------------------
async def paused_reason(db: AsyncSession) -> str | None:
    """Why sending is paused, or None if it is running."""
    row = await db.get(AppSetting, KEY_PAUSED)
    return row.value if row and row.value else None


async def _set(db: AsyncSession, key: str, value: str, user_id: int | None) -> None:
    row = await db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value, updated_by_user_id=user_id))
    else:
        row.value, row.updated_by_user_id = value, user_id
    await db.flush()


async def pause(
    db: AsyncSession, settings: Settings, reason: str, *, user_id: int | None = None,
    now: datetime | None = None,
) -> None:
    """Stop all reminder sending, and tell the admins why."""
    await _set(db, KEY_PAUSED, reason, user_id)
    logger.error("Reminder sending PAUSED: %s", reason)
    await alert_admins(db, settings, "Reminder sending is paused", reason, now=now)


async def resume(db: AsyncSession, *, user_id: int | None = None) -> None:
    await _set(db, KEY_PAUSED, "", user_id)
    logger.warning("Reminder sending RESUMED")


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
async def alert_admins(
    db: AsyncSession, settings: Settings, title: str, body: str, *, now: datetime | None = None
) -> int:
    """Leave an alert for every admin, unless they were already given this one
    in the last few hours - the loop runs every minute, and a tripped cap must
    not become sixty alerts an hour. Returns how many were made."""
    from agyary.services import reminders  # here: reminders imports models only, but keep it lazy

    now = now or _now()
    phones = admin_phones(settings)
    if not phones:
        logger.error("ALERT (no admin_phones set, so nobody was told): %s - %s", title, body)
        return 0
    admins = (await db.execute(select(User.id).where(User.phone.in_(phones)))).scalars().all()
    made = 0
    for uid in admins:
        recent = (
            await db.execute(
                select(AppNotification.id).where(
                    AppNotification.user_id == uid,
                    AppNotification.kind == KIND_ALERT,
                    AppNotification.title == title,
                    AppNotification.created_at > now - ALERT_DEDUPE,
                )
            )
        ).first()
        if recent:
            continue
        await reminders.notify(db, uid, KIND_ALERT, title, body, link="#/admin", now=now)
        made += 1
    return made


# ---------------------------------------------------------------------------
# Counting what has been planned or sent
# ---------------------------------------------------------------------------
def day_bounds(now: datetime) -> tuple[datetime, datetime]:
    today = now.astimezone(IST).date()
    start = datetime.combine(today, time.min, tzinfo=IST)
    return start, start + timedelta(days=1)


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(IST)
    start = datetime(local.year, local.month, 1, tzinfo=IST)
    nxt = datetime(local.year + (local.month == 12), local.month % 12 + 1, 1, tzinfo=IST)
    return start, nxt


@dataclass
class Usage:
    """Reminders planned or sent in the current IST day and month. Failed ones
    are not counted: they were not sent, so they cost nothing."""

    today: int = 0
    month: int = 0
    per_mobed: dict[int, int] = field(default_factory=dict)
    per_agyary: dict[int, int] = field(default_factory=dict)

    def blocker(self, settings: Settings, owner_id: int | None, agyary_id: int | None) -> str | None:
        """The name of the cap that forbids one more reminder, or None."""
        if self.today >= settings.reminders_daily_cap:
            return "the daily limit for all fire temples"
        if self.month >= settings.reminders_monthly_cap:
            return "the monthly limit for all fire temples"
        if owner_id is not None and self.per_mobed.get(owner_id, 0) >= settings.reminders_per_mobed_daily_cap:
            return "your daily limit"
        if agyary_id is not None and self.per_agyary.get(agyary_id, 0) >= settings.reminders_per_agyary_daily_cap:
            return "this fire temple's daily limit"
        return None

    def add(self, owner_id: int | None, agyary_id: int | None) -> None:
        self.today += 1
        self.month += 1
        if owner_id is not None:
            self.per_mobed[owner_id] = self.per_mobed.get(owner_id, 0) + 1
        if agyary_id is not None:
            self.per_agyary[agyary_id] = self.per_agyary.get(agyary_id, 0) + 1


async def usage(db: AsyncSession, now: datetime) -> Usage:
    day_start, day_end = day_bounds(now)
    month_start, month_end = month_bounds(now)
    counted = (Notification.notification_type == TYPE, Notification.status != "failed")
    month_total = (
        await db.execute(
            select(func.count()).where(
                *counted, Notification.created_at >= month_start, Notification.created_at < month_end
            )
        )
    ).scalar_one()
    day_total = (
        await db.execute(
            select(func.count()).where(
                *counted, Notification.created_at >= day_start, Notification.created_at < day_end
            )
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(Memorial.created_by_user_id, Notification.agyary_id, func.count())
            .select_from(Notification)
            .join(MemorialObservance, MemorialObservance.id == Notification.memorial_observance_id)
            .join(Memorial, Memorial.id == MemorialObservance.memorial_id)
            .where(
                Notification.notification_type == TYPE, Notification.status != "failed",
                Notification.created_at >= day_start, Notification.created_at < day_end,
            )
            .group_by(Memorial.created_by_user_id, Notification.agyary_id)
        )
    ).all()
    # The totals count every reminder, even one whose observance has since been
    # deleted and so has no owner; the per-mobed and per-temple figures can only
    # count those that still do.
    out = Usage(today=day_total, month=month_total)
    for owner, agyary, n in rows:
        out.per_mobed[owner] = out.per_mobed.get(owner, 0) + n
        out.per_agyary[agyary] = out.per_agyary.get(agyary, 0) + n
    return out


def estimated_cost_inr(settings: Settings, messages: int) -> float:
    return round(messages * settings.reminders_cost_per_message_inr, 2)


def today_ist(now: datetime) -> date:
    return now.astimezone(IST).date()
