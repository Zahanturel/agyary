from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base


class FuneralBehdin(Base):
    """A family in a funeral place's own book of behdins (DECISIONS D10,
    changed 19 Nov 2026): a name, a number, and the fire temple they usually
    go to, if the manager knows it. Recording a death picks the family from
    here and suggests their agyari first.

    Private to that funeral place (D2's spirit): its managers, and the admin
    acting for it, see and change it; nobody else, not another place and not
    any mobed. One row per place and number. Removing one turns it off and
    keeps it (D8); only a family's own request to be erased takes the row away
    (services/erasure.py)."""

    __tablename__ = "funeral_behdins"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    funeral_place_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("funeral_places.id"))
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(20))   # E.164, cleaned by services/phone.py
    usual_agyary_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agyaries.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name="phone_e164"),
        UniqueConstraint("funeral_place_id", "phone", name="uq_funeral_behdins_place_phone"),
        Index("idx_funeral_behdins_phone", "phone"),
    )
