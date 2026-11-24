from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base
from agyary.models.enums import CHANGE_PENDING, PLACE_CHANGE_STATUSES, sql_in


class PlaceChangeRequest(Base):
    """A Doongerwadi manager asking to work at another place (owner, 24 Nov 2026).
    The manager asks, the admin approves: nothing changes until then, because a
    place's family records are private to its managers (D2, D10). Approving moves
    the manager's link to the new place; the old place's records stay with it
    (D8). Kept after it is decided, as the record of who moved and when; it goes
    with the manager's account (services/account.py). At most one is pending per
    manager."""

    __tablename__ = "place_change_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    from_place_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("funeral_places.id"))
    to_place_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("funeral_places.id"))
    status: Mapped[str] = mapped_column(String(20), server_default=CHANGE_PENDING)
    decided_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in(PLACE_CHANGE_STATUSES)})", name="status"),
        Index(
            "uq_place_change_requests_one_pending", "user_id", unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("idx_place_change_requests_status", "status"),
    )
