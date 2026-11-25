"""A person's request to a fire temple (R4.2, 25 Nov 2026; redesigned the same day).

One request = one fire temple, several items (each a prayer with its own date, time left open if the
person likes, an optional repeat; or a memorial) and the names to pray. The panthaky confirms or
declines the WHOLE request. Until confirmed the panthaky reads it with the person's FIRST name only:
the number is shared at confirm, never before (DECISIONS D2). The rows belong to the person's account
and go with it (ON DELETE CASCADE; services/account.py and services/erasure.py say so in plain SQL).
What a confirm makes in the panthaky's own diary (the booking, the machi, the repeating series, the
memorial, one per item) is that panthaky's own record and stays when the request goes (D6); the
``result_*`` links are only pointers and are cleared if that record is deleted.

A memorial item holds only what the person gave (the departed's name, the date of passing, an optional
monthly or yearly repeat); the panthaky's confirm builds the memorial with the diary's own defaults.
"""

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import ASK_ITEM_KINDS, ASK_PURPOSES, ASK_STATUSES, sql_in


class ServiceAsk(Base):
    """The request: who, to which fire temple, the names, and where it stands."""

    __tablename__ = "service_asks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))

    # The earliest day among the items (for "No answer yet" and for cancelling); a request of memorials
    # alone holds a day a month ahead.
    ceremony_date: Mapped[date] = mapped_column(Date)
    # The names to pray, typed: a list of plain strings.
    names: Mapped[list] = mapped_column(JSONB, server_default="[]")

    status: Mapped[str] = mapped_column(String(30), server_default="waiting")
    reject_reason: Mapped[str | None] = mapped_column(String(100))
    # Told "No answer yet" once, after 24 hours. The request stays waiting.
    no_answer_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The fire temple changed (or removed) an item of what this made.
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # The person's own record in the panthaky's book, made at confirm.
    result_customer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("customers.id", ondelete="SET NULL"))
    copied_from_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("service_asks.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in(ASK_STATUSES)})", name="status"),
        Index("idx_service_asks_user", "user_id", text("created_at DESC")),
        Index("idx_service_asks_agyary_status", "agyary_id", "status", "created_at"),
        Index(
            "idx_service_asks_no_answer",
            "created_at",
            postgresql_where=text("status = 'waiting' AND no_answer_alert_at IS NULL"),
        ),
    )


class ServiceAskItem(Base):
    """One prayer of a request: a service with its day (and geh or time), a repeat, or a memorial."""

    __tablename__ = "service_ask_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ask_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("service_asks.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    kind: Mapped[str] = mapped_column(String(10), server_default="single")
    # None for a memorial: the panthaky's confirm chooses its prayers.
    service_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("services.id"))
    purpose: Mapped[str | None] = mapped_column(String(20))

    # The day (of a memorial: the date of passing); for Machi the geh; otherwise a time, which may be open.
    ceremony_date: Mapped[date] = mapped_column(Date)
    geh: Mapped[int | None] = mapped_column(SmallInteger)
    ceremony_time: Mapped[time | None] = mapped_column(Time)

    # A repeating item: "monthly" or "yearly" and how many times in all (None: no end), as in "+ Add".
    repeat_pattern: Mapped[str | None] = mapped_column(String(10))
    repeat_count: Mapped[int | None] = mapped_column(SmallInteger)
    # A memorial item: {"departed_name", "death_date", "recurring", "count"} (older ones also "legacy").
    memorial_choice: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))

    # The usual price when asked (what the person saw); None when the fire temple had none (a memorial).
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    result_booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="SET NULL"))
    result_machi_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("machis.id", ondelete="SET NULL"))
    result_memorial_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("memorials.id", ondelete="SET NULL"))
    # The fire temple changed this item's day, time or geh / deleted or stopped it.
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"kind IN ({sql_in(ASK_ITEM_KINDS)})", name="kind"),
        CheckConstraint(f"purpose IS NULL OR purpose IN ({sql_in(ASK_PURPOSES)})", name="purpose"),
        CheckConstraint("geh IS NULL OR geh BETWEEN 1 AND 5", name="geh"),
        CheckConstraint("geh IS NULL OR ceremony_time IS NULL", name="geh_or_time"),
        CheckConstraint("kind = 'memorial' OR service_id IS NOT NULL", name="service"),
        CheckConstraint("kind = 'memorial' OR memorial_choice IS NULL", name="memorial_only"),
        CheckConstraint("(kind = 'repeating') = (repeat_pattern IS NOT NULL)", name="repeat_pattern"),
        CheckConstraint("repeat_pattern IS NULL OR repeat_pattern IN ('monthly', 'yearly')", name="repeat_pattern_value"),
        Index("idx_service_ask_items_ask", "ask_id"),
    )
