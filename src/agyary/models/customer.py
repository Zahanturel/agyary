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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agyary.core.database import Base
from agyary.models.enums import NAME_SECTIONS, NAME_STATUSES, NAME_TITLES, sql_in


class Customer(Base):
    """A behdin, as one mobed keeps them (docs/DECISIONS.md D2).

    One row per mobed per family: the name, the saved names, the events and
    memorials, and the reminder consent are that mobed's own. Two mobeds who
    serve the same family each have a row with the same number, and neither
    can see or touch the other's. Behdins are WhatsApp-only and never see the PWA.
    """

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The mobed whose record this is. NULL only for a few legacy rows that no
    # mobed ever entered (bookings made through the old WhatsApp bot).
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(20))  # E.164; unique per owner
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Whether this behdin agreed, in person to this mobed, to WhatsApp reminders.
    # Off until the mobed turns it on; turned off again by a STOP.
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    reminders_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the person replied STOP. A STOP is the person's, so it reaches
    # every mobed's record of the number (and any made later, through
    # ReminderOptOut); each mobed lifts it only for their own record, and only
    # with "they asked me to".
    reminders_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
        # The number is how a mobed finds the family again, so its shape is
        # enforced where every writer has to pass it, not just in the API.
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name="phone_e164"),
        # One record per number in a mobed's book - not one per number overall.
        UniqueConstraint("owner_user_id", "phone", name="uq_customers_owner_phone"),
        # STOP and receipts look a number up across every mobed's records.
        Index("idx_customers_phone", "phone"),
        Index(
            "idx_customers_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class ReminderOptOut(Base):
    """A number that replied STOP. The person's, not any mobed's: it outlives
    every record of the number, so a mobed who adds the number later still
    starts with reminders stopped."""

    __tablename__ = "reminder_opt_outs"

    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    stopped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
