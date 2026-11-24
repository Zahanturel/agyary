"""A person's ask to an agyari for a service (R4.2, 25 Nov 2026).

The person asks, the agyari's panthaky accepts or rejects. Until accepted the
panthaky reads the ask with the person's FIRST name only: the number is shared
at accept, never before (DECISIONS D2). The row belongs to the person's account
and goes with it (ON DELETE CASCADE; services/account.py and services/erasure.py
say so in plain SQL). What an accept makes in the panthaky's own diary (the
booking, the machi, the repeating series, the memorial) is that panthaky's own
record and stays when the ask goes (D6); the ``result_*`` links are only
pointers and are cleared if that record is deleted.

A memorial ask holds a SNAPSHOT of the person's memorial choices (not a link
the panthaky could follow into the person's own memorials): nothing a panthaky
or admin screen reads leads into the person's private tables.
"""

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import ASK_KINDS, ASK_PURPOSES, ASK_STATUSES, ASK_VENUES, sql_in


class ServiceAsk(Base):
    __tablename__ = "service_asks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("services.id"))

    kind: Mapped[str] = mapped_column(String(10), server_default="single")
    purpose: Mapped[str] = mapped_column(String(20))

    # The day (of a memorial ask: the first chosen date) and, for a slot service (Machi), the geh,
    # or for any other service the time of day.
    ceremony_date: Mapped[date] = mapped_column(Date)
    geh: Mapped[int | None] = mapped_column(SmallInteger)
    ceremony_time: Mapped[time | None] = mapped_column(Time)

    # At the agyari, or at the person's home (area only, never an address).
    venue: Mapped[str] = mapped_column(String(10), server_default="agyari")
    area: Mapped[str | None] = mapped_column(String(100))

    # The names to pray, in the shape of a ceremony's names (section, title, name, status, pair_group).
    names: Mapped[list] = mapped_column(JSONB, server_default="[]")
    note: Mapped[str | None] = mapped_column(String(200))

    # A repeating ask: "monthly" or "yearly" and how many times in all (None: no end).
    repeat_pattern: Mapped[str | None] = mapped_column(String(10))
    repeat_count: Mapped[int | None] = mapped_column(SmallInteger)

    # A memorial ask: the person's choices as they were when asking, and the codes of the chosen dates.
    memorial_choice: Mapped[dict | None] = mapped_column(JSONB)
    memorial_codes: Mapped[list | None] = mapped_column(JSONB)

    status: Mapped[str] = mapped_column(String(10), server_default="waiting")
    reject_reason: Mapped[str | None] = mapped_column(String(100))
    # Told "No answer yet" once, after 24 hours. The ask stays waiting.
    no_answer_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # What accepting made, in the panthaky's own book.
    result_booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="SET NULL"))
    result_machi_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("machis.id", ondelete="SET NULL"))
    result_memorial_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("memorials.id", ondelete="SET NULL"))
    result_customer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("customers.id", ondelete="SET NULL"))

    copied_from_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("service_asks.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"kind IN ({sql_in(ASK_KINDS)})", name="kind"),
        CheckConstraint(f"status IN ({sql_in(ASK_STATUSES)})", name="status"),
        CheckConstraint(f"purpose IN ({sql_in(ASK_PURPOSES)})", name="purpose"),
        CheckConstraint(f"venue IN ({sql_in(ASK_VENUES)})", name="venue"),
        CheckConstraint("geh IS NULL OR geh BETWEEN 1 AND 5", name="geh"),
        CheckConstraint("kind = 'memorial' OR num_nonnulls(geh, ceremony_time) = 1", name="geh_or_time"),
        CheckConstraint("kind = 'memorial' OR (memorial_choice IS NULL AND memorial_codes IS NULL)", name="memorial_only"),
        CheckConstraint("(kind = 'repeating') = (repeat_pattern IS NOT NULL)", name="repeat_pattern"),
        CheckConstraint("repeat_pattern IS NULL OR repeat_pattern IN ('monthly', 'yearly')", name="repeat_pattern_value"),
        Index("idx_service_asks_user", "user_id", text("created_at DESC")),
        Index("idx_service_asks_agyary_status", "agyary_id", "status", "created_at"),
        Index(
            "idx_service_asks_no_answer",
            "created_at",
            postgresql_where=text("status = 'waiting' AND no_answer_alert_at IS NULL"),
        ),
    )
