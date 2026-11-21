from datetime import date, datetime
from datetime import time as dt_time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
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
    one, the Geh-saarnu and Uthamna, how many mobeds, the family's preferred
    fire temple, and one family contact.

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
    # The bungli or hall where the prayers are. No longer asked or shown (owner,
    # 19 Nov 2026); kept for the records that have it (D8), and never sent anywhere.
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
    # Step 5b: whether the manager's tick also said the family agreed to get
    # WhatsApp messages about the prayers from Mobed Diary (the tick's words
    # since 18 Nov 2026). Only then is the family messaged from our number.
    # False for every request sent before those words.
    family_whatsapp_agreed: Mapped[bool] = mapped_column(Boolean, server_default="false")
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
    # Step 5: whether the person who accepted let the funeral place have their
    # name and number (the tick, on by default). Set only on an accepted one;
    # the manager sees the number only when it is True, and the WhatsApp
    # messages from our number (Step 5b) read it too.
    accepter_shared_contact: Mapped[bool | None] = mapped_column(Boolean)
    # The memorial the accepter saved from this request, if they did. Theirs
    # only: never shown to the funeral place (D2).
    memorial_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("memorials.id", ondelete="SET NULL")
    )
    # R3.1 step 2: when the safety net asked all the fire temple's mobeds on
    # WhatsApp because the panthaky had not acted in Come to me first
    # (services/prayer_timers.py). Set once, before anything is sent, so it is
    # never done twice; NULL when it has not run.
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # R3.1 step 4: the panthaky's first action on the "Who will pray" board
    # (Ask everyone, I'll pray, a call's result) takes the request for the fire
    # temple - when, and by whom. Set once, by a conditional update; there is
    # no separate Accept. Then the safety net never fires for it.
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    taken_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # When the last place on the board filled and the request became all set
    # (services/all_set.py). decided_at is set with it, as for any request
    # that is no longer waiting.
    all_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # R3.1 step 5: True when the panthaky made it all set with fewer mobeds
    # going than wanted ("Confirm with who's going").
    confirmed_short: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # When the panthakys (or, with none, the funeral place's managers) were told
    # "Still 1 mobed short", 4 hours before the Geh-saarnu
    # (services/prayer_timers.py). Set once, before anyone is told.
    short_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in(REQUEST_STATUSES)})", name="status"),
        CheckConstraint("(status = 'waiting') = (decided_at IS NULL)", name="decided"),
        CheckConstraint(
            "accepter_shared_contact IS NULL OR status IN ('accepted', 'taken')", name="shared_contact"
        ),
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


class FuneralRequestBook(Base):
    """Whose own book a request put the family in at All set (R3.1 step 5;
    DECISIONS D10, changed 21 Nov 2026): the panthaky who took it (or, if
    nobody did, each confirmed panthaky it reached) and each app mobed going,
    once per person. Their own record of the family's number (D2), and the
    memorial they made from the request, if they did - each person's own,
    never shown to anyone else, nor to the funeral place. A request accepted
    the old way before R3.1 keeps its single funeral_requests.memorial_id
    instead (D8).

    ``is_panthaky``: their book was set up as the request's panthaky, so the
    family and the mobeds are told they are the panthaky. The row goes with
    that person's account; the record and the memorial may go on their own
    (a family's erasure), leaving it empty."""

    __tablename__ = "funeral_request_books"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    funeral_request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("funeral_requests.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="SET NULL")
    )
    memorial_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("memorials.id", ondelete="SET NULL")
    )
    is_panthaky: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("funeral_request_id", "user_id", name="uq_funeral_request_books_request_user"),
        Index("idx_funeral_request_books_user", "user_id"),
    )
