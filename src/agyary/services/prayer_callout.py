"""A fire temple's own list of mobeds, and the panthaky's call-out to them on
WhatsApp (DECISIONS D10, the owner's idea of 18 Nov 2026; Phase 2 Step 5c).

The list (the Mobeds page, "Our mobeds" before R3.1): the fire temple's mobeds
in the app, worked out from their memberships (never copied), and the mobeds a
confirmed panthaky added by name and number, each with the tick that they
agreed to get WhatsApp messages from Mobed Diary about prayers. Only that fire
temple's confirmed panthakys and the admin see or change it (D2's spirit): to
anyone else it does not exist. Since R3.1 step 3 the page shows the app
mobeds' numbers too, so the panthaky can call them or open a WhatsApp chat
from their own phone; nothing else shows those numbers (our_mobeds).

The call-out goes at Send (owner, 19 Nov 2026): when a funeral place sends a
request to a fire temple, everyone on its list who can be messaged (not
STOP'd, not an account that is off or waiting, not its confirmed panthakys, who
have the request in the app, nor whoever sent it) is asked at once whether they
can pray - template 4, with no family details. Each mobed asked has an answer
row with an unguessable token, which is all the quick-reply buttons carry. The
first tap counts; later ones change nothing. A mobed is asked once per request;
the board's Ask everyone asks those not asked yet (someone added to the list
since), while the request waits. Since R3.1 (21 Nov 2026) that is the way
Everyone at once; in Come to me first nothing goes at Send, and the panthaky
chooses who to ask on the board (after_send, request_settings.way_for). The
old call-out screen, with its hand-picked call-out and "Send the details
again", is gone since R3.1 step 7; the board is the only way.

The "Who will pray" board (R3.1 step 4, owner 21 Nov 2026): every answer and
every place is one row per person per request, whatever the channel - a
WhatsApp button, "I can pray" / "Not this time" in the app, the panthaky's
"I'll pray", or a mobed marked after a phone call - and the first answer of a
person counts. ``fill`` is the one rule for a yes: up to the record's "mobeds
wanted" (DEFAULT_WANTED if it gives none) each yes is a place, and the
panthakys are told "<name> is going (1 of 2)" in the app and on their phones
(nothing about the departed or the family on the lock screen); nobody is sent
the details at a yes any more - they go only at All set (services/all_set.py,
Step 5), which the last place filling calls. A later yes is a standby, told
"Thank you. Enough mobeds are going this time. If a place opens, we may ask
you again." If the request is withdrawn or declined, each yes is told "This
prayer request was withdrawn." - both plain text, so only inside WhatsApp's 24
hours from the answer; otherwise nothing is sent. A no answers only for the
one who said it; at a fire temple with no panthaky, everyone asked saying no
closes the request there (_after_no). Payment stays with the panthaky, outside
the app.

While FUNERAL_WHATSAPP_MODE is off the list can be built, nothing is sent, and
the screens say the messages start once Meta approves them.
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import (
    Agyary,
    AgyaryMobedContact,
    AgyaryUser,
    FuneralPlace,
    FuneralRecord,
    FuneralRequest,
    FuneralRequestRecipient,
    PrayerCallout,
    PrayerCalloutAnswer,
    ReminderOptOut,
    User,
)
from agyary.models.enums import (
    ACCESS_OFF,
    ACCESS_ON,
    ACCESS_PENDING,
    ACCOUNT_MOBED,
    CALLOUT_NO,
    CALLOUT_YES,
    HOW_APP,
    HOW_PHONE,
    HOW_SELF,
    HOW_WHATSAPP,
    REQUEST_ACCEPTED,
    REQUEST_ALL_SET,
    REQUEST_DECLINED,
    REQUEST_MODE_PANTHAKY_FIRST,
    REQUEST_TAKEN,
    REQUEST_WAITING,
    REQUEST_WITHDRAWN,
    ROLE_PANTHAKY,
)
from agyary.services import (
    funeral_whatsapp as fw,
    guardrails,
    mobed_access,
    reminders,
    request_settings,
    template_text,
    web_push,
)

logger = logging.getLogger(__name__)

NAME_MAX = template_text.MOBED_NAME_MAX
MAX_CONTACTS = 300
# To the panthaky: "<name> is going" (and on their phone), "<name> also said yes".
KIND_GOING = "prayer_callout_going"
KIND_YES = "prayer_callout_yes"
# To a mobed in the app, about their own yes.
KIND_MY_YES = "prayer_callout_my_yes"
# Mobeds go when nobody said how many are wanted.
DEFAULT_WANTED = 2
# A request that still wants mobeds: waiting for the fire temple, or accepted.
OPEN = (REQUEST_WAITING, REQUEST_ACCEPTED, REQUEST_TAKEN)
NOTICE_TTL = timedelta(days=3)
NO_TICK = "Please tick that they agreed to get WhatsApp messages from Mobed Diary about prayers."
CONSENT_WORDS = "They agreed to get WhatsApp messages from Mobed Diary about prayers"
# What the quick-reply buttons carry: "pca:<token>:y" or "pca:<token>:n" on the
# call-out (template 4), and "pca:<token>:x" - "I can't go any more" - on the
# details at All set (template 6, R3.1 step 5), where <token> is the same
# unguessable token of that person's row on the request (prayer_callout_answers.
# token). Step 5b answers the "x" (services/standbys.py: backing out); a standby
# asked again when a place opens gets the call-out with "y" / "n" on a fresh
# token of its own (prayer_callout_answers.reask_token), never this one.
PAYLOAD_PREFIX = "pca:"
BACK_OUT = "x"
_PAYLOAD = re.compile(r"^pca:([A-Za-z0-9_-]{20,40}):([ynx])$")


def back_out_payload(row: PrayerCalloutAnswer) -> str:
    """The payload of the "I can't go any more" button on this person's details."""
    return f"{PAYLOAD_PREFIX}{row.token}:{BACK_OUT}"


class CalloutError(ValueError):
    """Something that cannot be done now; the message is for the panthaky."""

    def __init__(self, message: str, status: int = 409, field: str | None = None):
        super().__init__(message)
        self.status = status
        self.field = field


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Who may ----------------------------------------------------------------------

async def is_confirmed_panthaky(db: AsyncSession, agyary_id: int, user_id: int) -> bool:
    return (await db.execute(select(AgyaryUser.user_id).where(
        AgyaryUser.agyary_id == agyary_id, AgyaryUser.user_id == user_id,
        AgyaryUser.role == ROLE_PANTHAKY, AgyaryUser.is_active.is_(True),
    ))).first() is not None


async def may_manage(db: AsyncSession, settings: Settings, user: User, agyary_id: int) -> bool:
    """A confirmed panthaky of this fire temple (role panthaky, which only the
    owner's confirmation sets - never a claim), or an admin."""
    if guardrails.is_admin(settings, user.phone):
        return True
    return await is_confirmed_panthaky(db, agyary_id, user.id)


# --- The list ---------------------------------------------------------------------

def _off_words(user: User, settings: Settings) -> str | None:
    access = mobed_access.effective(settings, user)
    if access == ACCESS_ON:
        return None
    if access == ACCESS_OFF:
        return "their Mobed Diary access is switched off"
    return "they are waiting for the admin's approval"


# Why a mobed added by hand cannot be asked, when their number's account is not
# on: said without saying that the number has an account, or its state.
CANNOT_ASK_NOW = "cannot be asked on WhatsApp now"


def _no_place_words(user: User | None, settings: Settings, *, hidden: bool = False) -> str | None:
    """Why someone cannot be given a place now (D9: nothing to or under an
    account that is not on, and their number never reaches the family), or
    None. ``hidden``: a mobed added by hand, whose account's state is never
    said (CANNOT_ASK_NOW)."""
    if user is None or account_on(settings, user):
        return None
    if hidden:
        return "cannot be marked Going now"
    if mobed_access.effective(settings, user) == ACCESS_PENDING:
        return "cannot be marked Going until the admin approves them"
    return "cannot be marked Going while their Mobed Diary access is switched off"


def account_on(settings: Settings, user: User | None) -> bool:
    """An account whose access is on (D9), and not gone."""
    return user is not None and user.is_active and mobed_access.has_access(settings, user)


async def accounts_by_phone(db: AsyncSession, phones) -> dict[str, User]:
    """The Mobed Diary accounts of these numbers, by number. A mobed added by
    hand is matched to an account by their number whenever they would be
    asked or sent something - not only when they were added, since the number
    may sign up later, or its account be switched off since."""
    phones = {p for p in phones if p}
    if not phones:
        return {}
    return {u.phone: u for u in (await db.execute(select(User).where(User.phone.in_(phones)))).scalars()}


async def our_mobeds(
    db: AsyncSession, settings: Settings, agyary_id: int, *, me: User | None = None, with_numbers: bool = False,
) -> list[dict]:
    """Everyone on the fire temple's list, app mobeds first, then those added
    by hand; each says whether they can be messaged now and, if not, why.

    An app mobed's own number is given only with ``with_numbers``, which only
    the Mobeds page and the board pass (owner, 21 Nov 2026): their routes let
    in only the fire temple's confirmed panthakys (the board: those the
    request reached) and the admin (routes/callouts.py). Everywhere else -
    asking everyone, a call's result - it stays None."""
    members = (await db.execute(
        select(User).join(AgyaryUser, AgyaryUser.user_id == User.id).where(
            AgyaryUser.agyary_id == agyary_id, AgyaryUser.is_active.is_(True),
            User.is_active.is_(True), User.account_kind == ACCOUNT_MOBED,
        ).order_by(User.name, User.id)
    )).scalars().all()
    contacts = (await db.execute(
        select(AgyaryMobedContact).where(AgyaryMobedContact.agyary_id == agyary_id,
                                         AgyaryMobedContact.is_active.is_(True))
        .order_by(AgyaryMobedContact.name, AgyaryMobedContact.id)
    )).scalars().all()
    # An account of a mobed added by hand, by their number now (accounts_by_phone).
    linked = await accounts_by_phone(db, {c.phone for c in contacts})
    adders_ids = {c.consent_by_user_id for c in contacts if c.consent_by_user_id}
    adders = dict((await db.execute(select(User.id, User.name).where(User.id.in_(adders_ids)))).all()) \
        if adders_ids else {}
    phones = {u.phone for u in members} | {c.phone for c in contacts}
    stopped = set((await db.execute(
        select(ReminderOptOut.phone).where(ReminderOptOut.phone.in_(phones))
    )).scalars()) if phones else set()

    out = []
    member_phones = set()
    for u in members:
        member_phones.add(u.phone)
        why = ("this is you" if me is not None and u.id == me.id else
               "they replied STOP to Mobed Diary" if u.phone in stopped else _off_words(u, settings))
        # Only an approved mobed's number (D10, 21 Nov 2026: "approved mobeds ... with their
        # numbers"): not one still waiting for the admin, and not the panthaky's own.
        shown = (with_numbers and not (me is not None and u.id == me.id)
                 and mobed_access.effective(settings, u) != ACCESS_PENDING)
        no_place = _no_place_words(u, settings)
        out.append({"key": f"u{u.id}", "kind": "app", "id": u.id, "name": u.name,
                    "phone": u.phone if shown else None,
                    "stopped": u.phone in stopped, "is_me": me is not None and u.id == me.id,
                    "can_message": why is None, "why_not": why,
                    # Whether a call's Going may give them a place (D9), and if not, why.
                    "may_place": no_place is None, "no_place": no_place})
    for c in contacts:
        if c.phone in member_phones:
            continue    # they joined the app: listed once, as an app mobed
        account = linked.get(c.phone)
        # A STOP is said (the panthaky needs to know it cannot be asked), but never that
        # the number has a Mobed Diary account, or what state it is in (D2's spirit).
        why = ("they replied STOP to Mobed Diary" if c.phone in stopped
               else CANNOT_ASK_NOW if account is not None and not account_on(settings, account) else None)
        no_place = _no_place_words(account, settings, hidden=True)
        out.append({"key": f"c{c.id}", "kind": "contact", "id": c.id, "name": c.name, "phone": c.phone,
                    "stopped": c.phone in stopped, "is_me": False, "can_message": why is None, "why_not": why,
                    "may_place": no_place is None, "no_place": no_place,
                    "agreed_at": c.consent_at.isoformat() if c.consent_at else None,
                    "added_by": adders.get(c.consent_by_user_id)})
    return out


async def add_contact(
    db: AsyncSession, settings: Settings, user: User, agyary: Agyary, *, name: str, phone: str, agreed: bool,
    now: datetime | None = None,
) -> AgyaryMobedContact:
    """Add a mobed to the list by hand, with the panthaky's tick. ``phone`` is
    already cleaned and checked (services/phone.py)."""
    if not agreed:
        raise CalloutError(NO_TICK, status=400, field="agreed")
    try:
        name = template_text.check(name, "name", max_len=NAME_MAX)
    except ValueError as exc:
        raise CalloutError(str(exc), status=400, field="name") from exc
    if not name:
        raise CalloutError("Please enter the mobed's name.", status=400, field="name")
    now = now or _now()
    member = (await db.execute(
        select(User.name).join(AgyaryUser, AgyaryUser.user_id == User.id).where(
            AgyaryUser.agyary_id == agyary.id, AgyaryUser.is_active.is_(True), User.phone == phone)
    )).scalar_one_or_none()
    if member is not None:
        raise CalloutError(f"{member} uses Mobed Diary at {agyary.name}, so they are on the list already.",
                           field="phone")
    existing = (await db.execute(select(AgyaryMobedContact).where(
        AgyaryMobedContact.agyary_id == agyary.id, AgyaryMobedContact.phone == phone))).scalar_one_or_none()
    if existing is not None and existing.is_active:
        raise CalloutError(f"That number is on the list already, as {existing.name}.", field="phone")
    count = len((await db.execute(select(AgyaryMobedContact.id).where(
        AgyaryMobedContact.agyary_id == agyary.id, AgyaryMobedContact.is_active.is_(True)))).all())
    if count >= MAX_CONTACTS:
        raise CalloutError(f"The list has {MAX_CONTACTS} mobeds, which is as many as it can hold.")
    account = (await db.execute(select(User.id).where(User.phone == phone))).scalar_one_or_none()
    if existing is None:
        existing = AgyaryMobedContact(agyary_id=agyary.id, phone=phone)
        db.add(existing)
    existing.name, existing.is_active = name, True
    existing.consent_at, existing.consent_by_user_id, existing.user_id = now, user.id, account
    await db.flush()
    logger.info("Mobed contact %s added to fire temple %s's list by user %s", existing.id, agyary.id, user.id)
    return existing


async def remove_contact(db: AsyncSession, agyary_id: int, contact_id: int, user: User) -> AgyaryMobedContact:
    """Take a mobed added by hand off the list. What they were sent before
    counts for nothing from now on (left_out): their buttons change nothing,
    they are not asked again as a standby, and at All set they are neither
    named nor sent the details."""
    contact = await db.get(AgyaryMobedContact, contact_id)
    if contact is None or contact.agyary_id != agyary_id or not contact.is_active:
        raise CalloutError("That mobed could not be found on the list.", status=404)
    contact.is_active = False
    await db.flush()
    logger.info("Mobed contact %s taken off fire temple %s's list by user %s", contact.id, agyary_id, user.id)
    return contact


# Why someone asked for a request can no longer take part in it (left_out).
LEFT_THE_LIST = "no longer on the fire temple's list"
ACCESS_NOT_ON = "their Mobed Diary access is not on"


async def left_out(
    db: AsyncSession, settings: Settings, agyary_id: int, rows: list[PrayerCalloutAnswer],
) -> dict[int, str]:
    """Those of ``rows`` (one request's, at fire temple ``agyary_id``) who can
    no longer take part in it, by row id, with why (for the log): a mobed added
    by hand whom the panthaky took off the list since (unless that number is
    one of its app mobeds now), an app mobed no longer at the fire temple, a
    row whose account is gone, or (D9: nothing to or under an account that is
    not on) someone whose account - an app mobed's, or the one their number
    has (accounts_by_phone) - is waiting for approval or switched off. Their
    old buttons count for nothing (record_answer), they are not asked again as
    a standby, and at All set they are neither named nor sent the details, and
    their number goes nowhere (services/all_set.py)."""
    if not rows:
        return {}
    members = (await db.execute(
        select(User.id, User.phone).join(AgyaryUser, AgyaryUser.user_id == User.id).where(
            AgyaryUser.agyary_id == agyary_id, AgyaryUser.is_active.is_(True),
            User.is_active.is_(True), User.account_kind == ACCOUNT_MOBED)
    )).all()
    member_ids, member_phones = {i for i, _ in members}, {p for _, p in members}
    contact_ids = {r.contact_id for r in rows if r.contact_id}
    listed = set((await db.execute(select(AgyaryMobedContact.id).where(
        AgyaryMobedContact.id.in_(contact_ids), AgyaryMobedContact.agyary_id == agyary_id,
        AgyaryMobedContact.is_active.is_(True)))).scalars()) if contact_ids else set()
    user_ids = {r.user_id for r in rows if r.user_id}
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()} \
        if user_ids else {}
    by_phone = await accounts_by_phone(db, {r.phone for r in rows if not r.user_id and r.contact_id})
    out = {}
    for r in rows:
        if r.user_id:
            on = r.user_id in member_ids
            account = users.get(r.user_id)
        elif r.contact_id:
            on = r.contact_id in listed or bool(r.phone and r.phone in member_phones)
            account = by_phone.get(r.phone) if r.phone else None
        else:
            on, account = False, None      # the account was deleted
        if not on:
            out[r.id] = LEFT_THE_LIST
        elif account is not None and not account_on(settings, account):
            out[r.id] = ACCESS_NOT_ON
    return out


# --- The call-out -----------------------------------------------------------------

def is_open(request: FuneralRequest) -> bool:
    """Waiting for the fire temple's answer, or accepted: mobeds are still
    wanted. A withdrawn or declined request asks nobody more."""
    return request.status in OPEN


def wanted(record: FuneralRecord) -> int:
    """How many mobeds go: the record's "mobeds wanted", else DEFAULT_WANTED."""
    return record.mobeds_wanted or DEFAULT_WANTED


async def _answers(db: AsyncSession, request_id: int) -> list[tuple[PrayerCalloutAnswer, PrayerCallout]]:
    return list((await db.execute(
        select(PrayerCalloutAnswer, PrayerCallout).join(PrayerCallout, PrayerCallout.id == PrayerCalloutAnswer.callout_id)
        .where(PrayerCallout.funeral_request_id == request_id).order_by(PrayerCalloutAnswer.id)
    )).all())


def _answer_key(a: PrayerCalloutAnswer) -> str | None:
    return f"u{a.user_id}" if a.user_id else f"c{a.contact_id}" if a.contact_id else None


def _latest(rows) -> dict[tuple[str, str], object]:
    """The latest message of each kind for each answer: (kind, answer id) -> row."""
    out: dict[tuple[str, str], object] = {}
    for n in rows:
        if n.template_params.get("answer"):
            out[(n.notification_type, n.template_params["answer"])] = n
    return out


def _state(n) -> dict | None:
    return {"state": fw.state_words(n), "why": fw.why(n)} if n is not None else None


async def summary(db: AsyncSession, request: FuneralRequest) -> dict:
    """For the request's own page: how many were asked, said yes and go."""
    record = await db.get(FuneralRecord, request.funeral_record_id)
    answered = await _answers(db, request.id)
    return {
        "asked": len(answered),
        "yes": sum(1 for a, _ in answered if a.answer == CALLOUT_YES and not backed_out(a)),
        "going": sum(1 for a, _ in answered if holds_place(a)),
        "wanted": wanted(record),
    }


def _new_token() -> str:
    return secrets.token_urlsafe(18)    # 24 characters, about 144 bits


def _names(record: FuneralRecord, place: FuneralPlace, agyary: Agyary, asker: str,
           asker_max: int) -> list[tuple[str, str, int]]:
    return [("the departed's name", fw.departed(record), template_text.DEPARTED_MAX),
            ("the place's name", place.name, template_text.TEMPLE_MAX),
            ("the panthaky's name", asker, asker_max),
            ("the fire temple's name", agyary.name, template_text.TEMPLE_MAX)]


async def _ask(
    db: AsyncSession, settings: Settings, request: FuneralRequest, chosen: list[dict], *, asker: str,
    asker_max: int, sent_by_user_id: int | None, now: datetime, client: httpx.AsyncClient | None,
) -> int:
    """Template 4 to each of ``chosen`` (from our_mobeds), each on their own
    row of the request - the one they have (asked in the app, say), or a new
    one with its own unguessable token - hung on the request's call-out.
    Commits; never raises for a message that did not go. Returns how many went."""
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    names = _names(record, place, agyary, asker, asker_max)
    phones = {u.id: u.phone for u in (await db.execute(select(User).where(
        User.id.in_([m["id"] for m in chosen if m["kind"] == "app"])))).scalars()}
    rows = await _request_rows(db, request.id)
    callout = await _callout_of(db, request, sent_by_user_id=sent_by_user_id, now=now)
    pairs = []
    for m in chosen:
        app = m["kind"] == "app"
        phone = phones.get(m["id"]) if app else m["phone"]
        if not phone:
            continue
        row = _find(rows, m["key"], phone)
        if row is None:
            row = _new_row(callout, name=m["name"], phone=phone, how=HOW_WHATSAPP,
                           user_id=m["id"] if app else None, contact_id=None if app else m["id"])
            db.add(row)
            rows.append(row)
        pairs.append((m, row))
    await db.flush()
    # The order of the approved template (docs/phase2-whatsapp-templates.md): "A prayer request has
    # come to {{1 agyari}} for {{2 departed}} at {{3 place}}. Geh-saarnu: {{4}}. Uthamna: {{5}}.
    # Please reply to tell {{6 panthaky}} whether you can take it."
    params = [agyary.name, fw.departed(record), place.name, fw.geh_saarnu_text(record), fw.uthamna_text(record),
              asker]
    sends = [fw.Send(kind=fw.TYPE_CALLOUT, phone=a.phone, recipient_type="user" if m["kind"] == "app" else "contact",
                     recipient_id=m["id"], agyary_id=agyary.id, params=params,
                     quick_replies=(f"{PAYLOAD_PREFIX}{a.token}:y", f"{PAYLOAD_PREFIX}{a.token}:n"),
                     refs={"request": request.id, "answer": a.id}, names=names)
             for m, a in pairs]
    sent = await fw.deliver(db, settings, sends, now=now, client=client)
    went = sum(1 for n in sent if fw.went(n))
    callout.asked = (callout.asked or 0) + went
    await db.commit()
    return went


def panthaky_first_words(agyary: Agyary, panthakys: list[User]) -> str:
    """What the sender is told after Send in Come to me first."""
    who = "panthaky" if len(panthakys) == 1 else "panthakys"
    return f"Sent to the {who} of {agyary.name}. They choose who to ask."


async def after_send(
    db: AsyncSession, settings: Settings, request_id: int, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Once a request is sent and committed, by the fire temple's way (R3.1
    step 2; request_settings.way_for). Everyone at once - and any fire temple
    with no confirmed panthaky whose access is on - is everyone asked now
    (at_send). Come to me first is nothing now: only the panthaky was told, and
    they choose who to ask; if they set the safety net, services/prayer_timers.py
    asks everyone later. Returns what the sender is told, as at_send does
    ({"state": "panthaky_first", ...} for Come to me first). Never raises."""
    from agyary.services import panthaky   # here: as in _plan

    try:
        request = await db.get(FuneralRequest, request_id)
        agyary = await db.get(Agyary, request.agyary_id)
        if await request_settings.way_for(db, settings, agyary) == REQUEST_MODE_PANTHAKY_FIRST:
            panthakys = await panthaky.panthakys_of(db, settings, agyary.id)
            logger.info("Request %s: Come to me first at fire temple %s, so nobody more is asked at sending",
                        request.id, agyary.id)
            return {"state": "panthaky_first", "asked": 0, "asked_in_app": 0,
                    "message": panthaky_first_words(agyary, panthakys)}
    except Exception:   # noqa: BLE001 - the request is sent; this must not undo or fail it
        logger.exception("Finding the way of request %s failed", request_id)
        await db.rollback()
        return {"state": "failed", "asked": 0, "asked_in_app": 0, "message": ASK_FAILED}
    return await at_send(db, settings, request_id, now=now, client=client)


async def panthaky_acted(db: AsyncSession, request: FuneralRequest) -> bool:
    """Whether the fire temple has done something with this request, for the
    safety net (services/prayer_timers.py): it is no longer waiting (accepted,
    declined, withdrawn, all set), the panthaky took it on the board (Ask
    everyone, I'll pray, a call's result: ``taken_at``), or a call-out exists
    for it (the panthaky asked on WhatsApp by hand, or the mobeds were asked
    already)."""
    if request.status != REQUEST_WAITING or request.taken_at is not None:
        return True
    return (await db.execute(
        select(PrayerCallout.id).where(PrayerCallout.funeral_request_id == request.id).limit(1)
    )).first() is not None


async def at_send(
    db: AsyncSession, settings: Settings, request_id: int, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """At Send in Everyone at once (after_send): everyone is asked
    (ask_everyone). Returns what the sender is told. Never raises: sending a
    request cannot fail because of this."""
    return await ask_everyone(db, settings, request_id, now=now, client=client)


ASK_FAILED = "The mobeds could not be asked. The panthaky can ask them from the request."


@dataclass
class _Plan:
    """What asking everyone would do now (see ask_everyone)."""

    panthakys: list[User]
    # App mobeds the request has not reached in the app yet.
    new_recipients: list[User] = field(default_factory=list)
    # App mobeds with no row on the request yet: (our_mobeds entry, account).
    app_rows: list[tuple[dict, User]] = field(default_factory=list)
    # Who can be asked on WhatsApp now and has not been (our_mobeds entries).
    whatsapp: list[dict] = field(default_factory=list)
    # Why nobody can be asked on WhatsApp now, or None.
    why_not_whatsapp: str | None = None
    # How many on the list have a row already (asked, or answered).
    asked_before: int = 0

    @property
    def anything(self) -> bool:
        """Whether someone would be asked: in the app (the request reaching
        them now) or on WhatsApp. A row for someone the request reached
        already is only bookkeeping."""
        return bool(self.new_recipients or self.whatsapp)


async def _plan(db: AsyncSession, settings: Settings, request: FuneralRequest, agyary: Agyary, *,
                by_user: User | None) -> _Plan:
    """Who asking everyone would ask, from the fire temple's list: its app
    mobeds whose access is on (D9) and the mobeds added by hand - never its
    confirmed panthakys (they have the request), whoever sent it, or whoever
    asks - each once."""
    from agyary.services import panthaky   # here: panthaky reaches mobed_access, which this module reads too

    panthakys = await panthaky.panthakys_of(db, settings, agyary.id)
    skip = {p.id for p in panthakys} | {request.sent_by_user_id} | ({by_user.id} if by_user is not None else set())
    people = await our_mobeds(db, settings, agyary.id)
    app_ids = [m["id"] for m in people if m["kind"] == "app"]
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(app_ids)))).scalars()} \
        if app_ids else {}
    reached = set((await db.execute(select(FuneralRequestRecipient.user_id).where(
        FuneralRequestRecipient.funeral_request_id == request.id))).scalars())
    rows = await _request_rows(db, request.id)
    latest = _latest(await fw.rows_for(db, request_id=request.id, kinds=(fw.TYPE_CALLOUT,)))
    plan = _Plan(panthakys=panthakys, why_not_whatsapp=await fw.why_not_now(db, settings))
    for m in people:
        user = users.get(m["id"]) if m["kind"] == "app" else None
        if m["kind"] == "app" and (user is None or user.id in skip or not user.is_active
                                   or not mobed_access.has_access(settings, user)):
            continue
        row = _find(rows, m["key"], user.phone if user is not None else m["phone"])
        if user is not None:
            if user.id not in reached:
                plan.new_recipients.append(user)
            if row is None:
                plan.app_rows.append((m, user))
        if row is not None:
            plan.asked_before += 1
            if row.answer is not None:
                continue
        on_whatsapp = row is not None and fw.went(latest.get((fw.TYPE_CALLOUT, str(row.id))))
        if plan.why_not_whatsapp is None and m["can_message"] and not on_whatsapp:
            plan.whatsapp.append(m)
    return plan


def _nobody_words(agyary: Agyary, plan: _Plan) -> str:
    """Why asking everyone would ask nobody now."""
    why = plan.why_not_whatsapp
    if why and plan.asked_before:
        return f"Everyone on {agyary.name}'s list in Mobed Diary has been asked already. {why}"
    if why:
        return why
    if plan.asked_before:
        return f"Everyone on {agyary.name}'s list of mobeds has been asked already."
    return f"Nobody on {agyary.name}'s list of mobeds could be asked on WhatsApp."


def _asked_words(agyary: Agyary, in_app: int, on_whatsapp: int, failed: int, why: str | None) -> str:
    def mobeds(n: int) -> str:
        return f"{n} mobed{'s' if n != 1 else ''} of {agyary.name} {'was' if n == 1 else 'were'}"

    if in_app and on_whatsapp:
        words = f"{mobeds(in_app)} asked in the app, and {on_whatsapp} on WhatsApp."
    elif in_app:
        words = f"{mobeds(in_app)} asked in the app."
    elif on_whatsapp:
        words = f"{mobeds(on_whatsapp)} asked on WhatsApp."
    else:
        words = f"The mobeds of {agyary.name} could not be asked on WhatsApp."
    if failed and on_whatsapp:
        words += f" {failed} could not be sent."
    if why:
        words += f" {why}"
    return words


async def ask_everyone(
    db: AsyncSession, settings: Settings, request_id: int, *, by_user: User | None = None, take: bool = False,
    now: datetime | None = None, client: httpx.AsyncClient | None = None,
) -> dict:
    """Ask everyone on the fire temple's list whether they can pray (owner,
    19 and 21 Nov 2026): at Send in Everyone at once (at_send), when the
    safety net fires (services/prayer_timers.py), and from the board's "Ask
    everyone" (``by_user``, with ``take``: the panthaky's action takes the
    request). Only a request still waiting. Each person is asked once:

    1. its app mobeds whose access is on (D9) - not its confirmed panthakys,
       not whoever sent the request or asks - become people the request
       reached (funeral_request_recipients): it shows in their Requests tab
       and red count, with a notice in the app and a phone notification ("A
       request for prayers", nothing about the family). This happens with
       WhatsApp off too: they answer in the app.
    2. everyone on the list not asked yet has a row on the request's board.
    3. template 4 goes on WhatsApp to those who can be messaged and have not
       been (STOP, D9, the caps, FUNERAL_WHATSAPP_MODE live: _ask).

    Returns what happened, in words for whoever asked: {"state", "asked" (on
    WhatsApp), "asked_in_app", "message"}; state "sent" when someone was
    asked, "closed" when the request is not waiting, else why nobody was
    ("off", "not_now", "none", "failed"). Never raises."""
    now = now or _now()
    try:
        return await _ask_everyone(db, settings, request_id, by_user=by_user, take=take, now=now, client=client)
    except Exception:   # noqa: BLE001 - the request is sent; this must not undo or fail it
        logger.exception("Asking everyone for request %s failed", request_id)
        await db.rollback()
        return {"state": "failed", "asked": 0, "asked_in_app": 0, "message": ASK_FAILED}


async def _ask_everyone(db, settings, request_id, *, by_user, take, now, client) -> dict:
    from agyary.services import funeral_requests   # here: funeral_answers reads this module

    request = await db.get(FuneralRequest, request_id)
    # Two asks at once (a tap and the safety net) wait here: the second sees the first's rows.
    await db.refresh(request, with_for_update=True)
    agyary = await db.get(Agyary, request.agyary_id)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    if request.status != REQUEST_WAITING:
        await db.commit()
        return {"state": "closed", "asked": 0, "asked_in_app": 0, "message": closed_words(request, place.name)}
    plan = await _plan(db, settings, request, agyary, by_user=by_user)
    cap = settings.prayer_callout_max_recipients
    whatsapp = plan.whatsapp[:cap]
    if len(plan.whatsapp) > cap:
        logger.warning("Request %s: %d to ask on WhatsApp, only the first %d asked", request.id,
                       len(plan.whatsapp), cap)
    if not (plan.new_recipients or plan.app_rows or whatsapp):
        await db.commit()
        why = plan.why_not_whatsapp
        state = ("off" if not fw.mode_on(settings) else "not_now") if why else "none"
        logger.info("Request %s: nobody more at fire temple %s to ask (%s)", request.id, agyary.id, state)
        return {"state": state, "asked": 0, "asked_in_app": 0, "message": _nobody_words(agyary, plan)}

    if take and by_user is not None and (plan.new_recipients or whatsapp):
        await take_request(db, request, by_user, now)
    sent_by = by_user.id if by_user is not None else request.sent_by_user_id
    callout = await _callout_of(db, request, sent_by_user_id=sent_by, now=now)
    for m, user in plan.app_rows:
        db.add(_new_row(callout, name=m["name"], phone=user.phone, how=HOW_APP, user_id=user.id))
    for user in plan.new_recipients:
        db.add(FuneralRequestRecipient(funeral_request_id=request.id, user_id=user.id, notified_at=now))
    await db.flush()
    title, body = funeral_requests.notice_text(record, place, agyary)
    for user in plan.new_recipients:
        await reminders.notify(db, user.id, funeral_requests.KIND_REQUEST, title, body,
                               link=funeral_requests.REQUESTS_LINK, agyary_id=agyary.id, now=now,
                               ttl=funeral_requests.NOTICE_TTL)
    went = 0
    if whatsapp:
        # "Please reply to tell <panthaky> whether you can take it": the panthaky who
        # asks, else the fire temple's, else the fire temple itself when it has none.
        asker = by_user if by_user is not None and by_user.id in {p.id for p in plan.panthakys} else \
            (plan.panthakys[0] if plan.panthakys else None)
        went = await _ask(db, settings, request, whatsapp,
                          asker=asker.name if asker else agyary.name,
                          asker_max=template_text.MOBED_NAME_MAX if asker else template_text.TEMPLE_MAX,
                          sent_by_user_id=sent_by, now=now, client=client)
    else:
        await db.commit()
    if plan.new_recipients:
        push = funeral_requests.push_text(place, agyary)
        await web_push.send_to_users(db, settings, [u.id for u in plan.new_recipients], title=push[0],
                                     body=push[1], url="/mobed" + funeral_requests.REQUESTS_LINK,
                                     tag=f"funeral-request-{request.id}")
        await db.commit()
    in_app = len(plan.new_recipients)
    logger.warning("Request %s: everyone at fire temple %s asked%s: %d in the app, %d of %d on WhatsApp",
                   request.id, agyary.id, f" by user {by_user.id}" if by_user is not None else "", in_app, went,
                   len(whatsapp))
    why = plan.why_not_whatsapp
    if in_app or went:
        state, message = "sent", _asked_words(agyary, in_app, went, len(whatsapp) - went, None if whatsapp else why)
    elif whatsapp:
        state, message = "failed", _asked_words(agyary, 0, 0, len(whatsapp), None)
    else:
        # Only rows for people the request had reached at Send (a fire temple
        # with no panthaky): nobody new was asked.
        state = ("off" if not fw.mode_on(settings) else "not_now") if why else "none"
        message = _nobody_words(agyary, plan)
    return {"state": state, "asked": went, "asked_in_app": in_app, "message": message}


async def ask_everyone_now(db: AsyncSession, settings: Settings, request: FuneralRequest,
                           user: User | None) -> dict:
    """For the board: whether "Ask everyone" would ask anyone now, and if
    not, why (greyed with the reason)."""
    agyary = await db.get(Agyary, request.agyary_id)
    if request.status != REQUEST_WAITING:
        record = await db.get(FuneralRecord, request.funeral_record_id)
        place = await db.get(FuneralPlace, record.funeral_place_id)
        return {"can": False, "why_not": closed_words(request, place.name)}
    plan = await _plan(db, settings, request, agyary, by_user=user)
    return {"can": plan.anything, "why_not": None if plan.anything else _nobody_words(agyary, plan)}


async def take_request(db: AsyncSession, request: FuneralRequest, user: User, now: datetime) -> bool:
    """The panthaky's first action on the board takes the request for the
    fire temple: once, by a conditional update (the first of two at the same
    moment). Not committed here. Returns whether this call took it."""
    taken = (await db.execute(
        update(FuneralRequest).where(FuneralRequest.id == request.id, FuneralRequest.taken_at.is_(None))
        .values(taken_at=now, taken_by_user_id=user.id).returning(FuneralRequest.id)
    )).scalar_one_or_none()
    if taken is not None:
        logger.info("Funeral request %s taken on the board by user %s", request.id, user.id)
    return taken is not None


# --- The board's rows: one per person per request (R3.1 step 4) ---------------------

async def _request_rows(db: AsyncSession, request_id: int) -> list[PrayerCalloutAnswer]:
    """Every row of this request, whichever call-out it hangs on, oldest first."""
    return list((await db.execute(
        select(PrayerCalloutAnswer).join(PrayerCallout, PrayerCallout.id == PrayerCalloutAnswer.callout_id)
        .where(PrayerCallout.funeral_request_id == request_id).order_by(PrayerCalloutAnswer.id)
        .execution_options(populate_existing=True)
    )).scalars().all())


def _find(rows: list[PrayerCalloutAnswer], key: str, phone: str | None) -> PrayerCalloutAnswer | None:
    """This person's row on the request, if they have one: by who they are
    ("u12", "c5"), or by their number (someone added by hand who has joined
    the app since is the same person). The answered one first, if a request
    from before R3.1 asked them twice."""
    mine = [r for r in rows if _answer_key(r) == key or (phone and r.phone == phone)]
    return next((r for r in mine if r.answer is not None), mine[-1] if mine else None)


async def _callout_of(db: AsyncSession, request: FuneralRequest, *, sent_by_user_id: int | None,
                      now: datetime) -> PrayerCallout:
    """The request's call-out, which every row of its board hangs on; made
    when the first person is asked or answers."""
    callout = (await db.execute(
        select(PrayerCallout).where(PrayerCallout.funeral_request_id == request.id).order_by(PrayerCallout.id).limit(1)
    )).scalar_one_or_none()
    if callout is None:
        callout = PrayerCallout(funeral_request_id=request.id, agyary_id=request.agyary_id,
                                sent_by_user_id=sent_by_user_id, sent_at=now, asked=0)
        db.add(callout)
        await db.flush()
    return callout


def _new_row(callout: PrayerCallout, *, name: str, phone: str | None, how: str, user_id: int | None = None,
             contact_id: int | None = None) -> PrayerCalloutAnswer:
    return PrayerCalloutAnswer(callout_id=callout.id, user_id=user_id, contact_id=contact_id, name=name[:NAME_MAX],
                               phone=phone, token=_new_token(), how=how)


def holds_place(row: PrayerCalloutAnswer) -> bool:
    """Going: picked for a place, and not backed out since (step 5b)."""
    return row.picked_at is not None and row.backed_out_at is None


def is_standby(row: PrayerCalloutAnswer) -> bool:
    """A yes kept for when a place opens: never picked (someone who backed out
    is neither going nor a standby)."""
    return row.answer == CALLOUT_YES and row.picked_at is None


def backed_out(row: PrayerCalloutAnswer) -> bool:
    return row.backed_out_at is not None


# The SQL of holds_place, for counting.
HOLDS_PLACE = (PrayerCalloutAnswer.picked_at.is_not(None), PrayerCalloutAnswer.backed_out_at.is_(None))


async def _going(db: AsyncSession, request_id: int) -> int:
    return (await db.execute(
        select(func.count()).select_from(PrayerCalloutAnswer)
        .join(PrayerCallout, PrayerCallout.id == PrayerCalloutAnswer.callout_id)
        .where(PrayerCallout.funeral_request_id == request_id, *HOLDS_PLACE)
    )).scalar_one()


def closed_words(request: FuneralRequest, place_name: str) -> str:
    """Why nothing more can be done with a request that is not waiting."""
    if request.status == REQUEST_WITHDRAWN:
        return f"{place_name} withdrew this request, so nothing more is needed for it."
    if request.status == REQUEST_DECLINED:
        return "This request was declined, so nothing more is needed for it."
    if request.status == REQUEST_ALL_SET:
        return "Enough mobeds are going for this request: it is all set."
    return "This request is no longer waiting, so nothing more can be done with it here."


# --- An answer arrives: on WhatsApp, in the app, by phone, or "I'll pray" ---------------

def is_ours(payload: str | None) -> bool:
    return bool(payload) and payload.startswith(PAYLOAD_PREFIX)


async def record_answer(
    db: AsyncSession, settings: Settings, payload: str, from_phone: str | None, *, wa_user_id: str | None = None,
    now: datetime | None = None, client: httpx.AsyncClient | None = None,
) -> str:
    """A tap on "Yes, I can pray" or "Not this time" (the call-out), or on "I
    can't go any more" (the details at All set, step 5b). Only a well-formed
    token of a row that exists, from the number it was sent to, counts, and
    only the first answer of that person, whichever way it came (R3.1: an
    answer in the app first makes this one "already answered"), and nothing
    from someone who can no longer take part (left_out: taken off the list
    since, say), who is sent nothing back. A yes then goes through ``fill``;
    "I can't go any more" through standbys.back_out_on_whatsapp. Returns what
    happened, for the log (no numbers)."""
    from agyary.services import standbys   # here: standbys reads this module

    now = now or _now()
    found = _PAYLOAD.match(payload or "")
    if not found:
        return "malformed"
    token, choice = found.groups()
    answer = (await db.execute(select(PrayerCalloutAnswer).where(PrayerCalloutAnswer.token == token)
                               )).scalar_one_or_none()
    # A standby asked again when a place opened (step 5b) answers on the re-ask's own token.
    reask = answer is None
    if reask:
        answer = (await db.execute(select(PrayerCalloutAnswer).where(PrayerCalloutAnswer.reask_token == token)
                                   )).scalar_one_or_none()
    if answer is None:
        return "unknown token"
    if not _from_them(answer, from_phone, wa_user_id, await _asked_user_id(db, answer)):
        return f"answer {answer.id}: not from the number asked"
    request = await db.get(FuneralRequest, await _request_id(db, answer))
    answer_id = answer.id   # what follows may roll the session back, which forgets it
    why = (await left_out(db, settings, request.agyary_id, [answer])).get(answer.id)
    if why:
        # Taken off the list since they were asked (or no longer there): their old
        # buttons count for nothing, and nothing is sent back (the quietest).
        return f"answer {answer_id}: {why}, so nothing changed"
    if reask:
        if choice == BACK_OUT:
            return f"answer {answer_id}: not a button of the re-ask"
        outcome = await standbys.answer_reask(db, settings, request, answer, choice == "y", how=HOW_WHATSAPP,
                                              by_user=None, now=now, client=client)
    elif choice == BACK_OUT:
        outcome = await standbys.back_out_on_whatsapp(db, settings, request, answer, now=now, client=client)
    else:
        outcome = await _answer(db, settings, request, answer, choice == "y", how=HOW_WHATSAPP, by_user=None,
                                now=now, client=client)
    return f"answer {answer_id}: {outcome}"


async def _answer(
    db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, yes: bool, *,
    how: str, by_user: User | None, now: datetime, client: httpx.AsyncClient | None, over_no: bool = False,
) -> str:
    """Record one person's answer on ``row``, if it is their first: the
    request is locked first (every answer and place of a request waits here
    for the one before), then the row. The answer is committed before anything
    follows, so whatever happens next it stands. Returns what happened, for
    the log; "already answered" when they had answered before.

    ``over_no`` (a call's Going, call_result): a yes may take the place of an
    earlier no of theirs - people change their mind on the phone (lead's
    choice, 21 Nov 2026) - but never of a yes: someone going or on standby
    is left as they are."""
    await db.refresh(request, with_for_update=True)
    await db.refresh(row, with_for_update=True)
    said = [r.answer for r in (row, *(r for r in await _request_rows(db, request.id)
                                      if r.id != row.id and _same_person(r, row))) if r.answer is not None]
    if said and not (over_no and yes and all(a == CALLOUT_NO for a in said)):
        await db.commit()
        return "already answered"
    if said:
        logger.info("Answer %s on request %s: an earlier no becomes a yes by phone", row.id, request.id)
    row.answer, row.answered_at, row.how = (CALLOUT_YES if yes else CALLOUT_NO), now, how
    row.recorded_by_user_id = by_user.id if by_user is not None and how in (HOW_PHONE, HOW_SELF) else None
    await db.commit()
    try:
        if yes:
            return await fill(db, settings, request, row, how, by_user, now, client)
        return await _after_no(db, settings, request, now=now)
    except Exception:   # noqa: BLE001 - the answer is kept; what did not follow is on the board
        logger.exception("After answer %s on request %s", row.id, request.id)
        await db.rollback()
        return ("yes" if yes else "no") + ", but what follows failed"


def _same_person(a: PrayerCalloutAnswer, b: PrayerCalloutAnswer) -> bool:
    return (_answer_key(a) is not None and _answer_key(a) == _answer_key(b)) or bool(a.phone and a.phone == b.phone)


# What a mobed going, or on standby, is told in the app (owner, 21 Nov 2026).
GOING_WORDS = "You are going. You will get the details once enough mobeds are going."
# An app mobed whose "I can pray" filled the last place: the details are on their card now.
ALL_SET_GOING_WORDS = "You are going, and all the places are filled: it is all set."
HOW_WORDS = {HOW_WHATSAPP: "said yes on WhatsApp", HOW_APP: "said yes in the app", HOW_PHONE: "said yes on the phone"}


def _said(row: PrayerCalloutAnswer, how: str, departed: str) -> str:
    if how == HOW_SELF:
        return f"{row.name} will pray for {departed}"
    return f"{row.name} {HOW_WORDS.get(how, 'said yes')} for the prayers for {departed}"


async def fill(
    db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, how: str,
    by_user: User | None, now: datetime, client: httpx.AsyncClient | None,
) -> str:
    """The one rule for a Yes (R3.1 step 4), whichever way it came: a WhatsApp
    button, "I can pray" in the app, the panthaky's "I'll pray", or a mobed
    marked Going after a call. ``row`` has said yes and is committed.

    - The request withdrawn or declined: nothing fills; a WhatsApp Yes is told
      "This prayer request was withdrawn." (inside the 24 hours it opened).
    - A place free (``wanted`` places): the row is one of those going
      (``picked_at``). Nobody is sent the details now - they go only at All
      set (Step 5). The panthakys are told in the app and on their phones
      "<name> is going (1 of 2)", with nothing about the family on the lock
      screen; an app mobed going is told so in the app.
    - The places full: the row stays a Yes without ``picked_at``, a standby,
      in ``answered_at`` order (Step 5b asks them when a place opens). A
      WhatsApp Yes gets the "Enough mobeds" text inside the 24 hours; an app
      mobed the same words in the app.
    - The last place filled: all_set.on_full, once.

    Two Yeses at the same moment fill exactly the free places: the request is
    locked while the places are counted. Commits. Returns what happened, for
    the log."""
    from agyary.services import all_set   # here: Step 5 makes all_set reach back into the books

    await db.refresh(request, with_for_update=True)
    await db.refresh(row)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    departed = fw.departed(record)
    if request.status in (REQUEST_WITHDRAWN, REQUEST_DECLINED):
        await db.commit()
        if how == HOW_WHATSAPP and row.phone:
            await fw.deliver(db, settings, [_text_send(row, request, fw.TYPE_WITHDRAWN, fw.WITHDRAWN_TEXT)],
                             now=now, client=client)
        return "yes, to a closed request"
    want, going = wanted(record), await _going(db, request.id)
    skip = by_user.id if by_user is not None else None
    if is_open(request) and going < want:
        row.picked_at = now
        await db.commit()
        going += 1
        await _tell_panthakys(
            db, settings, request, row, KIND_GOING, f"{row.name} is going ({going} of {want})",
            f"{_said(row, how, departed)}: {going} of {want} going.",
            push="Open Mobed Diary to see who is going.", now=now, skip_user_id=skip)
        if how != HOW_SELF:
            await _tell_mobed(db, settings, request, row, "You are going to pray", GOING_WORDS, now=now)
        await db.commit()
        if going >= want and request.status == REQUEST_WAITING:
            await all_set.on_full(db, settings, request, now=now, client=client, by_user_id=skip)
            return "yes, going, all set"
        return "yes, going"

    # A standby: kept, in the order they said yes.
    await db.commit()
    told = False
    if how == HOW_WHATSAPP and row.phone:
        sent = await fw.deliver(db, settings, [_text_send(row, request, fw.TYPE_ENOUGH, fw.ENOUGH_TEXT)],
                                now=now, client=client)
        told = any(fw.went(n) for n in sent)
        if told:
            row.enough_sent_at = now
    told_words = {HOW_WHATSAPP: (", and were told so on WhatsApp." if told
                                 else "; the WhatsApp reply to them could not be sent."),
                  HOW_APP: ", and were told so in the app."}.get(how, ".")
    await _tell_panthakys(
        db, settings, request, row, KIND_YES, f"{row.name} also said yes",
        f"{_said(row, how, departed)}. Enough mobeds are going, so they are on standby{told_words}",
        push=None, now=now, skip_user_id=skip)
    if how != HOW_SELF:
        await _tell_mobed(db, settings, request, row, "Enough mobeds are going", fw.ENOUGH_TEXT, now=now)
    await db.commit()
    if request.status == REQUEST_WAITING and going >= want:
        # Full, but not marked all set yet (it broke when the last place filled).
        await all_set.on_full(db, settings, request, now=now, client=client, by_user_id=skip)
    return "yes, standby"


async def _tell_mobed(db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer,
                      title: str, body: str, *, now: datetime) -> None:
    """An app mobed, about their own yes, in the app (D9: only an account that is on)."""
    if not row.user_id:
        return
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active or not mobed_access.has_access(settings, user):
        return
    await reminders.notify(db, user.id, KIND_MY_YES, title, body, agyary_id=request.agyary_id, now=now,
                           ttl=NOTICE_TTL)


# When everyone asked at a fire temple with no panthaky said no (owner, 21 Nov 2026, third round).
KIND_NOBODY = "funeral_request_nobody"


async def _after_no(db: AsyncSession, settings: Settings, request: FuneralRequest, *, now: datetime) -> str:
    """A no answers only for the one who said it. At a fire temple with no
    confirmed panthaky (whose access is on), once everyone asked has said no -
    every row of the request, and everyone the request reached in the app who
    can still answer - the request closes as declined for it, and the funeral
    place's managers (and the admin who sent it acting for the place) are told
    "Nobody at <agyari> can take it", so they can send it elsewhere. A
    panthaky decides for their fire temple ("We can't take this"), so where
    there is one the request stays open. Once only: a conditional update."""
    from agyary.services import funeral_answers, funeral_requests, panthaky

    await db.refresh(request, with_for_update=True)
    if request.status != REQUEST_WAITING or await panthaky.panthakys_of(db, settings, request.agyary_id):
        await db.commit()
        return "no"
    rows = await _request_rows(db, request.id)
    if not rows or any(r.answer != CALLOUT_NO for r in rows):
        await db.commit()
        return "no"
    members = set((await db.execute(select(AgyaryUser.user_id).where(
        AgyaryUser.agyary_id == request.agyary_id, AgyaryUser.is_active.is_(True)))).scalars())
    said_no = {r.user_id for r in rows if r.user_id}
    if any(u.id not in said_no and u.id in members and u.is_active and mobed_access.has_access(settings, u)
           for u in await funeral_requests.asked(db, request)):
        await db.commit()
        return "no"
    closed = (await db.execute(
        update(FuneralRequest).where(FuneralRequest.id == request.id, FuneralRequest.status == REQUEST_WAITING)
        .values(status=REQUEST_DECLINED, decided_at=now, decided_by_user_id=None, nobody_could=True)
        .returning(FuneralRequest.id)
    )).scalar_one_or_none()
    await db.commit()
    await db.refresh(request)
    if closed is None:
        return "no"
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    title = f"Nobody at {agyary.name} can take it"
    await funeral_answers._tell_managers(
        db, settings, record, request, kind=KIND_NOBODY, title=title,
        body=f"Everyone asked at {agyary.name} said they cannot pray for {fw.departed(record)}. "
             "You can send it to another fire temple.",
        push=(title, f"The request from {place.name}: you can send it to another fire temple."), now=now)
    await db.commit()
    logger.warning("Funeral request %s: everyone asked at fire temple %s said no, so it is declined there",
                   request.id, agyary.id)
    return "no, and nobody at the fire temple can take it"


async def _asked_user_id(db: AsyncSession, answer: PrayerCalloutAnswer) -> str | None:
    """The WhatsApp username id the call-out (or, since step 5b, the details
    with "I can't go any more" on them) was delivered to, if Meta gave one."""
    rows = await fw.rows_for(db, request_id=await _request_id(db, answer),
                             kinds=(fw.TYPE_CALLOUT, fw.TYPE_ALL_SET_DETAILS))
    for n in rows:
        if n.template_params.get("answer") == str(answer.id) and n.recipient_user_id:
            return n.recipient_user_id
    return None


async def _request_id(db: AsyncSession, answer: PrayerCalloutAnswer) -> int:
    callout = await db.get(PrayerCallout, answer.callout_id)
    return callout.funeral_request_id


def _from_them(answer: PrayerCalloutAnswer, from_phone: str | None, wa_user_id: str | None,
               asked_user_id: str | None) -> bool:
    if from_phone:
        return answer.phone is not None and from_phone == answer.phone
    return bool(wa_user_id) and wa_user_id == asked_user_id


def _to(a: PrayerCalloutAnswer) -> dict:
    return {"recipient_type": "user" if a.user_id else "contact", "recipient_id": a.user_id or a.contact_id or 0}


def _text_send(a: PrayerCalloutAnswer, request: FuneralRequest, kind: str, text: str) -> fw.Send:
    return fw.Send(kind=kind, phone=a.phone, agyary_id=request.agyary_id, text=text,
                   refs={"request": request.id, "answer": a.id}, **_to(a))


async def _tell_panthakys(
    db: AsyncSession, settings: Settings, request: FuneralRequest, answer: PrayerCalloutAnswer, kind: str,
    title: str, body: str, *, push: str | None, now: datetime, skip_user_id: int | None = None,
    push_title: str | None = None, link: str | None = None,
) -> list[User]:
    """The fire temple's confirmed panthakys the request reached, whose access
    is on (not the one who answered, nor the one who marked it): in the app,
    and with ``push`` on their phones too. The lock screen says who, and
    nothing about the departed or the family. A fire temple with no panthaky:
    nobody (each mobed's card shows how many are going). Returns who was told."""
    from agyary.services import funeral_requests, panthaky   # here: funeral_answers reads this module

    confirmed = {p.id for p in await panthaky.panthakys_of(db, settings, request.agyary_id)}
    people = [u for u in await funeral_requests.asked(db, request)
              if u.id in confirmed and u.id not in (answer.user_id, skip_user_id)]
    # The request's own page, with the board (the old call-out screen's address
    # still opens it, for notices from before R3.1 step 7).
    link = link or f"#/requests/{request.id}"
    for u in people:
        await reminders.notify(db, u.id, kind, title, body, link=link, agyary_id=request.agyary_id, now=now,
                               ttl=NOTICE_TTL)
    if push and people:
        await web_push.send_to_users(db, settings, [u.id for u in people], title=push_title or title, body=push,
                                     url="/mobed" + link, tag=f"callout-{kind}-{answer.id}")
    return people


# --- The board: "Who will pray: n of N" (R3.1 step 4) --------------------------------

async def board_request(db: AsyncSession, settings: Settings, user: User, request_id: int) -> FuneralRequest | None:
    """The request, if this person may use its board: a confirmed panthaky of
    the fire temple it was sent to whom the request reached, or the admin.
    None otherwise (a 404, whatever the reason: a mobed, another fire
    temple's panthaky, someone who only says they are the panthaky)."""
    request = await db.get(FuneralRequest, request_id)
    if request is None:
        return None
    if guardrails.is_admin(settings, user.phone):
        return request
    if not await is_confirmed_panthaky(db, request.agyary_id, user.id):
        return None
    reached = (await db.execute(select(FuneralRequestRecipient.user_id).where(
        FuneralRequestRecipient.funeral_request_id == request.id, FuneralRequestRecipient.user_id == user.id,
    ))).first()
    return request if reached is not None else None


# A person's state for this request, on the board's Mobeds list.
NOT_ASKED, ASKED_APP, ASKED_WHATSAPP = "not_asked", "asked_app", "asked_whatsapp"
SAID_NO, GOING, STANDBY = "said_no", "going", "standby"
# Was going, and can no longer go (step 5b): "Can't go".
BACKED_OUT = "backed_out"


def _person(row: PrayerCalloutAnswer | None, latest: dict, in_app: bool) -> dict:
    asked_n = latest.get((fw.TYPE_CALLOUT, str(row.id))) if row is not None else None
    if row is not None and backed_out(row):
        state = BACKED_OUT
    elif row is not None and row.picked_at is not None:
        state = GOING
    elif row is not None and row.answer == CALLOUT_YES:
        state = STANDBY
    elif row is not None and row.answer == CALLOUT_NO:
        state = SAID_NO
    elif asked_n is not None:
        state = ASKED_WHATSAPP
    else:
        state = ASKED_APP if in_app else NOT_ASKED
    return {
        "state": state, "in_app": in_app, "whatsapp": _state(asked_n),
        "how": row.how if row is not None and row.answer is not None else None,
        "answered_at": row.answered_at.isoformat() if row is not None and row.answered_at else None,
    }


def _place(row: PrayerCalloutAnswer, at: datetime | None) -> dict:
    return {"key": _answer_key(row), "name": row.name, "how": row.how, "at": at.isoformat() if at else None}


# Someone going can back out while the request is waiting or all set (step 5b).
MAY_BACK_OUT = (REQUEST_WAITING, REQUEST_ALL_SET)


def prayers_begun(record: FuneralRecord, now: datetime) -> bool:
    """Whether the prayers have begun (prayer_timers.prayers_begin): from then
    on nobody going can back out in the app. With no days given, never."""
    from agyary.services import prayer_timers   # here: prayer_timers reads this module

    start = prayer_timers.record_begins(record)
    return start is not None and now >= start


def may_back_out(request: FuneralRequest, record: FuneralRecord, now: datetime) -> bool:
    return request.status in MAY_BACK_OUT and not prayers_begun(record, now)


def reopened(request: FuneralRequest) -> bool:
    """All set once, and waiting again because someone going backed out (step 5b)."""
    return request.status == REQUEST_WAITING and request.all_set_at is not None


async def board(db: AsyncSession, settings: Settings, user: User, request: FuneralRequest) -> dict:
    """The board, for board_request's people only: the request (no family
    name or number), the way, who took it, the places and the standbys (in
    the order they said yes), the fire temple's Mobeds list with their numbers
    (as on the Mobeds page) and each one's state for this request, whether Ask
    everyone would ask anyone now, and whether WhatsApp sending is on; once
    all set, for the panthaky the family went to only, the family's contact
    and everyone going (all_set.contacts_for)."""
    from agyary.services import all_set   # here: all_set reads this module's readers
    from agyary.services import standbys as standbys_   # here: standbys reads this module

    # Read again, both: after a tap, something that broke after it was done (telling
    # everyone it is all set, say) rolled the session back, which forgets them.
    await db.refresh(request)
    await db.refresh(user)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    rows = await _request_rows(db, request.id)
    latest = _latest(await fw.rows_for(db, request_id=request.id, kinds=fw.CALLOUT_TYPES))
    reached = set((await db.execute(select(FuneralRequestRecipient.user_id).where(
        FuneralRequestRecipient.funeral_request_id == request.id))).scalars())
    places = sorted((r for r in rows if holds_place(r)), key=lambda r: (r.picked_at, r.id))
    # Not a standby who can no longer take part (taken off the list since): never asked again.
    out_of_it = await left_out(db, settings, agyary.id, rows)
    standbys = sorted((r for r in rows if is_standby(r) and r.id not in out_of_it),
                      key=lambda r: (r.answered_at, r.id))
    gone = sorted((r for r in rows if backed_out(r)), key=lambda r: (r.backed_out_at, r.id))
    waiting = request.status == REQUEST_WAITING
    plan = await _plan(db, settings, request, agyary, by_user=user) if waiting else None
    askable = set() if plan is None else (
        {m["key"] for m in plan.whatsapp} | {f"u{u.id}" for u in plan.new_recipients})
    people = await our_mobeds(db, settings, agyary.id, me=user, with_numbers=True)
    app_ids = [m["id"] for m in people if m["kind"] == "app"]
    phones = dict((await db.execute(select(User.id, User.phone).where(User.id.in_(app_ids)))).all()) \
        if app_ids else {}
    mobeds = []
    for m in people:
        if m["is_me"]:
            continue
        app = m["kind"] == "app"
        row = _find(rows, m["key"], phones.get(m["id"]) if app else m["phone"])
        mobeds.append({**m, **_person(row, latest, app and m["id"] in reached), "can_ask": m["key"] in askable})
    taker = await db.get(User, request.taken_by_user_id) if request.taken_by_user_id else None
    if plan is None:
        ask = {"can": False, "why_not": closed_words(request, place.name)}
    else:
        ask = {"can": plan.anything, "why_not": None if plan.anything else _nobody_words(agyary, plan)}
    return {
        "request_id": request.id,
        "status": request.status,
        "open": waiting,
        "agyari": {"id": agyary.id, "name": agyary.name},
        "prayed_name": fw.departed(record),
        "place": {"name": place.name, "kind": place.kind, "city": place.city},
        "geh_saarnu": {"date": record.geh_saarnu_date.isoformat(), "geh": record.geh_saarnu_geh,
                       "text": fw.geh_saarnu_text(record)} if record.geh_saarnu_date else None,
        "uthamna": {"date": record.uthamna_date.isoformat(),
                    "time": record.uthamna_time.strftime("%H:%M") if record.uthamna_time else None,
                    "text": fw.uthamna_text(record)} if record.uthamna_date else None,
        "mobeds_wanted": record.mobeds_wanted,
        "wanted": wanted(record),
        "going": len(places),
        "way": await request_settings.way_for(db, settings, agyary),
        "taken": {"at": request.taken_at.isoformat(), "by": taker.name if taker else None}
        if request.taken_at else None,
        "all_set_at": request.all_set_at.isoformat() if request.all_set_at else None,
        # All set once, waiting again: someone going backed out (step 5b).
        "reopened": reopened(request),
        "places": [_place(r, r.picked_at) for r in places],
        # In the order they said yes, each with where their asking again stands (step 5b):
        # "waiting" (not asked again), "asked_again", "said_no" or "no_answer".
        "standbys": [{**_place(r, r.answered_at), "reask": standbys_.reask_state(r)} for r in standbys],
        # Those who were going and can no longer go: "Can't go" (step 5b).
        "backed_out": [_place(r, r.backed_out_at) for r in gone],
        # Whether a place's "Can't go" can be marked now: not once the prayers have begun.
        "may_back_out": may_back_out(request, record, _now()),
        "mobeds": mobeds,
        "ask_everyone": ask,
        "may_pray": waiting and await is_confirmed_panthaky(db, agyary.id, user.id),
        "whatsapp": await fw.status(db, settings),
        # "Confirm with who's going": while waiting with someone going and places empty.
        "may_confirm_short": waiting and 0 < len(places) < wanted(record),
        "confirmed_short": bool(request.confirmed_short),
        # Once it is all set, for the panthaky whose book it put the family in (R3.1
        # step 5): the family's contact, everyone going, their own record and memorial.
        # None for anyone else - another panthaky, the admin - and before All set.
        "all_set": await all_set.contacts_for(db, request, user),
    }


async def _lock_waiting(db: AsyncSession, request: FuneralRequest) -> None:
    """The request locked for a board action, which only a waiting request takes."""
    await db.refresh(request, with_for_update=True)
    if request.status != REQUEST_WAITING:
        record = await db.get(FuneralRecord, request.funeral_record_id)
        place = await db.get(FuneralPlace, record.funeral_place_id)
        raise CalloutError(closed_words(request, place.name))


async def ask_from_board(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """The board's "Ask everyone": ask_everyone, taking the request. Refused in
    plain words when it can ask nobody (and then nothing is taken)."""
    done = await ask_everyone(db, settings, request.id, by_user=user, take=True, now=now, client=client)
    if done["state"] in ("closed", "off", "not_now", "none") or done["message"] == ASK_FAILED:
        raise CalloutError(done["message"])
    return done


def _already(name: str, row: PrayerCalloutAnswer, *, me: bool = False) -> str:
    if backed_out(row):
        return "You have said you can't go." if me else f"{name} has said they can't go."
    if row.picked_at is not None:
        return "You are already going." if me else f"{name} is already going."
    if row.answer == CALLOUT_YES:
        return "You are on standby already." if me else f"{name} already said yes and is on standby."
    return "You have already answered for yourself." if me else f"{name} has already said they cannot pray this time."


def _done_words(row: PrayerCalloutAnswer, request: FuneralRequest, going: int, want: int, *, me: bool) -> str:
    who = "You are" if me else f"{row.name} is"
    if row.picked_at is None:
        return f"Enough mobeds are going already, so {'you are' if me else row.name + ' is'} on standby."
    if request.status == REQUEST_ALL_SET:
        return f"{who} going. All the places are filled: it is all set."
    return f"{who} going: {going} of {want}."


async def pray_myself(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """The panthaky's "I'll pray": their own row, a yes "self", through
    ``fill``; it takes the request. Only a confirmed panthaky of the fire
    temple (an admin who is not one has no place to fill)."""
    now = now or _now()
    user_id = user.id   # what follows may roll the session back, which forgets the account
    if not await is_confirmed_panthaky(db, request.agyary_id, user.id):
        raise CalloutError("Only the fire temple's panthaky can fill a place from here.")
    await _lock_waiting(db, request)
    row = _find(await _request_rows(db, request.id), f"u{user.id}", user.phone)
    if row is not None and row.answer is not None:
        raise CalloutError(_already(user.name, row, me=True))
    if row is None:
        callout = await _callout_of(db, request, sent_by_user_id=user.id, now=now)
        row = _new_row(callout, name=user.name, phone=user.phone, how=HOW_SELF, user_id=user.id)
        db.add(row)
        await db.flush()
    await take_request(db, request, user, now)
    outcome = await _answer(db, settings, request, row, True, how=HOW_SELF, by_user=user, now=now, client=client)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    await db.refresh(request)
    await db.refresh(row)
    logger.info("Request %s: user %s will pray (%s)", request.id, user_id, outcome)
    return {"outcome": outcome,
            "message": _done_words(row, request, await _going(db, request.id), wanted(record), me=True)}


SHORT_NOBODY = ("Nobody is going yet, so there is nobody to confirm with. "
                "Ask everyone, call a mobed, or tap I'll pray.")
SHORT_FAILED = "It could not be made all set just now. Please try again."


async def confirm_short(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """The board's "Confirm with who's going" (owner, 21 Nov 2026; R3.1 step
    5): while the request is waiting with at least one going and fewer than
    wanted, it becomes all set with those going - ``confirmed_short`` - through
    the same All set as when the places fill (all_set.on_full: the books, the
    notices, the messages). It takes the request, as every board action does.
    Refused in plain words otherwise. (If the places are somehow all filled
    while it still waits, it is simply made all set.)"""
    from agyary.services import all_set   # here: all_set reads this module

    now = now or _now()
    user_id = user.id   # what follows may roll the session back, which forgets the account
    await _lock_waiting(db, request)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    want, going = wanted(record), await _going(db, request.id)
    if going == 0:
        raise CalloutError(SHORT_NOBODY)
    short = going < want
    await take_request(db, request, user, now)
    made = await all_set.on_full(db, settings, request, now=now, client=client, short=short, by_user_id=user_id)
    if not made:
        raise CalloutError(SHORT_FAILED)
    logger.warning("Request %s: user %s confirmed with %d of %d going", request.id, user_id, going, want)
    return {"outcome": "all set" + (", short" if short else ""),
            "message": f"All set with {going} of {want} going." if short
            else "All the places are filled: it is all set."}


CALL_RESULTS = ("going", "not_going", "no_answer")
_KEY = re.compile(r"^[uc][0-9]{1,18}$")


async def call_result(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, key, result, *,
    now: datetime | None = None, client: httpx.AsyncClient | None = None,
) -> dict:
    """What a phone call to one of the fire temple's mobeds came to, marked
    by the panthaky when back in the app: "going" (a yes by phone, recorded
    by them, through ``fill``), "not_going" (a no by phone), or "no_answer"
    (nothing kept). Any of them takes the request. Only someone on the fire
    temple's list, never "going" for someone whose account is waiting or
    switched off (D9; our_mobeds' ``may_place``), and only their first answer (an answer on WhatsApp or in
    the app first is "already answered") - except that "going" may turn an
    earlier no into a yes (lead's choice, 21 Nov 2026: people change their
    mind on the phone), and the same for someone who had said they can't go
    any more (lead's rule, R3.1 step 7: _back_in). Someone already going or
    on standby is never touched; "not_going" for them stays refused (backing
    out is Step 5b). "not_going" for someone who had said no, or that they
    can't go, already is noted quietly, the same as the first time (step 5)."""
    now = now or _now()
    # What follows may roll the session back, which forgets the account and the request.
    user_id, request_id = user.id, request.id
    if result not in CALL_RESULTS:
        raise CalloutError("Please say whether they are going, not going, or did not answer.", status=400,
                           field="result")
    if not isinstance(key, str) or not _KEY.match(key):
        raise CalloutError("That mobed could not be found on the list. Please open the board again.", status=400,
                           field="key")
    await _lock_waiting(db, request)
    agyary = await db.get(Agyary, request.agyary_id)
    m = next((m for m in await our_mobeds(db, settings, agyary.id, me=user) if m["key"] == key), None)
    if m is None:
        raise CalloutError(f"That mobed is not on {agyary.name}'s list. Please open the board again.", status=400,
                           field="key")
    if m["is_me"]:
        raise CalloutError("That is you: tap I'll pray to fill a place yourself.", status=400, field="key")
    if result == "going" and not m["may_place"]:
        # D9: nothing to or under an account that is not on, and their number never reaches the family.
        raise CalloutError(f"{m['name']} {m['no_place']}.")
    if result == "no_answer":
        await take_request(db, request, user, now)
        await db.commit()
        logger.info("Request %s: user %s called %s, no answer", request.id, user.id, key)
        return {"outcome": "no answer", "message": f"Noted: {m['name']} did not answer."}
    app = m["kind"] == "app"
    phone = (await db.get(User, m["id"])).phone if app else m["phone"]
    yes = result == "going"
    rows = await _request_rows(db, request.id)
    row = _find(rows, key, phone)
    if (row is not None and backed_out(row)
            and not any(holds_place(r) or is_standby(r) for r in rows if _same_person(r, row))):
        # They had said they can't go any more (step 5b). It takes the request.
        await take_request(db, request, user, now)
        if not yes:
            # The call says the same: noted quietly, as for an earlier no.
            await db.commit()
            logger.info("Request %s: user %s called %s, who had said they can't go", request_id, user_id, key)
            return {"outcome": "can't go, already", "message": f"Noted: {m['name']} cannot pray this time."}
        outcome = await _back_in(db, settings, request, row, by_user=user, now=now, client=client)
        await db.refresh(request)
        await db.refresh(row)
        if outcome == "already answered":
            raise CalloutError(_already(m["name"], row))
        logger.info("Request %s: user %s marked %s going by phone after they had said they can't go (%s)",
                    request_id, user_id, key, outcome)
        record = await db.get(FuneralRecord, request.funeral_record_id)
        return {"outcome": outcome,
                "message": _done_words(row, request, await _going(db, request_id), wanted(record), me=False)}
    if (not yes and row is not None and row.answer == CALLOUT_NO
            and not any(r.answer == CALLOUT_YES for r in rows if _same_person(r, row))):
        # They had said no already (on WhatsApp, in the app, or an earlier call): the call says
        # the same, so it is noted quietly rather than refused (R3.1 step 5). It takes the request.
        await take_request(db, request, user, now)
        await db.commit()
        logger.info("Request %s: user %s called %s, who had said no already", request.id, user.id, key)
        return {"outcome": "no, already", "message": f"Noted: {m['name']} cannot pray this time."}
    if row is not None and row.answer is not None and not (yes and row.answer == CALLOUT_NO):
        raise CalloutError(_already(m["name"], row))
    if row is None:
        callout = await _callout_of(db, request, sent_by_user_id=user.id, now=now)
        row = _new_row(callout, name=m["name"], phone=phone, how=HOW_PHONE, user_id=m["id"] if app else None,
                       contact_id=None if app else m["id"])
        db.add(row)
        await db.flush()
    await take_request(db, request, user, now)
    outcome = await _answer(db, settings, request, row, yes, how=HOW_PHONE, by_user=user, now=now, client=client,
                            over_no=yes)
    await db.refresh(request)
    await db.refresh(row)
    if outcome == "already answered":
        # A yes of theirs on another row (someone asked twice before R3.1): left as it is.
        theirs = [r for r in await _request_rows(db, request_id) if _same_person(r, row) and r.answer == CALLOUT_YES]
        raise CalloutError(_already(m["name"], theirs[0] if theirs else row))
    logger.info("Request %s: user %s marked %s %s by phone (%s)", request_id, user_id, key, result, outcome)
    if not yes:
        return {"outcome": outcome, "message": f"Noted: {m['name']} cannot pray this time."}
    record = await db.get(FuneralRecord, request.funeral_record_id)
    return {"outcome": outcome,
            "message": _done_words(row, request, await _going(db, request_id), wanted(record), me=False)}


async def _back_in(
    db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, *, by_user: User,
    now: datetime, client: httpx.AsyncClient | None,
) -> str:
    """A call's Going for someone who had said they can't go any more (lead's
    rule, R3.1 step 7: a call can turn a no into Going, and the same for a
    back-out). The request is locked first, then the row; the back-out is
    cleared and their yes is marked as by phone, now - so with no place free
    they are a standby, last in the order - and committed; then it goes
    through ``fill``: a place, which may make the request all set again (their
    details went at the first All set and are not sent twice), or a standby.
    Their own book kept the family (D8) and is theirs again. Returns what
    happened, for the log; "already answered" if they were no longer out."""
    row_id, request_id = row.id, request.id
    await db.refresh(request, with_for_update=True)
    await db.refresh(row, with_for_update=True)
    if not backed_out(row):
        await db.commit()
        return "already answered"
    row.backed_out_at = row.backed_out_by_user_id = row.picked_at = None
    row.answer, row.answered_at, row.how, row.recorded_by_user_id = CALLOUT_YES, now, HOW_PHONE, by_user.id
    await db.commit()
    logger.info("Answer %s on request %s: can't go any more becomes a yes by phone", row_id, request_id)
    try:
        return await fill(db, settings, request, row, HOW_PHONE, by_user, now, client)
    except Exception:   # noqa: BLE001 - the yes is kept; what did not follow is on the board
        logger.exception("After answer %s on request %s came back by phone", row_id, request_id)
        await db.rollback()
        return "yes again, but what follows failed"


# --- App mobeds answer in the app too (owner, 21 Nov 2026, third round) ---------------

PANTHAKY_USES_BOARD = "As the panthaky, please answer on the request's board: I'll pray, or We can't take this."
NO_WORDS = "Noted: you cannot pray this time."


def _mine_already(row: PrayerCalloutAnswer) -> str:
    if backed_out(row):
        return "You have said you can't go any more."
    if row.picked_at is not None:
        return "You have already said yes: you are going."
    if row.answer == CALLOUT_YES:
        return "You have already said yes: you are on standby."
    return "You have already said you cannot pray this time."


async def answer_in_app(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, choice, *,
    now: datetime | None = None, client: httpx.AsyncClient | None = None,
) -> dict:
    """An app mobed's "I can pray" (yes) or "Not this time" (no) on their
    request card: their own row, how "app", and only their first answer,
    whichever way it came (a WhatsApp tap first makes this "already
    answered", and the other way round). A yes goes through ``fill``; a no
    answers only for them (_after_no). Only someone the request reached
    (the caller checks: funeral_answers.get_for_user) who is not a confirmed
    panthaky of the fire temple - they use the board - and is still there,
    while the request is waiting, or all set (a yes is then a standby). A
    standby asked again when a place opened answers that instead
    (standbys.answer_reask_in_app, step 5b)."""
    from agyary.services import mobed_dashboard, standbys   # here: as the rest of the app's answering

    now = now or _now()
    # What follows may roll the session back, which forgets the account and the request.
    user_id, request_id = user.id, request.id
    if choice not in (CALLOUT_YES, CALLOUT_NO):
        raise CalloutError("Please answer I can pray or Not this time.", status=400, field="answer")
    if await is_confirmed_panthaky(db, request.agyary_id, user.id):
        raise CalloutError(PANTHAKY_USES_BOARD)
    await db.refresh(request, with_for_update=True)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    if request.status not in (REQUEST_WAITING, REQUEST_ALL_SET):
        place = await db.get(FuneralPlace, record.funeral_place_id)
        raise CalloutError(closed_words(request, place.name))
    agyary = await db.get(Agyary, request.agyary_id)
    if not agyary.is_active or not await mobed_dashboard.is_active_member(db, agyary.id, user.id):
        raise CalloutError(f"You are no longer at {agyary.name} in Mobed Diary, so you cannot answer for it.")
    row = _find(await _request_rows(db, request.id), f"u{user.id}", user.phone)
    if row is not None and standbys.awaiting_answer(row):
        # A standby asked again when a place opened (step 5b): this answers that.
        done = await standbys.answer_reask_in_app(db, settings, user, request, row, choice == CALLOUT_YES, now=now,
                                                  client=client)
        logger.info("Request %s: user %s answered being asked again in the app (%s)", request_id, user_id,
                    done["outcome"])
        return done
    if row is not None and row.answer is not None:
        raise CalloutError(_mine_already(row))
    if row is None:
        callout = await _callout_of(db, request, sent_by_user_id=request.sent_by_user_id, now=now)
        row = _new_row(callout, name=user.name, phone=user.phone, how=HOW_APP, user_id=user.id)
        db.add(row)
        await db.flush()
    yes = choice == CALLOUT_YES
    outcome = await _answer(db, settings, request, row, yes, how=HOW_APP, by_user=user, now=now, client=client)
    logger.info("Request %s: user %s answered in the app (%s)", request_id, user_id, outcome)
    await db.refresh(row)
    if outcome == "already answered":
        message = _mine_already(row)
    elif not yes:
        message = NO_WORDS
    elif row.picked_at is None:
        message = fw.ENOUGH_TEXT
    else:
        await db.refresh(request)
        message = ALL_SET_GOING_WORDS if request.status == REQUEST_ALL_SET else GOING_WORDS
    return {"outcome": outcome, "message": message}


async def card(db: AsyncSession, request: FuneralRequest, user: User, *, mine: bool) -> dict:
    """For a person's own request card (funeral_answers.serialize): how many
    are going of how many, and with ``mine`` (an app mobed, not a panthaky)
    their own answer and where they stand - asked, going, standby, said no,
    or (step 5b) said they can't go - whether they can still answer, back out,
    or answer being asked again. Never anyone else's name or number."""
    from agyary.services import standbys   # here: standbys reads this module

    record = await db.get(FuneralRecord, request.funeral_record_id)
    rows = await _request_rows(db, request.id)
    out = {"places": {"going": sum(1 for r in rows if holds_place(r)), "wanted": wanted(record)},
           "reopened": reopened(request)}
    if mine:
        row = _find(rows, f"u{user.id}", user.phone)
        answered = row is not None and row.answer is not None
        state = ("asked" if not answered else BACKED_OUT if backed_out(row) else GOING if row.picked_at is not None
                 else STANDBY if row.answer == CALLOUT_YES else SAID_NO)
        out["my_answer"] = {
            "state": state, "answer": row.answer if answered else None, "how": row.how if answered else None,
            "may_answer": not answered and request.status in (REQUEST_WAITING, REQUEST_ALL_SET),
            # "I can't go any more" (step 5b): someone going, before the prayers begin.
            "may_back_out": state == GOING and may_back_out(request, record, _now()),
        }
        if state == STANDBY:
            # Asked again when a place opened (step 5b): where it stands, and whether
            # "A place has opened: can you still pray?" waits for their answer.
            out["my_answer"]["reask"] = standbys.reask_state(row)
            out["my_answer"]["may_answer_again"] = (standbys.awaiting_answer(row)
                                                    and request.status == REQUEST_WAITING)
        if state in (GOING, BACKED_OUT):
            # Who "Tell <panthaky or fire temple> you can't go?" names.
            out["my_answer"]["tell"] = await standbys.who_hears(db, request)
    return out


# --- Afterwards -------------------------------------------------------------------

async def after_closed(
    db: AsyncSession, settings: Settings, request_id: int, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Once a request is withdrawn or declined and that is committed: each
    mobed whose yes came on WhatsApp is told "This prayer request was
    withdrawn." - only inside WhatsApp's 24 hours from their answer (they
    wrote to us, which is what lets a plain text go); after that nothing can
    be sent, and nothing is. Not someone who said they can't go any more:
    nothing else is sent to them (step 5b); nor anyone who can no longer take
    part (left_out: taken off the list, or an account that is not on, D9).

    A yes that came another way - in the app, by phone, the panthaky's own
    "I'll pray" - opened no WhatsApp window, so nothing goes on WhatsApp: an
    app mobed is told in the app (those the request reached are told by the
    withdrawing or declining itself, so only the others), and someone added by
    hand is not told by Mobed Diary. Returns how many went on WhatsApp. Never
    raises."""
    from agyary.services import funeral_answers, funeral_requests   # here: they read this module

    now = now or _now()
    try:
        request = await db.get(FuneralRequest, request_id)
        rows = [a for a, _ in await _answers(db, request_id)]
        out_of_it = await left_out(db, settings, request.agyary_id, rows)
        yeses = [a for a in rows if a.answer == CALLOUT_YES and not backed_out(a) and a.id not in out_of_it]
        done = _latest(await fw.rows_for(db, request_id=request_id, kinds=(fw.TYPE_WITHDRAWN,)))
        sends = [_text_send(a, request, fw.TYPE_WITHDRAWN, fw.WITHDRAWN_TEXT) for a in yeses
                 if a.how == HOW_WHATSAPP and a.phone and fw.in_window(a.answered_at, now)
                 and (fw.TYPE_WITHDRAWN, str(a.id)) not in done]
        reached = set((await db.execute(select(FuneralRequestRecipient.user_id).where(
            FuneralRequestRecipient.funeral_request_id == request_id))).scalars())
        in_app = sorted({a.user_id for a in yeses if a.how != HOW_WHATSAPP and a.user_id
                         and a.user_id not in reached and a.user_id != request.decided_by_user_id})
        if in_app:
            record = await db.get(FuneralRecord, request.funeral_record_id)
            place = await db.get(FuneralPlace, record.funeral_place_id)
            agyary = await db.get(Agyary, request.agyary_id)
            departed = fw.departed(record)
            if request.status == REQUEST_WITHDRAWN:
                kind, title = funeral_requests.KIND_WITHDRAWN, "A request for prayers was withdrawn"
                body = f"{place.name} withdrew its request to {agyary.name} for {departed}. Nothing more is needed for it."
            else:
                kind, title = funeral_answers.KIND_ANSWERED, "A request for prayers was declined"
                body = (f"{agyary.name} declined {place.name}'s request for {departed}. "
                        "Nothing more is needed from you.")
            for user_id in in_app:
                await reminders.notify(db, user_id, kind, title, body, agyary_id=request.agyary_id, now=now,
                                       ttl=NOTICE_TTL)
            await db.commit()
        rows = await fw.deliver(db, settings, sends, now=now, client=client)
        went = sum(1 for n in rows if fw.went(n))
        if sends:
            logger.warning("Request %s closed: %d of %d who said yes told", request_id, went, len(sends))
        return went
    except Exception:   # noqa: BLE001 - withdrawing or declining is done; this must not fail it
        logger.exception("Telling those who said yes that request %s is closed failed", request_id)
        await db.rollback()
        return 0
