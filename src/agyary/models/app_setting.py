from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base


class AppSetting(Base):
    """A switch that has to change while the app is running.

    Configuration that needs a restart lives in the environment. This is for the
    few things an admin must be able to flip from their phone at once - chiefly
    the sending pause, the kill switch for reminders - and that must survive a
    restart rather than quietly reset to "running".
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
