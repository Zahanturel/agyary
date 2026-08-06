from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import (
    CALENDAR_SYSTEMS,
    DEFAULT_DISPLAY_LANGUAGE,
    DEFAULT_SECONDARY_CALENDAR_SYSTEM,
    DEFAULT_VISIBLE_CALENDAR_SYSTEMS,
    DISPLAY_CALENDAR_SYSTEMS,
    DISPLAY_LANGUAGES,
    sql_in,
)


class UserPreferences(Base):
    """How one person wants their own screen to read.

    A separate table rather than columns on ``users`` because the two
    answer different questions. ``users`` is an identity shared with the
    WhatsApp side - a phone number and a name that other people's
    notifications are addressed to. This is display chrome that only its
    owner ever sees, it will keep growing as the UI does, and a missing row
    is a perfectly good "hasn't chosen anything yet" (the API serves the
    defaults below and writes a row only when someone actually picks
    something).

    Emphatically NOT related to ``Agyary.calendar_system``. That field
    decides which Parsi reckoning gets stamped onto a ceremony record and
    is part of the historical record - it must not move because someone
    toggled a display option. This decides which columns a calendar shows.
    """

    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    # Which calendars are shown side by side. Gregorian + Shenshai by
    # default; Kadmi and Fasli are the toggleable extras.
    visible_calendar_systems: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)),
        server_default=text("ARRAY['gregorian','shenshai']::varchar[]"),
    )
    # Which Parsi system the Roj/Mah reading defaults to. Gregorian isn't a
    # candidate here - it's the other half of the pair, not the secondary.
    default_secondary_system: Mapped[str] = mapped_column(
        String(10), server_default=DEFAULT_SECONDARY_CALENDAR_SYSTEM
    )
    display_language: Mapped[str] = mapped_column(
        String(10), server_default=DEFAULT_DISPLAY_LANGUAGE
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Array membership enforced in the database as well as the request
        # model, so a bad value can't arrive through a script or a fixture
        # and then crash whichever screen tries to render it.
        CheckConstraint(
            "visible_calendar_systems <@ ARRAY["
            + ",".join(f"'{s}'" for s in DISPLAY_CALENDAR_SYSTEMS)
            + "]::varchar[]",
            name="visible_calendar_systems",
        ),
        CheckConstraint("array_length(visible_calendar_systems, 1) >= 1", name="at_least_one_visible"),
        CheckConstraint(
            f"default_secondary_system IN ({sql_in(CALENDAR_SYSTEMS)})",
            name="default_secondary_system",
        ),
        CheckConstraint(f"display_language IN ({sql_in(DISPLAY_LANGUAGES)})", name="display_language"),
    )


def default_preferences() -> dict:
    """What a user who has never opened Settings sees. Kept next to the
    model so the API's absent-row response and the column server_defaults
    can't drift apart."""
    return {
        "visible_calendar_systems": list(DEFAULT_VISIBLE_CALENDAR_SYSTEMS),
        "default_secondary_system": DEFAULT_SECONDARY_CALENDAR_SYSTEM,
        "display_language": DEFAULT_DISPLAY_LANGUAGE,
    }
