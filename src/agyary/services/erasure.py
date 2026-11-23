"""Erasing a family, when they ask (LEG-04).

A family can ask us to remove them. A phone number is what identifies them, and
each mobed who serves them has a record of their own (D2), so erasing a number
reaches every mobed's book: the name and number, the saved names, the memorials,
the names recited at their ceremonies, the notes, and every message sent to them.

A Doongerwadi's funeral record that named them as the family's contact keeps the
death (the place's record, D8) but loses the contact's name and number, and a
funeral place's book of behdins loses them altogether (19 Nov 2026). The record
of the WhatsApp messages about that record's requests - the details to the
mobeds going and the panthaky, which carry the family's name - keeps the fact
that they went but not the name (the number was never kept in them).

A number a panthaky added by hand to a fire temple's list of mobeds (D10) is
taken off the list, kept as a row (D8) without the name or number, and so are
their answers to its requests and the record of messages to them.

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
    AgyaryMobedContact,
    Booking,
    CeremonyName,
    Customer,
    CustomerSavedName,
    FuneralBehdin,
    FuneralRecord,
    Machi,
    Memorial,
    FuneralRequest,
    Notification,
    Payment,
    PersonName,
    PrayerCalloutAnswer,
)
from agyary.services import funeral_whatsapp, reminders

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
        "funeral_records": await _count(db, FuneralRecord, FuneralRecord.family_contact_phone == phone),
        "funeral_books": await _count(db, FuneralBehdin, FuneralBehdin.phone == phone),
        # On a fire temple's list of mobeds, added by hand (D10).
        "mobed_contacts": await _count(db, AgyaryMobedContact, AgyaryMobedContact.phone == phone,
                                       AgyaryMobedContact.is_active.is_(True)),
    }


def _sent_to(phone: str, records: list[int]):
    return or_(
        (Notification.recipient_type == "customer")
        & or_(Notification.recipient_phone == phone, Notification.recipient_id.in_(records)),
        # A family messaged from a Doongerwadi's request (D10, Step 5b).
        (Notification.recipient_type == "family") & (Notification.recipient_phone == phone),
        # A mobed a panthaky added by hand, asked on WhatsApp (D10).
        (Notification.recipient_type == "contact") & (Notification.recipient_phone == phone),
    )


async def _blank_family_name(db: AsyncSession, record_ids: list[int]) -> None:
    """The family's name in what is kept of the WhatsApp messages about these
    funeral records' requests (templates 1-3 and 5-8: the details to the
    mobeds going and to the panthaky name the family's contact). The fact that
    each went stays; the number in them was never kept ("[number]")."""
    if not record_ids:
        return
    names = {n for n in (await db.execute(
        select(FuneralRecord.family_contact_name).where(FuneralRecord.id.in_(record_ids))
    )).scalars() if n}
    names |= {funeral_whatsapp.clean(n) for n in names}
    names.discard("")
    request_ids = [str(i) for i in (await db.execute(
        select(FuneralRequest.id).where(FuneralRequest.funeral_record_id.in_(record_ids))
    )).scalars()]
    if not names or not request_ids:
        return
    rows = (await db.execute(select(Notification).where(
        Notification.notification_type.in_(funeral_whatsapp.TYPES),
        Notification.template_params["request"].astext.in_(request_ids),
    ))).scalars().all()
    for n in rows:
        params = dict(n.template_params or {})
        blanks = {k: ERASED for k, v in params.items() if k.isdigit() and v in names}
        if blanks:
            n.template_params = {**params, **blanks}
    await db.flush()


async def _erase_mobed_contact(db: AsyncSession, phone: str) -> None:
    """A number a panthaky added by hand to a fire temple's list of mobeds:
    off the list, the row kept (D8) without the name or number, as their
    answers to its requests are (the fire temple's record, like a deleted
    account's)."""
    contacts = (await db.execute(
        select(AgyaryMobedContact.id).where(AgyaryMobedContact.phone == phone)
    )).scalars().all()
    for contact_id in contacts:
        await db.execute(update(AgyaryMobedContact).where(AgyaryMobedContact.id == contact_id).values(
            name=ERASED, phone=_no_ones_number(contact_id), is_active=False, user_id=None,
        ))
    await db.execute(update(PrayerCalloutAnswer).where(
        PrayerCalloutAnswer.phone == phone, PrayerCalloutAnswer.user_id.is_(None),
    ).values(name=ERASED, phone=None))


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
    # The family contact on a funeral record (D10). The column is required, so
    # it is given a number that can be nobody's, as a kept behdin record is.
    funeral = (await db.execute(
        select(FuneralRecord.id).where(FuneralRecord.family_contact_phone == phone)
    )).scalars().all()
    # Their name, first, in what is kept of the messages about those records' requests.
    await _blank_family_name(db, list(funeral))
    for record_id in funeral:
        await db.execute(update(FuneralRecord).where(FuneralRecord.id == record_id).values(
            family_contact_name=ERASED, family_contact_phone=_no_ones_number(record_id),
        ))
    # A funeral place's book of behdins: the family's name and number, nothing more.
    await db.execute(delete(FuneralBehdin).where(FuneralBehdin.phone == phone))
    # The departed's names kept for this person's number (D12): the whole pool goes.
    await db.execute(delete(PersonName).where(PersonName.phone == phone))
    # A fire temple's list of mobeds, if a panthaky added the number by hand (D10).
    await _erase_mobed_contact(db, phone)
    for owner in {owner for _i, owner in rows if owner is not None}:
        await reminders.notify(
            db, owner, KIND_ERASED, "A family's details were erased",
            "At their request, a family's name, number, memorials and prayer names were removed from your "
            "book. Any past events stay on your calendar, marked Erased.",
            now=now,
        )
    return found
