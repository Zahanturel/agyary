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
from agyary.models.enums import (
    ACCESS_ON,
    ACCOUNT_KINDS,
    ACCOUNT_MOBED,
    CLAIM_DECISIONS,
    CLAIMED_ROLES,
    USER_ACCESS,
    USER_ROLES,
    sql_in,
)


REQUESTS_CONFIRMED_BY_CHECK = "requests_confirmed_by_user_id IS NULL OR requests_confirmed_at IS NOT NULL"
REQUESTS_OFF_BY_CHECK = "requests_off_by_user_id IS NULL OR requests_off_at IS NOT NULL"


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
    # The mobed's own switch for the daily report: the evening before, what is on
    # their day tomorrow (services/daily_report.py). Off until they turn it on.
    daily_report: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # The owner's switch for this mobed (DECISIONS D9): "pending" (signed up,
    # waiting for an admin's approval), "on", or "off". Anything but "on" can
    # only choose a fire temple, and nothing is sent under the account. The
    # server default is "on" for the accounts that existed before approval did;
    # a sign-up is created "pending" (services/mobed_auth.login_user).
    access: Mapped[str] = mapped_column(String(10), server_default=ACCESS_ON)
    access_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "mobed" (a mobed or panthaky, the whole of the mobed app) or
    # "funeral_manager" (a Doongerwadi or prayer hall's manager, who sees none
    # of it), DECISIONS D10. One kind per person, chosen once at sign-up; every
    # account from before is a mobed's. The API keeps them apart
    # (api/routes/mobed.py, get_signed_in_user and get_current_manager).
    account_kind: Mapped[str] = mapped_column(String(20), server_default=ACCOUNT_MOBED)
    # Refresh tokens from before sessions existed (they carry no session) that
    # were issued before this moment are refused - set by "sign out everywhere".
    tokens_valid_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"access IN ({sql_in(USER_ACCESS)})", name="access"),
        CheckConstraint(f"account_kind IN ({sql_in(ACCOUNT_KINDS)})", name="account_kind"),
    )


class DeletedAccount(Base):
    """A number whose account was deleted, as a one-way digest and only for a
    while (services/account.py). Deleting an account and signing up again must
    not start that number's sending afresh (SEC-02)."""

    __tablename__ = "deleted_accounts"

    phone_hmac: Mapped[str] = mapped_column(String(64), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    # What they said they are here, "mobed" or "panthaky", when they chose this
    # fire temple or later from Settings (DECISIONS D10). A claim only: ``role``
    # above is what gives a panthaky's powers (D7), and only the owner's
    # "Confirm as panthaky" changes it (services/panthaky.py). NULL for those
    # who joined before the question was asked.
    claimed_role: Mapped[str | None] = mapped_column(String(20))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The owner's last decision on this membership's panthaky role, when, and
    # by which admin (cleared if that admin's account goes).
    claim_decision: Mapped[str | None] = mapped_column(String(20))
    claim_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_decided_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # Whether they are one of this fire temple's mobeds for prayer requests
    # (DECISIONS D10, owner 22 Nov 2026: joining another agyari needs its
    # panthaky's confirmation). Joining stays open (D1.4) and gives the
    # membership as before; prayer requests reach it only once it is confirmed:
    # by the admin's approval of a sign-up (the fire temple they signed up at),
    # by that fire temple's confirmed panthaky on the Mobeds page, or by the admin
    # when it has none (services/join_confirmation.py). Memberships from before
    # were all confirmed by the migration. Who confirmed is cleared if their
    # account goes. The one rule that reads these is panthaky.counts_for_requests.
    requests_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requests_confirmed_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # Taken off the list for prayer requests ("Not one of ours", "Take off the
    # list") by the panthaky or the admin, and by whom; NULL while on it. They
    # stay a member of the fire temple, and "Put back" clears it.
    requests_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requests_off_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(f"role IN ({sql_in(USER_ROLES)})", name="role"),
        CheckConstraint(f"claimed_role IN ({sql_in(CLAIMED_ROLES)})", name="claimed_role"),
        CheckConstraint(f"claim_decision IN ({sql_in(CLAIM_DECISIONS)})", name="claim_decision"),
        CheckConstraint("(claimed_role IS NULL) = (claimed_at IS NULL)", name="claimed_at"),
        CheckConstraint("(claim_decision IS NULL) = (claim_decided_at IS NULL)", name="claim_decided_at"),
        # Who did it only with when (the migration, b6c7d8e9f0a5, uses this same text).
        CheckConstraint(REQUESTS_CONFIRMED_BY_CHECK, name="requests_confirmed_by"),
        CheckConstraint(REQUESTS_OFF_BY_CHECK, name="requests_off_by"),
        Index("idx_agyary_users_user", "user_id"),
    )
