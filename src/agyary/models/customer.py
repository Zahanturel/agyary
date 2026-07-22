from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agyary.core.database import Base
from agyary.models.enums import NAME_SECTIONS, NAME_STATUSES, NAME_TITLES, sql_in


class Customer(Base):
    """Behdins. WhatsApp-only; never see the PWA."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(20), unique=True)  # E.164
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    saved_names: Mapped[list["CustomerSavedName"]] = relationship(
        back_populates="customer",
        order_by="CustomerSavedName.display_order",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "idx_customers_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class AgyaryCustomer(Base):
    """Junction, auto-created on first booking at an agyary."""

    __tablename__ = "agyary_customers"

    agyary_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agyaries.id"), primary_key=True
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customers.id"), primary_key=True
    )
    first_booking_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_agyary_customers_customer", "customer_id"),)


class CustomerSavedName(Base):
    """A customer's single saved name pool: departed pairs + farmayeshne names.

    Reused across bookings; on confirmation rows are snapshotted into
    ceremony_names so the prayer record stays immutable even if the customer
    later edits this pool.
    """

    __tablename__ = "customer_saved_names"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="CASCADE")
    )
    section: Mapped[str] = mapped_column(String(20))  # 'pair' | 'farmayeshne'
    title: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10))  # 'living' | 'departed'
    pair_group: Mapped[int | None] = mapped_column(SmallInteger)
    display_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    customer: Mapped[Customer] = relationship(back_populates="saved_names")

    __table_args__ = (
        CheckConstraint(f"section IN ({sql_in(NAME_SECTIONS)})", name="section"),
        CheckConstraint(f"title IN ({sql_in(NAME_TITLES)})", name="title"),
        CheckConstraint(f"status IN ({sql_in(NAME_STATUSES)})", name="status"),
        Index("idx_customer_saved_names_customer", "customer_id"),
    )
