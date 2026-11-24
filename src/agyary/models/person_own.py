"""What a person keeps for themselves in the behdin app (R4.1, 25 Nov 2026).

My agyari, the memorials of the person's own departed and their own events.
Private to the one account (DECISIONS D2, D6): every row hangs off ``user_id``
and goes with the account (ON DELETE CASCADE, and explicitly in
services/account.py and services/erasure.py). No mobed, fire temple or admin
screen reads these tables, and nothing outside ``api/routes/behdin_me.py`` and
``services/behdin_me.py`` imports this module (a test holds that).

The memorial rows mirror the mobed side's ``Memorial`` and its dates, minus
everything that belongs to a fire temple's book: the agyari, the family record,
who made it, paid and reminded. The schedule itself is the same engine's.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agyary.calendar.memorial import OPENINGS, PARABS
from agyary.core.database import Base
from agyary.models.enums import CALENDAR_SYSTEMS, EVENT_KINDS, EVENT_REPEATS, sql_in


class PersonAgyari(Base):
    """The agyari a person calls theirs: one row per person, changed freely."""

    __tablename__ = "person_agyari"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    chosen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PersonMemorial(Base):
    __tablename__ = "person_memorials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))

    # The name as the person gave it, or "(name not known)". Never copied anywhere else.
    departed_name: Mapped[str] = mapped_column(String(200))

    death_gregorian: Mapped[date] = mapped_column(Date)
    death_roj: Mapped[int] = mapped_column(SmallInteger)
    death_mah: Mapped[int] = mapped_column(SmallInteger)
    death_year: Mapped[int] = mapped_column(Integer)
    died_over_a_year_ago: Mapped[bool] = mapped_column(Boolean, server_default="false")
    calendar_system: Mapped[str] = mapped_column(String(10))

    opening: Mapped[str] = mapped_column(String(20))
    day_counts: Mapped[list] = mapped_column(JSONB, server_default="[]")
    monthly_months: Mapped[int | None] = mapped_column(SmallInteger)
    yearly_years: Mapped[int | None] = mapped_column(SmallInteger)
    parabs: Mapped[str | None] = mapped_column(String(20))
    parab_years: Mapped[int | None] = mapped_column(SmallInteger)
    parab_count: Mapped[int | None] = mapped_column(SmallInteger)
    fravardin_roj_months: Mapped[int | None] = mapped_column(SmallInteger)
    birthday_roj: Mapped[int | None] = mapped_column(SmallInteger)
    birthday_mah: Mapped[int | None] = mapped_column(SmallInteger)
    birthday_years: Mapped[int | None] = mapped_column(SmallInteger)
    start_from: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    observances: Mapped[list["PersonMemorialObservance"]] = relationship(
        back_populates="memorial",
        order_by="(PersonMemorialObservance.gregorian_date, PersonMemorialObservance.day_number)",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(f"calendar_system IN ({sql_in(CALENDAR_SYSTEMS)})", name="calendar_system"),
        CheckConstraint(f"opening IN ({sql_in(OPENINGS)})", name="opening"),
        CheckConstraint(f"parabs IS NULL OR parabs IN ({sql_in(PARABS)})", name="parabs"),
        CheckConstraint("death_mah BETWEEN 1 AND 13", name="death_mah"),
        CheckConstraint("death_roj BETWEEN 1 AND 30", name="death_roj"),
        CheckConstraint(
            "(parabs IS NULL) = (parab_years IS NULL AND parab_count IS NULL)", name="parab_length"
        ),
        CheckConstraint("monthly_months IS NULL OR monthly_months >= 1", name="monthly_length"),
        CheckConstraint("yearly_years IS NULL OR yearly_years >= 1", name="yearly_length"),
        CheckConstraint(
            "(birthday_roj IS NULL) = (birthday_mah IS NULL) AND (birthday_roj IS NULL) = (birthday_years IS NULL)",
            name="birthday_whole",
        ),
        CheckConstraint(
            "fravardin_roj_months IS NULL OR fravardin_roj_months >= 1", name="fravardin_roj_length"
        ),
        Index("idx_person_memorials_user", "user_id"),
    )


class PersonMemorialObservance(Base):
    """One dated observance of a person's memorial (the engine's output, as stored)."""

    __tablename__ = "person_memorial_observances"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    memorial_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("person_memorials.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))

    code: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(60))
    day_number: Mapped[int] = mapped_column(Integer)
    gregorian_date: Mapped[date] = mapped_column(Date)
    parsi_roj: Mapped[int | None] = mapped_column(SmallInteger)
    parsi_mah: Mapped[int | None] = mapped_column(SmallInteger)
    parsi_year: Mapped[int] = mapped_column(Integer)
    gatha_index: Mapped[int | None] = mapped_column(SmallInteger)

    memorial: Mapped[PersonMemorial] = relationship(back_populates="observances")

    __table_args__ = (
        UniqueConstraint("memorial_id", "code", name="uq_person_memorial_observance_code"),
        Index("idx_person_memorial_observances_user_date", "user_id", "gregorian_date"),
    )


class PersonEvent(Base):
    """A date the person keeps for themselves: a birthday, a navjote, an anniversary."""

    __tablename__ = "person_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    gregorian_date: Mapped[date] = mapped_column(Date)
    repeats: Mapped[str] = mapped_column(String(20), server_default="none")
    # Set when it repeats by Parsi date: that day's Roj and Mah in ``parsi_calendar`` (Mah 13 is a
    # Gatha day, the Gatha number in the Roj, as everywhere else).
    parsi_roj: Mapped[int | None] = mapped_column(SmallInteger)
    parsi_mah: Mapped[int | None] = mapped_column(SmallInteger)
    parsi_calendar: Mapped[str | None] = mapped_column(String(10))
    notes: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"kind IN ({sql_in(EVENT_KINDS)})", name="kind"),
        CheckConstraint(f"repeats IN ({sql_in(EVENT_REPEATS)})", name="repeats"),
        CheckConstraint(
            "(repeats = 'yearly_parsi') = (parsi_roj IS NOT NULL AND parsi_mah IS NOT NULL"
            " AND parsi_calendar IS NOT NULL)",
            name="parsi_day",
        ),
        CheckConstraint(f"parsi_calendar IS NULL OR parsi_calendar IN ({sql_in(CALENDAR_SYSTEMS)})",
                        name="parsi_calendar"),
        Index("idx_person_events_user", "user_id"),
    )
