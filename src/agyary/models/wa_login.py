from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base


class WaLoginAttempt(Base):
    """One inbound-WhatsApp sign-in in progress.

    The reverse of AuthOtp. There, the caller claims a phone number and we
    send a code to it. Here we mint a code first, with no phone attached at
    all, and learn the number only when WhatsApp delivers the message -
    which means the number is proven by Meta rather than asserted by the
    caller. Nothing in this table identifies anyone until it is claimed.

    Two secrets, doing different jobs:

    ``code`` travels through the wa.me link and the user's own WhatsApp, so
    it is a bearer token that anyone who sees it can send to our number. It
    identifies the attempt to the webhook, and nothing more.

    ``poll_secret_hash`` is the digest of a value that only ever lives in
    the originating browser's httpOnly cookie. Polling matches on it, not on
    the code, so possessing the code alone cannot collect the session the
    code created.
    """

    __tablename__ = "wa_login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    poll_secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Null until the webhook sees the code. Set together, always.
    claimed_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # Expired rows are swept on each start; this keeps that cheap.
        Index("idx_wa_login_attempts_expiry", "expires_at"),
    )
