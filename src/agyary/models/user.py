from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import USER_ROLES, sql_in


class User(Base):
    """Operators: panthakys, mobeds, caretakers. Global entity; role is per-agyary."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(20), unique=True)  # E.164, doubles as WhatsApp ID
    # The id WhatsApp sends for this mobed if they use a username (a BSUID),
    # learnt at a sign-in that carried both - so a later one that carries only
    # the id still finds them (AU-4).
    wa_user_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # The one switch for automatic WhatsApp reminders from this account
    # (docs/DECISIONS.md D4). On for everyone in the pilot; a free tier later is
    # this switch off, set for new accounts by REMINDERS_AUTOMATIC_DEFAULT.
    # Sending by hand (the wa.me button) never depends on it.
    automatic_reminders: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Refresh tokens from before sessions existed (they carry no session) that
    # were issued before this moment are refused - set by "sign out everywhere".
    tokens_valid_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserSession(Base):
    """One signed-in device (AU-2). The refresh token names it and carries its
    generation, which moves on at every refresh: an older generation coming
    back means the token was copied, and the session ends. Signing out, "sign
    out other devices" and an admin's "sign out everywhere" end sessions here,
    and every request checks its session is still live."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    generation: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_user_sessions_user", "user_id"),)


class AgyaryUser(Base):
    """Junction: who works where and in what capacity."""

    __tablename__ = "agyary_users"

    agyary_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agyaries.id"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    reminder_minutes_before: Mapped[int] = mapped_column(SmallInteger, server_default="30")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"role IN ({sql_in(USER_ROLES)})", name="role"),
        Index("idx_agyary_users_user", "user_id"),
    )
