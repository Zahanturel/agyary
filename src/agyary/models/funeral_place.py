from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import FUNERAL_MANAGER, FUNERAL_PLACE_KINDS, FUNERAL_PLACE_ROLES, sql_in

# Both or neither, and on the globe. Spelled with IS NOT NULL for the same
# reason as the fire temples' (models/agyary.py): a CHECK that comes out NULL
# passes. The migration (f1a2b3c4d5e7) uses this same text.
FUNERAL_LOCATION_CHECK = (
    "(latitude IS NULL AND longitude IS NULL)"
    " OR (latitude IS NOT NULL AND longitude IS NOT NULL"
    " AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)"
)


class FuneralPlace(Base):
    """A Doongerwadi, prayer hall or aramgah (DECISIONS D10). Only an admin
    adds or changes one; nobody can add one themselves. Never deleted (D8):
    an admin turns it off, and it stays for the record and for its managers."""

    __tablename__ = "funeral_places"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    # Who runs it, e.g. the Bombay Parsi Punchayet. Optional.
    run_by: Mapped[str | None] = mapped_column(String(200))
    # Where it is, put on the map by the admin. Optional; both or neither.
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # The admin who added it; cleared if their account goes, the place stays.
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"kind IN ({sql_in(FUNERAL_PLACE_KINDS)})", name="kind"),
        CheckConstraint(FUNERAL_LOCATION_CHECK, name="location"),
    )


class FuneralPlaceManager(Base):
    """Who manages which funeral place. A manager's account (users.account_kind
    "funeral_manager") has one; the link goes when their account does
    (services/account.py), and the place stays."""

    __tablename__ = "funeral_place_managers"

    funeral_place_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("funeral_places.id"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), server_default=FUNERAL_MANAGER)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"role IN ({sql_in(FUNERAL_PLACE_ROLES)})", name="role"),
        Index("idx_funeral_place_managers_user", "user_id"),
    )
