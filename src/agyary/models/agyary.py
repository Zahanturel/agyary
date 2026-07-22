from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import BEHDIN_LANGUAGES, CALENDAR_SYSTEMS, sql_in


class Agyary(Base):
    """Tenant table. Every tenant-scoped row carries agyary_id."""

    __tablename__ = "agyaries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    calendar_system: Mapped[str] = mapped_column(String(10), server_default="shenshai")
    contact_phone: Mapped[str | None] = mapped_column(String(20))

    # WhatsApp Cloud API identifiers
    wa_phone_number: Mapped[str | None] = mapped_column(String(20))  # E.164
    wa_phone_number_id: Mapped[str | None] = mapped_column(String(50))  # Meta phone_number_id
    wa_display_name: Mapped[str | None] = mapped_column(String(100))

    upi_id: Mapped[str | None] = mapped_column(String(100))
    qr_code_url: Mapped[str | None] = mapped_column(Text)

    max_machis_per_geh: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    require_mobed_acceptance: Mapped[bool] = mapped_column(Boolean, server_default="false")
    behdin_language: Mapped[str] = mapped_column(String(10), server_default="en")

    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"calendar_system IN ({sql_in(CALENDAR_SYSTEMS)})", name="calendar_system"),
        CheckConstraint(f"behdin_language IN ({sql_in(BEHDIN_LANGUAGES)})", name="behdin_language"),
        Index(
            "uq_agyaries_wa_phone_number_id",
            "wa_phone_number_id",
            unique=True,
            postgresql_where=text("wa_phone_number_id IS NOT NULL"),
        ),
        Index("idx_agyaries_city", "city"),
    )
