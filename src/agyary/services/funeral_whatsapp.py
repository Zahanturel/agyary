"""The Doongerwadi side's WhatsApp messages from Mobed Diary's own number
(DECISIONS D10 and its 18 Nov 2026 amendments; docs/phase2-whatsapp-templates.md;
Phase 2 Steps 5b and 5c).

Utility templates, and short text replies:

  1  funeral_accepted_manager  to the managers: who accepted       (not sent
  2  prayer_details_mobed_v2   to the accepter: the details         since
  3  prayers_mobed_family      to the family: who will pray          R3.1)
                               These went on accepting, before R3.1; the
                               Accept is gone (R3.1 step 7). Their rows are
                               kept, and a request accepted the old way still
                               reads what went (summary).
  4  prayer_request_mobeds_v2  the call-out to the agyari's mobeds: at Send in
                               Everyone at once, from the board's Ask everyone,
                               by the safety net, and to a standby asked again,
                               with "Yes, I can pray" / "Not this time" (v2
                               since R3.1; the same blanks as v1)

At All set (R3.1 step 5, services/all_set.py):

  5  prayers_all_set_family    to the family: who will pray, the times, who to
                               contact (the panthaky, else the first mobed going)
  6  prayer_details_mobed_v3   to each mobed going: the details, the family's
                               contact, everyone going, who to contact (never
                               themselves: the next mobed going, else the fire
                               temple's name); with the button "I can't go any
                               more" ("pca:<token>:x")
  7  prayers_all_set_panthaky  to the panthaky not going: who is going, the family
  8  funeral_accepted_manager_v2  to the funeral place's managers: who will pray,
                               who to contact, with their number

     "Thank you. Enough mobeds are going this time. If a place opens, we may
     ask you again."           plain text to a mobed who said yes once enough
                               were going (a standby, R3.1)
     "Sahebji <first name>, this prayer request has been closed, so you are
     not needed for now, but we will keep you updated. Thank you."  plain
                               text to a mobed who said yes, when the
                               request is withdrawn or declined
     "Thank you for letting us know. The panthaky has been told."  plain text
                               to a tap on "I can't go any more" (step 5b), or
                               why it cannot be done (the prayers have begun)
     These texts go only inside the 24 hours the mobed's answer or tap opened.

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
raises: a request cannot fail to be sent, or be all set, because a message did
not go.
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
from agyary.models import Agyary, FuneralPlace, FuneralRecord, FuneralRequest, Notification
from agyary.models.enums import GEH_NAMES
from agyary.services import funeral_records, guardrails, reminder_sender, reminders, template_text, wa_send

logger = logging.getLogger(__name__)

# notification_type of each message, the same as the template's default name.
# 1-3 are not sent since R3.1 (step 7): kept to read what went before.
TYPE_MANAGER = "funeral_accepted_manager"
TYPE_DETAILS = "prayer_details_mobed"
TYPE_FAMILY = "prayers_mobed_family"
TYPE_CALLOUT = "prayer_request_mobeds"
TYPE_ENOUGH = "prayer_enough_reply"
TYPE_WITHDRAWN = "prayer_withdrawn_reply"
# R3.1 step 5, at All set (templates 5-8).
TYPE_ALL_SET_FAMILY = "prayers_all_set_family"
TYPE_ALL_SET_DETAILS = "prayer_details_mobed_v3"
TYPE_ALL_SET_PANTHAKY = "prayers_all_set_panthaky"
TYPE_ALL_SET_MANAGER = "funeral_accepted_manager_v2"
ALL_SET_TYPES = (TYPE_ALL_SET_FAMILY, TYPE_ALL_SET_DETAILS, TYPE_ALL_SET_PANTHAKY, TYPE_ALL_SET_MANAGER)
# R3.1 step 5b: the plain text answering a tap on "I can't go any more".
TYPE_BACKED_OUT = "prayer_backed_out_reply"
TYPES = (TYPE_MANAGER, TYPE_DETAILS, TYPE_FAMILY, TYPE_CALLOUT, TYPE_ENOUGH, TYPE_WITHDRAWN, *ALL_SET_TYPES,
         TYPE_BACKED_OUT)
# What a call-out's screen reads, per mobed asked.
CALLOUT_TYPES = (TYPE_CALLOUT, TYPE_DETAILS, TYPE_ENOUGH, TYPE_WITHDRAWN)
TEXT_TEMPLATE = "text"   # template_name of the plain text reply

OFF_WORDS = "WhatsApp messages from Mobed Diary start once Meta approves them."
NOT_SET_UP = "WhatsApp sending is not set up on this server."
PAUSED = "All WhatsApp sending from Mobed Diary is paused at the moment."
NOT_FIXED = "not fixed yet"
ENOUGH_TEXT = "Thank you. Enough mobeds are going this time. If a place opens, we may ask you again."
# To a mobed whose yes is no longer needed because the request was withdrawn or
# declined: the owner's words (D11, word review of 23 Nov 2026), via withdrawn_text.
WITHDRAWN_TEXT = ("Sahebji {first_name}, this prayer request has been closed, so you are not needed for now, "
                  "but we will keep you updated. Thank you.")
WITHDRAWN_NO_NAME_TEXT = ("Sahebji, this prayer request has been closed, so you are not needed for now, "
                          "but we will keep you updated. Thank you.")
# To a tap on "I can't go any more" (step 5b); without "The panthaky has been
# told." at a fire temple with no panthaky in the app, where nobody is.
BACKED_OUT_TEXT = "Thank you for letting us know. The panthaky has been told."
BACKED_OUT_NO_PANTHAKY_TEXT = "Thank you for letting us know."
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


# Titles typed before a mobed's name, left out of "Sahebji <first name>": the
# same list as util.js NAME_PREFIXES (compared without dots, in any case): Parsi
# titles only (owner's word review, 23 Nov 2026), so no Shri or Smt, and "Dastur"
# is a surname ("Dasturji" is the title).
NAME_PREFIXES = frozenset({"er", "ervad", "mobed", "mobedji", "dasturji", "dr", "behdin",
                           "osta", "osti", "khud", "mr", "mrs", "ms"})


def first_name(full: str | None) -> str:
    """The first name, for "Sahebji <first name>" (D11), as util.js firstName:
    a title typed before it ("Er.", "Ervad", "Dasturji", ...) is skipped, and
    the whole name is used when nothing else is left."""
    words = str(full or "").split()
    i = 0
    while i < len(words) and words[i].replace(".", "").lower() in NAME_PREFIXES:
        i += 1
    return words[i] if i < len(words) else " ".join(words)


def withdrawn_text(name: str | None) -> str:
    """The text to a mobed whose yes is no longer needed (the request was
    withdrawn or declined): "Sahebji <first name>, this prayer request has
    been closed, ..."; "Sahebji, this prayer request ..." with no name."""
    first = first_name(name)
    return WITHDRAWN_TEXT.format(first_name=first) if first else WITHDRAWN_NO_NAME_TEXT


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
    # What is written down for a blank that holds names and numbers together
    # (1-based place -> the words with "[number]" for each number).
    recorded: dict[int, str] = field(default_factory=dict)
    # Why this one may not go whatever else holds (an account that is not on,
    # D9); it is written down as "failed" with this reason.
    why_not: str | None = None


def template_name(settings: Settings, kind: str) -> str:
    """The template a message of this kind goes out on. Templates 1-3 are not
    sent since R3.1, so they are not here (their settings are kept, unused)."""
    return {
        TYPE_CALLOUT: settings.whatsapp_prayer_request_template,
        TYPE_ALL_SET_FAMILY: settings.whatsapp_all_set_family_template,
        TYPE_ALL_SET_DETAILS: settings.whatsapp_all_set_details_template,
        TYPE_ALL_SET_PANTHAKY: settings.whatsapp_all_set_panthaky_template,
        TYPE_ALL_SET_MANAGER: settings.whatsapp_all_set_manager_template,
    }.get(kind, TEXT_TEMPLATE)


def _recorded_params(s: Send) -> dict:
    out = {str(i): (s.recorded[i] if i in s.recorded else HIDDEN if i in s.hidden else p)
           for i, p in enumerate(s.params, start=1)}
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
    if s.why_not:
        return s.why_not
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


# --- A request accepted the old way, before R3.1: what went then --------------------
# Templates 1-3 went on accepting (Step 5b, 18-19 Nov 2026). Nothing sends them
# since R3.1 step 7; their rows are kept (D8), and the accepter's request still
# reads what went.

ACCEPT_TO = ("manager", "accepter", "family")
TO_WORDS = {"manager": "the manager", "accepter": "you", "family": "the family"}


async def summary(db: AsyncSession, settings: Settings | None, request: FuneralRequest) -> dict:
    """What the accepter of a request accepted the old way reads about the
    messages for their accept: the state, a sentence, and each message (to the
    manager, them, the family)."""
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


# --- R3.1 step 5: at All set (templates 5-8) -----------------------------------------
# docs/phase2-requests-redesign.md, "Template drafts": the blanks below are in
# exactly that order. A blank that holds several people is built here, e.g.
# "Er. A (+91 9800000001), Er. B (+91 9800000002)": the numbers are only the
# sign-in number of an account, or the number a panthaky entered for a mobed
# added by hand (cleaned by services/phone.py) - never free text - and each
# name passes services/template_text.py. Meta's rules: no newline or tab, no
# four spaces in a row, and no blank left empty ("not fixed yet" instead).

@dataclass
class Person:
    """Someone named in a blank: their name, and their number where known."""

    name: str
    phone: str | None = None


def clean(text: str | None) -> str:
    """One line, single spaces (Meta refuses a newline, a tab or four spaces in a blank)."""
    return " ".join(str(text or "").split())


def spoken(phone: str) -> str:
    """A number as people read it: "+91 9800000001" for India, else as stored."""
    return f"+91 {phone[3:]}" if phone.startswith("+91") and len(phone) == 13 else phone


def people_blank(people: list[Person]) -> tuple[str, str]:
    """(what is sent, what is written down) for a blank of names with numbers:
    "Er. A (+91 9800000001), Er. B" is written down as "Er. A ([number]), Er. B"."""
    sent = ", ".join(f"{clean(p.name)} ({spoken(p.phone)})" if p.phone else clean(p.name) for p in people)
    kept = ", ".join(f"{clean(p.name)} ({HIDDEN})" if p.phone else clean(p.name) for p in people)
    return (sent, kept) if sent else (NOT_FIXED, NOT_FIXED)


def contact_people(panthakys: list[Person], going: list[Person], *, to: str | None = None,
                   fire_temple: str | None = None) -> list[Person]:
    """Who "For anything else, please contact {contact}" names in templates 5, 6
    and 8 (owner's word review, 23 Nov 2026): the request's panthaky (or
    panthakys) with their number; at a fire temple with no confirmed panthaky
    in the app, the first mobed going.

    Template 6 goes to each mobed going (``to``, the number it goes to), and
    never names them as their own contact - a panthaky who prays included: the
    other panthakys, else the first other mobed going, and with nobody else,
    the fire temple's own name (``fire_temple``) with no number."""
    def not_them(people: list[Person]) -> list[Person]:
        return [p for p in people if to is None or p.phone != to]

    if panthakys and not_them(panthakys):
        return not_them(panthakys)
    others = not_them(going)
    if others:
        return others[:1]
    if to is None:
        return []
    return [Person(fire_temple)] if fire_temple else []


def names_blank(people: list[Person]) -> str:
    """Names only: "Er. A and Er. B"."""
    names = [clean(p.name) for p in people if clean(p.name)]
    return _join(names) if names else NOT_FIXED


def _people_checks(people: list[Person], what: str) -> list[tuple[str, str, int]]:
    return [(what, p.name, template_text.MOBED_NAME_MAX) for p in people]


def _record_checks(record: FuneralRecord, place: FuneralPlace | None, agyary: Agyary | None,
                   family: bool) -> list[tuple[str, str, int]]:
    out = [("the departed's name", departed(record), template_text.DEPARTED_MAX)]
    if place is not None:
        out.append(("the place's name", place.name, template_text.TEMPLE_MAX))
    if agyary is not None:
        out.append(("the fire temple's name", agyary.name, template_text.TEMPLE_MAX))
    if family:
        out.append(("the family's name", record.family_contact_name, CONTACT_NAME_MAX))
    return out


def all_set_family_send(record: FuneralRecord, agyary: Agyary, *, going: list[Person], panthakys: list[Person],
                        refs: dict) -> Send:
    """Template 5 (prayers_all_set_family): "The prayers for {{1 departed}} will
    be offered by {{2 mobeds with numbers}} of {{3 agyari}}. Geh-saarnu: {{4}}.
    Uthamna: {{5}}. Please contact {{6 contact}} for anything else." (in short
    lines, docs/phase2-whatsapp-templates.md). No button. {{6}} is the panthaky
    with their number, else the first mobed going (``contact_people``).

    No closing blessing: Meta classes well-wishes as Marketing, and its form
    warned that a Utility template with "May the ruvan of the late ... attain
    Garothman Behesht." would be rejected (owner, 23 Nov 2026: drop it here only;
    the family's wa.me message, the app and the PDF keep it)."""
    mobeds, mobeds_kept = people_blank(going)
    contact, contact_kept = people_blank(contact_people(panthakys, going))
    return Send(
        kind=TYPE_ALL_SET_FAMILY, phone=record.family_contact_phone, recipient_type="family", recipient_id=record.id,
        agyary_id=agyary.id,
        params=[clean(departed(record)), mobeds, clean(agyary.name), geh_saarnu_text(record), uthamna_text(record),
                contact],
        recorded={2: mobeds_kept, 6: contact_kept}, refs=refs,
        names=_record_checks(record, None, agyary, False) + _people_checks(going, "the name of a mobed going")
        + _people_checks(panthakys, "the panthaky's name"),
    )


def all_set_details_send(
    record: FuneralRecord, place: FuneralPlace, *, going: list[Person], panthakys: list[Person], phone: str,
    recipient_type: str, recipient_id: int, agyary_id: int, fire_temple: str, back_out: str, refs: dict,
    why_not: str | None = None,
) -> Send:
    """Template 6 (prayer_details_mobed_v3): "You will pray for {{1 departed}} at
    {{2 place}}. Geh-saarnu: {{3}}. Uthamna: {{4}}. Family: {{5 family name}},
    {{6 family number}}. Mobeds going: {{7 mobeds with numbers}}. For anything
    else, please contact {{8 contact}}. Thank you for your service." (in short
    lines, docs/phase2-whatsapp-templates.md). One quick-reply button, "I can't go any more", whose
    payload is ``back_out`` (prayer_callout.back_out_payload: Step 5b reads
    it). {{8}} is the panthaky with their number, else the first mobed going
    who is not the one it goes to, else ``fire_temple``, the fire temple's own
    name with no number (``contact_people``)."""
    mobeds, mobeds_kept = people_blank(going)
    contacts = contact_people(panthakys, going, to=phone, fire_temple=fire_temple)
    contact, contact_kept = people_blank(contacts)
    # A contact who is neither going nor a panthaky is the fire temple's name.
    temple = [("the fire temple's name", p.name, template_text.TEMPLE_MAX)
              for p in contacts if p not in going and p not in panthakys]
    return Send(
        kind=TYPE_ALL_SET_DETAILS, phone=phone, recipient_type=recipient_type, recipient_id=recipient_id,
        agyary_id=agyary_id,
        params=[clean(departed(record)), clean(place.name), geh_saarnu_text(record), uthamna_text(record),
                clean(record.family_contact_name) or NOT_FIXED, record.family_contact_phone, mobeds, contact],
        hidden=(6,), recorded={7: mobeds_kept, 8: contact_kept}, quick_replies=(back_out,), refs=refs,
        why_not=why_not,
        names=_record_checks(record, place, None, True) + _people_checks(going, "the name of a mobed going")
        + _people_checks(panthakys, "the panthaky's name") + temple,
    )


def all_set_panthaky_send(record: FuneralRecord, place: FuneralPlace, *, going: list[Person], phone: str,
                          recipient_id: int, agyary_id: int, refs: dict) -> Send:
    """Template 7 (prayers_all_set_panthaky): "The prayers for {{1 departed}} at
    {{2 place}} are confirmed. Mobeds going: {{3 mobeds with numbers}}.
    Geh-saarnu: {{4}}. Uthamna: {{5}}. The family's contact: {{6 family
    name}}, {{7 family number}}. You can see the full details in Mobed Diary."
    (in short lines, docs/phase2-whatsapp-templates.md). No button. (Reworded 23 Nov 2026: Meta's form refused the first wording,
    which ended on a blank and had too many blanks for its length.)"""
    mobeds, mobeds_kept = people_blank(going)
    return Send(
        kind=TYPE_ALL_SET_PANTHAKY, phone=phone, recipient_type="user", recipient_id=recipient_id,
        agyary_id=agyary_id,
        params=[clean(departed(record)), clean(place.name), mobeds, geh_saarnu_text(record), uthamna_text(record),
                clean(record.family_contact_name) or NOT_FIXED, record.family_contact_phone],
        hidden=(7,), recorded={3: mobeds_kept}, refs=refs,
        names=_record_checks(record, place, None, True) + _people_checks(going, "the name of a mobed going"),
    )


def all_set_manager_send(record: FuneralRecord, agyary: Agyary, *, going: list[Person], panthakys: list[Person],
                         phone: str, recipient_id: int, refs: dict) -> Send:
    """Template 8 (funeral_accepted_manager_v2): "The prayers for {{1 departed}}
    will be offered by {{2 mobeds' names}} of {{3 agyari}}. For anything else,
    please contact {{4 contact}}. Thank you." No button. {{4}} is the panthaky with their
    number, else the first mobed going (``contact_people``)."""
    contact, contact_kept = people_blank(contact_people(panthakys, going))
    return Send(
        kind=TYPE_ALL_SET_MANAGER, phone=phone, recipient_type="user", recipient_id=recipient_id, agyary_id=agyary.id,
        params=[clean(departed(record)), names_blank(going), clean(agyary.name), contact],
        recorded={4: contact_kept}, refs=refs,
        names=_record_checks(record, None, agyary, False) + _people_checks(going, "the name of a mobed going")
        + _people_checks(panthakys, "the panthaky's name"),
    )

