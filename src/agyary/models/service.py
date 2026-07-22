from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base


class Service(Base):
    """Per-agyary service catalog, seeded from the standard list on onboarding."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    name: Mapped[str] = mapped_column(String(100))
    default_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    min_mobeds: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    typical_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    offsite_capable: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    display_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("agyary_id", "name", name="uq_services_agyary_name"),)
