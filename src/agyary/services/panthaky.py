"""Mobed or panthaky: what a person says they are at a fire temple, and the
owner's decision on it (DECISIONS D10).

The panthaky role lets a person see every machi at their fire temple (D7), and
nobody may give themselves that. So what a person says - when they choose
their fire temple, or later from Settings - is kept as a *claim* on the
membership (``claimed_role``) and never changes ``role``. Every power in the
app reads ``role`` alone (ADMIN_ROLES), so a claim grants nothing anywhere.
Only an admin's "Confirm as panthaky" on Admin -> Mobeds sets role = panthaky;
"Not the panthaky" keeps them a mobed, and a confirmed panthaky can be made a
mobed again. Each decision is kept on the membership, with when and by whom.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import Agyary, AgyaryUser, User
from agyary.models.enums import (
    CLAIM_CONFIRMED,
    CLAIM_DECLINED,
    CLAIM_REMOVED,
    CLAIMED_ROLES,
    ROLE_MOBED,
    ROLE_PANTHAKY,
)
from agyary.services import guardrails, reminders

logger = logging.getLogger(__name__)

KIND_CLAIM = "panthaky_claim"
KIND_DECISION = "panthaky_decision"
# Kept in front of the admin as long as a new mobed's request is.
CLAIM_TTL = timedelta(days=7)
MOBEDS_LINK = "#/admin/mobeds"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ClaimError(ValueError):
    """A claim or decision that cannot be made now; the message is for the person."""


def waiting(membership: AgyaryUser) -> bool:
    """Says they are the panthaky, and no admin has decided yet."""
    return (
        membership.claimed_role == ROLE_PANTHAKY
        and membership.claim_decision is None
        and membership.role == ROLE_MOBED
    )


def may_claim(membership: AgyaryUser) -> bool:
    """Whether this membership can still say what it is: a plain mobed who has
    said nothing yet, and on whom no admin has decided anything."""
    return (
        membership.role == ROLE_MOBED
        and membership.claimed_role is None
        and membership.claim_decision is None
    )


async def record_claim(
    db: AsyncSession, membership: AgyaryUser, claimed_role: str, *, now: datetime | None = None
) -> bool:
    """Keep what the person says they are here. ``role`` is not touched.

    One claim per membership: once one is made, or an admin has decided, it
    stays as it is (returns False) - choosing the same fire temple again must
    not reopen a decision. Returns True when the claim was recorded."""
    if claimed_role not in CLAIMED_ROLES:
        raise ClaimError("Please say whether you are a mobed or the panthaky here.")
    if not may_claim(membership):
        return False
    membership.claimed_role = claimed_role
    membership.claimed_at = now or _now()
    await db.flush()
    logger.info(
        "User %s says they are %s at fire temple %s", membership.user_id, claimed_role, membership.agyary_id
    )
    return True


async def tell_admins_of_claim(
    db: AsyncSession, settings: Settings, user: User, agyary: Agyary, *, now: datetime | None = None
) -> int:
    """Tell every admin, in the app, that a mobed already using the app says
    they are the panthaky of ``agyary``. (A new sign-up's claim is in its
    "A new mobed is waiting" notice instead.) Returns how many were told."""
    phones = guardrails.admin_phones(settings)
    if not phones:
        logger.error("User %s says they are a panthaky, but no ADMIN_PHONES is set, so nobody was told", user.id)
        return 0
    admins = (await db.execute(select(User.id).where(User.phone.in_(phones)))).scalars().all()
    for uid in admins:
        await reminders.notify(
            db, uid, KIND_CLAIM, "A mobed says they are the panthaky",
            f"{user.name} ({user.phone}) says they are the panthaky of {agyary.name}. "
            "Confirm it or not on the Mobeds page.",
            link=MOBEDS_LINK, now=now, ttl=CLAIM_TTL,
        )
    return len(admins)


def why_no_claim(membership: AgyaryUser) -> str:
    """Why this membership cannot say "panthaky" now, in words for the mobed."""
    if waiting(membership):
        return "You have already told us. The admin will check it."
    if membership.role == ROLE_PANTHAKY:
        return "You are already the panthaky here."
    if membership.role != ROLE_MOBED:
        return "Your role here is set by the admin."
    if membership.claim_decision is not None:
        return "The admin has already decided this. Please get in touch if it is wrong."
    return "You told us you are a mobed here. Please get in touch with the admin if that has changed."


async def claim_panthaky(
    db: AsyncSession, membership: AgyaryUser, *, now: datetime | None = None
) -> None:
    """From Settings: a mobed who has said nothing yet says they are the
    panthaky here. Still only a claim; ClaimError if they cannot say it now."""
    if not may_claim(membership):
        raise ClaimError(why_no_claim(membership))
    await record_claim(db, membership, ROLE_PANTHAKY, now=now)


async def withdraw_claim(db: AsyncSession, membership: AgyaryUser) -> None:
    """Take back a panthaky claim no admin has decided on yet. They are then as
    if they had never answered, and Settings asks them again."""
    if not waiting(membership):
        raise ClaimError("There is no panthaky claim waiting to take back.")
    membership.claimed_role = None
    membership.claimed_at = None
    await db.flush()
    logger.info("User %s took back their panthaky claim at fire temple %s", membership.user_id, membership.agyary_id)


# --- The owner's decision (Admin -> Mobeds) -----------------------------------
async def _decided(
    db: AsyncSession, membership: AgyaryUser, decision: str, admin: User, now: datetime | None
) -> None:
    membership.claim_decision = decision
    membership.claim_decided_at = now or _now()
    membership.claim_decided_by_user_id = admin.id
    await db.flush()


async def confirm(
    db: AsyncSession, membership: AgyaryUser, agyary: Agyary, admin: User, *, now: datetime | None = None
) -> None:
    """Make them the panthaky here: role = panthaky, with every power that role
    already has (D7). For someone who says they are the panthaky - waiting, or
    turned down or removed before, so an admin can correct themselves."""
    if membership.role != ROLE_MOBED or membership.claimed_role != ROLE_PANTHAKY:
        raise ClaimError("Only a mobed who says they are the panthaky can be confirmed as panthaky.")
    membership.role = ROLE_PANTHAKY
    # The owner's word that they are its panthaky confirms them for its prayer
    # requests too (D10, 22 Nov 2026), so made a mobed again later they stay one
    # of its mobeds rather than waiting to be confirmed.
    if membership.requests_confirmed_at is None:
        membership.requests_confirmed_at = now or _now()
        membership.requests_confirmed_by_user_id = admin.id
    await _decided(db, membership, CLAIM_CONFIRMED, admin, now)
    await reminders.notify(
        db, membership.user_id, KIND_DECISION, f"You are the panthaky of {agyary.name}",
        f"The admin confirmed it. You now see every machi at {agyary.name}.",
        link="#/menu", now=now, ttl=CLAIM_TTL,
    )
    logger.warning(
        "Admin %s confirmed user %s as panthaky of fire temple %s", admin.id, membership.user_id, agyary.id
    )


async def decline(
    db: AsyncSession, membership: AgyaryUser, agyary: Agyary, admin: User, *, now: datetime | None = None
) -> None:
    """Not the panthaky: they stay a mobed, and the decision is kept."""
    if not waiting(membership):
        raise ClaimError("There is no panthaky claim waiting here.")
    await _decided(db, membership, CLAIM_DECLINED, admin, now)
    await reminders.notify(
        db, membership.user_id, KIND_DECISION, "Not confirmed as panthaky",
        f"The admin did not confirm you as the panthaky of {agyary.name}. You stay a mobed there, and "
        "nothing else changes. If this is wrong, please get in touch.",
        link="#/menu", now=now, ttl=CLAIM_TTL,
    )
    logger.warning(
        "Admin %s said user %s is not the panthaky of fire temple %s", admin.id, membership.user_id, agyary.id
    )


async def remove(
    db: AsyncSession, membership: AgyaryUser, agyary: Agyary, admin: User, *, now: datetime | None = None
) -> None:
    """A panthaky made a mobed again: back to seeing only their own machis."""
    if membership.role != ROLE_PANTHAKY:
        raise ClaimError("They are not the panthaky here.")
    membership.role = ROLE_MOBED
    await _decided(db, membership, CLAIM_REMOVED, admin, now)
    await reminders.notify(
        db, membership.user_id, KIND_DECISION, f"No longer the panthaky of {agyary.name}",
        f"The admin has made you a mobed at {agyary.name} again. You see only your own machis there.",
        link="#/menu", now=now, ttl=CLAIM_TTL,
    )
    logger.warning(
        "Admin %s removed user %s as panthaky of fire temple %s", admin.id, membership.user_id, agyary.id
    )


# --- Who counts for a fire temple's prayer requests (D10, owner 22 Nov 2026) ----
# Joining another agyari needs its panthaky's confirmation. A membership is
# there for Settings, machis (D7) and the mobed's own behdins (D1.4, D2) as it
# always was, but for prayer requests only once it is confirmed and not taken
# off the list. This is the one rule; everything that lists a fire temple's
# mobeds for its requests reads it (request recipients, ask everyone and the
# safety net, the board and the Mobeds page, answering in the app, a standby
# asked again, the books at All set, the Requests tab's count).
REQUESTS_CONFIRMED, REQUESTS_WAITING, REQUESTS_OFF = "confirmed", "waiting", "off"


def counts_for_requests(settings: Settings, membership: AgyaryUser, user: User) -> bool:
    """Whether ``membership`` (of ``user``) is one of its fire temple's mobeds
    for prayer requests: an active membership that is its confirmed panthaky
    (role panthaky, which only the owner's confirmation sets), or one that is
    confirmed (the admin's approval of the sign-up, the panthaky or the admin
    on a Mobeds page, the migration for those from before) and not taken off
    the list. An admin (ADMIN_PHONES) is confirmed wherever they are a member.
    Access (D9) is the caller's to check, as before."""
    if not membership.is_active:
        return False
    if membership.role == ROLE_PANTHAKY:
        return True
    if membership.requests_off_at is not None:
        return False
    return membership.requests_confirmed_at is not None or guardrails.is_admin(settings, user.phone)


def request_state(settings: Settings, membership: AgyaryUser, user: User) -> str:
    """For the Mobeds pages: "confirmed" (counts_for_requests), "off" (taken
    off the list) or "waiting" (joined, not confirmed yet)."""
    if counts_for_requests(settings, membership, user):
        return REQUESTS_CONFIRMED
    return REQUESTS_OFF if membership.requests_off_at is not None else REQUESTS_WAITING


def counts_clause(settings: Settings):
    """counts_for_requests in SQL, for a query that joins agyary_users and
    users (the membership's is_active is the query's own)."""
    confirmed = AgyaryUser.requests_confirmed_at.is_not(None)
    admins = guardrails.admin_phones(settings)
    if admins:
        confirmed = or_(confirmed, User.phone.in_(admins))
    return or_(AgyaryUser.role == ROLE_PANTHAKY, and_(AgyaryUser.requests_off_at.is_(None), confirmed))


async def is_request_member(db: AsyncSession, settings: Settings, agyary_id: int, user_id: int) -> bool:
    """Whether this account is one of the fire temple's mobeds for its prayer
    requests now (counts_for_requests; the account itself still there)."""
    row = (await db.execute(
        select(AgyaryUser, User).join(User, User.id == AgyaryUser.user_id)
        .where(AgyaryUser.agyary_id == agyary_id, AgyaryUser.user_id == user_id)
    )).first()
    return row is not None and row[1].is_active and counts_for_requests(settings, row[0], row[1])


# --- Who a fire temple's requests go to (D10; used from Step 4) ----------------
async def _members(db: AsyncSession, settings: Settings, agyary_id: int, role: str) -> list[User]:
    """Active members of ``agyary_id`` with ``role`` who count for its
    requests (counts_for_requests) and whose access is on (D9: nothing goes
    to an account that is not on), oldest member first."""
    rows = (
        await db.execute(
            select(User)
            .join(AgyaryUser, AgyaryUser.user_id == User.id)
            .where(
                AgyaryUser.agyary_id == agyary_id,
                AgyaryUser.role == role,
                AgyaryUser.is_active.is_(True),
                User.is_active.is_(True),
                counts_clause(settings),
            )
            .order_by(AgyaryUser.joined_at, User.id)
        )
    ).scalars().all()
    from agyary.services import mobed_access   # here: mobed_access imports this module

    return [u for u in rows if mobed_access.has_access(settings, u)]


async def panthakys_of(db: AsyncSession, settings: Settings, agyary_id: int) -> list[User]:
    """The fire temple's confirmed panthakys: role panthaky (which only the
    owner's confirmation, or the seed, sets - never a claim), an active
    membership, and access on."""
    return await _members(db, settings, agyary_id, ROLE_PANTHAKY)


async def request_recipients(db: AsyncSession, settings: Settings, agyary_id: int) -> list[User]:
    """Who a request to this fire temple goes to: its confirmed panthakys, or
    if it has none whose access is on, its mobeds whose access is on and who
    are confirmed for its requests (with none, nobody: the fire temple has
    nobody in the app for requests). A claim to be panthaky changes nothing
    here until it is confirmed."""
    return await panthakys_of(db, settings, agyary_id) or await _members(db, settings, agyary_id, ROLE_MOBED)


# Whether a fire temple can be reached at all, for the manager's list (Step 4),
# by the same rule as request_recipients: "panthaky" (a confirmed panthaky whose
# access is on), else "mobeds" (approved mobeds confirmed for its requests
# only), else "nobody" in the app.
REACH_PANTHAKY, REACH_MOBEDS, REACH_NOBODY = "panthaky", "mobeds", "nobody"


async def reach_of(db: AsyncSession, settings: Settings, agyary_ids) -> dict[int, str]:
    """For each fire temple in ``agyary_ids``, who a request to it would reach."""
    from agyary.services import mobed_access   # here: mobed_access imports this module

    ids = list(agyary_ids)
    out = {i: REACH_NOBODY for i in ids}
    if not ids:
        return out
    rows = (
        await db.execute(
            select(AgyaryUser.agyary_id, AgyaryUser.role, User)
            .join(User, User.id == AgyaryUser.user_id)
            .where(
                AgyaryUser.agyary_id.in_(ids),
                AgyaryUser.role.in_((ROLE_PANTHAKY, ROLE_MOBED)),
                AgyaryUser.is_active.is_(True),
                User.is_active.is_(True),
                counts_clause(settings),
            )
        )
    ).all()
    for agyary_id, role, user in rows:
        if not mobed_access.has_access(settings, user):
            continue
        if role == ROLE_PANTHAKY:
            out[agyary_id] = REACH_PANTHAKY
        elif out[agyary_id] == REACH_NOBODY:
            out[agyary_id] = REACH_MOBEDS
    return out
