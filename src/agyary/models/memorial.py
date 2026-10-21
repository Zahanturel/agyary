from datetime import date, datetime
from datetime import time as dt_time

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agyary.calendar.memorial import OPENINGS, PARABS
from agyary.core.database import Base
from agyary.models.enums import CALENDAR_SYSTEMS, sql_in


class Memorial(Base):
    """The observances a family keeps for one departed person.

    Holds exactly what the mobed chose (opening, named days, how long each
    repeating series runs) as well as the schedule that came out of it, so a
    memorial can be shown, audited and re-derived. Whether it is still
    running is not stored: with no scheduler to flip a flag, it is simply
    whether any observance is still ahead of today.

    Scoped to the mobed who made it, like their behdin book - a memorial
    names a family's dead, which is not a colleague's to read.
    """

    __tablename__ = "memorials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customers.id"))
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))

    departed_name: Mapped[str] = mapped_column(String(200))

    # The death, as the mobed gave it (Gregorian) and as it reads in the
    # calendar the schedule was counted in.
    death_gregorian: Mapped[date] = mapped_column(Date)
    death_roj: Mapped[int] = mapped_column(SmallInteger)
    death_mah: Mapped[int] = mapped_column(SmallInteger)
    death_year: Mapped[int] = mapped_column(Integer)
    calendar_system: Mapped[str] = mapped_column(String(10))

    # The choices. A series that was not chosen is NULL; one that was chosen
    # always carries its length - there is no default and no "forever".
    opening: Mapped[str] = mapped_column(String(20))
    day_counts: Mapped[list] = mapped_column(JSONB, server_default="[]")
    monthly_months: Mapped[int | None] = mapped_column(SmallInteger)
    yearly_years: Mapped[int | None] = mapped_column(SmallInteger)
    parabs: Mapped[str | None] = mapped_column(String(20))
    parab_years: Mapped[int | None] = mapped_column(SmallInteger)
    # Parabs can instead be chosen as a number of Parabs (parab_count); memorials
    # saved before that have parab_years. At most one of the two is set.
    parab_count: Mapped[int | None] = mapped_column(SmallInteger)
    # Roj Fravardin kept every month, for this many months; NULL when not chosen.
    fravardin_roj_months: Mapped[int | None] = mapped_column(SmallInteger)
    # The deceased's birthday by Roj and Mah (never a Gatha day), repeated
    # for birthday_years years; NULL when not chosen.
    birthday_roj: Mapped[int | None] = mapped_column(SmallInteger)
    birthday_mah: Mapped[int | None] = mapped_column(SmallInteger)
    birthday_years: Mapped[int | None] = mapped_column(SmallInteger)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    observances: Mapped[list["MemorialObservance"]] = relationship(
        back_populates="memorial",
        order_by="(MemorialObservance.gregorian_date, MemorialObservance.day_number)",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(f"calendar_system IN ({sql_in(CALENDAR_SYSTEMS)})", name="calendar_system"),
        CheckConstraint(f"opening IN ({sql_in(OPENINGS)})", name="opening"),
        CheckConstraint(f"parabs IS NULL OR parabs IN ({sql_in(PARABS)})", name="parabs"),
        # 13 is a Gatha day, with the Gatha number in death_roj.
        CheckConstraint("death_mah BETWEEN 1 AND 13", name="death_mah"),
        CheckConstraint("death_roj BETWEEN 1 AND 30", name="death_roj"),
        # A series and its length stand or fall together.
        CheckConstraint(
            "(parabs IS NULL) = (parab_years IS NULL AND parab_count IS NULL)", name="parab_length"
        ),
        CheckConstraint(
            "monthly_months IS NULL OR monthly_months >= 1", name="monthly_length"
        ),
        CheckConstraint("yearly_years IS NULL OR yearly_years >= 1", name="yearly_length"),
        CheckConstraint(
            "(birthday_roj IS NULL) = (birthday_mah IS NULL) AND (birthday_roj IS NULL) = (birthday_years IS NULL)",
            name="birthday_whole",
        ),
        CheckConstraint(
            "fravardin_roj_months IS NULL OR fravardin_roj_months >= 1", name="fravardin_roj_length"
        ),
        Index("idx_memorials_customer", "customer_id"),
        Index("idx_memorials_owner", "created_by_user_id", "agyary_id"),
    )


class MemorialObservance(Base):
    """One dated observance of a memorial.

    The services are a set (Afringan, Farokshi, Baaj - any of them), which
    is why this is not a booking: a booking has one service, a mobed to
    accept it and a slip, and none of that applies here. The time is
    optional and usually blank.
    """

    __tablename__ = "memorial_observances"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    memorial_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("memorials.id", ondelete="CASCADE")
    )

    # Stable identity within the memorial ("day_10", "month_3", "year_1",
    # "parab_4_1396"); the label is display only.
    code: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(60))
    day_number: Mapped[int] = mapped_column(Integer)

    gregorian_date: Mapped[date] = mapped_column(Date)
    # NULL for a literal day that falls in the Gatha days (see gatha_index).
    parsi_roj: Mapped[int | None] = mapped_column(SmallInteger)
    parsi_mah: Mapped[int | None] = mapped_column(SmallInteger)
    parsi_year: Mapped[int] = mapped_column(Integer)
    gatha_index: Mapped[int | None] = mapped_column(SmallInteger)
    # When the mobed marked that they told the family themselves. The planner
    # then sends nothing for it, so the family is not told twice.
    reminded_by_hand_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the mobed ticked this date as paid (NULL = not paid). Their own note, like
    # the one on a booking: nothing is collected or calculated.
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Time of day in IST, or NULL - the norm.
    time_of_day: Mapped[dt_time | None] = mapped_column(Time)
    notes: Mapped[str | None] = mapped_column(Text)

    memorial: Mapped[Memorial] = relationship(back_populates="observances")
    services: Mapped[list["MemorialObservanceService"]] = relationship(
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("memorial_id", "code", name="uq_memorial_observance_code"),
        Index("idx_memorial_observances_date", "gregorian_date"),
    )


class MemorialObservanceService(Base):
    __tablename__ = "memorial_observance_services"

    observance_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("memorial_observances.id", ondelete="CASCADE"), primary_key=True
    )
    service_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("services.id"), primary_key=True
    )
