"""All set: a request whose places are all filled (DECISIONS D10, changed 21 Nov
2026; docs/phase2-requests-redesign.md, "All set"; R3.1).

When the last place on a request's "Who will pray" board fills - by a WhatsApp
Yes, an "I can pray" in the app, the panthaky's "I'll pray", or a mobed marked
Going after a call - services/prayer_callout.py's ``fill`` calls ``on_full``;
the panthaky's "Confirm with who's going" calls it too, with fewer going
(``short``). Only a request still waiting becomes all set: one accepted the old
way before R3.1 keeps its state (D8). A conditional update makes it all set
once, for the call that made it so, whoever else tries at the same moment.

Then, in the same transaction, the family goes into the own book of each
person praying for them (D10, 21 Nov 2026; each private, D2):

- the panthaky who took the request on the board (``taken_by_user_id``), if
  they are a confirmed panthaky of the fire temple whose access is on; if
  nobody did (Everyone at once, the mobeds filled it), each confirmed
  panthaky the request reached whose access is on;
- each app mobed going (a place with an account: an app mobed's yes, a
  panthaky's "I'll pray", a mobed marked Going after a call) whose access is
  on (D9) and who is still at the fire temple.

Each once, in their own book only: their own record of the family's number
(the one they have, or a new one), reminders off (D4), a STOP kept, and the
Geh-saarnu and Uthamna on their calendar (funeral_answers.put_in_book, the
same as accepting). Who has which book, and later the memorial each makes from
it, is in funeral_request_books. One person's book that cannot be set up is
logged and leaves the others'; anything else going wrong leaves the request
waiting, to be made all set by the next yes or tap.

Only those people, and only once it is all set, are given the family's
contact and the others praying (``contacts_for``): on the board and on their
own request card, with the memorial one tap away. Nobody else - another
panthaky, a mobed not going, the admin, the funeral place - ever is.

Once that is committed, everyone is told (``_tell``: the panthakys it reached,
each app mobed whose book it is, the funeral place's managers, in the app and
on their phones, the lock screen without the departed or the family), and,
only while FUNERAL_WHATSAPP_MODE is live, WhatsApp templates 5-8 go
(``_whatsapp``). Neither can undo the All set, and neither is ever repeated -
except that a request filled again after someone going backed out (step 5b,
services/standbys.py) is "all set again": the new names in the app, template 6
to the one new to it and template 5 to the family again, never 7 or 8.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings, get_settings
from agyary.messaging.geh_times import IST
from agyary.models import (
    Agyary,
    AgyaryMobedContact,
    Customer,
    FuneralPlace,
    FuneralRecord,
    FuneralRequest,
    FuneralRequestBook,
    PrayerCallout,
    PrayerCalloutAnswer,
    User,
)
from agyary.models.enums import REQUEST_ALL_SET, REQUEST_WAITING
from agyary.services import (
    funeral_answers,
    funeral_requests,
    mobed_access,
    mobed_dashboard,
    panthaky,
    prayer_callout,
    reminders,
    web_push,
)
from agyary.services import funeral_whatsapp as fw

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def on_full(
    db: AsyncSession, settings: Settings, request: FuneralRequest, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None, short: bool = False, by_user_id: int | None = None,
) -> bool:
    """The request's places are all filled (or, with ``short``, the panthaky
    confirmed it with those going): mark it all set and set up the books,
    once; then tell everyone (``by_user_id``, whose tap made it so, sees it on
    screen, so their phone is not woken). Commits. Returns whether this call
    made it all set (False if it already was, is no longer waiting, or the
    books could not be set up, when it stays waiting).

    Safe a second time (step 5b): a request filled again after someone going
    backed out is "all set again" - a book only for a going app mobed without
    one yet, the in-app notices with the new names, template 6 only to those
    going whose details have not gone, template 5 to the family again (with
    their agreement), and templates 7 and 8 not again."""
    now = now or _now()
    # Filled again after someone going backed out (step 5b): it was all set before.
    request_id = request.id
    again = (await db.execute(select(FuneralRequest.all_set_at).where(FuneralRequest.id == request_id))
             ).scalar_one_or_none() is not None
    values = {"status": REQUEST_ALL_SET, "all_set_at": now, "decided_at": now, "confirmed_short": short}
    done = (await db.execute(
        update(FuneralRequest)
        .where(FuneralRequest.id == request_id, FuneralRequest.status == REQUEST_WAITING)
        .values(**values)
        .returning(FuneralRequest.id)
    )).scalar_one_or_none()
    if done is None:
        await db.commit()
        await db.refresh(request)
        return False
    try:
        books = await _set_up_books(db, settings, request_id, now)
    except Exception:   # noqa: BLE001 - nothing is marked: the next yes, or tap, makes it all set
        logger.exception("Setting up the books of request %s failed, so it stays waiting", request_id)
        await db.rollback()
        await db.refresh(request)
        return False
    await db.commit()
    await db.refresh(request)
    logger.warning("Funeral request %s is all set%s at fire temple %s%s: %d book(s)", request_id,
                   " again" if again else "", request.agyary_id, " (confirmed short)" if short else "", len(books))
    try:
        await _tell(db, settings, request_id, now, by_user_id=by_user_id, again=again)
    except Exception:   # noqa: BLE001 - it is all set and the books are made; this must not undo it
        logger.exception("Telling everyone that request %s is all set failed", request_id)
        await db.rollback()
    try:
        await _whatsapp(db, settings, request_id, now, client, again=again)
    except Exception:   # noqa: BLE001 - as above; each message that went is written down (deliver)
        logger.exception("The WhatsApp messages for request %s being all set failed", request_id)
        await db.rollback()
    await db.refresh(request)
    return True


# --- Whose book --------------------------------------------------------------------

async def _going_rows(db: AsyncSession, request_id: int) -> list[PrayerCalloutAnswer]:
    """The places on the board, in the order they filled: never someone who
    said they can't go any more (step 5b)."""
    return list((await db.execute(
        select(PrayerCalloutAnswer).join(PrayerCallout, PrayerCallout.id == PrayerCalloutAnswer.callout_id)
        .where(PrayerCallout.funeral_request_id == request_id, *prayer_callout.HOLDS_PLACE)
        .order_by(PrayerCalloutAnswer.picked_at, PrayerCalloutAnswer.id)
        .execution_options(populate_existing=True)
    )).scalars().all())


async def book_people(
    db: AsyncSession, settings: Settings, request: FuneralRequest,
) -> tuple[list[User], list[User]]:
    """(the request's panthakys, the app mobeds going who are not one of them)
    whose own book the family goes into: see the module's docstring."""
    confirmed = await panthaky.panthakys_of(db, settings, request.agyary_id)
    taker = next((p for p in confirmed if p.id == request.taken_by_user_id), None)
    if taker is not None:
        panthakys = [taker]
    else:
        reached = {u.id for u in await funeral_requests.asked(db, request)}
        panthakys = [p for p in confirmed if p.id in reached]
    seen = {p.id for p in panthakys}
    going = []
    for row in await _going_rows(db, request.id):
        if not row.user_id or row.user_id in seen:
            continue
        seen.add(row.user_id)
        user = await db.get(User, row.user_id)
        if user is None or not user.is_active or not mobed_access.has_access(settings, user):
            logger.info("Request %s: no book for user %s, whose access is not on", request.id, row.user_id)
            continue
        if not await mobed_dashboard.is_active_member(db, request.agyary_id, user.id):
            logger.info("Request %s: no book for user %s, no longer at the fire temple", request.id, user.id)
            continue
        going.append(user)
    return panthakys, going


async def _set_up_books(db: AsyncSession, settings: Settings, request_id: int, now: datetime
                        ) -> list[FuneralRequestBook]:
    request = await db.get(FuneralRequest, request_id)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    panthakys, going = await book_people(db, settings, request)
    today = now.astimezone(IST).date()
    made = []
    for user, as_panthaky in [(p, True) for p in panthakys] + [(u, False) for u in going]:
        book = await set_up_book(db, request_id, user, agyary, record, place, is_panthaky=as_panthaky, today=today)
        if book is not None:
            made.append(book)
    return made


async def book_of(db: AsyncSession, request_id: int, user_id: int) -> FuneralRequestBook | None:
    return (await db.execute(select(FuneralRequestBook).where(
        FuneralRequestBook.funeral_request_id == request_id, FuneralRequestBook.user_id == user_id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()


async def set_up_book(
    db: AsyncSession, request_id: int, user: User, agyary: Agyary, record: FuneralRecord, place: FuneralPlace, *,
    is_panthaky: bool, today,
) -> FuneralRequestBook | None:
    """The family in this one person's own book for this request, once (their
    row in funeral_request_books says so). In a savepoint: if it fails, it is
    logged and nothing of it is kept, and the others' books still go. Not
    committed here. Returns their row, or None if it failed."""
    existing = await book_of(db, request_id, user.id)
    if existing is not None:
        return existing
    user_id = user.id
    try:
        async with db.begin_nested():
            done = await funeral_answers.put_in_book(db, user, agyary, record, place, today=today)
            book = FuneralRequestBook(funeral_request_id=request_id, user_id=user_id, customer_id=done.customer.id,
                                      is_panthaky=is_panthaky)
            db.add(book)
            await db.flush()
    except Exception:   # noqa: BLE001 - one person's book; the others' still go
        logger.exception("Request %s: the book of user %s could not be set up", request_id, user_id)
        return None
    logger.info("Request %s: the family is in the book of user %s (%s, new behdin: %s, %d event(s))", request_id,
                user_id, "panthaky" if is_panthaky else "going", done.created, len(done.events))
    return book


# --- What those people are given ---------------------------------------------------

async def going_people(db: AsyncSession, request_id: int, settings: Settings | None = None) -> list[dict]:
    """Those going, in the order the places filled: the row, their name, and
    their number where known - an account's sign-in number, or the number a
    panthaky entered for a mobed added by hand (cleaned by services/phone.py),
    never free text. Never someone who can no longer take part
    (prayer_callout.left_out: a mobed taken off the list since, say): they are
    not named to anyone, their number goes nowhere, and they are not sent the
    details."""
    settings = settings or get_settings()
    request = await db.get(FuneralRequest, request_id)
    rows = await _going_rows(db, request_id)
    out_of_it = await prayer_callout.left_out(db, settings, request.agyary_id, rows)
    for row_id, why in out_of_it.items():
        logger.info("Request %s: answer %s holds a place but is left out at All set (%s)", request_id, row_id, why)
    out = []
    for row in rows:
        if row.id in out_of_it:
            continue
        phone = row.phone
        if row.user_id:
            user = await db.get(User, row.user_id)
            phone = user.phone if user is not None else None
        elif row.contact_id:
            contact = await db.get(AgyaryMobedContact, row.contact_id)
            phone = contact.phone if contact is not None else row.phone
        out.append({"row": row, "name": row.name, "phone": phone or None})
    return out


async def _backed_out(db: AsyncSession, request_id: int, user_id: int) -> bool:
    """Whether this account was going for the request and said they can't go
    any more, and is not going again since."""
    rows = (await db.execute(
        select(PrayerCalloutAnswer).join(PrayerCallout, PrayerCallout.id == PrayerCalloutAnswer.callout_id)
        .where(PrayerCallout.funeral_request_id == request_id, PrayerCalloutAnswer.user_id == user_id)
    )).scalars().all()
    return any(prayer_callout.backed_out(r) for r in rows) and not any(prayer_callout.holds_place(r) for r in rows)


async def request_panthakys(db: AsyncSession, request_id: int) -> list[User]:
    """Those whose book was set up as the request's panthaky."""
    return list((await db.execute(
        select(User).join(FuneralRequestBook, FuneralRequestBook.user_id == User.id)
        .where(FuneralRequestBook.funeral_request_id == request_id, FuneralRequestBook.is_panthaky.is_(True))
        .order_by(FuneralRequestBook.id)
    )).scalars().all())


async def contacts_for(db: AsyncSession, request: FuneralRequest, user: User) -> dict | None:
    """What this person is given once the request is all set, if the family is
    in their book for it: the family's contact with the short message to them
    that their own WhatsApp opens with (the same words as for a request
    accepted the old way; for a panthaky not praying themselves, that the
    agyari was asked and who will pray), the panthaky, everyone going (with numbers where
    known), their own record of the family and the memorial they made from
    it, and the memorial form's fields. None for anyone else, and for everyone
    before All set. Nor for a mobed who said they can't go any more (step 5b):
    the family stays in their book (D8), and nothing more is given them."""
    if request.all_set_at is None:
        return None
    mine = await book_of(db, request.id, user.id)
    if mine is None:
        return None
    if not mine.is_panthaky and await _backed_out(db, request.id, user.id):
        return None
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    own = await db.get(Customer, mine.customer_id) if mine.customer_id else None
    going = await going_people(db, request.id)
    # A panthaky not praying themselves words it as the agyari asked, with who will pray
    # (R3.1 step 7); a mobed going, or a panthaky who prays, as "asked me".
    praying = any(g["row"].user_id == user.id for g in going)
    names = [g["name"] for g in going] if mine.is_panthaky and not praying else None
    return {
        "family_contact": {"name": record.family_contact_name, "phone": record.family_contact_phone},
        "family_message": funeral_answers.family_message(record, place, agyary, user, going=names),
        "panthakys": [{"name": p.name, "phone": p.phone, "is_me": p.id == user.id}
                      for p in await request_panthakys(db, request.id)],
        "going": [{"name": g["name"], "phone": g["phone"], "how": g["row"].how, "is_me": g["row"].user_id == user.id}
                  for g in going],
        "confirmed_short": bool(request.confirmed_short),
        "is_panthaky": mine.is_panthaky,
        # Their own record of the family, if it is still in their book.
        "customer_id": own.id if own is not None and own.is_active else None,
        "memorial_id": mine.memorial_id,
        "memorial_prefill": funeral_answers.memorial_prefill(record),
    }


# --- Everyone is told ----------------------------------------------------------------

KIND_ALL_SET = "funeral_request_all_set"
NOTICE_TTL = funeral_requests.NOTICE_TTL
NOTHING_MORE = "Nothing more is needed from you."


def join_names(names: list[str]) -> str:
    """Names as words: Er. A; Er. A and Er. B; Er. A, Er. B and Er. C."""
    if not names:
        return "The mobeds"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def going_words(names: list[str]) -> str:
    """Er. A is going; Er. A and Er. B are going."""
    return f"{join_names(names)} {'is' if len(names) == 1 else 'are'} going"


def mobeds(n: int) -> str:
    return f"{n} mobed{'' if n == 1 else 's'}"


# An in-app notice's title holds this many characters (app_notifications.title).
TITLE_MAX = 120


def fit_title(*choices: str) -> str:
    """The first of ``choices`` that fits a notice's title (names and the
    departed's name can be long; the body always has them in full)."""
    return next((c for c in choices if len(c) <= TITLE_MAX), choices[-1][:TITLE_MAX])


async def _tell(db: AsyncSession, settings: Settings, request_id: int, now: datetime, *,
                by_user_id: int | None, again: bool = False) -> None:
    """In the app and on their phones: the fire temple's confirmed panthakys
    the request reached, each app mobed going whose book it is, and the
    funeral place's managers (and the admin who sent it acting for the place,
    as for any answer). "All set: Er. A and Er. B are going for <prayed
    name>" - "All set again: ..." when it is filled again after someone going
    backed out (step 5b), who is not told; the lock screen says who and the
    place, and nothing about the departed or the family. D9: only accounts
    that are on."""
    request = await db.get(FuneralRequest, request_id)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    going = [g["name"] for g in await going_people(db, request_id, settings)]
    prayed = fw.departed(record)
    head = "All set again" if again else "All set"
    title = fit_title(f"{head}: {going_words(going)} for {prayed}",
                      f"{head}: {mobeds(len(going))} {'is' if len(going) == 1 else 'are'} going for {prayed}",
                      f"{head}: enough mobeds are going")
    said = f"{going_words(going)} for {prayed}" + (
        f", {len(going)} of {prayer_callout.wanted(record)} wanted: the panthaky confirmed with who is going."
        if request.confirmed_short else ".")
    books = {b.user_id: b for b in (await db.execute(select(FuneralRequestBook).where(
        FuneralRequestBook.funeral_request_id == request_id))).scalars()}
    confirmed = {p.id for p in await panthaky.panthakys_of(db, settings, agyary.id)}
    told: dict[int, str] = {}
    for u in await funeral_requests.asked(db, request):
        if u.id in confirmed:
            told[u.id] = (f"{said} The family's contact and everyone going are on the request from {place.name}."
                          if u.id in books else f"{said} The request from {place.name} is all set. {NOTHING_MORE}")
    going_ids = {g["row"].user_id for g in await going_people(db, request_id, settings) if g["row"].user_id}
    for uid in books:
        # The app mobeds going; never someone who said they can't go any more (step 5b).
        if uid not in told and uid in going_ids:
            user = await db.get(User, uid)
            if user is not None and user.is_active and mobed_access.has_access(settings, user):
                told[uid] = (f"{said} You are going. The family's contact, the panthaky and everyone going "
                             "are on your request card.")
    link = f"#/requests/{request_id}"
    for uid, body in told.items():
        await reminders.notify(db, uid, KIND_ALL_SET, title, body, link=link, agyary_id=agyary.id, now=now,
                               ttl=NOTICE_TTL)
    await db.commit()
    woken = [uid for uid in told if uid != by_user_id]
    if woken:
        await web_push.send_to_users(db, settings, woken, title=head,
                                     body=f"{going_words(going)} for the request from {place.name}.",
                                     url="/mobed" + link, tag=f"funeral-all-set-{request_id}")
    panthakys = await request_panthakys(db, request_id)
    who = (f" The panthaky is {join_names([p.name for p in panthakys])}." if len(panthakys) == 1 else
           f" The panthakys are {join_names([p.name for p in panthakys])}." if panthakys else "")
    await funeral_answers._tell_managers(
        db, settings, record, request, kind=KIND_ALL_SET, title=title,
        body=f"{agyary.name}: {said}{who}",
        push=(head, f"{going_words(going)} from {agyary.name}."), now=now,
    )
    await db.commit()


# --- On WhatsApp ---------------------------------------------------------------------

def _why_off(user: User | None, settings: Settings) -> str | None:
    """Why an account may not be messaged (D9), or None."""
    if user is None or not user.is_active:
        return "their Mobed Diary account is gone"
    if not mobed_access.has_access(settings, user):
        return "their Mobed Diary access is not on"
    return None


async def _whatsapp(db: AsyncSession, settings: Settings, request_id: int, now: datetime,
                    client: httpx.AsyncClient | None, *, again: bool = False) -> int:
    """The all-set messages from Mobed Diary's number, only while
    FUNERAL_WHATSAPP_MODE is live (approved templates only; each still passes
    STOP, the pause switch, the allowlist, the day's limits and the name
    checks in funeral_whatsapp.deliver, and nothing goes to an account that is
    not on, D9). Each is a row written before it is sent, at most once (this
    runs once, for the call that made it all set):

    5  to the family, only if the manager's tick recorded their agreement to
       hear from Mobed Diary (as template 3 before) - again, with the new
       names, when it is all set again (step 5b);
    6  to each mobed going with a number - app or added by hand, the panthaky
       too if they pray - with "I can't go any more" on it, once each: only
       to those whose details have not gone (``details_sent_at``, set when it
       goes), so all set again reaches only the one new to it;
    7  to the request's panthakys who are not going (they have 6);
    8  to the funeral place's managers;
    7 and 8 are not sent again (step 5b): the panthaky and the place see the
    new names in the app.

    Templates 1-3 are never sent for a request made all set. Returns how many
    went."""
    if not fw.mode_on(settings):
        logger.info("Doongerwadi WhatsApp is off: nothing sent for request %s being all set", request_id)
        return 0
    request = await db.get(FuneralRequest, request_id)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    going = await going_people(db, request_id, settings)
    people = [fw.Person(g["name"], g["phone"]) for g in going]
    panthakys = await request_panthakys(db, request_id)
    heads = [fw.Person(p.name, p.phone) for p in panthakys]

    sends = []
    if request.family_whatsapp_agreed:
        refs = {"request": request_id, "to": "family"}
        if again:
            refs["again"] = "1"
        sends.append(fw.all_set_family_send(record, agyary, going=people, panthakys=heads, refs=refs))
    for g in going:
        row = g["row"]
        if not g["phone"] or row.details_sent_at is not None:
            continue        # no number, or their details went at an earlier All set
        why = None
        if row.user_id:
            why, to = _why_off(await db.get(User, row.user_id), settings), ("user", row.user_id)
        else:
            # Matched to an account by the number it goes to, now (prayer_callout.accounts_by_phone).
            account = (await prayer_callout.accounts_by_phone(db, [g["phone"]])).get(g["phone"])
            if account is not None and not prayer_callout.account_on(settings, account):
                why = "their Mobed Diary access is not on"
            to = ("contact", row.contact_id or 0)
        sends.append(fw.all_set_details_send(
            record, place, going=people, panthakys=heads, phone=g["phone"], recipient_type=to[0],
            recipient_id=to[1], agyary_id=agyary.id, back_out=prayer_callout.back_out_payload(row),
            refs={"request": request_id, "to": "going", "answer": row.id}, why_not=why))
    going_ids = {g["row"].user_id for g in going if g["row"].user_id}
    if not again:
        for p in panthakys:
            if p.id not in going_ids:
                sends.append(fw.all_set_panthaky_send(record, place, going=people, phone=p.phone, recipient_id=p.id,
                                                      agyary_id=agyary.id,
                                                      refs={"request": request_id, "to": "panthaky"}))
        for m in await funeral_answers._managers(db, settings, record.funeral_place_id):
            sends.append(fw.all_set_manager_send(record, agyary, going=people, panthakys=heads, phone=m.phone,
                                                 recipient_id=m.id, refs={"request": request_id, "to": "manager"}))
    rows = await fw.deliver(db, settings, sends, now=now, client=client)
    # Whose details have gone, so they are never sent them twice (step 5b: all set again).
    by_id = {g["row"].id: g["row"] for g in going}
    for n in rows:
        row = by_id.get(int(n.template_params.get("answer", 0) or 0)) \
            if n.notification_type == fw.TYPE_ALL_SET_DETAILS else None
        if row is not None and fw.went(n):
            row.details_sent_at = now
    await db.commit()
    went = sum(1 for n in rows if fw.went(n))
    logger.warning("Request %s all set%s: %d of %d WhatsApp messages went", request_id, " again" if again else "",
                   went, len(rows))
    return went
