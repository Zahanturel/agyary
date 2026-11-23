"""A request for prayers, on the fire temple's side (DECISIONS D10 and its
18 Nov amendment, D2, D4; Phase 2 Step 5; R3.1).

Who sees a request: exactly the people it reached
(funeral_request_recipients) - a fire temple's confirmed panthakys, its app
mobeds once they are asked (R3.1), or if it had no panthaky, its mobeds.
Nobody else, however the request id is guessed: it is 404 to anyone not asked.
The family's name and number are shown only once it is all set, and then only
to those whose own book it put the family in (services/all_set.py).

Taking a request: since R3.1 only the "Who will pray" board's actions take it
(services/prayer_callout.py); the old Accept is gone (R3.1 step 7). A request
accepted the old way before R3.1 keeps its state and reads as it did (D8):
"Accepted by <name>" for the others asked, and for the one who accepted the
family's contact, the message to them, their own record of the family and the
memorial they made from it, and what our number sent then
(funeral_whatsapp.summary). Whether they let the place have their name and
number is kept on the request (accepter_shared_contact): the manager's screen
shows the number only when it is set.

Declining ("We can't take this", a confirmed panthaky's), with an optional
short reason, locks the funeral record and then the request (the order
withdrawing and editing use, so they cannot cross), closes the request for
that fire temple, and the manager can send it to another; a request that is no
longer waiting is refused in plain words. The funeral place's managers are
told in the app and on their phones, and so is the admin who sent the request
while acting for the place; neither carries the family's name or number.

put_in_book sets up one person's own book, and only theirs (D2): their own
record of the family's number (the one they already have, or a new one), with
reminders off as for anyone new (D4; a STOP the number sent is kept, as
always), and the Geh-saarnu and the Uthamna on their calendar. All set uses it
for each person praying.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.calendar import CalendarSystem
from agyary.core.config import Settings, get_settings
from agyary.messaging import booking_service
from agyary.messaging.geh_times import GEH_START_TIMES, IST, machi_ceremony_datetime
from agyary.models import (
    Agyary,
    AgyaryUser,
    Customer,
    FuneralPlace,
    FuneralPlaceManager,
    FuneralRecord,
    FuneralRequest,
    FuneralRequestBook,
    FuneralRequestRecipient,
    Memorial,
    PrayerCallout,
    PrayerCalloutAnswer,
    Service,
    User,
)
from agyary.models.enums import (
    ACCOUNT_FUNERAL_MANAGER,
    GEH_NAMES,
    REQUEST_ALL_SET,
    REQUEST_DECLINED,
    REQUEST_WAITING,
    REQUEST_WITHDRAWN,
    ROLE_PANTHAKY,
)
from agyary.services import (
    behdin_directory,
    funeral_records,
    funeral_requests,
    funeral_whatsapp,
    guardrails,
    mobed_access,
    prayer_callout,
    mobed_dashboard,
    reminders,
    template_text,
    web_push,
)

logger = logging.getLogger(__name__)

# How many answered requests the Requests tab shows under "Earlier": far more than a person
# meets in years (22 Nov 2026: it was 20, and older ones vanished with no word of it).
EARLIER = 500
REASON_MAX = 200
NOTICE_TTL = funeral_requests.NOTICE_TTL
KIND_DECLINED = "funeral_request_declined"
# To the others who were asked, once one of them has answered.
KIND_ANSWERED = "funeral_request_answered"

# The events put on each calendar (put_in_book), by these names in the fire
# temple's service list (added to it if it has none of that name).
GEH_SAARNU, UTHAMNA = "Geh-saarnu", "Uthamna"
# The Uthamna is in the afternoon (Uziran geh). With no time given, it goes on
# the calendar at the start of Uziran and the mobed is told to check it.
UTHAMNA_GEH = 3
KIND_LABELS = {"doongerwadi": "Doongerwadi", "prayer_hall": "Prayer hall", "aramgah": "Aramgah"}


class AnswerError(ValueError):
    """A request that cannot be answered now; the message is for the mobed."""

    def __init__(self, message: str, status: int = 409, field: str | None = None):
        super().__init__(message)
        self.status = status
        self.field = field


NOT_FOUND = "That request could not be found."


# --- Who was asked ---------------------------------------------------------------

def _asked(user_id: int):
    return select(FuneralRequestRecipient.funeral_request_id).where(FuneralRequestRecipient.user_id == user_id)


def _listed_at(user_id: int):
    """The fire temples this person is one of the mobeds of for prayer requests
    (panthaky.counts_for_requests; D10, 22 Nov 2026)."""
    from agyary.services import panthaky   # here: panthaky reaches mobed_access, which this module reads too

    return select(AgyaryUser.agyary_id).join(User, User.id == AgyaryUser.user_id).where(
        AgyaryUser.user_id == user_id, AgyaryUser.is_active.is_(True), panthaky.counts_clause(get_settings()))


async def waiting_count(db: AsyncSession, user_id: int) -> int:
    """The red count on the Requests tab: how many requests wait for this
    person (R3.1 step 4). For a confirmed panthaky of the fire temple, its
    waiting requests nobody has taken on the board yet (Ask everyone, I'll
    pray, a call's result). For anyone else it reached - an app mobed - its
    waiting requests they have not answered, in the app or on WhatsApp, and
    (step 5b) those where, a standby asked again, they have not answered that.
    Never one at a fire temple where they are no longer one of its mobeds for
    requests (taken off its list since): they cannot answer it."""
    panthaky_at = select(AgyaryUser.agyary_id).where(
        AgyaryUser.user_id == user_id, AgyaryUser.role == ROLE_PANTHAKY, AgyaryUser.is_active.is_(True))
    answered = (
        select(PrayerCallout.funeral_request_id)
        .join(PrayerCalloutAnswer, PrayerCalloutAnswer.callout_id == PrayerCallout.id)
        .where(PrayerCalloutAnswer.answer.is_not(None),
               or_(PrayerCalloutAnswer.reasked_at.is_(None), PrayerCalloutAnswer.reask_answer.is_not(None)),
               or_(PrayerCalloutAnswer.user_id == user_id,
                   PrayerCalloutAnswer.phone == select(User.phone).where(User.id == user_id).scalar_subquery()))
    )
    return (
        await db.execute(
            select(func.count()).select_from(FuneralRequest)
            .where(FuneralRequest.id.in_(_asked(user_id)), FuneralRequest.status == REQUEST_WAITING,
                   FuneralRequest.agyary_id.in_(_listed_at(user_id)),
                   or_(and_(FuneralRequest.agyary_id.in_(panthaky_at), FuneralRequest.taken_at.is_(None)),
                       and_(FuneralRequest.agyary_id.not_in(panthaky_at), FuneralRequest.id.not_in(answered))))
        )
    ).scalar_one()


async def for_user(db: AsyncSession, user_id: int) -> tuple[list[FuneralRequest], list[FuneralRequest]]:
    """The requests waiting for this person (oldest first: the soonest
    prayers) at fire temples where they are one of the mobeds for requests,
    and the last EARLIER they were asked that are answered or withdrawn
    (newest first)."""
    mine = select(FuneralRequest).where(FuneralRequest.id.in_(_asked(user_id)))
    waiting = (
        await db.execute(mine.where(FuneralRequest.status == REQUEST_WAITING,
                                    FuneralRequest.agyary_id.in_(_listed_at(user_id)))
                         .order_by(FuneralRequest.sent_at))
    ).scalars().all()
    earlier = (
        await db.execute(
            mine.where(FuneralRequest.status != REQUEST_WAITING)
            .order_by(FuneralRequest.decided_at.desc(), FuneralRequest.id.desc()).limit(EARLIER)
        )
    ).scalars().all()
    return list(waiting), list(earlier)


async def get_for_user(db: AsyncSession, user_id: int, request_id: int) -> FuneralRequest | None:
    """The request, if this person was asked; else None (404 either way)."""
    return (
        await db.execute(select(FuneralRequest).where(FuneralRequest.id == request_id,
                                                      FuneralRequest.id.in_(_asked(user_id))))
    ).scalar_one_or_none()


# --- What the person asked sees ----------------------------------------------------

def _day(d: date) -> str:
    return funeral_requests._day(d)


def _clock(t: time) -> str:
    return funeral_requests._clock(t)


def family_message(record: FuneralRecord, place: FuneralPlace, agyary: Agyary, mobed: User, *,
                   going: list[str] | None = None) -> str:
    """What the person's own WhatsApp opens with, to the family, for them to
    change as they like before sending. Short, and only what is known; it ends
    with the Zoroastrian wish of the family's template (owner, 19 Nov 2026),
    not "our prayers are with you".

    ``going``: the names of those going, for a panthaky whose book got the
    family but who is not praying themselves (R3.1 step 7): the agyari was
    asked, and they will pray. Without it - a mobed going, a panthaky who
    prays, the one who accepted the old way - it is "asked me"."""
    departed = funeral_records.prayed_name(record.departed_title, record.departed_name, record.departed_parent_name)
    parts = [f"Sahebji {record.family_contact_name}, I am {mobed.name} of {agyary.name}."]
    if going is None:
        parts.append(f"{place.name} has asked me to perform the prayers for {departed}.")
    else:
        parts.append(f"{place.name} has asked {agyary.name} to perform the prayers for {departed}.")
        if going:
            names = going[0] if len(going) == 1 else ", ".join(going[:-1]) + " and " + going[-1]
            parts.append(f"{names} will pray.")
    gs = (f"on {_day(record.geh_saarnu_date)}, {GEH_NAMES.get(record.geh_saarnu_geh)} geh"
          if record.geh_saarnu_date else None)
    ut = None
    if record.uthamna_date:
        ut = f"on {_day(record.uthamna_date)}" + (f", {_clock(record.uthamna_time)}" if record.uthamna_time else "")
    if gs and ut:
        parts.append(f"The Geh-saarnu is {gs}, and the Uthamna {ut}.")
    elif gs:
        parts.append(f"The Geh-saarnu is {gs}.")
    elif ut:
        parts.append(f"The Uthamna is {ut}.")
    parts.append("Please call or message me here for anything you need.")
    parts.append(f"May the ruvan of the late {departed} attain Garothman Behesht.")
    return " ".join(parts)


def memorial_prefill(record: FuneralRecord) -> dict:
    """The memorial form's fields from the record (memorial_form.js's draft):
    the name as it is prayed, and the death as it was given (D5)."""
    by_parsi = record.death_given_by == "roj_mah"
    return {
        "name": funeral_records.prayed_name(record.departed_title, record.departed_name, record.departed_parent_name),
        "calendar": record.calendar_system,
        "deathBy": "parsi" if by_parsi else "date",
        "death": "" if by_parsi else record.death_date.isoformat(),
        "deathRoj": str(record.death_roj) if by_parsi else "",
        "deathMah": str(record.death_mah) if by_parsi else "",
    }


async def serialize(db: AsyncSession, user: User, requests: list[FuneralRequest]) -> list[dict]:
    """Requests as the person asked sees them. The family's name and number,
    the message to them, and the accepter's own behdin and memorial are there
    only for the one who accepted; on an all-set request (R3.1), under
    "all_set", only for those whose book it put the family in."""
    from agyary.services import all_set   # here: all_set reads this module

    if not requests:
        return []
    records = {
        r.id: r for r in (await db.execute(
            select(FuneralRecord).where(FuneralRecord.id.in_({q.funeral_record_id for q in requests}))
        )).scalars()
    }
    places = {
        p.id: p for p in (await db.execute(
            select(FuneralPlace).where(FuneralPlace.id.in_({r.funeral_place_id for r in records.values()}))
        )).scalars()
    }
    agyaries = {
        a.id: a for a in (await db.execute(
            select(Agyary).where(Agyary.id.in_({q.agyary_id for q in requests}))
        )).scalars()
    }
    people = {q.accepted_by_user_id for q in requests} | {q.decided_by_user_id for q in requests}
    people.discard(None)
    names = dict((await db.execute(select(User.id, User.name).where(User.id.in_(people)))).all()) if people else {}

    out = []
    for q in requests:
        r = records[q.funeral_record_id]
        place = places[r.funeral_place_id]
        agyary = agyaries[q.agyary_id]
        accepted = q.status in funeral_records.ACCEPTED
        mine = accepted and q.accepted_by_user_id == user.id
        item = {
            "id": q.id,
            "status": q.status,
            "sent_at": funeral_records._when(q.sent_at),
            "decided_at": funeral_records._when(q.decided_at),
            "agyari": {"id": agyary.id, "name": agyary.name, "city": agyary.city},
            "funeral_place": {
                "name": place.name, "kind": place.kind, "kind_label": KIND_LABELS.get(place.kind, place.kind),
                "city": place.city,
            },
            "prayed_name": funeral_records.prayed_name(r.departed_title, r.departed_name, r.departed_parent_name),
            "death": {
                "date": r.death_date.isoformat(), "given_by": r.death_given_by,
                "label": funeral_records.parsi_label(r.death_date, CalendarSystem(r.calendar_system)),
            },
            "obsequies_label": funeral_records.OBSEQUIES_LABELS.get(r.obsequies, r.obsequies),
            "geh_saarnu": {
                "date": r.geh_saarnu_date.isoformat(), "geh": r.geh_saarnu_geh,
                "geh_name": GEH_NAMES.get(r.geh_saarnu_geh),
            } if r.geh_saarnu_date else None,
            "uthamna": {"date": r.uthamna_date.isoformat(), "time": funeral_records._hhmm(r.uthamna_time)}
            if r.uthamna_date else None,
            "mobeds_wanted": r.mobeds_wanted,
            "accepted_by": names.get(q.accepted_by_user_id) if accepted else None,
            "accepted_by_me": mine,
            "declined_by": names.get(q.decided_by_user_id) if q.status == REQUEST_DECLINED else None,
            "declined_by_me": q.status == REQUEST_DECLINED and q.decided_by_user_id == user.id,
        }
        if item["declined_by_me"]:
            item["decline_reason"] = q.decline_reason
        if mine:
            own = await booking_service.get_customer_by_phone(db, user.id, r.family_contact_phone)
            item.update({
                "family_contact": {"name": r.family_contact_name, "phone": r.family_contact_phone},
                "family_message": family_message(r, place, agyary, user),
                "shared_contact": bool(q.accepter_shared_contact),
                # Their own record of the family, if it is still in their book.
                "customer_id": own.id if own is not None and own.is_active else None,
                "memorial_id": q.memorial_id,
                "memorial_prefill": memorial_prefill(r),
                # The WhatsApp messages from our number on accepting (Step 5b).
                "whatsapp": await funeral_whatsapp.summary(db, None, q),
            })
        # How many are going of how many (R3.1 step 4); and for an app mobed (not
        # a confirmed panthaky, who has the board) their own answer, never anyone
        # else's name or number.
        is_panthaky = await prayer_callout.is_confirmed_panthaky(db, q.agyary_id, user.id)
        item.update(await prayer_callout.card(db, q, user, mine=not is_panthaky))
        # Once it is all set, for those it put the family in the book of only (R3.1
        # step 5): the family's contact, the panthaky, everyone going, their own
        # record and memorial. None for everyone else.
        item["all_set"] = await all_set.contacts_for(db, q, user)
        # A confirmed panthaky of the fire temple sees who was asked on WhatsApp
        # and who is going, while the request still wants mobeds (19 Nov 2026).
        item["may_call_out"] = False
        if is_panthaky:
            # Whether the board's first action has taken it for the fire temple: the
            # Requests list's "Waiting for you", counted as the red count counts it.
            item["taken"] = q.taken_at is not None
            callout = await prayer_callout.summary(db, q)
            if prayer_callout.is_open(q) or callout["asked"]:
                item.update(may_call_out=True, callout=callout,
                            callout_whatsapp=await funeral_whatsapp.status(db, get_settings()))
        out.append(item)
    return out


# --- Answering ---------------------------------------------------------------------

async def _lock(db: AsyncSession, request: FuneralRequest) -> FuneralRecord:
    """The record, then the request, locked: the order withdrawing and editing
    lock in, so a second accept (or a withdraw) waits here and then sees what
    the first did."""
    record = await db.get(FuneralRecord, request.funeral_record_id)
    await db.refresh(record, with_for_update=True)
    await db.refresh(request, with_for_update=True)
    return record


async def _not_waiting(db: AsyncSession, user: User, request: FuneralRequest, place: FuneralPlace) -> AnswerError:
    if request.status == REQUEST_ALL_SET:
        return AnswerError("Enough mobeds are going for this request: it is confirmed.")
    if request.status in funeral_records.ACCEPTED:
        if request.accepted_by_user_id == user.id:
            return AnswerError("You have already accepted this request.")
        who = await db.get(User, request.accepted_by_user_id) if request.accepted_by_user_id else None
        return AnswerError(f"Already accepted by {who.name}." if who else "Already accepted by someone else.")
    if request.status == REQUEST_WITHDRAWN:
        return AnswerError(f"{place.name} withdrew this request, so nothing more is needed for it.")
    who = await db.get(User, request.decided_by_user_id) if request.decided_by_user_id else None
    if who is not None and who.id == user.id:
        return AnswerError("You have already declined this request.")
    return AnswerError(f"This request was declined by {who.name}." if who else "This request was declined.")


async def _answerable(
    db: AsyncSession, user: User, request: FuneralRequest,
) -> tuple[FuneralRecord, FuneralPlace, Agyary]:
    record = await _lock(db, request)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    if request.status != REQUEST_WAITING:
        raise await _not_waiting(db, user, request, place)
    agyary = await db.get(Agyary, request.agyary_id)
    if agyary is None or not agyary.is_active or not await mobed_dashboard.is_active_member(db, agyary.id, user.id):
        raise AnswerError(f"You are no longer at {agyary.name if agyary else 'that fire temple'} in Mobed Diary, "
                          "so you cannot answer for it.")
    return record, place, agyary


async def _managers(db: AsyncSession, settings: Settings, place_id: int) -> list[User]:
    """The place's managers whose access is on (D9)."""
    rows = (
        await db.execute(
            select(User).join(FuneralPlaceManager, FuneralPlaceManager.user_id == User.id)
            .where(FuneralPlaceManager.funeral_place_id == place_id, FuneralPlaceManager.is_active.is_(True),
                   User.is_active.is_(True))
            .order_by(User.id)
        )
    ).scalars().all()
    return [u for u in rows if mobed_access.has_access(settings, u)]


async def _acting_admin(
    db: AsyncSession, settings: Settings, request: FuneralRequest, managers: list[User],
) -> User | None:
    """The admin who sent this request while acting for the place ("Act for
    this place"), so the owner sees the answer come back too; only while they
    are still an admin and on, and never twice."""
    uid = request.sent_by_user_id
    if uid is None or any(m.id == uid for m in managers):
        return None
    sender = await db.get(User, uid)
    if (sender is None or not sender.is_active or sender.account_kind == ACCOUNT_FUNERAL_MANAGER
            or not guardrails.is_admin(settings, sender.phone) or not mobed_access.has_access(settings, sender)):
        return None
    return sender


async def _tell_managers(
    db: AsyncSession, settings: Settings, record: FuneralRecord, request: FuneralRequest, *, kind: str,
    title: str, body: str, push: tuple[str, str], now: datetime,
) -> list[User]:
    """The place's managers, in the app and on their phones; and the admin who
    sent it while acting for the place, with a link back to that place."""
    managers = await _managers(db, settings, record.funeral_place_id)
    groups = [(managers, f"#/manager/record/{record.id}")]
    admin = await _acting_admin(db, settings, request, managers)
    if admin is not None:
        groups.append(([admin], f"#/admin/act/{record.funeral_place_id}/record/{record.id}"))
    for people, link in groups:
        for person in people:
            await reminders.notify(db, person.id, kind, title, body, link=link, now=now, ttl=NOTICE_TTL)
        if people:
            await web_push.send_to_users(
                db, settings, [p.id for p in people], title=push[0], body=push[1],
                url="/mobed" + link, tag=f"funeral-answer-{request.id}",
            )
    return managers


async def _tell_the_others(
    db: AsyncSession, request: FuneralRequest, user: User, *, title: str, body: str, now: datetime,
) -> None:
    """The others who were asked: a notice in the app only (nothing is needed
    of them, so their phones are not woken)."""
    for other in await funeral_requests.asked(db, request):
        if other.id != user.id:
            await reminders.notify(db, other.id, KIND_ANSWERED, title, body, link=funeral_requests.REQUESTS_LINK,
                                   agyary_id=request.agyary_id, now=now, ttl=NOTICE_TTL)


@dataclass
class InBook:
    """The family in one person's own book (put_in_book)."""

    customer: Customer
    created: bool
    # What went on the calendar: {"what", "date", "time", "booking_id", "conflict", "time_guessed"}.
    events: list[dict] = field(default_factory=list)
    # What did not: {"what", "why"}.
    skipped: list[dict] = field(default_factory=list)


async def _service(db: AsyncSession, agyary_id: int, name: str) -> Service:
    """The fire temple's service of this name, added to its list if missing."""
    service = (
        await db.execute(select(Service).where(Service.agyary_id == agyary_id, func.lower(Service.name) == name.lower()))
    ).scalars().first()
    if service is None:
        service = Service(agyary_id=agyary_id, name=name, offsite_capable=True, display_order=999)
        db.add(service)
        await db.flush()
    elif not service.is_active:
        service.is_active = True
        await db.flush()
    return service


async def put_in_book(
    db: AsyncSession, user: User, agyary: Agyary, record: FuneralRecord, place: FuneralPlace, *, today: date,
) -> InBook:
    """The family into this one person's own book, and only theirs (D2): their
    own record of the family's number (the one they already have, back in
    their book if they had removed it, never renamed; or a new one under the
    family contact's name), linked to the fire temple, with reminders off as
    for anyone new (D4; a STOP the number sent is kept, as always); and the
    Geh-saarnu and the Uthamna on their calendar as events at the funeral
    place. No other mobed's book is read or touched: the number is looked up
    only among this person's own records. Not committed here.

    All set (services/all_set.py) calls it once for each person whose book it
    is; accepting did the same for the one who accepted, before R3.1."""
    customer, created = await behdin_directory.create_or_link(
        db, agyary.id, user.id, name=record.family_contact_name, phone=record.family_contact_phone,
    )
    done = InBook(customer=customer, created=created)
    await _put_on_calendar(db, user, agyary, record, place, customer, done, today)
    return done


async def _put_on_calendar(
    db: AsyncSession, user: User, agyary: Agyary, record: FuneralRecord, place: FuneralPlace, customer, done: InBook,
    today: date,
) -> None:
    where = place.name
    events = (
        (GEH_SAARNU, record.geh_saarnu_date,
         machi_ceremony_datetime(record.geh_saarnu_date, record.geh_saarnu_geh) if record.geh_saarnu_date else None,
         False),
        (UTHAMNA, record.uthamna_date,
         datetime.combine(record.uthamna_date, record.uthamna_time or GEH_START_TIMES[UTHAMNA_GEH], tzinfo=IST)
         if record.uthamna_date else None,
         record.uthamna_date is not None and record.uthamna_time is None),
    )
    for what, day, at, guessed in events:
        if day is None:
            done.skipped.append({"what": what, "why": f"{place.name} did not give its day."})
            continue
        if day < today:
            done.skipped.append({"what": what, "why": f"It was on {_day(day)}, which has passed."})
            continue
        service = await _service(db, agyary.id, what)
        made = await mobed_dashboard.manual_add_booking(
            db, agyary, user.id, behdin_phone=customer.phone, behdin_name=customer.name, service_id=service.id,
            ceremony_dt_local=at, purpose="gujrela_nu", names=[], location=where, is_offsite=True,
            remember_names=False,
        )
        done.events.append({
            "what": what, "date": day.isoformat(), "time": at.strftime("%H:%M"), "booking_id": made.booking.id,
            "conflict": made.calendar_conflict, "time_guessed": guessed,
        })


def checked_reason(reason: str | None) -> str | None:
    text = " ".join(str(reason or "").split())
    if not text:
        return None
    try:
        return template_text.check(text, "reason", max_len=REASON_MAX)
    except ValueError as exc:
        raise AnswerError(str(exc), status=400, field="reason") from exc


async def decline(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, *, reason: str | None,
    now: datetime | None = None,
) -> FuneralRequest:
    """Decline for the fire temple, with an optional short reason the manager
    reads. The manager can then send it to another fire temple."""
    reason = checked_reason(reason)
    now = now or datetime.now(timezone.utc)
    record, place, agyary = await _answerable(db, user, request)
    request.status = REQUEST_DECLINED
    request.decided_by_user_id = user.id
    request.decided_at = now
    request.decline_reason = reason
    await db.flush()
    prayed = funeral_records.prayed_name(record.departed_title, record.departed_name, record.departed_parent_name)
    await _tell_managers(
        db, settings, record, request, kind=KIND_DECLINED,
        title=f"{agyary.name} declined the request",
        body=f"{user.name} of {agyary.name} cannot take the prayers for {prayed}"
             + (f": {reason.rstrip('.!? ')}." if reason else ".") + " You can send it to another fire temple.",
        push=("A request was declined", f"{agyary.name} declined the request from {place.name}."), now=now,
    )
    await _tell_the_others(
        db, request, user, title="A request for prayers was declined",
        body=f"{user.name} declined {place.name}'s request for {prayed}. Nothing more is needed from you.", now=now,
    )
    logger.warning("Funeral request %s declined by user %s at fire temple %s", request.id, user.id, agyary.id)
    return request


async def link_memorial(db: AsyncSession, user: User, request_id: int | None, memorial: Memorial) -> bool:
    """Note the memorial saved from a request: on an all-set request (R3.1
    step 5), on this person's own book row for it, if the request put the
    family in their book; on one accepted the old way, on the request, only
    for the one who accepted. Only their own memorial, and only once. Returns
    whether it was linked."""
    if request_id is None:
        return False
    request = await db.get(FuneralRequest, request_id)
    if request is None or memorial.created_by_user_id != user.id:
        return False
    linked = (await db.execute(
        update(FuneralRequestBook)
        .where(FuneralRequestBook.funeral_request_id == request.id, FuneralRequestBook.user_id == user.id,
               FuneralRequestBook.memorial_id.is_(None))
        .values(memorial_id=memorial.id).returning(FuneralRequestBook.id)
    )).scalar_one_or_none()
    if linked is not None:
        return True
    if (request.status not in funeral_records.ACCEPTED or request.accepted_by_user_id != user.id
            or request.memorial_id is not None):
        return False
    request.memorial_id = memorial.id
    await db.flush()
    return True
