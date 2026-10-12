from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base


class LoginOtp(Base):
    """A six digit sign-in code sent to a phone over WhatsApp.

    Unlike the inbound sign-in (wa_login_attempts), the caller here CLAIMS a
    number and we send to it, so the number is not proven until the right code
    comes back. That is the weaker shape, and everything about this table is
    shaped by it: the code is never stored (only a salted digest), it dies after
    a few wrong tries and after a few minutes, and every request is counted so
    the number of codes sent to one phone, from one place, and overall can be
    capped - each one is a paid message to someone who may not have asked.
    """

    __tablename__ = "login_otps"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20))
    salt: Mapped[str] = mapped_column(String(32))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Wrong guesses so far; the code is dead once this reaches the limit.
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Whether the number had an account when the code was asked for. Codes to
    # strangers are capped harder, since those are what an abuser would send.
    is_new_number: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # A digest of the requester's address, never the address itself.
    requester: Mapped[str | None] = mapped_column(String(16))
    # pending: not yet handed to Meta; sent: Meta took it; failed: it did not;
    # suppressed: a number that could not sign in, so nothing was sent.
    status: Mapped[str] = mapped_column(String(10), server_default="pending")
    wa_message_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_login_otps_phone", "phone", "created_at"),
        Index("idx_login_otps_created", "created_at"),
    )
