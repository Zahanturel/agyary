"""A fire temple's own list of mobeds, and the panthaky's call-out to them on
WhatsApp (DECISIONS D10, the owner's idea of 18 Nov 2026; Phase 2 Step 5c).

The list ("Our mobeds"): the fire temple's mobeds in the app, worked out from
their memberships (never copied), and the mobeds a confirmed panthaky added by
name and number, each with the tick that they agreed to get WhatsApp messages
from Mobed Diary about prayers. Only that fire temple's confirmed panthakys and
the admin see or change it (D2's spirit): to anyone else it does not exist.

The call-out: on a request their fire temple accepted, the panthaky asks the
mobeds they choose (by default everyone who can be messaged: not STOP'd, not an
account an admin switched off, not themselves, not already asked for it)
whether they can pray - template 4, with no family details. Each mobed asked
has an answer row with an unguessable token, which is all the quick-reply
buttons carry. The first tap counts; later ones change nothing. A yes is told
to the panthaky in the app and on their phone ("<name> can pray"; nothing about
the family on the lock screen), and an app mobed sees their own yes in the app.

Picking: the panthaky picks who goes from the yeses. Those picked get template
2 (the details, with the family's contact); a yes not picked gets the short
"enough mobeds are going" text, and only inside WhatsApp's 24 hours from their
answer - otherwise nothing is sent and the screen says so. Payment is not the
app's business here.

While FUNERAL_WHATSAPP_MODE is off the list can be built, and the call-out says
it starts once Meta approves the messages.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
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
from agyary.models.enums import ACCESS_OFF, ACCESS_ON, ACCOUNT_MOBED, CALLOUT_NO, CALLOUT_YES, ROLE_PANTHAKY
from agyary.services import (
    funeral_records,
    funeral_whatsapp as fw,
    guardrails,
    mobed_access,
    reminders,
    template_text,
    web_push,
)

logger = logging.getLogger(__name__)

NAME_MAX = template_text.MOBED_NAME_MAX
MAX_CONTACTS = 300
KIND_YES = "prayer_callout_yes"
KIND_MY_YES = "prayer_callout_my_yes"
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


async def our_mobeds(db: AsyncSession, settings: Settings, agyary_id: int, *, me: User | None = None) -> list[dict]:
    """Everyone on the fire temple's list, app mobeds first, then those added
    by hand; each says whether they can be messaged now and, if not, why."""
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
        out.append({"key": f"u{u.id}", "kind": "app", "id": u.id, "name": u.name, "phone": None,
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

async def callout_request(db: AsyncSession, settings: Settings, user: User, request_id: int) -> FuneralRequest | None:
    """The request, if this person may ask its fire temple's mobeds: it was
    accepted, and they are a confirmed panthaky there (or the admin). None
    otherwise (a 404, whatever the reason)."""
    request = await db.get(FuneralRequest, request_id)
    if request is None or request.status not in funeral_records.ACCEPTED:
        return None
    if not await may_manage(db, settings, user, request.agyary_id):
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
        # Two taps on Send (or two panthakys) wait here, and the second sees the first's picks.
        query = query.with_for_update(of=PrayerCalloutAnswer).execution_options(populate_existing=True)
    return list((await db.execute(query)).all())


def _answer_key(a: PrayerCalloutAnswer) -> str | None:
    return f"u{a.user_id}" if a.user_id else f"c{a.contact_id}" if a.contact_id else None


async def view(db: AsyncSession, settings: Settings, user: User, request: FuneralRequest,
               now: datetime | None = None) -> dict:
    """The call-out screen: the prayers (no family details), whether sending is
    on, who can be asked, and everyone asked with their answer."""
    now = now or _now()
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    answered = await _answers(db, request.id)
    asked_keys = {_answer_key(a) for a, _ in answered}
    rows = await fw.rows_for(db, request_id=request.id, kinds=(fw.TYPE_CALLOUT, fw.TYPE_DETAILS, fw.TYPE_ENOUGH))
    by_answer: dict[tuple[str, str], object] = {}
    for n in rows:
        if n.template_params.get("answer"):
            by_answer[(n.notification_type, n.template_params["answer"])] = n   # the latest of each
    people = []
    for a, callout in answered:
        asked_n = by_answer.get((fw.TYPE_CALLOUT, str(a.id)))
        details_n = by_answer.get((fw.TYPE_DETAILS, str(a.id)))
        enough_n = by_answer.get((fw.TYPE_ENOUGH, str(a.id)))
        enough = None
        if a.answer == CALLOUT_YES and not a.picked_at and callout.picked_at:
            if enough_n is not None:
                enough = {"state": fw.state_words(enough_n), "why": fw.why(enough_n)}
            elif a.answered_at and callout.picked_at - a.answered_at > fw.WINDOW:
                enough = {"state": "Not told", "why": "more than 24 hours had passed since they answered, "
                                                      "so WhatsApp does not let us send it"}
        people.append({
            "id": a.id, "name": a.name, "kind": "app" if a.user_id else "contact",
            "asked": {"state": fw.state_words(asked_n), "why": fw.why(asked_n)} if asked_n else None,
            "answer": a.answer, "answered_at": a.answered_at.isoformat() if a.answered_at else None,
            "picked": a.picked_at is not None,
            "details": {"state": fw.state_words(details_n), "why": fw.why(details_n)} if details_n else None,
            "enough": enough,
            # Picked again only while their details have not gone (say, sending was paused).
            "may_pick": a.answer == CALLOUT_YES and a.details_sent_at is None,
            "in_window": fw.in_window(a.answered_at, now),
        })
    candidates = []
    for m in await our_mobeds(db, settings, request.agyary_id, me=user):
        if m["is_me"]:
            continue
        already = m["key"] in asked_keys
        candidates.append({**m, "asked_already": already,
                           "may_ask": m["can_message"] and not already})
    return {
        "request_id": request.id,
        "agyari": {"id": agyary.id, "name": agyary.name},
        "prayed_name": fw.departed(record),
        "place": place.name,
        "bungli": record.bungli,
        "geh_saarnu": fw.geh_saarnu_text(record),
        "uthamna": fw.uthamna_text(record),
        "mobeds_wanted": record.mobeds_wanted,
        "whatsapp": await fw.status(db, settings),
        "candidates": candidates,
        "asked": people,
        "max": settings.prayer_callout_max_recipients,
    }


def _new_token() -> str:
    return secrets.token_urlsafe(18)    # 24 characters, about 144 bits


async def send(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, keys: list[str], *,
    now: datetime | None = None, client: httpx.AsyncClient | None = None,
) -> PrayerCallout:
    """Ask the chosen mobeds whether they can pray (template 4)."""
    now = now or _now()
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
    names = [("the departed's name", fw.departed(record), template_text.DEPARTED_MAX),
             ("the place's name", place.name, template_text.TEMPLE_MAX),
             ("your name", user.name, template_text.MOBED_NAME_MAX),
             ("the fire temple's name", agyary.name, template_text.TEMPLE_MAX)]
    for what, text, max_len in names:
        problem = template_text.problem(text or "", max_len=max_len)
        if problem:
            raise CalloutError(f"This cannot be sent from Mobed Diary's number: {what} {problem}.")

    phones = {u.id: u.phone for u in (await db.execute(select(User).where(
        User.id.in_([m["id"] for m in chosen if m["kind"] == "app"])))).scalars()}
    callout = PrayerCallout(funeral_request_id=request.id, agyary_id=agyary.id, sent_by_user_id=user.id, sent_at=now)
    db.add(callout)
    await db.flush()
    pairs = []
    for m in chosen:
        app = m["kind"] == "app"
        a = PrayerCalloutAnswer(callout_id=callout.id, user_id=m["id"] if app else None,
                                contact_id=None if app else m["id"], name=m["name"][:NAME_MAX],
                                phone=phones[m["id"]] if app else m["phone"], token=_new_token())
        db.add(a)
        pairs.append((m, a))
    await db.flush()
    # The order of the approved template (docs/phase2-whatsapp-templates.md): "A prayer request has
    # come to {{1 agyari}} for {{2 departed}} at {{3 place}}. Geh-saarnu: {{4}}. Uthamna: {{5}}.
    # Please reply to tell {{6 panthaky}} whether you can take it."
    params = [agyary.name, fw.departed(record), place.name, fw.geh_saarnu_text(record), fw.uthamna_text(record),
              user.name]
    sends = [fw.Send(kind=fw.TYPE_CALLOUT, phone=a.phone, recipient_type="user" if m["kind"] == "app" else "contact",
                     recipient_id=m["id"], agyary_id=agyary.id, params=params,
                     quick_replies=(f"{PAYLOAD_PREFIX}{a.token}:y", f"{PAYLOAD_PREFIX}{a.token}:n"),
                     refs={"request": request.id, "answer": a.id}, names=names)
             for m, a in pairs]
    rows = await fw.deliver(db, settings, sends, now=now, client=client)
    callout.asked = sum(1 for n in rows if fw.went(n))
    await db.commit()
    logger.warning("Call-out %s for request %s by user %s: %d asked of %d chosen",
                   callout.id, request.id, user.id, callout.asked, len(chosen))
    return callout


# --- An answer arrives (the webhook) ----------------------------------------------

def is_ours(payload: str | None) -> bool:
    return bool(payload) and payload.startswith(PAYLOAD_PREFIX)


async def record_answer(
    db: AsyncSession, settings: Settings, payload: str, from_phone: str | None, *, wa_user_id: str | None = None,
    now: datetime | None = None,
) -> str:
    """A tap on "Yes, I can pray" or "Not this time". Only a well-formed token
    of a row that exists, from the number it was sent to, counts, and only the
    first time. Returns what happened, for the log (no numbers)."""
    now = now or _now()
    found = _PAYLOAD.match(payload or "")
    if not found:
        return "malformed"
    token, choice = found.groups()
    answer = (await db.execute(select(PrayerCalloutAnswer).where(PrayerCalloutAnswer.token == token)
                               .with_for_update())).scalar_one_or_none()
    if answer is None:
        return "unknown token"
    if not _from_them(answer, from_phone, wa_user_id, await _asked_user_id(db, answer)):
        return f"answer {answer.id}: not from the number asked"
    if answer.answer is not None:
        return f"answer {answer.id}: already answered"
    answer.answer = CALLOUT_YES if choice == "y" else CALLOUT_NO
    answer.answered_at = now
    await db.flush()
    if answer.answer == CALLOUT_YES:
        await _tell_of_yes(db, settings, answer, now)
    return f"answer {answer.id}: {answer.answer}"


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


async def _tell_of_yes(db: AsyncSession, settings: Settings, answer: PrayerCalloutAnswer, now: datetime) -> None:
    callout = await db.get(PrayerCallout, answer.callout_id)
    request = await db.get(FuneralRequest, callout.funeral_request_id)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    agyary = await db.get(Agyary, callout.agyary_id)
    link = f"#/requests/{request.id}/callout"
    title = f"{answer.name} can pray"
    if callout.sent_by_user_id:
        await reminders.notify(
            db, callout.sent_by_user_id, KIND_YES, title,
            f"{answer.name} said yes on WhatsApp for the prayers for {fw.departed(record)}. "
            "Open the request to pick who goes.",
            link=link, agyary_id=agyary.id, now=now, ttl=NOTICE_TTL,
        )
        # The lock screen: who, and nothing about the departed or the family.
        await web_push.send_to_users(db, settings, [callout.sent_by_user_id], title=title,
                                     body="Open Mobed Diary to pick who goes.", url="/mobed" + link,
                                     tag=f"callout-yes-{answer.id}")
    if answer.user_id:
        sender = await db.get(User, callout.sent_by_user_id) if callout.sent_by_user_id else None
        await reminders.notify(
            db, answer.user_id, KIND_MY_YES, "You said you can pray",
            f"You told {sender.name if sender else 'the panthaky'} of {agyary.name} on WhatsApp that you can pray "
            f"for {fw.departed(record)}. They will let you know who goes.",
            agyary_id=agyary.id, now=now, ttl=NOTICE_TTL,
        )


# --- Picking who goes -------------------------------------------------------------

async def pick(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, answer_ids: list[int], *,
    now: datetime | None = None, client: httpx.AsyncClient | None = None,
) -> dict:
    """Those picked get template 2 (the details, with the family's contact);
    each yes not picked gets the "enough mobeds" text, only inside 24 hours of
    their answer. Returns {"picked", "details_sent", "enough_sent", "enough_too_late"}."""
    now = now or _now()
    answered = await _answers(db, request.id, lock=True)
    by_id = {a.id: (a, c) for a, c in answered}
    ids = list(dict.fromkeys(answer_ids))
    if not ids:
        raise CalloutError("Please choose who goes.", status=400)
    chosen = []
    for i in ids:
        found = by_id.get(i)
        if found is None:
            raise CalloutError("Someone chosen could not be found. Please open the list again.", status=400)
        a, _ = found
        if a.answer != CALLOUT_YES:
            raise CalloutError(f"{a.name} has not said yes, so they cannot be picked.", status=400)
        if a.details_sent_at is None:      # picked before, but the details did not go: try again
            chosen.append(a)
    for a in chosen:
        if a.picked_at is None:
            a.picked_at, a.picked_by_user_id = now, user.id
    for c in {c.id: c for _, c in answered}.values():
        c.picked_at = now
    await db.flush()

    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    sends = [fw.details_send(record, place, phone=a.phone, recipient_type="user" if a.user_id else "contact",
                             recipient_id=a.user_id or a.contact_id or 0, agyary_id=request.agyary_id,
                             refs={"request": request.id, "answer": a.id, "to": "picked"})
             for a in chosen if a.phone]
    too_late = []
    for a, _ in answered:
        if a.answer != CALLOUT_YES or a.picked_at is not None or a.enough_sent_at is not None or not a.phone:
            continue
        if not fw.in_window(a.answered_at, now):
            too_late.append(a)
            continue
        sends.append(fw.Send(kind=fw.TYPE_ENOUGH, phone=a.phone, recipient_type="user" if a.user_id else "contact",
                             recipient_id=a.user_id or a.contact_id or 0, agyary_id=request.agyary_id,
                             text=fw.ENOUGH_TEXT, refs={"request": request.id, "answer": a.id}))
    await db.commit()
    rows = await fw.deliver(db, settings, sends, now=now, client=client)
    answers = {a.id: a for a, _ in answered}
    details = enough = 0
    for n in rows:
        a = answers.get(int(n.template_params.get("answer", 0)))
        if a is None or not fw.went(n):
            continue
        if n.notification_type == fw.TYPE_DETAILS:
            a.details_sent_at, details = now, details + 1
        else:
            a.enough_sent_at, enough = now, enough + 1
    await db.commit()
    logger.warning("Request %s: user %s picked %d (details sent to %d, %d told enough, %d too late to tell)",
                   request.id, user.id, len(chosen), details, enough, len(too_late))
    return {"picked": len(chosen), "details_sent": details, "enough_sent": enough, "enough_too_late": len(too_late)}
