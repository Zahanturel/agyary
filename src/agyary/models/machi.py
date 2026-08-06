from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agyary.core.database import Base
from agyary.models.enums import (
    CEREMONY_STATUSES,
    MACHI_PURPOSES,
    PAYMENT_METHODS,
    PAYMENT_STATUSES,
    SLOT_RELEASING_STATUSES,
    sql_in,
)


class Machi(Base):
    """Slot-based ceremonies: one machi per geh per day per agyary.

    ``gregorian_date`` anchors the Parsi day (which starts at sunrise);
    ``ceremony_datetime`` is when the ceremony physically happens. For the
    Ushahin geh those differ by a day: Roj Bahman / Ushahin is performed at
    ~4 AM on the *next* Gregorian morning. Reminders and dashboards must use
    ``ceremony_datetime``.
    """

    __tablename__ = "machis"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customers.id"))

    # Parsi date: source of truth for the slot
    parsi_roj: Mapped[int] = mapped_column(SmallInteger)
    parsi_mah: Mapped[int] = mapped_column(SmallInteger)  # 13 = Gatha days
    parsi_year: Mapped[int] = mapped_column(Integer)
    calendar_system: Mapped[str] = mapped_column(String(10))  # copied from agyary, kept for history
    geh: Mapped[int] = mapped_column(SmallInteger)

    gregorian_date: Mapped[date] = mapped_column(Date)
    ceremony_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    purpose: Mapped[str] = mapped_column(String(20))  # 'patet' | 'tandarosti'

    assigned_mobed_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))

    # Which mobed personally manually-entered this (PWA walk-in flow only -
    # NULL for WhatsApp-originated machis). Basis for "my customers" search:
    # a customer relationship belongs to the mobed, not the fire temple.
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))

    status: Mapped[str] = mapped_column(String(20), server_default="requested")

    recurrence_rule_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("recurrence_rules.id", use_alter=True, name="fk_machis_recurrence_rule"),
    )
    is_recurring_instance: Mapped[bool] = mapped_column(Boolean, server_default="false")

    bulk_batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bulk_batches.id"))

    # Payment, denormalized from payments for calendar views
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    payment_status: Mapped[str] = mapped_column(String(20), server_default="pending")
    payment_method: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)

    # Mobed earnings
    mobed_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    mobed_paid: Mapped[bool] = mapped_column(Boolean, server_default="false")
    mobed_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    customer: Mapped["Customer"] = relationship()  # noqa: F821
    names: Mapped[list["CeremonyName"]] = relationship(  # noqa: F821
        back_populates="machi",
        order_by="CeremonyName.display_order",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("geh BETWEEN 1 AND 5", name="geh"),
        CheckConstraint("parsi_roj BETWEEN 1 AND 30", name="parsi_roj"),
        CheckConstraint("parsi_mah BETWEEN 1 AND 13", name="parsi_mah"),
        CheckConstraint(f"purpose IN ({sql_in(MACHI_PURPOSES)})", name="purpose"),
        CheckConstraint(f"status IN ({sql_in(CEREMONY_STATUSES)})", name="status"),
        CheckConstraint(f"payment_status IN ({sql_in(PAYMENT_STATUSES)})", name="payment_status"),
        CheckConstraint(
            f"payment_method IS NULL OR payment_method IN ({sql_in(PAYMENT_METHODS)})",
            name="payment_method",
        ),
        # THE critical constraint: one active machi per geh per day per agyary.
        # Cancelled/declined/rescheduled slots reopen for booking.
        Index(
            "uq_machis_slot",
            "agyary_id",
            "parsi_roj",
            "parsi_mah",
            "parsi_year",
            "geh",
            unique=True,
            postgresql_where=text(f"status NOT IN ({sql_in(SLOT_RELEASING_STATUSES)})"),
        ),
        Index("idx_machis_agyary_date", "agyary_id", "gregorian_date"),
        Index("idx_machis_agyary_ceremony_datetime", "agyary_id", "ceremony_datetime"),
        Index(
            "idx_machis_mobed_date",
            "assigned_mobed_id",
            "gregorian_date",
            postgresql_where=text("assigned_mobed_id IS NOT NULL"),
        ),
        Index(
            "idx_machis_created_by",
            "created_by_user_id",
            postgresql_where=text("created_by_user_id IS NOT NULL"),
        ),
        Index(
            "idx_machis_pending",
            "agyary_id",
            "status",
            postgresql_where=text("status = 'requested'"),
        ),
        Index("idx_machis_customer", "customer_id", text("gregorian_date DESC")),
        Index(
            "idx_machis_recurrence",
            "recurrence_rule_id",
            postgresql_where=text("recurrence_rule_id IS NOT NULL"),
        ),
        Index(
            "idx_machis_bulk",
            "bulk_batch_id",
            postgresql_where=text("bulk_batch_id IS NOT NULL"),
        ),
    )
