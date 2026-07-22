from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agyary.core.database import Base
from agyary.models.enums import NAME_SECTIONS, NAME_STATUSES, NAME_TITLES, sql_in


class CeremonyName(Base):
    """Names recited during a ceremony; the data on the thermal printer slip.

    Snapshotted from the customer's saved pool at booking confirmation, so
    the prayer record stays immutable if the saved pool later changes.

    Sections (v2): 'pair' rows are the pair-name section (departed or living,
    grouped via pair_group; tandarosti machi names are ungrouped singles here).
    'farmayeshne' rows are single living names of the organizing family -
    present for every service except machis.
    """

    __tablename__ = "ceremony_names"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Polymorphic link: exactly one must be set (real FKs, unlike type+id pattern)
    machi_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("machis.id", ondelete="CASCADE")
    )
    booking_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bookings.id", ondelete="CASCADE")
    )

    section: Mapped[str] = mapped_column(String(20))  # 'pair' | 'farmayeshne'
    title: Mapped[str] = mapped_column(String(20))  # khud/osta/osti/ervad/behdin
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10))  # 'living' | 'departed'

    display_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    pair_group: Mapped[int | None] = mapped_column(SmallInteger)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    machi: Mapped["Machi | None"] = relationship(back_populates="names")  # noqa: F821
    booking: Mapped["Booking | None"] = relationship(back_populates="names")  # noqa: F821

    __table_args__ = (
        CheckConstraint("num_nonnulls(machi_id, booking_id) = 1", name="exactly_one_parent"),
        CheckConstraint(f"section IN ({sql_in(NAME_SECTIONS)})", name="section"),
        CheckConstraint(f"title IN ({sql_in(NAME_TITLES)})", name="title"),
        CheckConstraint(f"status IN ({sql_in(NAME_STATUSES)})", name="status"),
        Index(
            "idx_ceremony_names_machi",
            "machi_id",
            postgresql_where=text("machi_id IS NOT NULL"),
        ),
        Index(
            "idx_ceremony_names_booking",
            "booking_id",
            postgresql_where=text("booking_id IS NOT NULL"),
        ),
    )
