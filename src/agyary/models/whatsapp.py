from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import MESSAGE_DIRECTIONS, sql_in


class WhatsAppMessage(Base):
    """Audit log of all message traffic, both directions.

    In the web-chat simulator the same table logs simulated traffic, so the
    future WhatsApp transport adapter inherits a working audit trail.
    """

    __tablename__ = "whatsapp_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    direction: Mapped[str] = mapped_column(String(10))

    wa_phone: Mapped[str] = mapped_column(String(20))  # counterparty phone
    customer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("customers.id"))

    wa_message_id: Mapped[str | None] = mapped_column(String(100))
    wa_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    message_type: Mapped[str] = mapped_column(String(20))
    content: Mapped[dict | None] = mapped_column(JSONB)  # raw payload
    template_name: Mapped[str | None] = mapped_column(String(100))

    status: Mapped[str | None] = mapped_column(String(20))  # outbound delivery status

    # Send-worker bookkeeping (outbound rows only): status pending -> sent |
    # failed, retried with backoff via next_attempt_at until attempts runs out.
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"direction IN ({sql_in(MESSAGE_DIRECTIONS)})", name="direction"),
        Index("idx_wa_messages_agyary_phone", "agyary_id", "wa_phone", text("created_at DESC")),
        Index(
            "idx_wa_messages_wa_id",
            "wa_message_id",
            postgresql_where=text("wa_message_id IS NOT NULL"),
        ),
        Index(
            "idx_wa_messages_outbox_pending",
            "next_attempt_at",
            postgresql_where=text("direction = 'outbound' AND status = 'pending'"),
        ),
    )
