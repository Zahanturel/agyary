"""How a prayer request from a funeral place reaches a fire temple (DECISIONS
D10, changed 21 Nov 2026; R3.1 step 1), chosen by its confirmed panthaky, or
the admin, on Settings -> Prayer requests.

- "everyone" (Everyone at once, the default and what was live before): the
  moment a funeral place sends, every mobed on the fire temple's list who can
  be messaged is asked on WhatsApp.
- "panthaky_first" (Come to me first): only the panthaky is told, and they
  choose how to find mobeds. The safety net: if they have not acted in 15, 30
  or 60 minutes, all the mobeds are asked; Never (None) is the default.

The minutes are kept whatever the way, so switching back keeps the panthaky's
last choice; they matter only in "panthaky_first". Who may read or change it
is prayer_callout.may_manage, checked by the route. Which way a request takes
is way_for (step 2), read by prayer_callout.after_send at Send.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import Agyary, User
from agyary.models.enums import (
    REQUEST_ESCALATE_MINUTES,
    REQUEST_MODE_EVERYONE,
    REQUEST_MODE_PANTHAKY_FIRST,
    REQUEST_MODES,
)
from agyary.services import panthaky

logger = logging.getLogger(__name__)

NO_MODE = "Please choose how requests reach your agyari: Everyone at once, or Come to me first."
NO_MINUTES = "The safety net can be Never, 15 minutes, 30 minutes or 1 hour."


class SettingsError(ValueError):
    """A value that cannot be saved; the message is for the panthaky, and
    ``field`` names what is wrong."""

    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.field = field


def read(agyary: Agyary) -> dict:
    return {"mode": agyary.request_mode or REQUEST_MODE_EVERYONE,
            "escalate_minutes": agyary.request_escalate_minutes}


async def way_for(db: AsyncSession, settings: Settings, agyary: Agyary) -> str:
    """Which way a request to ``agyary`` takes now: "panthaky_first" only when
    its panthaky chose Come to me first and it has a confirmed panthaky whose
    access is on (panthaky.panthakys_of: someone to choose who to ask);
    otherwise "everyone", whatever the setting (D10, 21 Nov 2026: a fire
    temple with no panthaky in the app is Everyone at once)."""
    if (agyary.request_mode or REQUEST_MODE_EVERYONE) != REQUEST_MODE_PANTHAKY_FIRST:
        return REQUEST_MODE_EVERYONE
    if not await panthaky.panthakys_of(db, settings, agyary.id):
        return REQUEST_MODE_EVERYONE
    return REQUEST_MODE_PANTHAKY_FIRST


def change(agyary: Agyary, user: User, *, mode: object, escalate_minutes: object) -> dict:
    """Set both, as given (not committed). A way that is not one of the two,
    or minutes that are not None, 15, 30 or 60, are refused in plain words;
    true and false are not minutes, nor is "15" or 15.0."""
    if not isinstance(mode, str) or mode not in REQUEST_MODES:
        raise SettingsError(NO_MODE, "mode")
    if escalate_minutes is not None and (
        type(escalate_minutes) is not int or escalate_minutes not in REQUEST_ESCALATE_MINUTES
    ):
        raise SettingsError(NO_MINUTES, "escalate_minutes")
    agyary.request_mode, agyary.request_escalate_minutes = mode, escalate_minutes
    logger.info("Fire temple %s: prayer requests %s, safety net %s, set by user %s",
                agyary.id, mode, escalate_minutes or "never", user.id)
    return read(agyary)
