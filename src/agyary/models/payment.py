from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import PAYMENT_METHODS, PAYMENT_STATUSES, sql_in


class Payment(Base):
    """Records money flow from customer to agyary. NOT a payment gateway:
    the system generates UPI intent links to the agyary's own VPA and the
    panthaky marks receipt manually. Never touches the money."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customers.id"))

    machi_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("machis.id"))
    booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.id"))

    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    method: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), server_default="pending")

    upi_intent_link: Mapped[str | None] = mapped_column(Text)
    upi_transaction_ref: Mapped[str | None] = mapped_column(String(100))

    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("num_nonnulls(machi_id, booking_id) = 1", name="exactly_one_parent"),
        CheckConstraint(f"method IN ({sql_in(PAYMENT_METHODS)})", name="method"),
        CheckConstraint(f"status IN ({sql_in(PAYMENT_STATUSES)})", name="status"),
        Index("idx_payments_agyary_status", "agyary_id", "status"),
        Index("idx_payments_customer", "customer_id"),
        Index("idx_payments_machi", "machi_id", postgresql_where=text("machi_id IS NOT NULL")),
        Index(
            "idx_payments_booking", "booking_id", postgresql_where=text("booking_id IS NOT NULL")
        ),
        Index("idx_payments_date", "agyary_id", "created_at"),
    )
