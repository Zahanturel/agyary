from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import DEPARTED_TITLES, sql_in


class PersonName(Base):
    """Names of the departed that follow a PERSON, keyed by phone number (DECISIONS
    D12, "Departed names for the family", 24 Nov 2026): one number is one person
    with many roles (behdin, mobed, Doongerwadi manager, trustee).

    Written when a Doongerwadi manager records a death: the departed's name and
    the father's or husband's name go to the pool of the family contact's number.
    The newest comes first (created_at, then id, both descending).

    Privacy, built exactly: the pool is readable ONLY by the account that signs
    in with that number (GET /api/mobed/me/person-names). No mobed, manager or
    admin screen reads it, and nothing takes a phone as a parameter. A mobed gets
    these names only as copies in their OWN book of behdins, at All set for a
    request they are assigned to (services/all_set.py). Typing the number as a
    behdin shows nothing of it.

    Goes only when the family asks to be erased or the account is deleted
    (services/erasure.py, services/account.py); never because of its age (D8).
    The record that made a row may go on its own: the row stays."""

    __tablename__ = "person_names"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20))   # E.164
    departed_title: Mapped[str] = mapped_column(String(10))
    departed_name: Mapped[str] = mapped_column(String(80), server_default="")
    departed_parent_name: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(20), server_default="death_record")
    source_record_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("funeral_records.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name="phone_e164"),
        CheckConstraint(f"departed_title IN ({sql_in(DEPARTED_TITLES)})", name="departed_title"),
        CheckConstraint("source IN ('death_record')", name="source"),
        Index("idx_person_names_phone", "phone"),
        Index("idx_person_names_record", "source_record_id"),
    )
