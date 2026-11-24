"""Joining another agyari needs its panthaky's confirmation (DECISIONS D10,
owner 22 Nov 2026, from the security pass; docs/phase2-requests-redesign.md).

Joining a fire temple stays open (D1.4) and grants nobody's behdins (D2): the
membership is there for Settings, machis (D7) and the mobed's own book as it
always was. For prayer requests it counts only once it is confirmed and not
taken off the list (panthaky.counts_for_requests, the one rule):

- the admin's approval of a new sign-up confirms the fire temple they signed
  up at (mobed_access.set_access);
- the one who adds a brand-new fire temple is confirmed for it, since nobody
  else is there to (routes/mobed.py, create_agyari);
- the owner confirming someone as its panthaky confirms them (panthaky.confirm);
- an admin (ADMIN_PHONES) is confirmed wherever they are a member;
- anyone else who joins - a mobed already using the app who joins another fire
  temple from Settings - waits: its confirmed panthakys (access on) are told in
  the app and on their phones (no number on the lock screen) and confirm them
  on the Mobeds page; with no confirmed panthaky in the app, every admin is
  told and confirms them on Admin -> Mobeds (tell_of_join).

On the Mobeds page, a confirmed panthaky (or the admin) can **Confirm** a mobed
waiting, or say they are **Not one of ours**; can **Take off the list** one of
its mobeds; and can **Put back** one taken off. Taken off, they stay a member
(nothing else changes for them), a mobed the panthaky had added by hand with
the same number goes off the list with them, and a place they hold on one of
its requests is freed as "Can't go" frees it. Confirmed or put back, the mobed is
told in the app; taken off or not added, in the app and on their phone (no
reason; owner, 24 Nov 2026), never on WhatsApp. A waiting mobed's number is never shown, nor one taken off:
only the fire temple's mobeds' numbers are on the page (D10, "approved mobeds
with their numbers").
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import Agyary, AgyaryMobedContact, AgyaryUser, User
from agyary.models.enums import ACCOUNT_MOBED, ROLE_PANTHAKY
from agyary.services import guardrails, mobed_access, panthaky, reminders, web_push

logger = logging.getLogger(__name__)

# To the panthakys (or, with none, the admins): someone has joined and waits.
KIND_JOINED = "member_joined"
# To the mobed: confirmed (or put back) for the fire temple's prayer requests.
KIND_CONFIRMED = "requests_confirmed"
NOTICE_TTL = timedelta(days=7)
MOBEDS_LINK = "#/mobeds"
ADMIN_MOBEDS_LINK = "#/admin/mobeds"
# An in-app notice's title holds this many characters (app_notifications.title).
TITLE_MAX = 120

CONFIRM_WORDS = "Confirm them on Mobeds to send them prayer requests."
ADMIN_CONFIRM_WORDS = "Confirm them on the Mobeds page to send them prayer requests."
CONFIRMED_TITLE = "Confirmed for prayer requests"
# To the mobed: taken off the list, or not added (owner, 24 Nov 2026). No reason is given.
KIND_TAKEN_OFF = "requests_taken_off"
TAKEN_OFF_TITLE = "Not on the list for prayer requests"
NOT_FOUND = "That mobed could not be found at this fire temple."


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JoinError(ValueError):
    """Something that cannot be done now; the message is for whoever tapped."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def joined_title(user: User, agyary: Agyary) -> str:
    """ "Er. A has joined <agyari>", shorter if the names are long."""
    title = f"{user.name} has joined {agyary.name}"
    return title if len(title) <= TITLE_MAX else f"A mobed has joined {agyary.name}"[:TITLE_MAX]


def confirmed_words(agyary: Agyary) -> str:
    return f"{agyary.name} has confirmed you: you will now get its prayer requests."


def taken_off_words(agyary_name: str, *, waiting: bool) -> str:
    """What the mobed is told: no reason, only that they remain at the fire temple."""
    what = ("has not added you to its list for prayer requests" if waiting
            else "has taken you off its list for prayer requests")
    return f"The panthaky of {agyary_name} {what}. You remain at {agyary_name} in Mobed Diary."


# --- Joining ----------------------------------------------------------------------

async def tell_of_join(
    db: AsyncSession, settings: Settings, user: User, agyary: Agyary, membership: AgyaryUser, *,
    now: datetime | None = None,
) -> str | None:
    """Someone already using the app (access on) has just joined ``agyary``
    and waits to be confirmed for its requests: its confirmed panthakys whose
    access is on are told in the app and on their phones; with none, every
    admin, for Admin -> Mobeds. Nothing for a membership that already counts
    (an admin, one confirmed before) or was taken off the list before. Not
    committed here. Returns who was told ("panthaky", "admin") or None."""
    if (not mobed_access.has_access(settings, user)
            or panthaky.request_state(settings, membership, user) != panthaky.REQUESTS_WAITING):
        return None
    now = now or _now()
    title = joined_title(user, agyary)
    heads = await panthaky.panthakys_of(db, settings, agyary.id)
    if heads:
        for p in heads:
            await reminders.notify(db, p.id, KIND_JOINED, title, CONFIRM_WORDS, link=MOBEDS_LINK,
                                   agyary_id=agyary.id, now=now, ttl=NOTICE_TTL)
        await web_push.send_to_users(db, settings, [p.id for p in heads], title=title, body=CONFIRM_WORDS,
                                     url="/mobed" + MOBEDS_LINK, tag=f"member-joined-{agyary.id}-{user.id}")
        logger.info("User %s joined fire temple %s and waits: %d panthaky(s) told", user.id, agyary.id, len(heads))
        return "panthaky"
    phones = guardrails.admin_phones(settings)
    admins = (await db.execute(select(User.id).where(User.phone.in_(phones)))).scalars().all() if phones else []
    if not admins:
        logger.error("User %s joined fire temple %s, which has no panthaky, and no admin could be told",
                     user.id, agyary.id)
        return None
    body = f"{agyary.name} has no panthaky in the app. {ADMIN_CONFIRM_WORDS}"
    for uid in admins:
        await reminders.notify(db, uid, KIND_JOINED, title, body, link=ADMIN_MOBEDS_LINK, now=now, ttl=NOTICE_TTL)
    await web_push.send_to_users(db, settings, admins, title=title, body=ADMIN_CONFIRM_WORDS,
                                 url="/mobed" + ADMIN_MOBEDS_LINK, tag=f"member-joined-{agyary.id}-{user.id}")
    logger.info("User %s joined fire temple %s, which has no panthaky: %d admin(s) told", user.id, agyary.id,
                len(admins))
    return "admin"


# --- Who is waiting, and who is off the list (the Mobeds pages) --------------------

async def not_on_the_list(db: AsyncSession, settings: Settings, agyary_id: int) -> dict:
    """The fire temple's app mobeds who are not on its list for requests, by
    name only (never a number, nor the state of their account): "waiting" -
    joined, not confirmed yet (a sign-up still waiting for the admin is
    confirmed by the approval, unless the panthaky says first that they are not
    one of theirs) - and "off", taken off the list. Its panthakys never appear."""
    rows = (await db.execute(
        select(AgyaryUser, User).join(User, User.id == AgyaryUser.user_id).where(
            AgyaryUser.agyary_id == agyary_id, AgyaryUser.is_active.is_(True), AgyaryUser.role != ROLE_PANTHAKY,
            User.is_active.is_(True), User.account_kind == ACCOUNT_MOBED,
        ).order_by(User.name, User.id)
    )).all()
    out: dict[str, list[dict]] = {"waiting": [], "off": []}
    for m, u in rows:
        state = panthaky.request_state(settings, m, u)
        if state == panthaky.REQUESTS_OFF:
            out["off"].append({"id": u.id, "name": u.name,
                               "at": m.requests_off_at.isoformat() if m.requests_off_at else None})
        elif state == panthaky.REQUESTS_WAITING:
            out["waiting"].append({"id": u.id, "name": u.name, "at": m.joined_at.isoformat() if m.joined_at else None})
    return out


# --- Confirm, Not one of ours / Take off the list, Put back -------------------------

async def _member(db: AsyncSession, agyary_id: int, user_id) -> tuple[AgyaryUser, User]:
    """The membership, locked, of an app mobed at this fire temple; JoinError
    404 for anything else."""
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        raise JoinError(NOT_FOUND, 404)
    row = (await db.execute(
        select(AgyaryUser, User).join(User, User.id == AgyaryUser.user_id).where(
            AgyaryUser.agyary_id == agyary_id, AgyaryUser.user_id == user_id, AgyaryUser.is_active.is_(True),
            User.is_active.is_(True), User.account_kind == ACCOUNT_MOBED,
        ).with_for_update(of=AgyaryUser).execution_options(populate_existing=True)
    )).first()
    if row is None:
        raise JoinError(NOT_FOUND, 404)
    return row[0], row[1]


async def _on_the_list(db: AsyncSession, settings: Settings, actor: User, agyary: Agyary, m: AgyaryUser,
                       user: User, now: datetime) -> None:
    """Confirmed for its requests, now, by ``actor``, and on the list; the
    mobed is told in the app (D9: only an account that is on)."""
    m.requests_confirmed_at, m.requests_confirmed_by_user_id = now, actor.id
    m.requests_off_at = m.requests_off_by_user_id = None
    await db.flush()
    if mobed_access.has_access(settings, user):
        await reminders.notify(db, user.id, KIND_CONFIRMED, CONFIRMED_TITLE, confirmed_words(agyary),
                               link="#/requests", agyary_id=agyary.id, now=now, ttl=NOTICE_TTL)


async def confirm(
    db: AsyncSession, settings: Settings, actor: User, agyary: Agyary, user_id, *, now: datetime | None = None,
) -> dict:
    """ "Confirm": a mobed waiting becomes one of the fire temple's mobeds for
    its prayer requests. Not committed here. Returns {"message"}."""
    now = now or _now()
    m, user = await _member(db, agyary.id, user_id)
    state = panthaky.request_state(settings, m, user)
    if state == panthaky.REQUESTS_CONFIRMED:
        raise JoinError(f"{user.name} is on the list already.")
    if state == panthaky.REQUESTS_OFF:
        raise JoinError(f"{user.name} is off the list. Tap Put back to send them prayer requests.")
    await _on_the_list(db, settings, actor, agyary, m, user, now)
    logger.warning("User %s confirmed user %s for the requests of fire temple %s", actor.id, user.id, agyary.id)
    return {"message": f"{user.name} is confirmed: they will now get prayer requests."}


async def put_back(
    db: AsyncSession, settings: Settings, actor: User, agyary: Agyary, user_id, *, now: datetime | None = None,
) -> dict:
    """ "Put back": one taken off the list is one of its mobeds again,
    confirmed. Not committed here. Returns {"message"}."""
    now = now or _now()
    m, user = await _member(db, agyary.id, user_id)
    if panthaky.request_state(settings, m, user) != panthaky.REQUESTS_OFF:
        raise JoinError(f"{user.name} is not off the list.")
    await _on_the_list(db, settings, actor, agyary, m, user, now)
    logger.warning("User %s put user %s back on the list of fire temple %s", actor.id, user.id, agyary.id)
    return {"message": f"{user.name} is back on the list: they will get prayer requests."}


async def take_off(
    db: AsyncSession, settings: Settings, actor: User, agyary: Agyary, user_id, *, now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """ "Not one of ours" (a mobed waiting) or "Take off the list" (one of its
    mobeds): off the list for its prayer requests, by ``actor``. They stay a
    member, and nothing else changes for them; a mobed added by hand with the
    same number goes off the list too. A place they hold on one of its
    requests is freed as "Can't go" frees it (lead's decision, 22 Nov 2026:
    standbys.free_places_of), and their own book keeps the family (D8). Never
    a panthaky of the fire temple (the owner decides that, on Admin ->
    Mobeds). Committed. Returns {"message"}, saying any place freed."""
    from agyary.services import standbys   # here: standbys reaches all_set, which reaches the books

    now = now or _now()
    m, user = await _member(db, agyary.id, user_id)
    if m.role == ROLE_PANTHAKY:
        raise JoinError(f"{user.name} is a panthaky of {agyary.name}, so they stay on the list.")
    if m.requests_off_at is not None:
        raise JoinError(f"{user.name} is off the list already.")
    waiting = panthaky.request_state(settings, m, user) == panthaky.REQUESTS_WAITING
    told = mobed_access.has_access(settings, user)   # D9: nothing to an account that is not on
    m.requests_off_at, m.requests_off_by_user_id = now, actor.id
    await db.execute(
        update(AgyaryMobedContact)
        .where(AgyaryMobedContact.agyary_id == agyary.id, AgyaryMobedContact.phone == user.phone,
               AgyaryMobedContact.is_active.is_(True))
        .values(is_active=False)
    )
    await db.commit()
    name, uid, phone, aid, agyary_name = user.name, user.id, user.phone, agyary.id, agyary.name
    logger.warning("User %s took user %s off the list of fire temple %s%s", actor.id, uid, aid,
                   " (not one of ours)" if waiting else "")
    freed = await standbys.free_places_of(db, settings, by_user=actor, agyary_id=aid, user_id=uid, phone=phone,
                                          now=now, client=client)
    if told:
        try:
            words = taken_off_words(agyary_name, waiting=waiting)
            await reminders.notify(db, uid, KIND_TAKEN_OFF, TAKEN_OFF_TITLE, words, link="#/requests",
                                   agyary_id=aid, now=now, ttl=NOTICE_TTL)
            await web_push.send_to_users(db, settings, [uid], title=TAKEN_OFF_TITLE, body=words,
                                         url="/mobed#/requests", tag=f"requests-taken-off-{aid}-{uid}")
            await db.commit()
        except Exception:   # the action is done; telling them must not undo or fail it
            logger.exception("Could not tell user %s they were taken off the list of fire temple %s", uid, aid)
            await db.rollback()
    return {"message": " ".join(w for w in (f"{name} is off the list.", standbys.freed_words(freed)) if w),
            "places_freed": len(freed)}
