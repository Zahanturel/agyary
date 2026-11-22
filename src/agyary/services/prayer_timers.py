"""The prayer requests' timers (R3.1), run by the one-minute loop on every
tick, whatever the hour (reminder_worker.tick). Each looks only at what is due
now, keeps what it did in the database, and does it once, so a restart or two
loops at the same time change nothing.

The safety net (step 2; DECISIONS D10, changed 21 Nov 2026): in Come to me
first, a panthaky may choose "if I haven't acted in 15 min / 30 min / 1 hour,
ask all our mobeds on WhatsApp" (Never is the default). Once that long has
passed since a request was sent, if it is still waiting and the panthaky has
not acted (prayer_callout.panthaky_acted: since R3.1 step 4 that includes
taking it on the board), all the fire temple's mobeds are asked - in the app
and on WhatsApp, as Everyone at once asks them at Send
(prayer_callout.ask_everyone) - and the panthaky is told in the app and on
their phone, with nothing about the family.

- The setting is read as it is when the timer looks: a panthaky who switched
  to Everyone at once, or to Never, in the meantime is left to it.
- Once: the request is claimed by a conditional update of escalated_at,
  committed before anything is sent (at most once, like the rest of the app's
  sending), and only while nobody has taken it on the board. When nobody can
  be asked (nobody on the list who is not asked already, WhatsApp off and no
  app mobed) it is still done, and the panthaky is told what happened.
- D9: nothing is sent to or under an account that is not on (ask_everyone's rule),
  and only panthakys whose access is on are told. A panthaky switched off
  meanwhile does not hold the request back: nobody else could act on it.

"Still short" (step 5; owner, 21 Nov 2026): a request still waiting with
places empty 4 hours before its Geh-saarnu - or at once, if it came later than
that - is told once to the fire temple's confirmed panthakys it reached whose
access is on, in the app and on their phones ("Still 1 mobed short for <prayed
name>"; the lock screen without the departed or the family), or, with none,
to the funeral place's managers (and the admin who sent it acting for the
place). The 4 hours count from the start of the Geh-saarnu's geh in IST (the
lead's choice): Havan 6:30 am, Rapithwin 12:30 pm, Uziran 3:30 pm, or 6:30 am
with no geh; with no Geh-saarnu day, from the Uthamna's day and time (6:30 am
with no time); with neither, never. Claimed by a conditional update of
short_alert_at before anyone is told, so it is told once, two loops included.

A standby's 30 minutes (step 5b; services/standbys.py, timed_out): a standby
asked again when a place opened who has not answered in 30 minutes is passed
over once (a conditional update of reask_passed_at), and the next standby is
asked, while the request waits with a place open. The prayers begin
(prayers_begin) also bounds backing out.

No answer for an hour (step 6; owner, 21 Nov 2026, third round): a request
still waiting an hour after it was sent, never taken on the board and with no
answer from anyone at the fire temple (no yes, no no - in the app, on WhatsApp
or by phone - and no call's result, which takes it), is told once to the
funeral place's managers, and the admin who sent it acting for the place, in
the app and on their phones: "No answer yet from <agyari>", with the record's
link, so they can send it to another fire temple. The request stays open
there until they withdraw it. Never for a request whose prayers have begun,
nor for one sent more than 24 hours ago (R3.1 step 7: no burst of alerts on old
records when it goes live).
Claimed by a conditional update of no_answer_alert_at (only while still
unanswered and untaken) before anyone is told, so it is told once, two loops
included.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.messaging.geh_times import IST
from agyary.models import Agyary, FuneralPlace, FuneralRecord, FuneralRequest, PrayerCallout, PrayerCalloutAnswer
from agyary.models.enums import REQUEST_MODE_PANTHAKY_FIRST, REQUEST_WAITING
from agyary.services import (
    all_set,
    funeral_answers,
    funeral_requests,
    panthaky,
    prayer_callout,
    reminders,
    standbys,
    web_push,
)
from agyary.services import funeral_whatsapp as fw

logger = logging.getLogger(__name__)

# To the panthaky: the safety net asked everyone, or could not.
KIND_ESCALATED = "prayer_request_escalated"
ASKED_TITLE = "All your mobeds were asked"
NOT_ASKED_TITLE = "Your mobeds could not be asked"


async def run(db: AsyncSession, now: datetime, settings: Settings, client: httpx.AsyncClient | None) -> int:
    """Every timer that is due now. Returns how many requests it acted on.
    Commits as it goes; the loop calls it in its own step."""
    done = await safety_net(db, now, settings, client)
    done += await still_short(db, now, settings)
    done += await no_answer(db, now, settings)
    return done + await standbys.timed_out(db, now, settings, client)


def minutes_words(minutes: int) -> str:
    return "1 hour" if minutes == 60 else f"{minutes} minutes"


async def _due(db: AsyncSession, now: datetime) -> list[tuple[int, int]]:
    """(request id, minutes) of each request waiting in Come to me first with a
    safety net, not asked by it yet, whose minutes have passed since it was
    sent. Only waiting requests at such fire temples are read: a handful."""
    rows = (await db.execute(
        select(FuneralRequest.id, FuneralRequest.sent_at, Agyary.request_escalate_minutes)
        .join(Agyary, Agyary.id == FuneralRequest.agyary_id)
        .where(FuneralRequest.status == REQUEST_WAITING, FuneralRequest.escalated_at.is_(None),
               FuneralRequest.taken_at.is_(None),
               Agyary.request_mode == REQUEST_MODE_PANTHAKY_FIRST, Agyary.request_escalate_minutes.is_not(None))
        .order_by(FuneralRequest.sent_at, FuneralRequest.id)
    )).all()
    return [(rid, minutes) for rid, sent_at, minutes in rows if sent_at + timedelta(minutes=minutes) <= now]


async def _claim(db: AsyncSession, request_id: int, now: datetime) -> bool:
    """Take this request for the safety net, once: only while it is waiting,
    the safety net has not run for it, and the panthaky has not taken it on
    the board (a board action holding the request waits here, then wins).
    Committed before anything is sent, so a second loop (or this one after a
    restart) finds it taken and does nothing."""
    claimed = (await db.execute(
        update(FuneralRequest)
        .where(FuneralRequest.id == request_id, FuneralRequest.escalated_at.is_(None),
               FuneralRequest.status == REQUEST_WAITING, FuneralRequest.taken_at.is_(None))
        .values(escalated_at=now)
        .returning(FuneralRequest.id)
    )).scalar_one_or_none()
    await db.commit()
    return claimed is not None


async def safety_net(db: AsyncSession, now: datetime, settings: Settings, client: httpx.AsyncClient | None) -> int:
    """Ask everyone for each request whose safety net is due. Returns how
    many it asked for (or tried to: see the module's docstring)."""
    done = 0
    for request_id, minutes in await _due(db, now):
        request = await db.get(FuneralRequest, request_id, populate_existing=True)
        if request is None or await prayer_callout.panthaky_acted(db, request):
            continue
        agyary_id, record_id = request.agyary_id, request.funeral_record_id
        if not await _claim(db, request_id, now):
            continue            # another loop has it, or it stopped waiting just now
        done += 1
        try:
            await _ask_and_tell(db, settings, request_id, agyary_id, record_id, minutes, now, client)
        except Exception:   # noqa: BLE001 - it is claimed (at most once); the next request still goes
            logger.exception("The safety net for request %s failed after it was claimed", request_id)
            await db.rollback()
    await db.commit()
    return done


async def _ask_and_tell(db: AsyncSession, settings: Settings, request_id: int, agyary_id: int, record_id: int,
                        minutes: int, now: datetime, client: httpx.AsyncClient | None) -> None:
    record = await db.get(FuneralRecord, record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    place_name, departed, waited = place.name, fw.departed(record), minutes_words(minutes)

    outcome = await prayer_callout.ask_everyone(db, settings, request_id, now=now, client=client)
    logger.warning("Safety net: request %s at fire temple %s, %d minutes without the panthaky acting: %s "
                   "(%d in the app, %d on WhatsApp)", request_id, agyary_id, minutes, outcome["state"],
                   outcome["asked_in_app"], outcome["asked"])

    # Read again: a call-out that broke rolls the session back.
    request = await db.get(FuneralRequest, request_id)
    confirmed = {p.id for p in await panthaky.panthakys_of(db, settings, agyary_id)}
    people = [u for u in await funeral_requests.asked(db, request) if u.id in confirmed]
    if not people:
        logger.info("Safety net: request %s has no panthaky whose access is on to tell", request_id)
        await db.commit()
        return
    late = f"Nobody had answered the request from {place_name}"
    if outcome["state"] == "sent":
        title, link = ASKED_TITLE, f"#/requests/{request_id}"
        body = f"{late} for {departed} in {waited}, so Mobed Diary asked all your mobeds. {outcome['message']}"
        push = f"{late} in {waited}, so Mobed Diary asked all your mobeds."
    else:
        title, link = NOT_ASKED_TITLE, f"#/requests/{request_id}"
        body = (f"{late} for {departed} in {waited}, so Mobed Diary tried to ask all your mobeds. "
                f"{outcome['message']} Please open the request to find mobeds.")
        push = f"{late} in {waited}, and Mobed Diary could not ask your mobeds."
    for u in people:
        await reminders.notify(db, u.id, KIND_ESCALATED, title, body, link=link, agyary_id=agyary_id, now=now,
                               ttl=prayer_callout.NOTICE_TTL)
    await db.commit()
    await web_push.send_to_users(db, settings, [u.id for u in people], title=title, body=push,
                                 url="/mobed" + link, tag=f"prayer-escalated-{request_id}")


# --- Still short (step 5) -------------------------------------------------------------

KIND_STILL_SHORT = "prayer_request_still_short"
SHORT_BEFORE = timedelta(hours=4)
# When each day geh starts, for "4 hours before the Geh-saarnu" (the lead's
# choice; the Geh-saarnu is prayed only in these gehs).
GEH_SAARNU_STARTS = {1: time(6, 30), 2: time(12, 30), 3: time(15, 30)}
DAY_START = time(6, 30)


def prayers_begin(geh_saarnu_date: date | None, geh: int | None, uthamna_date: date | None,
                  uthamna_time: time | None) -> datetime | None:
    """When the prayers begin, for a record's days: the start of the
    Geh-saarnu's geh in IST (6:30 am with no geh), else the Uthamna's day and
    time (6:30 am with no time), else None. "Still short" is due 4 hours
    before; backing out is refused from then on (step 5b)."""
    if geh_saarnu_date is not None:
        return datetime.combine(geh_saarnu_date, GEH_SAARNU_STARTS.get(geh, DAY_START), tzinfo=IST)
    if uthamna_date is not None:
        return datetime.combine(uthamna_date, uthamna_time or DAY_START, tzinfo=IST)
    return None


def record_begins(record: FuneralRecord) -> datetime | None:
    """prayers_begin for a funeral record."""
    return prayers_begin(record.geh_saarnu_date, record.geh_saarnu_geh, record.uthamna_date, record.uthamna_time)


def short_alert_at(geh_saarnu_date: date | None, geh: int | None, uthamna_date: date | None,
                   uthamna_time: time | None) -> datetime | None:
    """When "still short" is due for a record's days (see the module's
    docstring), or None when it has neither day."""
    start = prayers_begin(geh_saarnu_date, geh, uthamna_date, uthamna_time)
    return None if start is None else start - SHORT_BEFORE


async def _short_due(db: AsyncSession, now: datetime) -> list[int]:
    """The waiting requests not told yet whose time has come. Only those whose
    first day is no later than 4 hours from now are read: a handful. A request
    whose prayers have already begun (or passed, e.g. an old test record left
    waiting) is never told: "still short" helps only before the prayers."""
    today = now.astimezone(IST).date()
    latest = (now.astimezone(IST) + SHORT_BEFORE).date()
    first_day = func.coalesce(FuneralRecord.geh_saarnu_date, FuneralRecord.uthamna_date)
    rows = (await db.execute(
        select(FuneralRequest.id, FuneralRecord.geh_saarnu_date, FuneralRecord.geh_saarnu_geh,
               FuneralRecord.uthamna_date, FuneralRecord.uthamna_time)
        .join(FuneralRecord, FuneralRecord.id == FuneralRequest.funeral_record_id)
        .where(FuneralRequest.status == REQUEST_WAITING, FuneralRequest.short_alert_at.is_(None),
               first_day <= latest, first_day >= today)
        .order_by(FuneralRequest.sent_at, FuneralRequest.id)
    )).all()
    out = []
    for rid, gs_date, geh, ut_date, ut_time in rows:
        at = short_alert_at(gs_date, geh, ut_date, ut_time)
        if at is not None and at <= now < at + SHORT_BEFORE:
            out.append(rid)
    return out


async def _claim_short(db: AsyncSession, request_id: int, now: datetime) -> bool:
    """Take this request for "still short", once, while it is waiting:
    committed before anyone is told."""
    claimed = (await db.execute(
        update(FuneralRequest)
        .where(FuneralRequest.id == request_id, FuneralRequest.short_alert_at.is_(None),
               FuneralRequest.status == REQUEST_WAITING)
        .values(short_alert_at=now)
        .returning(FuneralRequest.id)
    )).scalar_one_or_none()
    await db.commit()
    return claimed is not None


async def still_short(db: AsyncSession, now: datetime, settings: Settings) -> int:
    """Tell, once, each waiting request with places empty whose time has come.
    Returns how many it told (or claimed: see _tell_short)."""
    done = 0
    for request_id in await _short_due(db, now):
        request = await db.get(FuneralRequest, request_id, populate_existing=True)
        record = await db.get(FuneralRecord, request.funeral_record_id)
        if await prayer_callout._going(db, request_id) >= prayer_callout.wanted(record):
            continue            # full: it is made all set by the next yes or tap, not told it is short
        if not await _claim_short(db, request_id, now):
            continue            # another loop has it, or it stopped waiting just now
        done += 1
        try:
            await _tell_short(db, settings, request_id, now)
        except Exception:   # noqa: BLE001 - it is claimed (at most once); the next request still goes
            logger.exception("Telling that request %s is still short failed after it was claimed", request_id)
            await db.rollback()
    await db.commit()
    return done


async def _tell_short(db: AsyncSession, settings: Settings, request_id: int, now: datetime) -> None:
    request = await db.get(FuneralRequest, request_id)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    want, going = prayer_callout.wanted(record), await prayer_callout._going(db, request_id)
    missing = all_set.mobeds(want - going)
    prayed = fw.departed(record)
    when = (f"the Geh-saarnu is {fw.geh_saarnu_text(record)}" if record.geh_saarnu_date
            else f"the Uthamna is {fw.uthamna_text(record)}")
    confirmed = {p.id for p in await panthaky.panthakys_of(db, settings, agyary.id)}
    people = [u for u in await funeral_requests.asked(db, request) if u.id in confirmed]
    logger.warning("Request %s at fire temple %s is still short (%d of %d going): telling %s", request_id,
                   agyary.id, going, want, f"{len(people)} panthaky(s)" if people else "the funeral place")
    if not people:
        await funeral_answers._tell_managers(
            db, settings, record, request, kind=KIND_STILL_SHORT,
            title=all_set.fit_title(f"Still {missing} short at {agyary.name} for {prayed}",
                                    f"Still {missing} short at {agyary.name}", f"Still {missing} short"),
            body=(f"{going} of {want} mobeds are going from {agyary.name} for {prayed}, and {when}. "
                  "You can withdraw the request and send it to another fire temple."),
            push=(f"Still {missing} short", f"The request to {agyary.name}: {going} of {want} going."), now=now,
        )
        await db.commit()
        return
    ways = "Ask everyone, call a mobed, or pray yourself" if going == 0 else \
        "Ask everyone, call a mobed, or Confirm with who's going"
    title = all_set.fit_title(f"Still {missing} short for {prayed}", f"Still {missing} short")
    body = f"{going} of {want} going for the request from {place.name}, and {when}. {ways}."
    link = f"#/requests/{request_id}"
    for u in people:
        await reminders.notify(db, u.id, KIND_STILL_SHORT, title, body, link=link, agyary_id=agyary.id, now=now,
                               ttl=prayer_callout.NOTICE_TTL)
    await db.commit()
    await web_push.send_to_users(db, settings, [u.id for u in people], title=f"Still {missing} short",
                                 body=f"The request from {place.name}: {going} of {want} going.",
                                 url="/mobed" + link, tag=f"prayer-short-{request_id}")


# --- No answer for an hour (step 6) ----------------------------------------------------

KIND_NO_ANSWER = "funeral_request_no_answer"
NO_ANSWER_AFTER = timedelta(hours=1)
# Only up to this long after it was sent (R3.1 step 7): an older request is never
# told, so records from before (old test ones left waiting) bring no burst of alerts.
NO_ANSWER_WITHIN = timedelta(hours=24)


def _unanswered():
    """SQL: nobody at the fire temple has answered the request (no yes or no
    on any of its rows, whichever way it came)."""
    return ~(
        select(PrayerCalloutAnswer.id)
        .join(PrayerCallout, PrayerCallout.id == PrayerCalloutAnswer.callout_id)
        .where(PrayerCallout.funeral_request_id == FuneralRequest.id, PrayerCalloutAnswer.answer.is_not(None))
        .correlate(FuneralRequest)
        .exists()
    )


# A request nobody at the fire temple has done anything with: still waiting,
# never all set (someone was going), never taken on the board, never answered.
_UNTOUCHED = (FuneralRequest.status == REQUEST_WAITING, FuneralRequest.all_set_at.is_(None),
              FuneralRequest.taken_at.is_(None))


async def _no_answer_due(db: AsyncSession, now: datetime) -> list[int]:
    """The requests sent between an hour and a day ago that nobody at the fire
    temple has touched, not told yet, whose prayers have not begun. Those whose
    first day is before today have begun: they are not even read."""
    today = now.astimezone(IST).date()
    first_day = func.coalesce(FuneralRecord.geh_saarnu_date, FuneralRecord.uthamna_date)
    rows = (await db.execute(
        select(FuneralRequest.id, FuneralRecord.geh_saarnu_date, FuneralRecord.geh_saarnu_geh,
               FuneralRecord.uthamna_date, FuneralRecord.uthamna_time)
        .join(FuneralRecord, FuneralRecord.id == FuneralRequest.funeral_record_id)
        .where(*_UNTOUCHED, FuneralRequest.no_answer_alert_at.is_(None),
               FuneralRequest.sent_at <= now - NO_ANSWER_AFTER, FuneralRequest.sent_at > now - NO_ANSWER_WITHIN,
               or_(first_day.is_(None), first_day >= today), _unanswered())
        .order_by(FuneralRequest.sent_at, FuneralRequest.id)
    )).all()
    out = []
    for rid, gs_date, geh, ut_date, ut_time in rows:
        begins = prayers_begin(gs_date, geh, ut_date, ut_time)
        if begins is None or now < begins:
            out.append(rid)
    return out


async def _claim_no_answer(db: AsyncSession, request_id: int, now: datetime) -> bool:
    """Take this request for "No answer yet", once, while nobody at the fire
    temple has touched it: committed before anyone is told."""
    claimed = (await db.execute(
        update(FuneralRequest)
        .where(FuneralRequest.id == request_id, FuneralRequest.no_answer_alert_at.is_(None), *_UNTOUCHED,
               _unanswered())
        .values(no_answer_alert_at=now)
        .returning(FuneralRequest.id)
    )).scalar_one_or_none()
    await db.commit()
    return claimed is not None


async def no_answer(db: AsyncSession, now: datetime, settings: Settings) -> int:
    """Tell, once, the funeral place of each request nobody at the fire temple
    has answered or taken in an hour. Returns how many it told (or claimed:
    see _tell_no_answer)."""
    done = 0
    for request_id in await _no_answer_due(db, now):
        if not await _claim_no_answer(db, request_id, now):
            continue            # another loop has it, or someone answered or took it just now
        done += 1
        try:
            await _tell_no_answer(db, settings, request_id, now)
        except Exception:   # noqa: BLE001 - it is claimed (at most once); the next request still goes
            logger.exception("Telling that nobody answered request %s failed after it was claimed", request_id)
            await db.rollback()
    await db.commit()
    return done


async def _tell_no_answer(db: AsyncSession, settings: Settings, request_id: int, now: datetime) -> None:
    request = await db.get(FuneralRequest, request_id, populate_existing=True)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    agyary = await db.get(Agyary, request.agyary_id)
    title = all_set.fit_title(f"No answer yet from {agyary.name}", "No answer yet")
    managers = await funeral_answers._tell_managers(
        db, settings, record, request, kind=KIND_NO_ANSWER, title=title,
        body=(f"Nobody at {agyary.name} has answered the request for {fw.departed(record)} in an hour. "
              "You can send it to another fire temple."),
        push=(title, f"Nobody at {agyary.name} has answered in an hour. You can send the request to another "
                     "fire temple."),
        now=now,
    )
    await db.commit()
    logger.warning("Request %s at fire temple %s: no answer in an hour, so the funeral place was told "
                   "(%d manager(s))", request_id, agyary.id, len(managers))
