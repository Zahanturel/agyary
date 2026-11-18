"""The Doongerwadi side's WhatsApp messages from Mobed Diary's own number
(DECISIONS D10 and its 18 Nov 2026 amendments; docs/phase2-whatsapp-templates.md;
Phase 2 Steps 5b and 5c).

Four approved Utility templates, and one short text reply:

  1  funeral_accepted_manager  to the funeral place's managers: who accepted
  2  prayer_details_mobed_v2   to the mobed who will pray: the details and the
                               family's contact (the accepter, and each of the
                               first mobeds to say yes to a call-out)
  3  prayers_mobed_family      to the family: who will pray
  4  prayer_request_mobeds     the panthaky's call-out to the agyari's mobeds,
                               with "Yes, I can pray" / "Not this time"
     "Thank you. Enough mobeds are going this time."  plain text to a mobed who
                               said yes and was not picked, only inside the 24
                               hours their answer opened

Everything here is off until FUNERAL_WHATSAPP_MODE=live (once Meta has approved
the templates): while it is off nothing is sent and the app says so. Live, every
message still passes the same safeguards as the rest of the app's sending: the
token and number id are set, the pause switch is not on, the number never
replied STOP (reminder_opt_outs, global per number, D2), it is on the allowlist
(REMINDERS_ALLOWLIST), the names in the blanks pass services/template_text.py
(phone numbers in the blanks come only from verified sign-in numbers or numbers
cleaned by services/phone.py for a specific person), and the day's limits for
all fire temples and for this one are not reached. A message that may not go is
still written down, as "failed" with the reason, so the person who asked for it
can see why; it costs nothing and counts against no limit.

Each message is a Notification row, written as "sending" and committed before
Meta is called (at most once, as for reminders and schedules): an answer lost
on the way is "may or may not have been sent", never retried. Meta's account
errors (an invalid token, payment, throttling) pause all sending and alert the
admins, as the reminder loop does. The rows carry the names that went out but
never a phone number (template_params has "[number]" where one went), and the
logs carry ids only (core/log_safety.py).

Sending happens after the caller's own work has been committed, and never
raises: accepting a request cannot fail because a message did not go.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings, get_settings
from agyary.models import Agyary, FuneralPlace, FuneralRecord, FuneralRequest, Notification, User
from agyary.models.enums import GEH_NAMES
from agyary.services import funeral_records, guardrails, reminder_sender, reminders, template_text, wa_send

logger = logging.getLogger(__name__)

# notification_type of each message, the same as the template's default name.
TYPE_MANAGER = "funeral_accepted_manager"
TYPE_DETAILS = "prayer_details_mobed"
TYPE_FAMILY = "prayers_mobed_family"
TYPE_CALLOUT = "prayer_request_mobeds"
TYPE_ENOUGH = "prayer_enough_reply"
TYPES = (TYPE_MANAGER, TYPE_DETAILS, TYPE_FAMILY, TYPE_CALLOUT, TYPE_ENOUGH)
TEXT_TEMPLATE = "text"   # template_name of the plain text reply

OFF_WORDS = "WhatsApp messages from Mobed Diary start once Meta approves them."
NOT_SET_UP = "WhatsApp sending is not set up on this server."
PAUSED = "All WhatsApp sending from Mobed Diary is paused at the moment."
NOT_FIXED = "not fixed yet"
ENOUGH_TEXT = "Thank you. Enough mobeds are going this time."
# WhatsApp's customer-service window: plain text may answer a person only this
# long after their last message to us.
WINDOW = timedelta(hours=24)
HIDDEN = "[number]"
CAP_TITLE = "Doongerwadi WhatsApp limit reached"
UNKNOWN = "No answer from WhatsApp: it may or may not have been sent, so it was not tried again"
CONTACT_NAME_MAX = 100


def make_client() -> httpx.AsyncClient:
    """The client the messages go out on (replaced in tests)."""
    return httpx.AsyncClient(timeout=10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def mode_on(settings: Settings) -> bool:
    return settings.funeral_whatsapp_mode.strip().lower() == "live"


async def why_not_now(db: AsyncSession, settings: Settings) -> str | None:
    """Why nothing can be sent at all right now, in words for the person who
    would send it; None when messages can go (each still checked on its own)."""
    if not mode_on(settings):
        return OFF_WORDS
    if not wa_send.can_send(settings):
        return NOT_SET_UP
    if await guardrails.paused_reason(db):
        return PAUSED
    return None


async def status(db: AsyncSession, settings: Settings) -> dict:
    """For the app: whether these messages are going, and if not, why."""
    why = await why_not_now(db, settings)
    return {"on": why is None, "why_not": why}


def digits(phone: str) -> str:
    """A number as a wa.me link wants it: digits only, no "+"."""
    return "".join(c for c in phone if c.isdigit())


# --- The words in the blanks ------------------------------------------------------

def _day(d) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _clock(t) -> str:
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def geh_saarnu_text(record: FuneralRecord) -> str:
    if not record.geh_saarnu_date:
        return NOT_FIXED
    return f"{_day(record.geh_saarnu_date)}, {GEH_NAMES.get(record.geh_saarnu_geh)} geh"


def uthamna_text(record: FuneralRecord) -> str:
    if not record.uthamna_date:
        return NOT_FIXED
    at = _clock(record.uthamna_time) if record.uthamna_time else f"time {NOT_FIXED}"
    return f"{_day(record.uthamna_date)}, {at}"


def departed(record: FuneralRecord) -> str:
    return funeral_records.prayed_name(record.departed_title, record.departed_name, record.departed_parent_name)


# --- One message ------------------------------------------------------------------

@dataclass
class Send:
    """One message to go: who to, which template and blanks, and what it is about."""

    kind: str
    phone: str
    recipient_type: str
    recipient_id: int
    agyary_id: int
    # The template's body blanks in order; the 1-based places in ``hidden`` are
    # phone numbers, sent but recorded as "[number]".
    params: list[str] = field(default_factory=list)
    hidden: tuple[int, ...] = ()
    # The dynamic part of a URL button (wa.me/<digits>), and quick-reply payloads.
    url_digits: str | None = None
    quick_replies: tuple[str, ...] = ()
    # Plain text instead of a template.
    text: str | None = None
    # What it is about, kept on the row: {"request": "12", "to": "manager", "answer": "3"}.
    refs: dict = field(default_factory=dict)
    # The free text in the blanks, checked before anything goes: (what, text, max length).
    names: list[tuple[str, str, int]] = field(default_factory=list)


def template_name(settings: Settings, kind: str) -> str:
    return {
        TYPE_MANAGER: settings.whatsapp_funeral_manager_template,
        TYPE_DETAILS: settings.whatsapp_prayer_details_template,
        TYPE_FAMILY: settings.whatsapp_prayers_family_template,
        TYPE_CALLOUT: settings.whatsapp_prayer_request_template,
    }.get(kind, TEXT_TEMPLATE)


def _recorded_params(s: Send) -> dict:
    out = {str(i): (HIDDEN if i in s.hidden else p) for i, p in enumerate(s.params, start=1)}
    out.update({k: str(v) for k, v in s.refs.items()})
    return out


def _payload(settings: Settings, s: Send) -> dict:
    components = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in s.params]}]
    if s.url_digits:
        components.append({"type": "button", "sub_type": "url", "index": "0",
                           "parameters": [{"type": "text", "text": s.url_digits}]})
    for i, payload in enumerate(s.quick_replies):
        components.append({"type": "button", "sub_type": "quick_reply", "index": str(i),
                           "parameters": [{"type": "payload", "payload": payload}]})
    return {
        "messaging_product": "whatsapp",
        "to": wa_send.to_number(s.phone),
        "type": "template",
        "template": {
            "name": template_name(settings, s.kind),
            "language": {"code": settings.whatsapp_template_language},
            "components": components,
        },
    }


@dataclass
class _Outcome:
    wa_message_id: str | None = None
    error: str | None = None
    account_code: int | None = None   # set when Meta says the account itself has a problem


async def _post(client: httpx.AsyncClient, settings: Settings, s: Send) -> _Outcome:
    """Hand one message to Meta. Never raises."""
    if s.text is not None:
        ok = await wa_send.send_text(settings, s.phone, s.text, client=client)
        return _Outcome(error=None if ok else "WhatsApp did not accept it")
    url = f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{settings.whatsapp_phone_number_id}/messages"
    try:
        resp = await client.post(url, json=_payload(settings, s),
                                 headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"})
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
        return _Outcome(error=f"WhatsApp could not be reached ({exc.__class__.__name__})")
    except httpx.HTTPError as exc:
        return _Outcome(error=f"{UNKNOWN} ({exc.__class__.__name__})")
    if resp.status_code == 200:
        try:
            return _Outcome(wa_message_id=resp.json()["messages"][0]["id"])
        except (KeyError, IndexError, ValueError, TypeError):
            return _Outcome()
    code = None
    try:
        error = resp.json()["error"]
        reason, code = str(error["message"])[:300], error.get("code")
    except (KeyError, ValueError, TypeError):
        reason = f"HTTP {resp.status_code}"
    out = _Outcome(error=f"WhatsApp refused it: {reason}" + (f" ({code})" if code else ""))
    if code in reminder_sender.ACCOUNT_CODES:
        out.account_code = code
    return out


# --- The limits -------------------------------------------------------------------

async def sent_today(db: AsyncSession, now: datetime, agyary_id: int | None = None) -> int:
    """These messages gone out today or going (a failed one was not sent)."""
    start, end = guardrails.day_bounds(now)
    where = [Notification.notification_type.in_(TYPES), Notification.status != "failed",
             Notification.created_at >= start, Notification.created_at < end]
    if agyary_id is not None:
        where.append(Notification.agyary_id == agyary_id)
    return (await db.execute(select(func.count()).select_from(Notification).where(*where))).scalar_one()


async def room_today(db: AsyncSession, settings: Settings, agyary_id: int, now: datetime) -> int:
    """How many more may go today for this fire temple, under both limits."""
    return max(0, min(
        settings.funeral_whatsapp_daily_cap - await sent_today(db, now),
        settings.funeral_whatsapp_per_agyari_daily_cap - await sent_today(db, now, agyary_id),
    ))


def _text_problem(s: Send) -> str | None:
    for what, text, max_len in s.names:
        why = template_text.problem(text or "", max_len=max_len)
        if why:
            return f"{what} {why}"
    return None


async def _blocked(db: AsyncSession, settings: Settings, s: Send, used: dict, now: datetime) -> str | None:
    """Why this one message may not go, or None. ``used`` counts what this
    batch has already let through, against the day's limits."""
    why = await why_not_now(db, settings)
    if why:
        return why
    if await reminders.already_stopped(db, s.phone):
        return "they replied STOP to Mobed Diary, so nothing more goes to them"
    if not reminders.may_send_to(settings, s.phone):
        return "this number is not on the list allowed to receive messages yet"
    why = _text_problem(s)
    if why:
        return why
    if used.get("global", 0) >= settings.funeral_whatsapp_daily_cap:
        return "today's limit for these messages from Mobed Diary has been reached"
    if used.get(s.agyary_id, 0) >= settings.funeral_whatsapp_per_agyari_daily_cap:
        return "today's limit for this fire temple has been reached"
    return None


async def deliver(
    db: AsyncSession, settings: Settings, sends: list[Send], *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[Notification]:
    """Write a row for each message, send those that may go, and record what
    happened. Commits. Never raises for a message that did not go."""
    now = now or _now()
    if not sends:
        return []
    used: dict = {"global": await sent_today(db, now)}
    for agyary_id in {s.agyary_id for s in sends}:
        used[agyary_id] = await sent_today(db, now, agyary_id)
    rows: list[tuple[Send, Notification]] = []
    capped = 0
    for s in sends:
        why = await _blocked(db, settings, s, used, now)
        n = Notification(
            agyary_id=s.agyary_id, recipient_phone=s.phone, recipient_type=s.recipient_type,
            recipient_id=s.recipient_id, notification_type=s.kind, template_name=template_name(settings, s.kind),
            template_params=_recorded_params(s), scheduled_at=now, created_at=now,
            status="failed" if why else "sending", error_message=f"Not sent: {why}"[:500] if why else None,
        )
        db.add(n)
        rows.append((s, n))
        if why is None:
            used["global"] += 1
            used[s.agyary_id] = used.get(s.agyary_id, 0) + 1
        elif "limit" in why:
            capped += 1
    if capped:
        await guardrails.alert_admins(
            db, settings, CAP_TITLE,
            f"{capped} Doongerwadi WhatsApp message{'s' if capped != 1 else ''} not sent because a daily limit "
            "was reached. Raise FUNERAL_WHATSAPP_DAILY_CAP or FUNERAL_WHATSAPP_PER_AGYARI_DAILY_CAP if this is expected.",
            now=now,
        )
    # Written down before Meta is called: an answer lost on the way leaves
    # "sending", which still counts and is never sent again.
    await db.commit()

    going = [(s, n) for s, n in rows if n.status == "sending"]
    if going:
        own = client is None
        client = client or make_client()
        try:
            outcomes = await asyncio.gather(*(_post(client, settings, s) for s, _ in going))
        finally:
            if own:
                await client.aclose()
        account_problem = None
        for (s, n), out in zip(going, outcomes):
            if out.error:
                n.status, n.error_message = "failed", out.error[:500]
                if out.account_code is not None:
                    account_problem = (out.account_code, out.error)
            else:
                n.status, n.sent_at, n.wa_message_id = "sent", now, out.wa_message_id
            logger.info("Doongerwadi WhatsApp %s (notification %s, %s): %s",
                        s.kind, n.id, ", ".join(f"{k} {v}" for k, v in s.refs.items()), n.status)
        if account_problem:
            await guardrails.pause(
                db, settings, f"Meta reported a problem with the account ({account_problem[0]}): {account_problem[1]}",
                now=now,
            )
        await db.commit()
    for s, n in rows:
        if n.status == "failed" and n.id is not None and not any(n is m for _, m in going):
            logger.info("Doongerwadi WhatsApp %s (notification %s) not sent: %s", s.kind, n.id, n.error_message)
    return [n for _, n in rows]


# --- Meta's delivery receipts -----------------------------------------------------

_RANK = {"sending": 0, "sent": 1, "delivered": 2, "read": 3}


async def apply_status(
    db: AsyncSession, wa_message_id: str, status_: str, error: str | None, now: datetime,
    *, recipient_user_id: str | None = None,
) -> bool:
    """A receipt for one of these messages: it only moves forward. Returns
    whether the message was one of ours."""
    n = (
        await db.execute(select(Notification).where(
            Notification.wa_message_id == wa_message_id, Notification.notification_type.in_(TYPES)))
    ).scalars().first()
    if n is None:
        return False
    if recipient_user_id and not n.recipient_user_id:
        n.recipient_user_id = recipient_user_id[:128]
    if status_ == "failed":
        if n.status != "failed":
            n.status, n.error_message = "failed", f"WhatsApp could not deliver it: {error or 'no reason given'}"[:500]
        return True
    if status_ in ("delivered", "read") and _RANK.get(status_, 0) > _RANK.get(n.status, -1):
        n.status = status_
        if status_ == "delivered":
            n.delivered_at = now
        else:
            n.read_at = now
            n.delivered_at = n.delivered_at or now
    return True


# --- Reading what was sent --------------------------------------------------------

async def rows_for(db: AsyncSession, *, request_id: int, kinds=TYPES) -> list[Notification]:
    return list((await db.execute(
        select(Notification).where(
            Notification.notification_type.in_(kinds),
            Notification.template_params["request"].astext == str(request_id),
        ).order_by(Notification.id)
    )).scalars().all())


def went(n: Notification | None) -> bool:
    return n is not None and n.status in ("sending", "sent", "delivered", "read")


def state_words(n: Notification) -> str:
    if n.status in ("sent", "delivered", "read"):
        return {"sent": "Sent", "delivered": "Delivered", "read": "Read"}[n.status]
    if n.status == "sending":
        return "Sending"
    return "Not sent"


def why(n: Notification) -> str | None:
    if n.status != "failed":
        return None
    text = n.error_message or "It could not be sent"
    return text.removeprefix("Not sent: ")


# --- Step 5b: on accept -----------------------------------------------------------

ACCEPT_TO = ("manager", "accepter", "family")
TO_WORDS = {"manager": "the manager", "accepter": "you", "family": "the family"}


def details_send(
    record: FuneralRecord, place: FuneralPlace, *, phone: str, recipient_type: str, recipient_id: int,
    agyary_id: int, refs: dict,
) -> Send:
    """Template 2 (prayer_details_mobed_v2, the owner's wording of 19 Nov 2026, no bungli): "You
    will pray for {{1 departed}} at {{2 place}}. Geh-saarnu: {{3}}. Uthamna: {{4}}.
    The family's contact is {{5 name}}, {{6 number}}. Thank you for your service."""
    return Send(
        kind=TYPE_DETAILS, phone=phone, recipient_type=recipient_type, recipient_id=recipient_id,
        agyary_id=agyary_id,
        params=[departed(record), place.name, geh_saarnu_text(record), uthamna_text(record),
                record.family_contact_name, record.family_contact_phone],
        hidden=(6,), refs=refs,
        names=[("the departed's name", departed(record), template_text.DEPARTED_MAX),
               ("the place's name", place.name, template_text.TEMPLE_MAX),
               ("the family's name", record.family_contact_name, CONTACT_NAME_MAX)],
    )


async def after_accept(
    db: AsyncSession, settings: Settings, request_id: int, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Once an accept is committed: with "Share my name and number" ticked,
    template 1 to the place's managers whose access is on, template 2 to the
    accepter, and template 3 to the family if the manager's tick recorded their
    agreement. Returns what the accepter is shown. Never raises."""
    try:
        return await _after_accept(db, settings, request_id, now=now or _now(), client=client)
    except Exception:   # noqa: BLE001 - accepting must never fail because of a message
        logger.exception("Doongerwadi WhatsApp after accepting request %s failed", request_id)
        await db.rollback()
        return {"state": "failed", "message": "The WhatsApp messages could not be sent.", "items": []}


async def _after_accept(db, settings, request_id, *, now, client) -> dict:
    from agyary.services import funeral_answers   # here: funeral_answers reads summary() from this module

    request = await db.get(FuneralRequest, request_id)
    if request is None or not request.accepter_shared_contact or not request.accepted_by_user_id:
        return await summary(db, settings, request) if request else {"state": "not_shared", "items": []}
    if not mode_on(settings):
        logger.info("Doongerwadi WhatsApp is off: nothing sent for request %s", request.id)
        return await summary(db, settings, request)
    if await rows_for(db, request_id=request.id, kinds=(TYPE_MANAGER, TYPE_FAMILY)):
        return await summary(db, settings, request)     # already done once
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    mobed = await db.get(User, request.accepted_by_user_id)
    name = departed(record)
    who = [("the departed's name", name, template_text.DEPARTED_MAX),
           ("the mobed's name", mobed.name, template_text.MOBED_NAME_MAX),
           ("the fire temple's name", agyary.name, template_text.TEMPLE_MAX)]
    who_params = [name, mobed.name, agyary.name, mobed.phone]
    sends = [
        Send(kind=TYPE_MANAGER, phone=m.phone, recipient_type="user", recipient_id=m.id, agyary_id=agyary.id,
             params=who_params, hidden=(4,),
             refs={"request": request.id, "to": "manager"}, names=who)
        for m in await funeral_answers._managers(db, settings, record.funeral_place_id)
    ]
    sends.append(details_send(record, place, phone=mobed.phone, recipient_type="user", recipient_id=mobed.id,
                              agyary_id=agyary.id, refs={"request": request.id, "to": "accepter"}))
    if request.family_whatsapp_agreed:
        sends.append(Send(kind=TYPE_FAMILY, phone=record.family_contact_phone, recipient_type="family",
                          recipient_id=record.id, agyary_id=agyary.id, params=who_params, hidden=(4,),
                          refs={"request": request.id, "to": "family"}, names=who))
    await deliver(db, settings, sends, now=now, client=client)
    return await summary(db, settings, request)


async def summary(db: AsyncSession, settings: Settings | None, request: FuneralRequest) -> dict:
    """What the accepter is told about the messages for their accept: the
    state, a sentence, and each message (to the manager, them, the family)."""
    settings = settings or get_settings()
    if not request.accepter_shared_contact:
        return {"state": "not_shared", "message": None, "items": []}
    rows = [n for n in await rows_for(db, request_id=request.id, kinds=(TYPE_MANAGER, TYPE_DETAILS, TYPE_FAMILY))
            if n.template_params.get("to") in ACCEPT_TO]
    family_note = None if request.family_whatsapp_agreed else (
        "The family is not messaged by Mobed Diary: the Doongerwadi's tick did not include their agreement.")
    if not rows:
        message = OFF_WORDS if not mode_on(settings) else "No WhatsApp messages were sent from Mobed Diary for this."
        return {"state": "off" if not mode_on(settings) else "none", "message": message, "items": [],
                "family_note": family_note}
    items = [{"to": n.template_params.get("to"), "to_words": TO_WORDS.get(n.template_params.get("to"), ""),
              "status": n.status, "state": state_words(n), "why": why(n)} for n in rows]
    failed = [i for i in items if i["status"] == "failed"]
    if not failed:
        message = "WhatsApp messages sent from Mobed Diary to " + _join(sorted(
            {i["to_words"] for i in items}, key=lambda w: list(TO_WORDS.values()).index(w))) + "."
        state = "sent"
    else:
        message = " ".join(f"The WhatsApp message to {i['to_words']} could not be sent: {i['why']}." for i in failed)
        state = "failed"
    return {"state": state, "message": message, "items": items, "family_note": family_note}


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def in_window(answered_at: datetime | None, now: datetime) -> bool:
    return answered_at is not None and now - answered_at <= WINDOW

