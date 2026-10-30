"""Erasing a family, when they ask (LEG-04).

A family can ask us to remove them. A phone number is what identifies them, and
each mobed who serves them has a record of their own (D2), so erasing a number
reaches every mobed's book: the name and number, the saved names, the memorials,
the names recited at their ceremonies, the notes, and every message sent to them.

A ceremony that was performed is the mobed's history and a slip must still
print, so a record that events or payments point at stays, called "Erased", with
a number that can be nobody's. Only what says who they were goes. The one thing
kept is the STOP, if they sent one: it is how we go on honouring it (D2).

Nothing here runs by itself. No record is ever deleted because of its age (D8):
this happens only when an admin acts on a family's own request.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.models import (
    AgyaryCustomer,
    Booking,
    CeremonyName,
    Customer,
    CustomerSavedName,
    Machi,
    Memorial,
    Notification,
    Payment,
)
from agyary.services import reminders

ERASED = "Erased"
KIND_ERASED = "behdin_erased"


def _no_ones_number(customer_id: int) -> str:
    """+999 is no country's code, so this can never reach anyone. It stays
    unique within a mobed's book, and has the shape the database insists on."""
    return f"+999{customer_id:011d}"


async def _count(db: AsyncSession, model, *where) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


async def what_we_hold(db: AsyncSession, phone: str) -> dict:
    """Counts only, for the admin to see before erasing: no names."""
    ids = (await db.execute(select(Customer.id, Customer.owner_user_id).where(Customer.phone == phone))).all()
    records = [i for i, _owner in ids]
    return {
        "records": len(records),
        "mobeds": len({owner for _i, owner in ids if owner is not None}),
        "memorials": await _count(db, Memorial, Memorial.customer_id.in_(records)),
        "events": await _count(db, Machi, Machi.customer_id.in_(records))
        + await _count(db, Booking, Booking.customer_id.in_(records)),
        "messages": await _count(db, Notification, _sent_to(phone, records)),
    }


def _sent_to(phone: str, records: list[int]):
    return (Notification.recipient_type == "customer") & or_(
        Notification.recipient_phone == phone, Notification.recipient_id.in_(records)
    )


async def _erase_record(db: AsyncSession, customer_id: int) -> None:
    """Everything that says who this record's family were. Ends with the record
    gone, or called Erased if an event or payment still points at it."""
    machis = select(Machi.id).where(Machi.customer_id == customer_id)
    bookings = select(Booking.id).where(Booking.customer_id == customer_id)
    await db.execute(delete(Memorial).where(Memorial.customer_id == customer_id))  # its dates cascade
    await db.execute(delete(CustomerSavedName).where(CustomerSavedName.customer_id == customer_id))
    await db.execute(delete(CeremonyName).where(or_(
        CeremonyName.machi_id.in_(machis), CeremonyName.booking_id.in_(bookings)
    )))
    await db.execute(update(Machi).where(Machi.customer_id == customer_id).values(notes=None))
    await db.execute(update(Booking).where(Booking.customer_id == customer_id).values(notes=None, location=None))
    await db.execute(update(Payment).where(Payment.customer_id == customer_id).values(notes=None))

    still_needed = 0
    for model in (Machi, Booking, Payment):
        still_needed += await _count(db, model, model.customer_id == customer_id)
    if still_needed:
        await db.execute(update(Customer).where(Customer.id == customer_id).values(
            name=ERASED, phone=_no_ones_number(customer_id), is_active=False, reminders_enabled=False,
            reminders_enabled_at=None, reminders_consent_version=None, reminders_stopped_at=None,
        ))
    else:
        await db.execute(delete(AgyaryCustomer).where(AgyaryCustomer.customer_id == customer_id))
        await db.execute(delete(Customer).where(Customer.id == customer_id))


async def erase_number(db: AsyncSession, phone: str, *, now: datetime | None = None) -> dict:
    """Erase ``phone`` from every mobed's book, and tell each of them that it
    happened. Returns what was held. The caller commits."""
    found = await what_we_hold(db, phone)
    rows = (await db.execute(select(Customer.id, Customer.owner_user_id).where(Customer.phone == phone))).all()
    await db.execute(delete(Notification).where(_sent_to(phone, [i for i, _owner in rows])))
    for customer_id, _owner in rows:
        await _erase_record(db, customer_id)
    for owner in {owner for _i, owner in rows if owner is not None}:
        await reminders.notify(
            db, owner, KIND_ERASED, "A family's details were erased",
            "At their request, a family's name, number, memorials and prayer names were removed from your "
            "book. Any past events stay on your calendar, marked Erased.",
            now=now,
        )
    return found
