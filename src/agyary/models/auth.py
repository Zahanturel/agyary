from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base


class AuthOtp(Base):
    """WhatsApp OTP login codes. One live code per phone (UPSERT on request)."""

    __tablename__ = "auth_otps"

    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 of the 6-digit OTP
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")  # max 3
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
