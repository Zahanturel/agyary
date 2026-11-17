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
from agyary.models.enums import CLAIMED_ROLES, ROLE_MOBED, ROLE_PANTHAKY
from agyary.services import guardrails, reminders

logger = logging.getLogger(__name__)

KIND_CLAIM = "panthaky_claim"
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
