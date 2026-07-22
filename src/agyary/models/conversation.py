from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base


class ConversationState(Base):
    """Where a customer is in a chat flow. Postgres, not Redis: survives
    restarts, and one less dependency at this scale.

    Note: doc 1 specified a partial index ``WHERE expires_at < now()`` -
    that's invalid in Postgres (index predicates must be immutable), so the
    cleanup job uses a plain index on expires_at instead.
    """

    __tablename__ = "conversation_states"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    phone: Mapped[str] = mapped_column(String(20))

    flow: Mapped[str] = mapped_column(String(50))  # 'machi_booking', 'service_booking', ...
    step: Mapped[str] = mapped_column(String(50))  # 'select_date', 'enter_names', ...
    data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # One active conversation per customer per agyary
        UniqueConstraint("agyary_id", "phone", name="uq_conversation_states_agyary_phone"),
        Index("idx_conversation_states_expiry", "expires_at"),
    )
