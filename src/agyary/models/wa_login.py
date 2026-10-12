from datetime import datetime

from sqlalchemy import DateTime, Index, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base


class WaLoginAttempt(Base):
    """One inbound-WhatsApp sign-in in progress.

    The inverse of the usual OTP shape, which this replaced. There, the
    caller claims a phone number and the server sends a code to it. Here
    the code is minted first with no phone attached at all, and the number
    arrives only when WhatsApp delivers the message - so it is proven by
    Meta rather than asserted by the caller. Nothing in this table
    identifies anyone until it is claimed.

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
    # The id WhatsApp sends for someone who uses a username (a BSUID), when it
    # sends one - with or instead of the number (AU-4).
    claimed_wa_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # AU-1: when the code arrives, a short number is sent back to that phone and
    # only its digest is kept here; the sign-in finishes only once it is typed on
    # the screen that started it. NULL means none is outstanding.
    confirm_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirm_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # Expired rows are swept on each start; this keeps that cheap.
        Index("idx_wa_login_attempts_expiry", "expires_at"),
    )
