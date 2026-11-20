"""The prayer requests' timers (R3.1), run by the one-minute loop on every
tick, whatever the hour (reminder_worker.tick). Each looks only at what is due
now, keeps what it did in the database, and does it once, so a restart or two
loops at the same time change nothing.

The safety net (step 2; DECISIONS D10, changed 21 Nov 2026): in Come to me
first, a panthaky may choose "if I haven't acted in 15 min / 30 min / 1 hour,
ask all our mobeds on WhatsApp" (Never is the default). Once that long has
passed since a request was sent, if it is still waiting and the panthaky has
not acted (prayer_callout.panthaky_acted), all the fire temple's mobeds are
asked, as Everyone at once asks them at Send (prayer_callout.at_send), and the
panthaky is told in the app and on their phone, with nothing about the family.

- The setting is read as it is when the timer looks: a panthaky who switched
  to Everyone at once, or to Never, in the meantime is left to it.
- Once: the request is claimed by a conditional update of escalated_at,
  committed before anything is sent (at most once, like the rest of the app's
  sending). When nobody can be asked (WhatsApp off, nobody on the list) it is
  still done, and the panthaky is told what happened.
- D9: nothing is sent to or under an account that is not on (at_send's rule),
  and only panthakys whose access is on are told. A panthaky switched off
  meanwhile does not hold the request back: nobody else could act on it.

Later timers belong here too: "still short" 4 hours before the Geh-saarnu
(step 5), and asking the next standby after 30 minutes (step 5b).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import Agyary, FuneralPlace, FuneralRecord, FuneralRequest
from agyary.models.enums import REQUEST_MODE_PANTHAKY_FIRST, REQUEST_WAITING
from agyary.services import funeral_requests, panthaky, prayer_callout, reminders, web_push
from agyary.services import funeral_whatsapp as fw

logger = logging.getLogger(__name__)

# To the panthaky: the safety net asked everyone, or could not.
KIND_ESCALATED = "prayer_request_escalated"
ASKED_TITLE = "All your mobeds were asked"
NOT_ASKED_TITLE = "Your mobeds could not be asked"


async def run(db: AsyncSession, now: datetime, settings: Settings, client: httpx.AsyncClient | None) -> int:
    """Every timer that is due now. Returns how many requests it acted on.
    Commits as it goes; the loop calls it in its own step."""
    return await safety_net(db, now, settings, client)


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
               Agyary.request_mode == REQUEST_MODE_PANTHAKY_FIRST, Agyary.request_escalate_minutes.is_not(None))
        .order_by(FuneralRequest.sent_at, FuneralRequest.id)
    )).all()
    return [(rid, minutes) for rid, sent_at, minutes in rows if sent_at + timedelta(minutes=minutes) <= now]


async def _claim(db: AsyncSession, request_id: int, now: datetime) -> bool:
    """Take this request for the safety net, once: only while it is waiting
    and nobody has taken it yet. Committed before anything is sent, so a
    second loop (or this one after a restart) finds it taken and does nothing."""
    claimed = (await db.execute(
        update(FuneralRequest)
        .where(FuneralRequest.id == request_id, FuneralRequest.escalated_at.is_(None),
               FuneralRequest.status == REQUEST_WAITING)
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

    outcome = await prayer_callout.at_send(db, settings, request_id, now=now, client=client)
    logger.warning("Safety net: request %s at fire temple %s, %d minutes without the panthaky acting: %s (%d asked)",
                   request_id, agyary_id, minutes, outcome["state"], outcome["asked"])

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
        title, link = ASKED_TITLE, f"#/requests/{request_id}/callout"
        body = (f"{late} for {departed} in {waited}, so Mobed Diary asked all your mobeds on WhatsApp. "
                f"{outcome['message']}")
        push = f"{late} in {waited}, so Mobed Diary asked all your mobeds on WhatsApp."
    else:
        title, link = NOT_ASKED_TITLE, f"#/requests/{request_id}"
        body = (f"{late} for {departed} in {waited}, so Mobed Diary tried to ask all your mobeds on WhatsApp. "
                f"{outcome['message']} Please open the request to find mobeds.")
        push = f"{late} in {waited}, and Mobed Diary could not ask your mobeds on WhatsApp."
    for u in people:
        await reminders.notify(db, u.id, KIND_ESCALATED, title, body, link=link, agyary_id=agyary_id, now=now,
                               ttl=prayer_callout.NOTICE_TTL)
    await db.commit()
    await web_push.send_to_users(db, settings, [u.id for u in people], title=title, body=push,
                                 url="/mobed" + link, tag=f"prayer-escalated-{request_id}")
