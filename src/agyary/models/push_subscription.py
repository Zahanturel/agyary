from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base


class PushSubscription(Base):
    """One phone or browser that has agreed to show this user's notifications
    even when the app is closed (web push, services/web_push.py).

    For admins only for now: a new mobed waiting for approval (D9). The
    endpoint is the push service's address for that device; the two keys are
    the device's, to encrypt what is sent to it. A device that is gone (the
    push service answers 404 or 410) is deleted the first time we find out.
    """

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_push_subscriptions_user", "user_id"),)
