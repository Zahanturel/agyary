from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import USER_ROLES, sql_in


class AgyaryInvite(Base):
    """A pending role assignment, addressed to a phone number.

    Self-serve login (phone + OTP) can only ever produce a plain 'mobed'
    membership - that is deliberate, it's an unvouched-for stranger. The
    two privileged roles have to come from someone who already holds one,
    and this table is that hand-off: an admin names a phone and a role, and
    whoever proves possession of that phone through the normal OTP login
    picks up the membership at the role stated here.

    Addressed to a phone rather than a user id because the invitee usually
    has no User row yet - being invited is frequently how they first arrive.
    Redemption is therefore keyed on the phone that OTP just verified, which
    is the whole reason this is safe: an invite is a claim about a phone
    number, and OTP is the proof of that claim.
    """

    __tablename__ = "agyary_invites"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agyary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agyaries.id"))
    phone: Mapped[str] = mapped_column(String(20))  # E.164, matched against User.phone
    role: Mapped[str] = mapped_column(String(20))

    invited_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    # Revocation is a soft delete: an admin who mis-types a number needs the
    # invite to stop working, but the record of who invited whom is exactly
    # the sort of thing you want to still be able to read afterwards.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"role IN ({sql_in(USER_ROLES)})", name="role"),
        # At most one live invite per (agyari, phone): re-inviting the same
        # number replaces the pending one rather than stacking a second,
        # so "which role do they get" can never be ambiguous at redemption.
        Index(
            "uq_agyary_invites_pending",
            "agyary_id",
            "phone",
            unique=True,
            postgresql_where=text("redeemed_at IS NULL AND revoked_at IS NULL"),
        ),
        Index(
            "idx_agyary_invites_phone",
            "phone",
            postgresql_where=text("redeemed_at IS NULL AND revoked_at IS NULL"),
        ),
    )
