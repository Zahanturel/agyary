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
the panthaky can ask again by hand those not asked yet (someone added to the
list since), while the request is open. Since R3.1 (21 Nov 2026) that is the
way Everyone at once; in Come to me first nothing goes at Send, and the
panthaky chooses who to ask (after_send, request_settings.way_for).

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
# What the quick-reply buttons carry: "pca:<token>:y" or "pca:<token>:n".
PAYLOAD_PREFIX = "pca:"
_PAYLOAD = re.compile(r"^pca:([A-Za-z0-9_-]{20,40}):([yn])$")


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


async def our_mobeds(
    db: AsyncSession, settings: Settings, agyary_id: int, *, me: User | None = None, with_numbers: bool = False,
) -> list[dict]:
    """Everyone on the fire temple's list, app mobeds first, then those added
    by hand; each says whether they can be messaged now and, if not, why.

    An app mobed's own number is given only with ``with_numbers``, which only
    the Mobeds page passes (owner, 21 Nov 2026): its route lets in only the
    fire temple's confirmed panthakys and the admin (routes/callouts.py,
    _managed_agyary). Everywhere else - the call-out screen, the call-out
    itself - it stays None."""
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
    linked_ids = {c.user_id for c in contacts if c.user_id}
    linked = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(linked_ids)))).scalars()} \
        if linked_ids else {}
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
        out.append({"key": f"u{u.id}", "kind": "app", "id": u.id, "name": u.name,
                    "phone": u.phone if shown else None,
                    "stopped": u.phone in stopped, "is_me": me is not None and u.id == me.id,
                    "can_message": why is None, "why_not": why})
    for c in contacts:
        if c.phone in member_phones:
            continue    # they joined the app: listed once, as an app mobed
        account = linked.get(c.user_id) if c.user_id else None
        why = ("they replied STOP to Mobed Diary" if c.phone in stopped
               else _off_words(account, settings) if account is not None and account.access == ACCESS_OFF else None)
        out.append({"key": f"c{c.id}", "kind": "contact", "id": c.id, "name": c.name, "phone": c.phone,
                    "stopped": c.phone in stopped, "is_me": False, "can_message": why is None, "why_not": why,
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
    contact = await db.get(AgyaryMobedContact, contact_id)
    if contact is None or contact.agyary_id != agyary_id or not contact.is_active:
        raise CalloutError("That mobed could not be found on the list.", status=404)
    contact.is_active = False
    await db.flush()
    logger.info("Mobed contact %s taken off fire temple %s's list by user %s", contact.id, agyary_id, user.id)
    return contact



# --- The call-out -----------------------------------------------------------------

def is_open(request: FuneralRequest) -> bool:
    """Waiting for the fire temple's answer, or accepted: mobeds are still
    wanted. A withdrawn or declined request asks nobody more."""
    return request.status in OPEN


def wanted(record: FuneralRecord) -> int:
    """How many mobeds go: the record's "mobeds wanted", else DEFAULT_WANTED."""
    return record.mobeds_wanted or DEFAULT_WANTED


async def callout_request(db: AsyncSession, settings: Settings, user: User, request_id: int) -> FuneralRequest | None:
    """The request, if this person may see its call-out: a confirmed panthaky
    of the fire temple it was sent to, or the admin. None otherwise (a 404,
    whatever the reason). Asking and sending need it to be open too."""
    request = await db.get(FuneralRequest, request_id)
    if request is None or not await may_manage(db, settings, user, request.agyary_id):
        return None
    return request


async def _answers(
    db: AsyncSession, request_id: int, *, lock: bool = False,
) -> list[tuple[PrayerCalloutAnswer, PrayerCallout]]:
    query = (
        select(PrayerCalloutAnswer, PrayerCallout).join(PrayerCallout, PrayerCallout.id == PrayerCalloutAnswer.callout_id)
        .where(PrayerCallout.funeral_request_id == request_id).order_by(PrayerCalloutAnswer.id)
    )
    if lock:
        # Two taps on "Send the details again" wait here, and the second sees the first's.
        query = query.with_for_update(of=PrayerCalloutAnswer).execution_options(populate_existing=True)
    return list((await db.execute(query)).all())


def _answer_key(a: PrayerCalloutAnswer) -> str | None:
    return f"u{a.user_id}" if a.user_id else f"c{a.contact_id}" if a.contact_id else None


def _latest(rows) -> dict[tuple[str, str], object]:
    """The latest message of each kind for each answer: (kind, answer id) -> row."""
    out: dict[tuple[str, str], object] = {}
    for n in rows:
        if n.template_params.get("answer"):
            out[(n.notification_type, n.template_params["answer"])] = n
    return out


def _asked_keys(answered, latest) -> set:
    """Who has been asked for this request: a call-out that went (or was
    answered). One that WhatsApp did not take may be asked again."""
    keys = set()
    for a, _ in answered:
        asked_n = latest.get((fw.TYPE_CALLOUT, str(a.id)))
        if a.answer is not None or asked_n is None or fw.went(asked_n):
            keys.add(_answer_key(a))
    return keys


def _state(n) -> dict | None:
    return {"state": fw.state_words(n), "why": fw.why(n)} if n is not None else None


async def view(db: AsyncSession, settings: Settings, user: User, request: FuneralRequest,
               now: datetime | None = None) -> dict:
    """The call-out screen: the prayers (no family details), whether sending is
    on, everyone asked with their answer and whether they are going, and who
    can still be asked."""
    now = now or _now()
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    answered = await _answers(db, request.id)
    latest = _latest(await fw.rows_for(db, request_id=request.id, kinds=fw.CALLOUT_TYPES))
    asked_keys = _asked_keys(answered, latest)
    people = []
    for a, _ in answered:
        key = str(a.id)
        details_n = latest.get((fw.TYPE_DETAILS, key))
        going = a.picked_at is not None
        people.append({
            "id": a.id, "name": a.name, "kind": "app" if a.user_id else "contact",
            "asked": _state(latest.get((fw.TYPE_CALLOUT, key))),
            "answer": a.answer, "answered_at": a.answered_at.isoformat() if a.answered_at else None,
            "going": going,
            "details": _state(details_n),
            "enough": _state(latest.get((fw.TYPE_ENOUGH, key))),
            "withdrawn_note": _state(latest.get((fw.TYPE_WITHDRAWN, key))),
            # A mobed going whose details were tried and did not go (sending was
            # paused, say), before R3.1. Since R3.1 nobody going is sent the
            # details until All set, so there is nothing to send again.
            "may_resend": going and a.details_sent_at is None and bool(a.phone) and details_n is not None
                          and not fw.went(details_n) and is_open(request),
        })
    candidates = []
    if is_open(request):
        for m in await our_mobeds(db, settings, request.agyary_id, me=user):
            if m["is_me"]:
                continue
            already = m["key"] in asked_keys
            candidates.append({**m, "asked_already": already, "may_ask": m["can_message"] and not already})
    return {
        "request_id": request.id,
        "status": request.status,
        "open": is_open(request),
        "agyari": {"id": agyary.id, "name": agyary.name},
        "prayed_name": fw.departed(record),
        "place": place.name,
        "geh_saarnu": fw.geh_saarnu_text(record),
        "uthamna": fw.uthamna_text(record),
        "mobeds_wanted": record.mobeds_wanted,
        "wanted": wanted(record),
        "going": sum(1 for p in people if p["going"]),
        "whatsapp": await fw.status(db, settings),
        "candidates": candidates,
        "asked": people,
        "max": settings.prayer_callout_max_recipients,
    }


async def summary(db: AsyncSession, request: FuneralRequest) -> dict:
    """For the request's own page: how many were asked, said yes and go."""
    record = await db.get(FuneralRecord, request.funeral_record_id)
    answered = await _answers(db, request.id)
    return {
        "asked": len(answered),
        "yes": sum(1 for a, _ in answered if a.answer == CALLOUT_YES),
        "going": sum(1 for a, _ in answered if a.picked_at is not None),
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
) -> PrayerCallout:
    """Template 4 to each of ``chosen`` (from our_mobeds), each with its own
    answer row and token. Commits; never raises for a message that did not go."""
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    names = _names(record, place, agyary, asker, asker_max)
    phones = {u.id: u.phone for u in (await db.execute(select(User).where(
        User.id.in_([m["id"] for m in chosen if m["kind"] == "app"])))).scalars()}
    callout = PrayerCallout(funeral_request_id=request.id, agyary_id=agyary.id, sent_by_user_id=sent_by_user_id,
                            sent_at=now)
    db.add(callout)
    await db.flush()
    pairs = []
    for m in chosen:
        app = m["kind"] == "app"
        a = PrayerCalloutAnswer(callout_id=callout.id, user_id=m["id"] if app else None,
                                contact_id=None if app else m["id"], name=m["name"][:NAME_MAX],
                                phone=phones[m["id"]] if app else m["phone"], token=_new_token(),
                                how=HOW_WHATSAPP)
        db.add(a)
        pairs.append((m, a))
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
    rows = await fw.deliver(db, settings, sends, now=now, client=client)
    callout.asked = sum(1 for n in rows if fw.went(n))
    await db.commit()
    return callout


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
    with no confirmed panthaky whose access is on - is the call-out now
    (at_send). Come to me first is nothing now: only the panthaky was told, and
    they choose who to ask; if they set the safety net, services/prayer_timers.py
    asks everyone later. Returns what the sender is told, as at_send does
    ({"state": "panthaky_first", ...} for Come to me first). Never raises."""
    from agyary.services import panthaky   # here: as in _at_send

    try:
        request = await db.get(FuneralRequest, request_id)
        agyary = await db.get(Agyary, request.agyary_id)
        if await request_settings.way_for(db, settings, agyary) == REQUEST_MODE_PANTHAKY_FIRST:
            panthakys = await panthaky.panthakys_of(db, settings, agyary.id)
            logger.info("Request %s: Come to me first at fire temple %s, so no call-out at sending",
                        request.id, agyary.id)
            return {"state": "panthaky_first", "asked": 0, "message": panthaky_first_words(agyary, panthakys)}
    except Exception:   # noqa: BLE001 - the request is sent; this must not undo or fail it
        logger.exception("Finding the way of request %s failed", request_id)
        await db.rollback()
        return {"state": "failed", "asked": 0,
                "message": "The mobeds could not be asked on WhatsApp. The panthaky can ask them from the request."}
    return await at_send(db, settings, request_id, now=now, client=client)


async def panthaky_acted(db: AsyncSession, request: FuneralRequest) -> bool:
    """Whether the fire temple has done something with this request, for the
    safety net (services/prayer_timers.py): it is no longer waiting (accepted,
    declined, withdrawn), or a call-out exists for it (the panthaky asked on
    WhatsApp by hand, or the mobeds were asked already). Step 4 adds the
    board's first action (I'll pray, a mobed marked Going), which takes the
    request: add it here, the one place the safety net asks."""
    if request.status != REQUEST_WAITING:
        return True
    return (await db.execute(
        select(PrayerCallout.id).where(PrayerCallout.funeral_request_id == request.id).limit(1)
    )).first() is not None


async def at_send(
    db: AsyncSession, settings: Settings, request_id: int, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """The call-out to everyone (owner, 19 Nov 2026): template 4 at once to
    everyone on the fire temple's list who can be messaged - its app mobeds
    whose access is on and the mobeds added by hand with the consent tick,
    never a STOP'd number - except its confirmed panthakys (they have the
    request in the app, and the message asks the mobeds to answer them) and
    whoever sent it. Runs once a request is sent and committed in Everyone at
    once (after_send), and in Come to me first when the safety net asks
    everyone (services/prayer_timers.py). Returns what the sender is told:
    {"state", "asked", "message"}. Never raises: sending a request cannot fail
    because of this."""
    try:
        return await _at_send(db, settings, request_id, now=now or _now(), client=client)
    except Exception:   # noqa: BLE001 - the request is sent; this must not undo or fail it
        logger.exception("The WhatsApp call-out for request %s failed", request_id)
        await db.rollback()
        return {"state": "failed", "asked": 0,
                "message": "The mobeds could not be asked on WhatsApp. The panthaky can ask them from the request."}


async def _at_send(db, settings, request_id, *, now, client) -> dict:
    from agyary.services import panthaky   # here: panthaky reaches mobed_access, which this module reads too

    request = await db.get(FuneralRequest, request_id)
    agyary = await db.get(Agyary, request.agyary_id)
    why = await fw.why_not_now(db, settings)
    if why:
        logger.info("Request %s: no WhatsApp call-out at sending (%s)", request.id,
                    "switched off" if not fw.mode_on(settings) else "cannot send now")
        return {"state": "off" if not fw.mode_on(settings) else "not_now", "asked": 0, "message": why}
    panthakys = await panthaky.panthakys_of(db, settings, agyary.id)
    skip = {p.id for p in panthakys} | {request.sent_by_user_id}
    answered = await _answers(db, request.id)
    asked = _asked_keys(answered, _latest(await fw.rows_for(db, request_id=request.id, kinds=(fw.TYPE_CALLOUT,))))
    chosen = [m for m in await our_mobeds(db, settings, agyary.id)
              if m["can_message"] and m["key"] not in asked and not (m["kind"] == "app" and m["id"] in skip)]
    if not chosen:
        logger.info("Request %s: nobody on fire temple %s's list to ask on WhatsApp", request.id, agyary.id)
        return {"state": "none", "asked": 0,
                "message": f"Nobody on {agyary.name}'s list of mobeds could be asked on WhatsApp."}
    cap = settings.prayer_callout_max_recipients
    if len(chosen) > cap:
        logger.warning("Request %s: %d on the list, only the first %d asked", request.id, len(chosen), cap)
        chosen = chosen[:cap]
    # "Please reply to tell <panthaky> whether you can take it": the panthaky, or
    # the fire temple itself when it has none in the app.
    asker, asker_max = ((panthakys[0].name, template_text.MOBED_NAME_MAX) if panthakys
                        else (agyary.name, template_text.TEMPLE_MAX))
    callout = await _ask(db, settings, request, chosen, asker=asker, asker_max=asker_max,
                         sent_by_user_id=request.sent_by_user_id, now=now, client=client)
    logger.warning("Call-out %s at sending request %s: %d asked of %d", callout.id, request.id, callout.asked,
                   len(chosen))
    n, failed = callout.asked, len(chosen) - callout.asked
    message = (f"{n} mobed{'s' if n != 1 else ''} of {agyary.name} {'was' if n == 1 else 'were'} asked on WhatsApp."
               if n else f"The mobeds of {agyary.name} could not be asked on WhatsApp.")
    if n and failed:
        message += f" {failed} could not be sent."
    return {"state": "sent" if n else "failed", "asked": n, "message": message}


async def send(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, keys: list[str], *,
    now: datetime | None = None, client: httpx.AsyncClient | None = None,
) -> PrayerCallout:
    """The panthaky asks again, by hand: those chosen who have not been asked
    for this request yet (a mobed added to the list since, say)."""
    now = now or _now()
    if not is_open(request):
        raise CalloutError("This request is closed, so nobody more can be asked for it.")
    why = await fw.why_not_now(db, settings)
    if why:
        raise CalloutError(why)
    keys = list(dict.fromkeys(keys))
    if not keys:
        raise CalloutError("Please choose who to ask.", status=400)
    if len(keys) > settings.prayer_callout_max_recipients:
        raise CalloutError(f"One call-out can ask at most {settings.prayer_callout_max_recipients} mobeds.", status=400)
    by_key = {m["key"]: m for m in (await view(db, settings, user, request, now))["candidates"]}
    chosen = []
    for key in keys:
        m = by_key.get(key)
        if m is None:
            raise CalloutError("Someone chosen is no longer on the list. Please open the list again.", status=400)
        if m["asked_already"]:
            raise CalloutError(f"{m['name']} has been asked already for these prayers.", status=400)
        if not m["can_message"]:
            raise CalloutError(f"{m['name']} cannot be asked: {m['why_not']}.", status=400)
        chosen.append(m)
    room = await fw.room_today(db, settings, request.agyary_id, now)
    if len(chosen) > room:
        raise CalloutError(f"Today's limit for WhatsApp messages from Mobed Diary allows {room} more, "
                           f"so {len(chosen)} cannot be asked now.")
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    for what, text, max_len in _names(record, place, agyary, user.name, template_text.MOBED_NAME_MAX):
        problem = template_text.problem(text or "", max_len=max_len)
        if problem:
            what = "your name" if what == "the panthaky's name" else what
            raise CalloutError(f"This cannot be sent from Mobed Diary's number: {what} {problem}.")
    callout = await _ask(db, settings, request, chosen, asker=user.name, asker_max=template_text.MOBED_NAME_MAX,
                         sent_by_user_id=user.id, now=now, client=client)
    logger.warning("Call-out %s for request %s by user %s: %d asked of %d chosen",
                   callout.id, request.id, user.id, callout.asked, len(chosen))
    return callout


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


async def _going(db: AsyncSession, request_id: int) -> int:
    return (await db.execute(
        select(func.count()).select_from(PrayerCalloutAnswer)
        .join(PrayerCallout, PrayerCallout.id == PrayerCalloutAnswer.callout_id)
        .where(PrayerCallout.funeral_request_id == request_id, PrayerCalloutAnswer.picked_at.is_not(None))
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
    """A tap on "Yes, I can pray" or "Not this time". Only a well-formed token
    of a row that exists, from the number it was sent to, counts, and only the
    first answer of that person, whichever way it came (R3.1: an answer in the
    app first makes this one "already answered"). A yes then goes through
    ``fill``. Returns what happened, for the log (no numbers)."""
    now = now or _now()
    found = _PAYLOAD.match(payload or "")
    if not found:
        return "malformed"
    token, choice = found.groups()
    answer = (await db.execute(select(PrayerCalloutAnswer).where(PrayerCalloutAnswer.token == token)
                               )).scalar_one_or_none()
    if answer is None:
        return "unknown token"
    if not _from_them(answer, from_phone, wa_user_id, await _asked_user_id(db, answer)):
        return f"answer {answer.id}: not from the number asked"
    request = await db.get(FuneralRequest, await _request_id(db, answer))
    outcome = await _answer(db, settings, request, answer, choice == "y", how=HOW_WHATSAPP, by_user=None,
                            now=now, client=client)
    return f"answer {answer.id}: {outcome}"


async def _answer(
    db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, yes: bool, *,
    how: str, by_user: User | None, now: datetime, client: httpx.AsyncClient | None,
) -> str:
    """Record one person's answer on ``row``, if it is their first: the
    request is locked first (every answer and place of a request waits here
    for the one before), then the row. The answer is committed before anything
    follows, so whatever happens next it stands. Returns what happened, for
    the log; "already answered" when they had answered before."""
    await db.refresh(request, with_for_update=True)
    await db.refresh(row, with_for_update=True)
    if row.answer is not None or any(
        r.answer is not None for r in await _request_rows(db, request.id)
        if r.id != row.id and _same_person(r, row)
    ):
        await db.commit()
        return "already answered"
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
            await all_set.on_full(db, settings, request, now=now, client=client)
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
        await all_set.on_full(db, settings, request, now=now, client=client)
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
        .values(status=REQUEST_DECLINED, decided_at=now, decided_by_user_id=None).returning(FuneralRequest.id)
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
    """The WhatsApp username id the call-out was delivered to, if Meta gave one."""
    rows = await fw.rows_for(db, request_id=await _request_id(db, answer), kinds=(fw.TYPE_CALLOUT,))
    for n in rows:
        if n.template_params.get("answer") == str(answer.id):
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
) -> None:
    """The fire temple's confirmed panthakys the request reached, whose access
    is on (not the one who answered, nor the one who marked it): in the app,
    and with ``push`` on their phones too. The lock screen says who, and
    nothing about the departed or the family. A fire temple with no panthaky:
    nobody (each mobed's card shows how many are going)."""
    from agyary.services import funeral_requests, panthaky   # here: funeral_answers reads this module

    confirmed = {p.id for p in await panthaky.panthakys_of(db, settings, request.agyary_id)}
    people = [u for u in await funeral_requests.asked(db, request)
              if u.id in confirmed and u.id not in (answer.user_id, skip_user_id)]
    link = f"#/requests/{request.id}/callout"
    for u in people:
        await reminders.notify(db, u.id, kind, title, body, link=link, agyary_id=request.agyary_id, now=now,
                               ttl=NOTICE_TTL)
    if push and people:
        await web_push.send_to_users(db, settings, [u.id for u in people], title=title, body=push,
                                     url="/mobed" + link, tag=f"callout-{kind}-{answer.id}")


# --- Afterwards -------------------------------------------------------------------

async def details_again(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, *,
    now: datetime | None = None, client: httpx.AsyncClient | None = None,
) -> dict:
    """Message 2 again to those going whose details were tried and did not go
    (sending was paused, say, before R3.1); never twice to anyone, and never
    to someone going whose details were never tried: since R3.1 step 4 they go
    only at All set. Returns {"tried", "sent"}."""
    now = now or _now()
    if not is_open(request):
        raise CalloutError("This request is closed, so nothing more is sent for it.")
    why = await fw.why_not_now(db, settings)
    if why:
        raise CalloutError(why)
    answered = await _answers(db, request.id, lock=True)
    latest = _latest(await fw.rows_for(db, request_id=request.id, kinds=(fw.TYPE_DETAILS,)))
    due = [a for a, _ in answered if a.picked_at is not None and a.details_sent_at is None and a.phone
           and (fw.TYPE_DETAILS, str(a.id)) in latest and not fw.went(latest[(fw.TYPE_DETAILS, str(a.id))])]
    if not due:
        await db.commit()
        return {"tried": 0, "sent": 0}
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    sends = [fw.details_send(record, place, phone=a.phone, agyary_id=request.agyary_id,
                             refs={"request": request.id, "answer": a.id, "to": "going"}, **_to(a)) for a in due]
    rows = await fw.deliver(db, settings, sends, now=now, client=client)
    by_id = {a.id: a for a in due}
    sent = 0
    for n in rows:
        a = by_id.get(int(n.template_params.get("answer", 0)))
        if a is not None and fw.went(n):
            a.details_sent_at, sent = now, sent + 1
    await db.commit()
    logger.warning("Request %s: details sent again by user %s to %d of %d", request.id, user.id, sent, len(due))
    return {"tried": len(due), "sent": sent}


async def after_closed(
    db: AsyncSession, settings: Settings, request_id: int, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Once a request is withdrawn or declined and that is committed: each
    mobed who said yes is told "This prayer request was withdrawn." - only
    inside WhatsApp's 24 hours from their answer; after that nothing can be
    sent, and nothing is. Returns how many went. Never raises."""
    now = now or _now()
    try:
        request = await db.get(FuneralRequest, request_id)
        answered = await _answers(db, request_id)
        done = _latest(await fw.rows_for(db, request_id=request_id, kinds=(fw.TYPE_WITHDRAWN,)))
        sends = [_text_send(a, request, fw.TYPE_WITHDRAWN, fw.WITHDRAWN_TEXT) for a, _ in answered
                 if a.answer == CALLOUT_YES and a.phone and fw.in_window(a.answered_at, now)
                 and (fw.TYPE_WITHDRAWN, str(a.id)) not in done]
        rows = await fw.deliver(db, settings, sends, now=now, client=client)
        went = sum(1 for n in rows if fw.went(n))
        if sends:
            logger.warning("Request %s closed: %d of %d who said yes told", request_id, went, len(sends))
        return went
    except Exception:   # noqa: BLE001 - withdrawing or declining is done; this must not fail it
        logger.exception("Telling those who said yes that request %s is closed failed", request_id)
        await db.rollback()
        return 0
