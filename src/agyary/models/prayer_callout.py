from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import ANSWER_HOWS, CALLOUT_ANSWERS, sql_in


class AgyaryMobedContact(Base):
    """A mobed a fire temple's panthaky added by name and number to the
    agyari's own list (DECISIONS D10, 18 Nov 2026), to be asked on WhatsApp
    whether they can pray. Its approved mobeds in the app are on the list too,
    but are worked out from their memberships, never copied here.

    Private to that fire temple's confirmed panthakys and the admin (D2's
    spirit): no other fire temple or mobed sees it. Every row was added by hand,
    so it carries the panthaky's tick that the mobed agreed to get WhatsApp
    messages from Mobed Diary about prayers: when, and by whom. Removing one
    turns it off; it is kept (D8). A STOP from the number is honoured through
    reminder_opt_outs, as for everyone."""

    __tablename__ = "agyary_mobed_contacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    name: Mapped[str] = mapped_column(String(60))
    phone: Mapped[str] = mapped_column(String(20))   # E.164, cleaned by services/phone.py
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consent_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # The Mobed Diary account with this number, if there is one, so that an
    # account an admin has switched off is not messaged (D9).
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name="phone_e164"),
        UniqueConstraint("agyary_id", "phone", name="uq_agyary_mobed_contacts_agyary_phone"),
        Index("idx_agyary_mobed_contacts_phone", "phone"),
    )


class PrayerCallout(Base):
    """Asking the agyari's mobeds on WhatsApp whether they can pray for a
    funeral request (template 4, no family details): at once when the request
    is sent (19 Nov 2026; sent_by is who sent the request), or again by the
    panthaky's hand. Kept with the request; who was asked, and what they said,
    is in the answers."""

    __tablename__ = "prayer_callouts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    funeral_request_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("funeral_requests.id"))
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    sent_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    asked: Mapped[int] = mapped_column(Integer, server_default="0")
    # When the panthaky last picked who goes from this call-out (18 Nov 2026;
    # since 19 Nov the first yeses go and this is no longer set).
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_prayer_callouts_request", "funeral_request_id"),)


class PrayerCalloutAnswer(Base):
    """One mobed asked in a call-out, and their answer. The quick-reply
    buttons carry ``token`` (unguessable, never the row's id), which is how a
    tap on WhatsApp finds this row; only the first answer counts. The name and
    number are as they were when asked. ``picked_at`` is when they became one
    of those going: since 19 Nov 2026 the first yeses up to the number wanted
    (``picked_by_user_id`` empty); before, the panthaky's pick.

    Since R3.1 step 4 this is the board's one row per person per request,
    whatever the channel: an app mobed (``user_id``), a mobed added by hand
    (``contact_id``), or the panthaky's own "I'll pray". ``how`` is how they
    were asked until they answer, then how the answer came (a WhatsApp button,
    in the app, by phone, or "self"); ``recorded_by_user_id`` is the panthaky
    who marked a phone answer or "I'll pray". A Yes with ``picked_at`` is a
    place; a Yes without it is a standby, in ``answered_at`` order."""

    __tablename__ = "prayer_callout_answers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    callout_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prayer_callouts.id", ondelete="CASCADE"))
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agyary_mobed_contacts.id", ondelete="SET NULL")
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(60))
    # E.164 when asked; cleared if the account it belonged to is deleted.
    phone: Mapped[str | None] = mapped_column(String(20))
    token: Mapped[str] = mapped_column(String(40), unique=True)
    answer: Mapped[str | None] = mapped_column(String(5))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    details_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When "Thank you. Enough mobeds are going this time." went to a Yes not picked.
    enough_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Every row from before R3.1 step 4 was a WhatsApp call-out; new code always sets it.
    how: Mapped[str] = mapped_column(String(10), server_default="whatsapp")
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(f"answer IN ({sql_in(CALLOUT_ANSWERS)})", name="answer"),
        CheckConstraint(f"how IN ({sql_in(ANSWER_HOWS)})", name="how"),
        CheckConstraint("(answer IS NULL) = (answered_at IS NULL)", name="answered"),
        CheckConstraint("picked_at IS NULL OR answer = 'yes'", name="picked_said_yes"),
        CheckConstraint("contact_id IS NULL OR user_id IS NULL", name="one_kind"),
        UniqueConstraint("callout_id", "phone", name="uq_prayer_callout_answers_callout_phone"),
        Index("idx_prayer_callout_answers_callout", "callout_id"),
    )
