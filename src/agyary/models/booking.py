from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agyary.core.database import Base
from agyary.models.enums import (
    BOOKING_MOBED_STATUSES,
    BOOKING_PURPOSES,
    CEREMONY_STATUSES,
    PAYMENT_METHODS,
    PAYMENT_STATUSES,
    sql_in,
)


class Booking(Base):
    """All non-machi services. Time-based, not slot-based.

    ``ceremony_datetime`` mirrors ``date_time`` for normal services and holds
    the actual physical start for overnight ones (e.g. Vandidad).
    """

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("services.id"))
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customers.id"))

    date_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ceremony_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Parsi date stored alongside for display
    parsi_roj: Mapped[int] = mapped_column(SmallInteger)
    parsi_mah: Mapped[int] = mapped_column(SmallInteger)
    parsi_year: Mapped[int] = mapped_column(Integer)
    calendar_system: Mapped[str] = mapped_column(String(10))

    purpose: Mapped[str] = mapped_column(String(20))  # gujrela_nu | khushali_nu | hama_anjuman

    location: Mapped[str | None] = mapped_column(Text)
    is_offsite: Mapped[bool] = mapped_column(Boolean, server_default="false")

    status: Mapped[str] = mapped_column(String(20), server_default="requested")

    recurrence_rule_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("recurrence_rules.id", use_alter=True, name="fk_bookings_recurrence_rule"),
    )
    is_recurring_instance: Mapped[bool] = mapped_column(Boolean, server_default="false")

    bulk_batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bulk_batches.id"))

    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    payment_status: Mapped[str] = mapped_column(String(20), server_default="pending")
    payment_method: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    customer: Mapped["Customer"] = relationship()  # noqa: F821
    service: Mapped["Service"] = relationship()  # noqa: F821
    names: Mapped[list["CeremonyName"]] = relationship(  # noqa: F821
        back_populates="booking",
        order_by="CeremonyName.display_order",
        cascade="all, delete-orphan",
    )
    mobeds: Mapped[list["BookingMobed"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("parsi_roj BETWEEN 1 AND 30", name="parsi_roj"),
        CheckConstraint("parsi_mah BETWEEN 1 AND 13", name="parsi_mah"),
        CheckConstraint(f"purpose IN ({sql_in(BOOKING_PURPOSES)})", name="purpose"),
        CheckConstraint(f"status IN ({sql_in(CEREMONY_STATUSES)})", name="status"),
        CheckConstraint(f"payment_status IN ({sql_in(PAYMENT_STATUSES)})", name="payment_status"),
        CheckConstraint(
            f"payment_method IS NULL OR payment_method IN ({sql_in(PAYMENT_METHODS)})",
            name="payment_method",
        ),
        Index("idx_bookings_agyary_date", "agyary_id", "date_time"),
        Index("idx_bookings_agyary_ceremony_datetime", "agyary_id", "ceremony_datetime"),
        Index(
            "idx_bookings_pending",
            "agyary_id",
            "status",
            postgresql_where=text("status = 'requested'"),
        ),
        Index("idx_bookings_customer", "customer_id", text("date_time DESC")),
        Index("idx_bookings_service", "service_id", "date_time"),
        Index(
            "idx_bookings_recurrence",
            "recurrence_rule_id",
            postgresql_where=text("recurrence_rule_id IS NOT NULL"),
        ),
        Index(
            "idx_bookings_bulk",
            "bulk_batch_id",
            postgresql_where=text("bulk_batch_id IS NOT NULL"),
        ),
    )


class BookingMobed(Base):
    """Mobed assignments per booking; yazeshni needs 2 (Jyoti + Rathvi)."""

    __tablename__ = "booking_mobeds"

    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    mobed_role: Mapped[str | None] = mapped_column(String(30))  # 'jyoti' | 'rathvi' | NULL
    status: Mapped[str] = mapped_column(String(20), server_default="assigned")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    is_paid: Mapped[bool] = mapped_column(Boolean, server_default="false")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    booking: Mapped[Booking] = relationship(back_populates="mobeds")

    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in(BOOKING_MOBED_STATUSES)})", name="status"),
        Index("idx_booking_mobeds_user", "user_id"),
    )
