"""Standbys and backing out (DECISIONS D10, changed 21 Nov 2026, second round;
docs/phase2-requests-redesign.md, "Standbys and backing out"; R3.1 step 5b).

Backing out: someone going can say they can no longer go, three ways:

- an app mobed's "I can't go any more" on their own request card
  (back_out_in_app);
- a tap on "I can't go any more" on their WhatsApp details (template 6,
  payload "pca:<token>:x"; prayer_callout.record_answer, which keeps the check
  that it came from the number it was sent to): back_out_on_whatsapp, answered
  with a short plain text inside the 24 hours the tap opened;
- the panthaky (a confirmed panthaky the request reached, or the admin)
  marking a place "Can't go" on the board, for someone who phoned
  (mark_cant_go).

Their row gets ``backed_out_at`` (and who said so in the app) and no longer
holds a place (prayer_callout.holds_place: every count of those going reads
it). Their own book keeps the family (D8), and nothing more is sent to them.
The place reopens at once: an all-set request is waiting again (``all_set_at``
kept as history; ``taken_at`` stays, so the safety net never fires), and the
panthakys it reached are told in the app and on their phones - with no
confirmed panthaky, the funeral place's managers - the lock screen naming only
mobeds. Refused in plain words for someone not going, for a request withdrawn
or declined (or accepted the old way), and once the prayers have begun (the
Geh-saarnu's geh, as "still short" counts it: prayer_timers.prayers_begin; with
no days given, never for time).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings, get_settings
from agyary.models import Agyary, FuneralPlace, FuneralRecord, FuneralRequest, PrayerCalloutAnswer, User
from agyary.models.enums import REQUEST_ALL_SET, REQUEST_WAITING
from agyary.services import all_set, funeral_answers, funeral_requests, panthaky
from agyary.services import funeral_whatsapp as fw
from agyary.services import prayer_callout as pc
from agyary.services.prayer_callout import CalloutError

logger = logging.getLogger(__name__)

# To the panthakys (or the funeral place's managers): a place has opened.
KIND_PLACE_OPENED = "prayer_place_opened"
BOARD_BEGUN = "The prayers have begun, so who is going can no longer be changed here."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def begun_words(tell: str) -> str:
    return (f"The prayers have begun, so this can no longer be changed in Mobed Diary. "
            f"Please tell {tell} yourself.")


class AlreadyOut(CalloutError):
    """They are not going (they said they can't go already, or never were)."""


@dataclass
class _Words:
    """The refusals, for whoever is backing out."""

    already: str
    not_going: str
    begun: str


@dataclass
class Opened:
    """What followed a place opening: who was told."""

    panthakys: list[User] = field(default_factory=list)
    managers: bool = False
    has_panthaky: bool = False


async def who_hears(db: AsyncSession, request: FuneralRequest, settings: Settings | None = None) -> str:
    """Whom "Tell <...> you can't go?" names: the request's panthaky (whose
    book it put the family in as the panthaky; else who took it; else the
    confirmed panthakys it reached), or else the fire temple."""
    settings = settings or get_settings()
    heads = await all_set.request_panthakys(db, request.id)
    if not heads:
        confirmed = await panthaky.panthakys_of(db, settings, request.agyary_id)
        taker = next((p for p in confirmed if p.id == request.taken_by_user_id), None)
        reached = {u.id for u in await funeral_requests.asked(db, request)}
        heads = [taker] if taker is not None else [p for p in confirmed if p.id in reached]
    if heads:
        return all_set.join_names([p.name for p in heads])
    agyary = await db.get(Agyary, request.agyary_id)
    return agyary.name


async def _back_out(
    db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, *,
    by_user: User | None, words: _Words, now: datetime, client: httpx.AsyncClient | None,
    take_by: User | None = None, skip_user_id: int | None = None,
) -> Opened:
    """``row`` can no longer go. The request is locked first (every answer
    and place of a request waits here for the one before), then the row; the
    refusals are CalloutErrors (AlreadyOut for someone not going), with
    nothing changed. Committed before anything follows, so whatever happens
    next it stands."""
    await db.refresh(request, with_for_update=True)
    await db.refresh(row, with_for_update=True)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    if pc.backed_out(row):
        raise AlreadyOut(words.already)
    if not pc.holds_place(row):
        raise AlreadyOut(words.not_going)
    if request.status not in pc.MAY_BACK_OUT:
        raise CalloutError(pc.closed_words(request, place.name))
    if pc.prayers_begun(record, now):
        raise CalloutError(words.begun)
    if take_by is not None:
        await pc.take_request(db, request, take_by, now)
    row.backed_out_at = now
    row.backed_out_by_user_id = by_user.id if by_user is not None else None
    was_all_set = request.status == REQUEST_ALL_SET
    if was_all_set:
        # The place reopens: waiting again, all_set_at kept as when it was all set.
        request.status, request.decided_at = REQUEST_WAITING, None
    await db.commit()
    logger.warning("Request %s: answer %s can't go any more (%s)%s", request.id, row.id,
                   f"marked by user {by_user.id}" if by_user is not None else "on WhatsApp",
                   ", so it is waiting again" if was_all_set else "")
    try:
        return await place_opened(db, settings, request, row, now=now, skip_user_id=skip_user_id)
    except Exception:   # noqa: BLE001 - they have backed out; what did not follow is on the board
        logger.exception("After answer %s backed out of request %s", row.id, request.id)
        await db.rollback()
        await db.refresh(request)
        await db.refresh(row)
        return Opened()


async def place_opened(
    db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, *, now: datetime,
    skip_user_id: int | None = None,
) -> Opened:
    """A place opened because ``row`` can't go: the panthakys the request
    reached are told (not the one who marked it), or with no confirmed
    panthaky, the funeral place's managers. Commits."""
    record = await db.get(FuneralRecord, request.funeral_record_id)
    agyary = await db.get(Agyary, request.agyary_id)
    out = Opened(has_panthaky=bool(await panthaky.panthakys_of(db, settings, agyary.id)))
    who, departed = row.name, fw.departed(record)
    title = all_set.fit_title(f"{who} can't go and nobody is on standby: please find someone",
                              f"{who} can't go: please find someone", "A mobed can't go: please find someone")
    body = (f"{who} can't go any more for the prayers for {departed}, and nobody is on standby: please find "
            "someone. Ask everyone, call a mobed, or pray yourself.")
    out.panthakys = await pc._tell_panthakys(
        db, settings, request, row, KIND_PLACE_OPENED, title, body, push="Nobody is on standby: please find someone.",
        push_title=all_set.fit_title(f"{who} can't go", "A mobed can't go"), now=now, skip_user_id=skip_user_id,
        link=f"#/requests/{request.id}")
    if not out.has_panthaky:
        await funeral_answers._tell_managers(
            db, settings, record, request, kind=KIND_PLACE_OPENED,
            title=all_set.fit_title(f"{who} can't go: nobody is on standby at {agyary.name}",
                                    f"A mobed can't go at {agyary.name}", "A mobed can't go"),
            body=(f"{who} can't go any more for the prayers for {departed}, and nobody at {agyary.name} is on "
                  "standby: please find someone. You can withdraw the request and send it to another fire temple."),
            push=(all_set.fit_title(f"{who} can't go", "A mobed can't go"),
                  f"The request to {agyary.name}: nobody is on standby."), now=now)
        out.managers = True
    await db.commit()
    return out


def _told(opened: Opened, request_tell: str, place_name: str) -> str:
    """Who has been told, in words for the one who backed out."""
    if opened.panthakys:
        return f"{request_tell} has been told."
    if opened.managers:
        return f"{place_name} has been told."
    return ""


# --- Three ways in -----------------------------------------------------------------

async def back_out_in_app(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """An app mobed's own "I can't go any more" (the request reached them:
    the route checks). Returns {"outcome", "message"}; refusals are
    CalloutErrors."""
    now = now or _now()
    row = pc._find(await pc._request_rows(db, request.id), f"u{user.id}", user.phone)
    tell = await who_hears(db, request, settings)
    if row is None or row.answer is None:
        raise AlreadyOut("You are not going for this request, so there is nothing to change.")
    words = _Words(already="You have already said you can't go.",
                   not_going="You are not going for this request, so there is nothing to change.",
                   begun=begun_words(tell))
    opened = await _back_out(db, settings, request, row, by_user=user, words=words, now=now, client=client,
                             skip_user_id=user.id)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    told = _told(opened, tell, place.name)
    logger.info("Request %s: user %s can't go any more, in the app", request.id, user.id)
    return {"outcome": "backed out", "message": " ".join(w for w in ("Noted: you can't go.", told) if w)}


async def back_out_on_whatsapp(
    db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, *,
    now: datetime | None = None, client: httpx.AsyncClient | None = None,
) -> str:
    """A tap on "I can't go any more" on the details (template 6), from the
    number they were sent to (record_answer checks). Answered with a short
    text, inside the 24 hours the tap opened: thanked, or told why not (the
    prayers have begun, the request closed). A second tap changes and sends
    nothing. Returns what happened, for the log. Never raises."""
    now = now or _now()
    row_id, request_id = row.id, request.id
    try:
        tell = await who_hears(db, request, settings)
        words = _Words(already="", not_going="", begun=begun_words(tell))
        opened = await _back_out(db, settings, request, row, by_user=None, words=words, now=now, client=client)
    except AlreadyOut:
        await db.rollback()
        return "not going, so nothing changed"
    except CalloutError as exc:
        await db.rollback()
        await db.refresh(request)
        await db.refresh(row)
        await _reply(db, settings, request, row, str(exc), now=now, client=client, refused=True)
        return "refused"
    except Exception:   # noqa: BLE001 - a webhook must not fail; nothing was kept
        logger.exception("Backing out answer %s of request %s on WhatsApp failed", row_id, request_id)
        await db.rollback()
        return "failed"
    text = fw.BACKED_OUT_TEXT if opened.has_panthaky else fw.BACKED_OUT_NO_PANTHAKY_TEXT
    await _reply(db, settings, request, row, text, now=now, client=client)
    return "backed out"


async def _reply(db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer,
                 text: str, *, now: datetime, client: httpx.AsyncClient | None, refused: bool = False) -> None:
    if not row.phone:
        return
    row_id, request_id = row.id, request.id
    send = pc._text_send(row, request, fw.TYPE_BACKED_OUT, text)
    if refused:
        send.refs["refused"] = "1"
    try:
        await fw.deliver(db, settings, [send], now=now, client=client)
    except Exception:   # noqa: BLE001 - what was done stands; the reply is only a courtesy
        logger.exception("The reply to answer %s backing out of request %s failed", row_id, request_id)
        await db.rollback()


async def mark_cant_go(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, key, *,
    now: datetime | None = None, client: httpx.AsyncClient | None = None,
) -> dict:
    """The board's "Can't go" on a place (the route lets in only the
    confirmed panthakys the request reached, and the admin): for someone who
    phoned to say so. ``key`` is the place's "u<user id>" or "c<contact id>".
    It takes the request, as every board action does. Returns {"outcome",
    "message"}; refusals are CalloutErrors."""
    now = now or _now()
    if not isinstance(key, str) or not pc._KEY.match(key):
        raise CalloutError("That mobed could not be found on the board. Please open it again.", status=400,
                           field="key")
    mine = [r for r in await pc._request_rows(db, request.id) if pc._answer_key(r) == key]
    row = (next((r for r in mine if pc.holds_place(r)), None) or next((r for r in mine if pc.backed_out(r)), None)
           or (mine[-1] if mine else None))
    if row is None:
        raise AlreadyOut("That mobed is not going for this request. Please open the board again.")
    me = row.user_id == user.id
    words = _Words(already="You have already said you can't go." if me else f"{row.name} has already said they can't go.",
                   not_going=f"{'You are' if me else row.name + ' is'} not going for this request.",
                   begun=BOARD_BEGUN)
    await _back_out(db, settings, request, row, by_user=user, words=words, now=now, client=client,
                    take_by=user, skip_user_id=user.id)
    logger.info("Request %s: user %s marked %s can't go", request.id, user.id, key)
    return {"outcome": "backed out",
            "message": f"Noted: {'you' if me else row.name} can't go. The place is open again: please find someone."}
