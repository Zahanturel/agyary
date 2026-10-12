from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base


class AppNotification(Base):
    """Something a mobed needs to see the next time they open the app.

    Not the WhatsApp ``notifications`` queue, which is messages to behdins.
    These are for the mobed: a family replied STOP, a reminder could not be
    sent, a memorial is about to close. They are shown in a popup on open and
    can be revisited from the bell, and they lapse after a day - they are
    about what to do now, not a history.
    """

    __tablename__ = "app_notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    agyary_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agyaries.id"))

    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    # An app route to open from the notification ("#/behdins/4"), or none.
    link: Mapped[str | None] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set when the popup has shown it, so it is not shown on every open.
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_app_notifications_user", "user_id", "expires_at"),)
