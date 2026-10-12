"""Sending memorial reminders automatically.

Two steps, kept apart so each can be checked on its own:

  plan_tomorrow  decides WHO is reminded of WHAT and writes one pending row per
                 observance. It is the only place that applies the rules - the
                 behdin agreed, has not said STOP, is past the opening days -
                 so a row that exists is a row that is allowed to be sent.
  send_pending   takes pending rows and posts them to Meta.

A reminder is sent at most once per observance: the rows are unique on it, so
planning twice (a restart, two deploys overlapping) plans once. And each row
is committed the moment Meta accepts it, so a crash between two sends can
never send the first again.

Nothing leaves unless ``reminders_send_mode`` is "live", and then only to the
numbers in ``reminders_allowlist`` (or everyone, if it is "*"). "dry_run"
plans and logs without writing anything, so it can be run any number of times
and still leave the real run untouched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agyary.core.config import Settings
from agyary.models import (
    Agyary,
    Customer,
    Memorial,
    MemorialObservance,
    Notification,
    Service,
    User,
)
from agyary.services import guardrails, reminder_message, reminders, template_text
from agyary.services.memorials import OPENING_DAYS

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
TYPE = "memorial_reminder"

# A reminder that will not send is retried this many times, then given up on
# and the mobed told, rather than hammered all evening. The spend ceilings (per
# day, month, mobed and fire temple) are in guardrails and the settings.
MAX_ATTEMPTS = 3

# Meta error codes that say something is wrong with the ACCOUNT, not with one
# recipient, so carrying on only repeats the problem: an invalid or expired
# token (190), a payment or eligibility problem (131042), a locked account
# (131031), spam or throughput limits (131048, 130429, 80007), a policy block
# (368), and a template that is missing, paused or disabled (132001, 132015,
# 132016). Any of them pauses all sending.
ACCOUNT_CODES = {190, 131042, 131031, 131048, 130429, 80007, 368, 132001, 132015, 132016}
# Codes that are about one recipient (not on WhatsApp, not allowed to receive):
# they fail that reminder but never count toward pausing everything.
RECIPIENT_CODES = {131026, 131021, 131030}


@dataclass
class Report:
    planned: int = 0
    sent: int = 0
    failed: int = 0
    missed: int = 0
    closing: int = 0
    notes: list[str] = field(default_factory=list)


# Which dry-run reminders have already been logged, so they are not repeated
# every tick. Per process; a restart logs them once more, which is what you
# want when you restart to look.
_dry_run_logged: set[tuple[int, object]] = set()


def reset_dry_run_log() -> None:
    _dry_run_logged.clear()


class _Permanent(Exception):
    """Meta refused it and asking again will not help (a bad number, a
    template that is not approved). ``code`` is Meta's error code, if it gave one."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class _AccountProblem(_Permanent):
    """Something is wrong with the account itself - the token, payment, a
    throttle, the template - so every send will hit it. Pauses all sending."""


class _Transient(Exception):
    """A network problem or a Meta outage; worth trying again."""


def _allowlist(settings: Settings) -> set[str] | None:
    """None means everyone."""
    raw = settings.reminders_allowlist.strip()
    if raw == "*":
        return None
    return {p.strip() for p in raw.split(",") if p.strip()}


def _may_send_to(settings: Settings, phone: str) -> bool:
    allowed = _allowlist(settings)
    return allowed is None or phone in allowed


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
def _masked(phone: str) -> str:
    """Enough of a number to tell two apart in a log, not enough to read it."""
    return f"{phone[:3]}...{phone[-2:]}" if len(phone) > 6 else "..."


def _text_problem(agyary_name: str, departed: str, services: list[str]) -> str | None:
    """Why this reminder's free text cannot go out, or None. The same rules as
    where the text is typed (template_text), for anything saved before them."""
    checks = [(agyary_name, template_text.TEMPLE_MAX), (departed, template_text.DEPARTED_MAX)]
    checks += [(name, template_text.SERVICE_MAX) for name in services]
    for text_, max_len in checks:
        if template_text.problem(text_, max_len=max_len):
            return "its wording cannot be sent automatically (a temple, service or departed name)"
    return None


async def _owner_caps(db: AsyncSession, settings: Settings, owner_ids: set[int], now: datetime) -> dict[int, int]:
    """The daily cap for each account in its first days (D1): a handful, until
    it is older than reminders_new_account_days or the owner vouches for it
    (REMINDERS_VOUCHED) - admins are trusted. Accounts not listed have only
    the ordinary per-mobed cap."""
    vouched = {p.strip() for p in settings.reminders_vouched.split(",") if p.strip()}
    vouched |= guardrails.admin_phones(settings)
    young = now - timedelta(days=settings.reminders_new_account_days)
    users = (await db.execute(select(User.id, User.phone, User.created_at).where(User.id.in_(owner_ids)))).all()
    return {
        uid: settings.reminders_new_account_daily_cap
        for uid, phone, created_at in users
        if created_at > young and phone not in vouched
    }


async def plan_tomorrow(db: AsyncSession, now: datetime, settings: Settings) -> int:
    """Write a pending reminder for every observance tomorrow that may be
    reminded. Returns how many were newly planned (in dry_run, how many would be).

    What may be reminded: the family agreed (on the memorial's own mobed's
    record), has not said STOP, is past the opening days, is on the allowlist
    in live mode; the text passes the rules for paid messages; no other
    reminder goes to that number that day; and no cap - overall, per mobed
    (lower for a new account), per fire temple - is reached."""
    mode = settings.reminders_send_mode
    if mode == "off":
        return 0
    today = now.astimezone(IST).date()
    tomorrow = today + timedelta(days=1)

    rows = (
        await db.execute(
            select(MemorialObservance, Memorial, Customer, Agyary.name)
            .join(Memorial, Memorial.id == MemorialObservance.memorial_id)
            .join(Customer, Customer.id == Memorial.customer_id)
            .join(Agyary, Agyary.id == Memorial.agyary_id)
            .options(selectinload(MemorialObservance.services))
            .where(
                MemorialObservance.gregorian_date == tomorrow,
                MemorialObservance.day_number > OPENING_DAYS,
                # The memorial's own mobed's record of the family, with their consent.
                Customer.owner_user_id == Memorial.created_by_user_id,
                Customer.reminders_enabled.is_(True),
                Customer.reminders_stopped_at.is_(None),
                Customer.is_active.is_(True),
            )
            .order_by(MemorialObservance.id)
        )
    ).all()

    service_names: dict[int, dict[int, str]] = {}
    used = await guardrails.usage(db, now)
    owner_caps = await _owner_caps(db, settings, {m.created_by_user_id for _, m, _, _ in rows}, now)
    # Numbers already given a reminder today (planned or sent): one per number per day.
    day_start, day_end = guardrails.day_bounds(now)
    reminded = set(
        (
            await db.execute(
                select(Notification.recipient_phone).where(
                    Notification.notification_type == TYPE, Notification.status != "failed",
                    Notification.created_at >= day_start, Notification.created_at < day_end,
                )
            )
        ).scalars()
    )
    blocked: dict[str, int] = {}
    planned = 0
    for obs, memorial, customer, agyary_name in rows:
        if mode == "live" and not _may_send_to(settings, customer.phone):
            continue
        if await _already_planned(db, obs.id):
            continue

        if memorial.agyary_id not in service_names:
            found = await db.execute(select(Service.id, Service.name).where(Service.agyary_id == memorial.agyary_id))
            service_names[memorial.agyary_id] = dict(found.all())
        names = service_names[memorial.agyary_id]
        services = [names.get(s.service_id, "") for s in sorted(obs.services, key=lambda s: s.service_id)
                    if names.get(s.service_id)]

        why = _text_problem(agyary_name, memorial.departed_name, services)
        if why is None and customer.phone in reminded:
            why = "only one automatic reminder goes to a number each day"
        if why is not None:
            if mode == "live":
                await _record_not_sent(db, settings, obs, memorial, customer, why, now)
            continue

        # The ceilings: a reminder over any of them is not sent, the mobed is
        # told (so they can send it by hand), and the admins are alerted below.
        limit = used.blocker(
            settings, memorial.created_by_user_id, memorial.agyary_id,
            owner_cap=owner_caps.get(memorial.created_by_user_id),
        )
        if limit:
            blocked[limit] = blocked.get(limit, 0) + 1
            if mode == "live":
                await _record_not_sent(db, settings, obs, memorial, customer, f"{limit} was reached", now)
            continue

        parts = reminder_message.build_parts(agyary_name, obs, memorial.departed_name, services, today)

        if mode == "dry_run":
            # The loop runs every minute for two hours; say it once. The words
            # are on the mobed's Reminders list; the log needs no family's number.
            if (obs.id, tomorrow) not in _dry_run_logged:
                _dry_run_logged.add((obs.id, tomorrow))
                logger.info("DRY RUN - would send observance %s to %s", obs.id, _masked(customer.phone))
            planned += 1
            reminded.add(customer.phone)
            used.add(memorial.created_by_user_id, memorial.agyary_id)
            continue

        inserted = await db.execute(
            pg_insert(Notification)
            .values(
                agyary_id=memorial.agyary_id,
                recipient_phone=customer.phone,
                recipient_type="customer",
                recipient_id=customer.id,
                notification_type=TYPE,
                template_name=settings.whatsapp_reminder_template,
                template_params={str(i): v for i, v in enumerate(parts.as_params(), start=1)},
                memorial_observance_id=obs.id,
                scheduled_at=now,
                created_at=now,
                status="pending",
            )
            .on_conflict_do_nothing(
                index_elements=[Notification.memorial_observance_id],
                index_where=text("notification_type = 'memorial_reminder'"),
            )
        )
        if inserted.rowcount:
            planned += 1
            reminded.add(customer.phone)
            used.add(memorial.created_by_user_id, memorial.agyary_id)
    if blocked:
        await guardrails.alert_admins(
            db, settings, "Reminder limit reached",
            "; ".join(f"{n} reminder{'s' if n != 1 else ''} not sent because of {why}" for why, n in blocked.items())
            + ". Raise the limit in the server settings if this is expected.",
            now=now,
        )
    await db.flush()
    return planned


async def _already_planned(db: AsyncSession, observance_id: int) -> bool:
    """Whether this observance already has its one reminder row (planned, sent
    or given up on) - the loop asks every minute, and the answer must not change."""
    found = await db.execute(
        select(Notification.id).where(
            Notification.notification_type == TYPE, Notification.memorial_observance_id == observance_id
        )
    )
    return found.first() is not None


async def _record_not_sent(
    db: AsyncSession, settings: Settings, obs, memorial, customer, why: str, now: datetime
) -> None:
    """Note a reminder that will not go automatically, and tell its mobed - once.
    The row is unique on the observance, so the loop asking every minute does
    not tell them every minute; and it shows on their Reminders list as not sent."""
    inserted = await db.execute(
        pg_insert(Notification)
        .values(
            agyary_id=memorial.agyary_id,
            recipient_phone=customer.phone,
            recipient_type="customer",
            recipient_id=customer.id,
            notification_type=TYPE,
            template_name=settings.whatsapp_reminder_template,
            memorial_observance_id=obs.id,
            scheduled_at=now,
            created_at=now,
            status="failed",
            error_message=f"Not sent: {why}"[:500],
        )
        .on_conflict_do_nothing(
            index_elements=[Notification.memorial_observance_id],
            index_where=text("notification_type = 'memorial_reminder'"),
        )
    )
    if inserted.rowcount:
        await reminders.notify(
            db, memorial.created_by_user_id, "reminder_failed", f"Reminder to {customer.name} was not sent",
            f"We did not send tomorrow's reminder to {customer.name} automatically: {why}. "
            "You can still send it yourself with Remind on WhatsApp in the Reminders list.",
            link="#/reminders", agyary_id=memorial.agyary_id, now=now,
        )


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
def _payload(n: Notification, settings: Settings) -> dict:
    params = [n.template_params[k] for k in sorted(n.template_params, key=int)]
    return {
        "messaging_product": "whatsapp",
        "to": n.recipient_phone.lstrip("+"),
        "type": "template",
        "template": {
            "name": n.template_name,
            "language": {"code": settings.whatsapp_template_language},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}],
        },
    }


async def _post(client: httpx.AsyncClient, n: Notification, settings: Settings) -> str:
    """Send one template message; returns Meta's message id."""
    url = f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{settings.whatsapp_phone_number_id}/messages"
    try:
        resp = await client.post(
            url, json=_payload(n, settings), headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"}
        )
    except httpx.HTTPError as exc:
        raise _Transient(f"network error: {exc.__class__.__name__}") from exc

    if resp.status_code == 200:
        try:
            return resp.json()["messages"][0]["id"]
        except (KeyError, IndexError, ValueError) as exc:
            raise _Transient("Meta accepted the message but sent no id") from exc

    code = None
    try:
        error = resp.json()["error"]
        reason, code = error["message"], error.get("code")
    except (KeyError, ValueError, TypeError):
        reason = f"HTTP {resp.status_code}"
    if code in ACCOUNT_CODES:
        raise _AccountProblem(reason, code)
    # 4xx (except "slow down") is a refusal that repeating will not change.
    if 400 <= resp.status_code < 500 and resp.status_code != 429:
        raise _Permanent(reason, code)
    raise _Transient(reason)


async def _owner_and_name(db: AsyncSession, n: Notification) -> tuple[int | None, str]:
    """The mobed who set this reminder up, and the behdin's name."""
    name = "a behdin"
    if n.recipient_id:
        found = await db.get(Customer, n.recipient_id)
        if found:
            name = found.name
    if n.memorial_observance_id is None:
        return None, name
    owner = (
        await db.execute(
            select(Memorial.created_by_user_id)
            .join(MemorialObservance, MemorialObservance.memorial_id == Memorial.id)
            .where(MemorialObservance.id == n.memorial_observance_id)
        )
    ).scalar_one_or_none()
    return owner, name


async def _withdrawn(db: AsyncSession, n: Notification) -> str | None:
    """Why this reminder must not go after all, or None if it may."""
    customer = await db.get(Customer, n.recipient_id) if n.recipient_id else None
    if customer is None or not customer.is_active:
        return "The behdin is no longer on file"
    if customer.reminders_stopped_at is not None:
        return "Replied STOP before it was sent"
    owner, _ = await _owner_and_name(db, n)
    if owner is None or customer.owner_user_id != owner or not customer.reminders_enabled:
        return "Reminders were turned off before it was sent"
    return None


async def _tell_mobed_failed(db: AsyncSession, n: Notification, why: str, now: datetime) -> None:
    owner, name = await _owner_and_name(db, n)
    if owner is None:
        return
    await reminders.notify(
        db, owner, "reminder_failed", f"Reminder to {name} was not sent",
        f"We could not send tomorrow's reminder to {name} ({why}). You can still send it "
        "yourself with Remind on WhatsApp in the Reminders list.",
        link="#/reminders", agyary_id=n.agyary_id, now=now,
    )


async def send_pending(
    db: AsyncSession, client: httpx.AsyncClient, now: datetime, settings: Settings
) -> Report:
    """Send what planning queued. One row at a time, committed as it goes."""
    report = Report()
    if settings.reminders_send_mode != "live":
        return report
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        logger.error("Reminders are live but WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID are not set")
        return report

    paused = await guardrails.paused_reason(db)
    if paused:
        logger.warning("Reminder sending is paused (%s); nothing will be sent", paused)

    local = now.astimezone(IST)
    sent_for: dict[int, list[str]] = {}
    streak = 0            # failures in a row, not counting a single bad number
    while True:
        n = (
            await db.execute(
                select(Notification)
                .where(Notification.notification_type == TYPE, Notification.status == "pending",
                       Notification.scheduled_at <= now)
                .order_by(Notification.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if n is None:
            break

        # Too late to say "tomorrow": it is past the cutoff, or it is a later day.
        late = local.hour >= settings.reminders_cutoff_hour or n.scheduled_at.astimezone(IST).date() != local.date()
        if late:
            n.status, n.error_message = "failed", "Not sent: sending was paused" if paused else "Not sent in time"
            await _tell_mobed_failed(
                db, n, "sending was paused" if paused else "it was not ready before the evening ended", now
            )
            report.missed += 1
            await db.commit()
            continue

        # Paused: leave it pending. If the pause is lifted in time it goes;
        # if not, the branch above tells the mobed once the evening is over.
        if paused:
            break

        # Consent is checked again here, not only when planning: a STOP can
        # arrive between the two, and it must win. The mobed was already told
        # about a STOP, so this does not tell them again.
        withdrawn = await _withdrawn(db, n)
        if withdrawn:
            n.status, n.error_message = "failed", withdrawn
            report.missed += 1
            await db.commit()
            continue

        try:
            n.wa_message_id = await _post(client, n, settings)
        except _AccountProblem as exc:
            # The account itself is the problem, so the next send would hit it
            # too. Keep this reminder pending (it was not this one's fault),
            # stop everything, and tell the admins.
            n.error_message = str(exc)[:500]
            await guardrails.pause(
                db, settings, f"Meta reported a problem with the account ({exc.code}): {exc}", now=now
            )
            await db.commit()
            break
        except _Permanent as exc:
            n.status, n.error_message = "failed", str(exc)[:500]
            await _tell_mobed_failed(db, n, str(exc), now)
            report.failed += 1
            if exc.code not in RECIPIENT_CODES:
                streak += 1
        except _Transient as exc:
            n.retry_count += 1
            n.error_message = str(exc)[:500]
            if n.retry_count >= MAX_ATTEMPTS:
                n.status = "failed"
                await _tell_mobed_failed(db, n, "WhatsApp did not accept it after several tries", now)
                report.failed += 1
                streak += 1
            else:
                # Leave it pending for the next tick, and stop for now: a
                # network that is down is down for the rest of the queue too.
                await db.commit()
                break
        else:
            n.status, n.sent_at, n.error_message = "sent", now, None
            report.sent += 1
            streak = 0
            owner, name = await _owner_and_name(db, n)
            if owner is not None:
                sent_for.setdefault(owner, []).append(name)
        # Committed straight away: once Meta has accepted a message, losing the
        # fact that we sent it would send it again.
        await db.commit()

        if streak >= settings.reminders_breaker_failures:
            await guardrails.pause(
                db, settings, f"{streak} reminders in a row failed to send, so sending was paused", now=now
            )
            await db.commit()
            break

    for owner, names in sent_for.items():
        await reminders.notify(
            db, owner, "reminders_sent",
            f"{len(names)} reminder{'s' if len(names) != 1 else ''} sent for tomorrow",
            "Sent to " + ", ".join(names) + ".", link="#/reminders", now=now,
        )
    if sent_for:
        await db.commit()
    return report


# ---------------------------------------------------------------------------
# Meta's delivery receipts
# ---------------------------------------------------------------------------
_RANK = {"pending": 0, "sent": 1, "delivered": 2, "read": 3}


async def apply_status(
    db: AsyncSession, wa_message_id: str, status: str, error: str | None, now: datetime
) -> None:
    """A delivery receipt for a message we sent. Receipts arrive out of order
    and more than once, so a status only ever moves a message forward."""
    n = (
        await db.execute(
            select(Notification).where(
                Notification.wa_message_id == wa_message_id, Notification.notification_type == TYPE
            )
        )
    ).scalar_one_or_none()
    if n is None:
        return

    if status == "failed":
        if n.status != "failed":
            n.status, n.error_message = "failed", (error or "WhatsApp could not deliver it")[:500]
            await _tell_mobed_failed(db, n, error or "WhatsApp could not deliver it", now)
        return
    if status not in ("delivered", "read"):
        return
    if _RANK.get(status, 0) <= _RANK.get(n.status, 0):
        return
    n.status = status
    if status == "delivered":
        n.delivered_at = now
    else:
        n.read_at = now
        n.delivered_at = n.delivered_at or now
