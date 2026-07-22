from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import BULK_BATCH_STATUSES, sql_in


class BulkBatch(Base):
    """Groups bulk ceremony bookings - the '50 afringans on muktad day' case."""

    __tablename__ = "bulk_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("services.id"))

    gregorian_date: Mapped[date] = mapped_column(Date)
    parsi_roj: Mapped[int] = mapped_column(SmallInteger)
    parsi_mah: Mapped[int] = mapped_column(SmallInteger)
    parsi_year: Mapped[int] = mapped_column(Integer)
    calendar_system: Mapped[str] = mapped_column(String(10))

    total_entries: Mapped[int] = mapped_column(Integer, server_default="0")
    completed_count: Mapped[int] = mapped_column(Integer, server_default="0")

    status: Mapped[str] = mapped_column(String(20), server_default="open")

    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in(BULK_BATCH_STATUSES)})", name="status"),
        Index("idx_bulk_batches_agyary_date", "agyary_id", "gregorian_date"),
    )
