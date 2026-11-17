from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import (
    AGYARY_STATUSES,
    BEHDIN_LANGUAGES,
    CALENDAR_SYSTEMS,
    LOCATION_SOURCES,
    sql_in,
)


# All three or none, and on the globe. Spelled with IS NOT NULL on purpose: a
# CHECK passes when it comes out NULL, so a bare BETWEEN would let a half-set
# position through. The migration (d0e1f2a3b4c6) uses this same text.
LOCATION_CHECK = (
    "(latitude IS NULL AND longitude IS NULL AND location_source IS NULL)"
    " OR (latitude IS NOT NULL AND longitude IS NOT NULL AND location_source IS NOT NULL"
    " AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)"
)


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

    # Lifecycle: 'unclaimed' seed entry vs 'active' (set up by a real mobed).
    status: Mapped[str] = mapped_column(String(20), server_default="active")
    # WhatsApp behdin self-service toggle (parked feature). Schema-only for
    # now: nothing reads or writes it this pass - added here to avoid a second
    # agyari migration when that work lands.
    auto_booking_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")

    # Where the fire temple is on the map (DECISIONS D10), for the Doongerwadi
    # side's "nearest first". location_source says how good it is: "town" is
    # the seed list's town-level start (scripts/seed_fire_temple_locations.py),
    # "pin" was put there by a person. Latitude, longitude and source are all
    # set or all empty. Who last moved it and when are kept for the record;
    # the person's id goes if their account does.
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    location_source: Mapped[str | None] = mapped_column(String(10))
    location_set_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    location_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"calendar_system IN ({sql_in(CALENDAR_SYSTEMS)})", name="calendar_system"),
        CheckConstraint(f"behdin_language IN ({sql_in(BEHDIN_LANGUAGES)})", name="behdin_language"),
        CheckConstraint(f"status IN ({sql_in(AGYARY_STATUSES)})", name="status"),
        CheckConstraint(f"location_source IN ({sql_in(LOCATION_SOURCES)})", name="location_source"),
        CheckConstraint(LOCATION_CHECK, name="location"),
        Index(
            "uq_agyaries_wa_phone_number_id",
            "wa_phone_number_id",
            unique=True,
            postgresql_where=text("wa_phone_number_id IS NOT NULL"),
        ),
        Index("idx_agyaries_city", "city"),
        Index(
            "idx_agyaries_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )
