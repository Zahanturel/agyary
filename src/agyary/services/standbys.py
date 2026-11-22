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
kept as history; ``taken_at`` stays, so the safety net never fires). Refused
in plain words for someone not going, for a request withdrawn or declined (or
accepted the old way), and once the prayers have begun (the Geh-saarnu's geh,
as "still short" counts it: prayer_timers.prayers_begin; with no days given,
never for time).

Standbys asked again, by themselves (owner): the standbys are the yeses never
picked, in the order they said yes (prayer_callout.is_standby). While a
waiting request has places open, as many standbys as there are open places
not already waited for are asked again (ask_standbys), each once: on WhatsApp
with the call-out template (it works outside the 24 hours) carrying a fresh
unguessable token of their own (``reask_token``), and in the app for an app
mobed ("A place has opened: can you still pray?", answered with I can pray /
Not this time on their card, through the same answer_reask). Someone neither
can reach is passed over. Not the panthaky, who fills a place from the board.

- A yes to it goes through prayer_callout.fill: it fills the place (and may
  make the request all set again), or, the place filled meanwhile by other
  means, they stay a standby and are thanked with the "Enough mobeds" words.
- A no, or no answer in 30 minutes (``timed_out``, run by the one-minute loop,
  claimed once by a conditional update of ``reask_passed_at``, so two loops or
  a no at the same moment move on once), asks the next standby.
- The panthakys the request reached are told at each step, in the app and on
  their phones (the lock screen naming only mobeds): "<A> can't go; we have
  asked <B>", "<B> said no / did not answer; we have asked <C>", and with
  nobody left "<A> can't go and nobody is on standby: please find someone",
  with the board. With no confirmed panthaky, the funeral place's managers are
  told only that (they can send the request elsewhere) - by name only of
  someone the place learned was going at All set; otherwise "A mobed can't
  go" and how many are going (D10: the place learns names only at All set).
- Once the places are filled again, nobody more is asked; a late answer still
  counts as above.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings, get_settings
from agyary.models import (
    Agyary,
    FuneralPlace,
    FuneralRecord,
    FuneralRequest,
    FuneralRequestRecipient,
    PrayerCallout,
    PrayerCalloutAnswer,
    User,
)
from agyary.models.enums import CALLOUT_NO, CALLOUT_YES, HOW_APP, HOW_SELF, REQUEST_ALL_SET, REQUEST_WAITING
from agyary.services import (
    all_set,
    funeral_answers,
    funeral_requests,
    mobed_access,
    mobed_dashboard,
    panthaky,
    reminders,
    template_text,
    web_push,
)
from agyary.services import funeral_whatsapp as fw
from agyary.services import prayer_callout as pc
from agyary.services.prayer_callout import CalloutError

logger = logging.getLogger(__name__)

# To the panthakys (or the funeral place's managers): a place has opened, and what was done.
KIND_PLACE_OPENED = "prayer_place_opened"
# To a standby in the app: a place has opened, can you still pray?
KIND_REASK = "prayer_reask"
REASK_TITLE = "A place has opened"
# How long a standby asked again has before the next is asked (the lead's default).
REASK_WAIT = timedelta(minutes=30)
# Rounds of asking in one go, each passing over those who could not be reached.
MAX_ROUNDS = 20
BOARD_BEGUN = "The prayers have begun, so who is going can no longer be changed here."

# A standby's re-ask, on the board and their card.
REASK_WAITING, REASK_ASKED, REASK_SAID_NO, REASK_NO_ANSWER = "waiting", "asked_again", "said_no", "no_answer"


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
class Asked:
    """Where asking the standbys stands."""

    # Asked again just now, and reached (in the app or on WhatsApp).
    asked: list[PrayerCalloutAnswer] = field(default_factory=list)
    # Asked again and not answered within the 30 minutes yet (including those just asked).
    waiting_on: list[PrayerCalloutAnswer] = field(default_factory=list)
    # Neither the app nor WhatsApp could reach them, so they were passed over.
    unreachable: list[PrayerCalloutAnswer] = field(default_factory=list)
    # Places open now (0 when full, or the request is not waiting).
    open: int = 0


@dataclass
class Opened:
    """What followed a place opening: who was told, and who was asked."""

    panthakys: list[User] = field(default_factory=list)
    managers: bool = False
    has_panthaky: bool = False
    asked: Asked = field(default_factory=Asked)


# --- A standby's re-ask -------------------------------------------------------------

def reask_state(row: PrayerCalloutAnswer) -> str:
    """Not asked again (or a late yes: a standby again), asked and waited for,
    said no, or no answer in the 30 minutes."""
    if row.reasked_at is None or row.reask_answer == CALLOUT_YES:
        return REASK_WAITING
    if row.reask_answer == CALLOUT_NO:
        return REASK_SAID_NO
    if row.reask_passed_at is not None:
        return REASK_NO_ANSWER
    return REASK_ASKED


def awaiting_answer(row: PrayerCalloutAnswer) -> bool:
    """Asked again and not answered: a late answer still counts after the 30 minutes."""
    return pc.is_standby(row) and row.reasked_at is not None and row.reask_answer is None


def _waited_on(row: PrayerCalloutAnswer) -> bool:
    return awaiting_answer(row) and row.reask_passed_at is None


def _askable(row: PrayerCalloutAnswer, panthaky_ids: set[int]) -> bool:
    """A standby who may be asked again now: not asked yet, or a late yes
    since (a standby again); never the panthaky, who uses the board (nor
    anyone prayer_callout.left_out leaves out: _choose)."""
    if not pc.is_standby(row) or row.how == HOW_SELF or (row.user_id and row.user_id in panthaky_ids):
        return False
    return row.reasked_at is None or row.reask_answer == CALLOUT_YES


async def _heads(db: AsyncSession, settings: Settings, request: FuneralRequest) -> list[User]:
    """The request's panthaky: whose book it put the family in as the
    panthaky; else who took it; else the confirmed panthakys it reached."""
    heads = await all_set.request_panthakys(db, request.id)
    if heads:
        return heads
    confirmed = await panthaky.panthakys_of(db, settings, request.agyary_id)
    taker = next((p for p in confirmed if p.id == request.taken_by_user_id), None)
    if taker is not None:
        return [taker]
    reached = {u.id for u in await funeral_requests.asked(db, request)}
    return [p for p in confirmed if p.id in reached]


async def who_hears(db: AsyncSession, request: FuneralRequest, settings: Settings | None = None) -> str:
    """Whom "Tell <...> you can't go?" names: the request's panthaky (_heads),
    or else the fire temple."""
    heads = await _heads(db, settings or get_settings(), request)
    if heads:
        return all_set.join_names([p.name for p in heads])
    agyary = await db.get(Agyary, request.agyary_id)
    return agyary.name


async def ask_standbys(
    db: AsyncSession, settings: Settings, request: FuneralRequest, *, now: datetime,
    client: httpx.AsyncClient | None,
) -> Asked:
    """Ask again, in their order, as many standbys as there are open places
    not already waited for (see the module's docstring). Each is marked asked
    (with their fresh token) under the request's lock and committed before
    anything is sent, so two at the same moment never ask the same one; one
    neither the app nor WhatsApp reaches is passed over and the next asked.
    Returns where it stands."""
    out = Asked()
    for _ in range(MAX_ROUNDS):
        chosen = await _choose(db, settings, request, now)
        missed = 0
        for row in chosen:
            if await _send_reask(db, settings, request, row, now=now, client=client):
                out.asked.append(row)
            else:
                await _pass(db, row, now)
                out.unreachable.append(row)
                missed += 1
        if not missed:
            break
    await db.refresh(request)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    rows = await pc._request_rows(db, request.id)
    if request.status == REQUEST_WAITING:
        out.open = max(0, pc.wanted(record) - sum(1 for r in rows if pc.holds_place(r)))
    out.waiting_on = sorted((r for r in rows if _waited_on(r)), key=lambda r: (r.answered_at, r.id))
    if out.asked or out.unreachable:
        logger.warning("Request %s: %d standby(s) asked again, %d could not be reached, %d open", request.id,
                       len(out.asked), len(out.unreachable), out.open)
    return out


async def _choose(db: AsyncSession, settings: Settings, request: FuneralRequest, now: datetime
                  ) -> list[PrayerCalloutAnswer]:
    await db.refresh(request, with_for_update=True)
    if request.status != REQUEST_WAITING:
        await db.commit()
        return []
    record = await db.get(FuneralRecord, request.funeral_record_id)
    rows = await pc._request_rows(db, request.id)
    need = pc.wanted(record) - sum(1 for r in rows if pc.holds_place(r)) - sum(1 for r in rows if _waited_on(r))
    if need <= 0:
        await db.commit()
        return []
    heads = {p.id for p in await panthaky.panthakys_of(db, settings, request.agyary_id)}
    # Never someone who can no longer take part: taken off the list since, say.
    out = await pc.left_out(db, settings, request.agyary_id, rows)
    chosen = sorted((r for r in rows if _askable(r, heads) and r.id not in out),
                    key=lambda r: (r.answered_at, r.id))[:need]
    for r in chosen:
        r.reask_token, r.reasked_at = pc._new_token(), now
        r.reask_answer = r.reask_answered_at = r.reask_passed_at = None
    await db.commit()
    return chosen


async def _pass(db: AsyncSession, row: PrayerCalloutAnswer, now: datetime) -> bool:
    """Move on past this standby, once (a no, 30 minutes, or nobody could
    reach them): a conditional update, so a no and the timer at the same
    moment move on once. Commits. Returns whether this call did it."""
    done = (await db.execute(
        update(PrayerCalloutAnswer)
        .where(PrayerCalloutAnswer.id == row.id, PrayerCalloutAnswer.reask_passed_at.is_(None),
               PrayerCalloutAnswer.reask_answer.is_(None), PrayerCalloutAnswer.reasked_at.is_not(None))
        .values(reask_passed_at=now).returning(PrayerCalloutAnswer.id)
    )).scalar_one_or_none()
    await db.commit()
    await db.refresh(row)
    return done is not None


async def _send_reask(db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, *,
                      now: datetime, client: httpx.AsyncClient | None) -> bool:
    """"A place has opened: can you still pray?" to one standby: in the app
    (an app mobed whose access is on and who is still at the fire temple,
    with a phone notification naming nothing) and on WhatsApp (the call-out
    template with the re-ask's own buttons; STOP, D9, the caps and the pause
    switch as for every message). Returns whether either reached them."""
    record = await db.get(FuneralRecord, request.funeral_record_id)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    departed = fw.departed(record)
    reached = False
    account = await db.get(User, row.user_id) if row.user_id else None
    if (account is not None and account.is_active and mobed_access.has_access(settings, account)
            and await mobed_dashboard.is_active_member(db, agyary.id, account.id)):
        if (await db.execute(select(FuneralRequestRecipient.user_id).where(
                FuneralRequestRecipient.funeral_request_id == request.id,
                FuneralRequestRecipient.user_id == account.id))).first() is None:
            db.add(FuneralRequestRecipient(funeral_request_id=request.id, user_id=account.id, notified_at=now))
        link = f"#/requests/{request.id}"
        await reminders.notify(db, account.id, KIND_REASK, REASK_TITLE,
                               f"A place has opened for the prayers for {departed}: can you still pray? "
                               "Please answer on the request.", link=link, agyary_id=agyary.id, now=now,
                               ttl=pc.NOTICE_TTL)
        await db.commit()
        await web_push.send_to_users(db, settings, [account.id], title=REASK_TITLE,
                                     body="Can you still pray? Open Mobed Diary to answer.", url="/mobed" + link,
                                     tag=f"prayer-reask-{row.id}")
        await db.commit()
        reached = True
    if row.phone and await fw.why_not_now(db, settings) is None:
        heads = await _heads(db, settings, request)
        asker = heads[0].name if heads else agyary.name
        asker_max = template_text.MOBED_NAME_MAX if heads else template_text.TEMPLE_MAX
        why = None
        if account is not None:
            why = all_set._why_off(account, settings)
        elif row.contact_id:
            # Matched to an account by their number now, not only when they were added.
            linked = (await pc.accounts_by_phone(db, [row.phone])).get(row.phone)
            if linked is not None and not pc.account_on(settings, linked):
                why = "their Mobed Diary access is not on"
        # The call-out's own words (template 4 v2), with the re-ask's buttons.
        send = fw.Send(
            kind=fw.TYPE_CALLOUT, phone=row.phone, agyary_id=agyary.id,
            params=[agyary.name, departed, place.name, fw.geh_saarnu_text(record), fw.uthamna_text(record), asker],
            quick_replies=(f"{pc.PAYLOAD_PREFIX}{row.reask_token}:y", f"{pc.PAYLOAD_PREFIX}{row.reask_token}:n"),
            refs={"request": request.id, "answer": row.id, "reask": "1"},
            names=pc._names(record, place, agyary, asker, asker_max), why_not=why, **pc._to(row))
        sent = await fw.deliver(db, settings, [send], now=now, client=client)
        reached = reached or any(fw.went(n) for n in sent)
    return reached


# --- Telling the panthaky -----------------------------------------------------------

def _named_to_the_place(request: FuneralRequest, row: PrayerCalloutAnswer, first: bool) -> bool:
    """Whether the funeral place may be told this person's name: only someone
    who was going when the request was last all set, which is when the place
    learned who is going (D10: names only at All set). Never a standby."""
    return (first and request.all_set_at is not None and row.picked_at is not None
            and row.picked_at <= request.all_set_at)


async def _tell_step(
    db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, *, lead: str,
    unnamed: str, asked: Asked, first: bool, now: datetime, skip_user_id: int | None = None,
) -> Opened:
    """The panthakys the request reached (not ``skip_user_id``, who did it on
    screen), and with none, the funeral place's managers when nobody is left:
    ``lead`` ("Er. A can't go", "Er. B said no", "Er. B did not answer") and
    what was done. Commits. ``first``: the place has just opened. The place
    is told the name only of someone it learned was going at All set
    (_named_to_the_place); otherwise ``unnamed`` ("A mobed can't go") and how
    many are going, never a name."""
    record = await db.get(FuneralRecord, request.funeral_record_id)
    agyary = await db.get(Agyary, request.agyary_id)
    out = Opened(has_panthaky=bool(await panthaky.panthakys_of(db, settings, agyary.id)), asked=asked)
    departed = fw.departed(record)
    link = f"#/requests/{request.id}"
    push_title = all_set.fit_title(lead, "A place has opened")
    if asked.waiting_on:
        names = all_set.join_names([r.name for r in asked.waiting_on])
        title = all_set.fit_title(f"{lead}; we have asked {names}", f"{lead}; we have asked a standby",
                                  "We have asked a standby")
        body = (f"For the prayers for {departed}: {lead}; we have asked {names}. If there is no yes in 30 "
                "minutes, the next on standby is asked.")
        out.panthakys = await pc._tell_panthakys(
            db, settings, request, row, KIND_PLACE_OPENED, title, body, push=f"We have asked {names}.",
            push_title=push_title, now=now, skip_user_id=skip_user_id, link=link)
    elif asked.open > 0:
        nobody = ("nobody on standby could be asked" if asked.unreachable
                  else "nobody is on standby" if first else "nobody else is on standby")
        title = all_set.fit_title(f"{lead} and {nobody}: please find someone", f"{lead}: please find someone",
                                  "Please find someone")
        body = (f"For the prayers for {departed}: {lead} and {nobody}: please find someone. Ask everyone, call a "
                "mobed, or pray yourself.")
        out.panthakys = await pc._tell_panthakys(
            db, settings, request, row, KIND_PLACE_OPENED, title, body, push=f"{nobody[0].upper()}{nobody[1:]}: "
            "please find someone.", push_title=push_title, now=now, skip_user_id=skip_user_id, link=link)
        if not out.has_panthaky:
            if _named_to_the_place(request, row, first):
                title = all_set.fit_title(f"{lead}: nobody is on standby at {agyary.name}",
                                          f"A mobed can't go at {agyary.name}", "A mobed can't go")
                said, place_push = lead, push_title
            else:
                # Before All set the place learns only how many are going, never who (D10).
                going = sum(1 for r in await pc._request_rows(db, request.id) if pc.holds_place(r))
                count = f"{going} of {pc.wanted(record)} going"
                title = all_set.fit_title(f"{unnamed} at {agyary.name}; {count}", f"{unnamed}; {count}", unnamed)
                said, place_push = f"{unnamed[0].lower()}{unnamed[1:]} ({count})", unnamed
            await funeral_answers._tell_managers(
                db, settings, record, request, kind=KIND_PLACE_OPENED, title=title,
                body=(f"For the prayers for {departed}: {said}, and nobody at {agyary.name} is on standby: please "
                      "find someone. You can withdraw the request and send it to another fire temple."),
                push=(place_push, f"The request to {agyary.name}: nobody is on standby."), now=now)
            out.managers = True
    elif first:
        # Filled again at the same moment by other means: said so, and nobody is asked.
        out.panthakys = await pc._tell_panthakys(
            db, settings, request, row, KIND_PLACE_OPENED, all_set.fit_title(lead, "A mobed can't go"),
            f"For the prayers for {departed}: {lead}; the place has been filled again.", push=None, now=now,
            skip_user_id=skip_user_id, link=link)
    await db.commit()
    return out


async def place_opened(
    db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, *, now: datetime,
    client: httpx.AsyncClient | None, skip_user_id: int | None = None,
) -> Opened:
    """A place opened because ``row`` can't go: the standbys are asked, and
    the panthakys told. Commits."""
    asked = await ask_standbys(db, settings, request, now=now, client=client)
    return await _tell_step(db, settings, request, row, lead=f"{row.name} can't go", unnamed="A mobed can't go",
                            asked=asked, first=True, now=now, skip_user_id=skip_user_id)


async def _move_on(db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, *,
                   lead: str, unnamed: str, now: datetime, client: httpx.AsyncClient | None) -> Asked:
    """Past ``row`` (who said no, or did not answer): the next standby is
    asked, and the panthakys told - unless the places are filled meanwhile
    (or the request is no longer waiting), when nobody more is asked or told."""
    asked = await ask_standbys(db, settings, request, now=now, client=client)
    if asked.open > 0:
        await _tell_step(db, settings, request, row, lead=lead, unnamed=unnamed, asked=asked, first=False, now=now)
    return asked


# --- Backing out ----------------------------------------------------------------------

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
        return await place_opened(db, settings, request, row, now=now, client=client, skip_user_id=skip_user_id)
    except Exception:   # noqa: BLE001 - they have backed out; what did not follow is on the board
        logger.exception("After answer %s backed out of request %s", row.id, request.id)
        await db.rollback()
        await db.refresh(request)
        await db.refresh(row)
        return Opened()


def _asked_words(opened: Opened) -> str:
    """What was done about the open place, for the panthaky on screen."""
    asked = opened.asked
    if asked.waiting_on:
        return f"We have asked {all_set.join_names([r.name for r in asked.waiting_on])}."
    if asked.open > 0:
        return ("Nobody on standby could be asked: please find someone." if asked.unreachable
                else "Nobody is on standby: please find someone.")
    return ""


async def back_out_in_app(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """An app mobed's own "I can't go any more" (the request reached them:
    the route checks). Returns {"outcome", "message"}; refusals are
    CalloutErrors."""
    now = now or _now()
    user_id = user.id   # what follows may roll the session back, which forgets the account
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
    if opened.panthakys:
        told = f"{tell} has been told."
    elif opened.managers:
        told = f"{place.name} has been told."
    elif opened.asked.waiting_on:
        told = "A mobed on standby has been asked to take your place."
    else:
        told = ""
    logger.info("Request %s: user %s can't go any more, in the app", request.id, user_id)
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
    user_id = user.id   # what follows may roll the session back, which forgets the account
    me = row.user_id == user_id
    name = row.name
    words = _Words(already="You have already said you can't go." if me else f"{name} has already said they can't go.",
                   not_going=f"{'You are' if me else name + ' is'} not going for this request.",
                   begun=BOARD_BEGUN)
    opened = await _back_out(db, settings, request, row, by_user=user, words=words, now=now, client=client,
                             take_by=user, skip_user_id=user.id)
    logger.info("Request %s: user %s marked %s can't go", request.id, user_id, key)
    return {"outcome": "backed out",
            "message": " ".join(w for w in (f"Noted: {'you' if me else name} can't go.", _asked_words(opened)) if w)}


# --- A standby's answer to being asked again ------------------------------------------

async def answer_reask(
    db: AsyncSession, settings: Settings, request: FuneralRequest, row: PrayerCalloutAnswer, yes: bool, *,
    how: str, by_user: User | None, now: datetime, client: httpx.AsyncClient | None,
) -> str:
    """A standby's answer to "can you still pray?" - on WhatsApp (the
    re-ask's own token) or in the app - only their first. Committed before
    anything follows. A yes goes through prayer_callout.fill (a place, or
    with none open a standby again, thanked); a no asks the next standby and
    tells the panthaky, unless the 30 minutes had already moved on. Returns
    what happened, for the log."""
    await db.refresh(request, with_for_update=True)
    await db.refresh(row, with_for_update=True)
    if row.reasked_at is None or not pc.is_standby(row):
        await db.commit()
        return "not asked again"
    if row.reask_answer is not None:
        await db.commit()
        return "already answered again"
    row.reask_answer, row.reask_answered_at = (CALLOUT_YES if yes else CALLOUT_NO), now
    moved = not yes and row.reask_passed_at is None
    if moved:
        row.reask_passed_at = now
    await db.commit()
    logger.info("Request %s: standby %s answered again %s (%s)", request.id, row.id, "yes" if yes else "no", how)
    try:
        if yes:
            return "yes again, " + await pc.fill(db, settings, request, row, how, by_user, now, client)
        if moved:
            await _move_on(db, settings, request, row, lead=f"{row.name} said no",
                           unnamed="A mobed on standby said no", now=now, client=client)
        return "no again"
    except Exception:   # noqa: BLE001 - the answer is kept; what did not follow is on the board
        logger.exception("After standby %s answered again on request %s", row.id, request.id)
        await db.rollback()
        return ("yes" if yes else "no") + " again, but what follows failed"


async def answer_reask_in_app(
    db: AsyncSession, settings: Settings, user: User, request: FuneralRequest, row: PrayerCalloutAnswer,
    yes: bool, *, now: datetime, client: httpx.AsyncClient | None,
) -> dict:
    """An app standby's I can pray / Not this time to "A place has opened"
    (prayer_callout.answer_in_app sends it here). Returns {"outcome", "message"}."""
    outcome = await answer_reask(db, settings, request, row, yes, how=HOW_APP, by_user=user, now=now, client=client)
    await db.refresh(row)
    await db.refresh(request)
    if outcome == "already answered again":
        message = "You have answered already."
    elif not yes:
        message = pc.NO_WORDS
    elif pc.holds_place(row):
        message = pc.ALL_SET_GOING_WORDS if request.status == REQUEST_ALL_SET else pc.GOING_WORDS
    else:
        message = fw.ENOUGH_TEXT
    return {"outcome": outcome, "message": message}


# --- The 30 minutes (run by the one-minute loop: prayer_timers.run) -------------------

async def timed_out(db: AsyncSession, now: datetime, settings: Settings, client: httpx.AsyncClient | None) -> int:
    """Each standby asked again 30 minutes ago or more who has not answered:
    the asking moves on past them once (claimed by a conditional update,
    committed first, so two loops at the same moment move on once), and the
    next standby is asked - only while the request waits with a place open.
    Returns how many it moved on past."""
    due = (await db.execute(
        select(PrayerCalloutAnswer.id, PrayerCallout.funeral_request_id)
        .join(PrayerCallout, PrayerCallout.id == PrayerCalloutAnswer.callout_id)
        .where(PrayerCalloutAnswer.reasked_at <= now - REASK_WAIT, PrayerCalloutAnswer.reask_answer.is_(None),
               PrayerCalloutAnswer.reask_passed_at.is_(None))
        .order_by(PrayerCalloutAnswer.reasked_at, PrayerCalloutAnswer.id)
    )).all()
    done = 0
    for row_id, request_id in due:
        row = await db.get(PrayerCalloutAnswer, row_id, populate_existing=True)
        if row is None or not await _pass(db, row, now):
            continue            # answered just now, or another loop has it
        done += 1
        try:
            request = await db.get(FuneralRequest, request_id, populate_existing=True)
            logger.warning("Request %s: standby %s did not answer in 30 minutes", request_id, row_id)
            await _move_on(db, settings, request, row, lead=f"{row.name} did not answer",
                           unnamed="A mobed on standby did not answer", now=now, client=client)
        except Exception:   # noqa: BLE001 - it is claimed (once); the next one still goes
            logger.exception("Moving on past standby %s of request %s failed", row_id, request_id)
            await db.rollback()
    await db.commit()
    return done
