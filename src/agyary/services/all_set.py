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
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
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
from agyary.services import funeral_answers, funeral_requests, mobed_access, mobed_dashboard, panthaky

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def on_full(
    db: AsyncSession, settings: Settings, request: FuneralRequest, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None, short: bool = False,
) -> bool:
    """The request's places are all filled (or, with ``short``, the panthaky
    confirmed it with those going): mark it all set and set up the books,
    once. Commits. Returns whether this call made it all set (False if it
    already was, is no longer waiting, or the books could not be set up, when
    it stays waiting)."""
    now = now or _now()
    values = {"status": REQUEST_ALL_SET, "all_set_at": now, "decided_at": now}
    if short:
        values["confirmed_short"] = True
    request_id = request.id
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
    logger.warning("Funeral request %s is all set at fire temple %s%s: %d book(s)", request_id, request.agyary_id,
                   " (confirmed short)" if short else "", len(books))
    return True


# --- Whose book --------------------------------------------------------------------

async def _going_rows(db: AsyncSession, request_id: int) -> list[PrayerCalloutAnswer]:
    """The places on the board, in the order they filled."""
    return list((await db.execute(
        select(PrayerCalloutAnswer).join(PrayerCallout, PrayerCallout.id == PrayerCalloutAnswer.callout_id)
        .where(PrayerCallout.funeral_request_id == request_id, PrayerCalloutAnswer.picked_at.is_not(None))
        .order_by(PrayerCalloutAnswer.picked_at, PrayerCalloutAnswer.id)
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

async def going_people(db: AsyncSession, request_id: int) -> list[dict]:
    """Those going, in the order the places filled: the row, their name, and
    their number where known - an account's sign-in number, or the number a
    panthaky entered for a mobed added by hand (cleaned by services/phone.py),
    never free text."""
    out = []
    for row in await _going_rows(db, request_id):
        phone = row.phone
        if row.user_id:
            user = await db.get(User, row.user_id)
            phone = user.phone if user is not None else None
        elif row.contact_id:
            contact = await db.get(AgyaryMobedContact, row.contact_id)
            phone = contact.phone if contact is not None else row.phone
        out.append({"row": row, "name": row.name, "phone": phone or None})
    return out


async def request_panthakys(db: AsyncSession, request_id: int) -> list[User]:
    """Those whose book was set up as the request's panthaky."""
    return list((await db.execute(
        select(User).join(FuneralRequestBook, FuneralRequestBook.user_id == User.id)
        .where(FuneralRequestBook.funeral_request_id == request_id, FuneralRequestBook.is_panthaky.is_(True))
        .order_by(FuneralRequestBook.id)
    )).scalars().all())


async def contacts_for(db: AsyncSession, request: FuneralRequest, user: User) -> dict | None:
    """What this person is given once the request is all set, if the family is
    in their book for it: the family's contact, the panthaky, everyone going
    (with numbers where known), their own record of the family and the
    memorial they made from it, and the memorial form's fields. None for
    anyone else, and for everyone before All set."""
    if request.all_set_at is None:
        return None
    mine = await book_of(db, request.id, user.id)
    if mine is None:
        return None
    record = await db.get(FuneralRecord, request.funeral_record_id)
    own = await db.get(Customer, mine.customer_id) if mine.customer_id else None
    return {
        "family_contact": {"name": record.family_contact_name, "phone": record.family_contact_phone},
        "panthakys": [{"name": p.name, "phone": p.phone, "is_me": p.id == user.id}
                      for p in await request_panthakys(db, request.id)],
        "going": [{"name": g["name"], "phone": g["phone"], "how": g["row"].how, "is_me": g["row"].user_id == user.id}
                  for g in await going_people(db, request.id)],
        "confirmed_short": bool(request.confirmed_short),
        "is_panthaky": mine.is_panthaky,
        # Their own record of the family, if it is still in their book.
        "customer_id": own.id if own is not None and own.is_active else None,
        "memorial_id": mine.memorial_id,
        "memorial_prefill": funeral_answers.memorial_prefill(record),
    }
