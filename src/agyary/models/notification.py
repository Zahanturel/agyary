from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import NOTIFICATION_STATUSES, RECIPIENT_TYPES, sql_in


class Notification(Base):
    """Outbound notification queue; the engine polls, sends via WhatsApp, updates status."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))

    recipient_phone: Mapped[str] = mapped_column(String(20))
    recipient_type: Mapped[str] = mapped_column(String(10))  # 'user' | 'customer'
    recipient_id: Mapped[int] = mapped_column(BigInteger)

    notification_type: Mapped[str] = mapped_column(String(50))
    template_name: Mapped[str] = mapped_column(String(100))
    template_params: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    machi_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("machis.id"))
    booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.id"))

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wa_message_id: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"recipient_type IN ({sql_in(RECIPIENT_TYPES)})", name="recipient_type"),
        CheckConstraint(f"status IN ({sql_in(NOTIFICATION_STATUSES)})", name="status"),
        Index(
            "idx_notifications_queue",
            "scheduled_at",
            "status",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("idx_notifications_agyary", "agyary_id", text("created_at DESC")),
        Index(
            "idx_notifications_wa_message",
            "wa_message_id",
            postgresql_where=text("wa_message_id IS NOT NULL"),
        ),
    )
