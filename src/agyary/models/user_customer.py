from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from agyary.core.database import Base


class UserCustomer(Base):
    """A mobed's own behdin book: which behdins THIS mobed deals with.

    A behdin is a global row keyed by phone - one person, one record,
    however many fire temples they visit. But knowing them is personal. A
    mobed's behdins are the people they have registered or performed for,
    and are nobody else's business: names and phone numbers of third
    parties who never agreed to be visible to a stranger who happens to
    work at the same fire temple.

    This exists because ownership could not previously be expressed at all.
    It was inferred from ``created_by_user_id`` on machis and bookings,
    which says nothing about a behdin registered ahead of any ceremony -
    so "my behdins" could not include someone entered five minutes ago,
    and the only list that could be built was the whole temple's.

    Deliberately not scoped by agyari: a mobed who serves at two fire
    temples keeps one address book. The API still checks agyari membership
    separately, so both scopes have to hold.
    """

    __tablename__ = "user_customers"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_user_customers_customer", "customer_id"),)
