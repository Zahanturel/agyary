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

from sqlalchemy import select
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


# --- Who a fire temple's requests go to (D10; used from Step 4) ----------------
async def _members(db: AsyncSession, settings: Settings, agyary_id: int, role: str) -> list[User]:
    """Active members of ``agyary_id`` with ``role`` whose access is on (D9:
    nothing goes to an account that is not on), oldest member first."""
    rows = (
        await db.execute(
            select(User)
            .join(AgyaryUser, AgyaryUser.user_id == User.id)
            .where(
                AgyaryUser.agyary_id == agyary_id,
                AgyaryUser.role == role,
                AgyaryUser.is_active.is_(True),
                User.is_active.is_(True),
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
    if it has none whose access is on, its mobeds whose access is on. A claim
    to be panthaky changes nothing here until it is confirmed."""
    return await panthakys_of(db, settings, agyary_id) or await _members(db, settings, agyary_id, ROLE_MOBED)
