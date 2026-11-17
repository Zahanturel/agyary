from datetime import date, datetime
from datetime import time as dt_time

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
    Time,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import (
    CALENDAR_SYSTEMS,
    DEATH_GIVEN_BY,
    DEPARTED_TITLES,
    OBSEQUIES,
    REQUEST_STATUSES,
    sql_in,
)


class FuneralRecord(Base):
    """A death recorded by a funeral place's manager (DECISIONS D10), to ask a
    fire temple for the prayers. Only what is needed to arrange them: the name
    as it is prayed, the death (date and its Roj and Mah, D5), four days or
    one, the bungli, the Geh-saarnu and Uthamna, how many mobeds, the family's
    preferred fire temple, and one family contact.

    Never recorded (D10): cause of death, age, address, the death certificate,
    ID numbers, how the body goes. The record belongs to the place, not to the
    manager: it stays when their account goes (D8), with who made it cleared.
    The family's contact is seen by the place's managers, and by a mobed only
    once they accept a request (Step 5).
    """

    __tablename__ = "funeral_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    funeral_place_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("funeral_places.id"))

    # The name as it is prayed: title, own name, father's or husband's name.
    departed_title: Mapped[str] = mapped_column(String(10))
    departed_name: Mapped[str] = mapped_column(String(80))
    departed_parent_name: Mapped[str | None] = mapped_column(String(80))

    # The death as a Gregorian date, and as it reads in the family's calendar.
    # Given either way (death_given_by); the other is worked out. Mah 13 is a
    # Gatha day, with the Gatha number in death_roj (as memorials store it).
    death_date: Mapped[date] = mapped_column(Date)
    death_given_by: Mapped[str] = mapped_column(String(10))
    death_roj: Mapped[int] = mapped_column(SmallInteger)
    death_mah: Mapped[int] = mapped_column(SmallInteger)
    death_year: Mapped[int] = mapped_column(Integer)
    calendar_system: Mapped[str] = mapped_column(String(10))

    obsequies: Mapped[str] = mapped_column(String(10))
    # The bungli or hall where the prayers are (short text).
    bungli: Mapped[str | None] = mapped_column(String(80))
    # The Geh-saarnu: the day and the geh, both or neither.
    geh_saarnu_date: Mapped[date | None] = mapped_column(Date)
    geh_saarnu_geh: Mapped[int | None] = mapped_column(SmallInteger)
    # The Uthamna: the day, and the time (IST) if known.
    uthamna_date: Mapped[date | None] = mapped_column(Date)
    uthamna_time: Mapped[dt_time | None] = mapped_column(Time)
    mobeds_wanted: Mapped[int | None] = mapped_column(SmallInteger)
    # The fire temple the family would like, if they named one.
    preferred_agyary_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agyaries.id"))

    # One family contact.
    family_contact_name: Mapped[str] = mapped_column(String(100))
    family_contact_phone: Mapped[str] = mapped_column(String(20))   # E.164

    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"departed_title IN ({sql_in(DEPARTED_TITLES)})", name="departed_title"),
        CheckConstraint(f"death_given_by IN ({sql_in(DEATH_GIVEN_BY)})", name="death_given_by"),
        CheckConstraint(f"calendar_system IN ({sql_in(CALENDAR_SYSTEMS)})", name="calendar_system"),
        CheckConstraint(f"obsequies IN ({sql_in(OBSEQUIES)})", name="obsequies"),
        CheckConstraint("death_mah BETWEEN 1 AND 13", name="death_mah"),
        CheckConstraint("death_roj BETWEEN 1 AND 30", name="death_roj"),
        CheckConstraint(
            "(geh_saarnu_date IS NULL AND geh_saarnu_geh IS NULL)"
            " OR (geh_saarnu_date IS NOT NULL AND geh_saarnu_geh IS NOT NULL AND geh_saarnu_geh BETWEEN 1 AND 5)",
            name="geh_saarnu",
        ),
        CheckConstraint("uthamna_time IS NULL OR uthamna_date IS NOT NULL", name="uthamna"),
        CheckConstraint("mobeds_wanted IS NULL OR mobeds_wanted BETWEEN 1 AND 20", name="mobeds_wanted"),
        Index("idx_funeral_records_place", "funeral_place_id", "created_at"),
    )


class FuneralRequest(Base):
    """A funeral record sent to one fire temple, asking for the prayers.

    One "waiting" at a time per record (a partial unique index). The manager
    can withdraw it and send to another; someone asked accepts or declines it
    (Step 5). The tick that the family agreed to share their name and number
    with this fire temple is required: family_share_agreed_at is when it was
    given. Who was asked is in funeral_request_recipients, so the request is
    shown to exactly them.
    """

    __tablename__ = "funeral_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    funeral_record_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("funeral_records.id"))
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    status: Mapped[str] = mapped_column(String(10), server_default="waiting")
    family_share_agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # When it stopped waiting, and who did it: the manager withdrawing, or the
    # person who accepted or declined.
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    accepted_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    decline_reason: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in(REQUEST_STATUSES)})", name="status"),
        CheckConstraint("(status = 'waiting') = (decided_at IS NULL)", name="decided"),
        Index(
            "uq_funeral_requests_one_waiting", "funeral_record_id", unique=True,
            postgresql_where=text("status = 'waiting'"),
        ),
        Index("idx_funeral_requests_record", "funeral_record_id", "sent_at"),
        Index("idx_funeral_requests_agyary", "agyary_id", "status"),
    )


class FuneralRequestRecipient(Base):
    """Who a request was sent to: the fire temple's confirmed panthakys, or if
    it had none, its mobeds whose access was on (services/panthaky.py). Only
    they see it (Step 5). The row goes with that person's account."""

    __tablename__ = "funeral_request_recipients"

    funeral_request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("funeral_requests.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_funeral_request_recipients_user", "user_id"),)
