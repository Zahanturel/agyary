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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import RECURRENCE_END_TYPES, RECURRENCE_PATTERNS, sql_in


class RecurrenceRule(Base):
    """How a machi/booking repeats; the daily generator materializes instances."""

    __tablename__ = "recurrence_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))

    # Source ceremony (circular FK with machis/bookings -> created via ALTER)
    source_machi_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("machis.id", use_alter=True, name="fk_recurrence_rules_source_machi"),
    )
    source_booking_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bookings.id", use_alter=True, name="fk_recurrence_rules_source_booking"),
    )

    pattern: Mapped[str] = mapped_column(String(30))
    pattern_data: Mapped[dict | None] = mapped_column(JSONB)

    end_type: Mapped[str] = mapped_column(String(20), server_default="indefinite")
    end_count: Mapped[int | None] = mapped_column(Integer)
    end_date: Mapped[date | None] = mapped_column(Date)

    last_generated_until: Mapped[date | None] = mapped_column(Date)
    generation_horizon_months: Mapped[int] = mapped_column(SmallInteger, server_default="3")

    approved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(source_machi_id, source_booking_id) = 1", name="exactly_one_source"
        ),
        CheckConstraint(f"pattern IN ({sql_in(RECURRENCE_PATTERNS)})", name="pattern"),
        CheckConstraint(f"end_type IN ({sql_in(RECURRENCE_END_TYPES)})", name="end_type"),
        Index(
            "idx_recurrence_active",
            "agyary_id",
            "is_active",
            postgresql_where=text("is_active = true"),
        ),
    )
