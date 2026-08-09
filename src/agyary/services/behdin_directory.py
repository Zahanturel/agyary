"""Explicit behdin (customer) management, and their saved name pool.

Until now a Customer row only ever came into existence as a side effect of
saving a booking (``mobed_dashboard._resolve_customer``). That stays - a
walk-in dictated over the counter shouldn't require a separate "create the
person first" step - but it can't be the only way, because there was no
way to correct a mistyped number, or to set up a family's names ahead of
the day they book.

Scoping: a behdin is a global row keyed by phone (one person, one record,
however many fire temples they visit), but reachable here only through an
agyari the caller is a member of, via the agyary_customers junction. So
this exposes "the behdins of a temple I work at", never the whole
customer table.

The saved-name pool is the same ``customer_saved_names`` rows the WhatsApp
flows already read and write (booking_service.saved_pairs /
saved_farmayeshne / replace_saved_section), not a parallel copy. A behdin
who set their departed pair over WhatsApp should see the mobed reading it
back to them, and vice versa.
"""

from __future__ import annotations

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.messaging import booking_service
from agyary.models import AgyaryCustomer, Customer, CustomerSavedName, UserCustomer


class BehdinError(Exception):
    """Rejected behdin edit - message is safe to show the caller."""


def customer_summary(customer: Customer) -> dict:
    return {"id": customer.id, "name": customer.name, "phone": customer.phone}


async def is_linked(db: AsyncSession, agyary_id: int, customer_id: int) -> bool:
    result = await db.execute(
        select(AgyaryCustomer).where(
            AgyaryCustomer.agyary_id == agyary_id,
            AgyaryCustomer.customer_id == customer_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def owns(db: AsyncSession, user_id: int, customer_id: int) -> bool:
    """Whether this behdin is in this mobed's own book."""
    row = await db.get(UserCustomer, (user_id, customer_id))
    return row is not None


async def claim(db: AsyncSession, user_id: int, customer_id: int) -> None:
    """Record that this mobed deals with this behdin. Idempotent."""
    if not await owns(db, user_id, customer_id):
        db.add(UserCustomer(user_id=user_id, customer_id=customer_id))
        await db.flush()


async def get_scoped(
    db: AsyncSession, agyary_id: int, customer_id: int, user_id: int
) -> Customer | None:
    """A behdin, but only if they are BOTH one of this agyari's and one of
    this mobed's own.

    Both checks matter and neither is redundant. Agyari membership stops
    cross-tenant reads; ownership stops a mobed reading a colleague's
    behdins - names and phone numbers of people who never agreed to be
    visible to them. Enforced here rather than filtered in the UI, because
    a filtered list is not a permission.
    """
    customer = await db.get(Customer, customer_id)
    if customer is None:
        return None
    if not await is_linked(db, agyary_id, customer.id):
        return None
    if not await owns(db, user_id, customer.id):
        return None
    return customer


async def search_mine(
    db: AsyncSession, agyary_id: int, user_id: int, query: str, limit: int = 30
) -> list[Customer]:
    """This mobed's own behdins at this fire temple, optionally filtered.

    Not the temple's register. A behdin's name and phone number belong to
    them, not to everyone who happens to work at the same fire temple, so
    the list is scoped to the mobed who registered or served them. Includes
    someone registered moments ago and never booked for - which is exactly
    who you are looking for right after adding them, and which a
    booking-derived list cannot see.
    """
    q = query.strip()
    stmt = (
        select(Customer)
        .join(AgyaryCustomer, AgyaryCustomer.customer_id == Customer.id)
        .join(UserCustomer, UserCustomer.customer_id == Customer.id)
        .where(
            AgyaryCustomer.agyary_id == agyary_id,
            UserCustomer.user_id == user_id,
            Customer.is_active.is_(True),
        )
        .order_by(Customer.name)
        .limit(limit)
    )
    if q:
        stmt = stmt.where(or_(Customer.name.ilike(f"%{q}%"), Customer.phone.ilike(f"%{q}%")))
    return list((await db.execute(stmt)).scalars())


async def create_or_link(
    db: AsyncSession, agyary_id: int, user_id: int, *, name: str, phone: str
) -> tuple[Customer, bool]:
    """Register a behdin at this agyari. Returns (customer, created).

    Phone is globally unique and is the identity, so a number already on
    file resolves to that existing person and is linked to this agyari
    rather than rejected as a duplicate - the same rule
    ``_resolve_customer`` has always applied on the booking path, and the
    reason a behdin who moves between temples keeps one history.

    Their stored name is left alone in that case. A mobed typing a name
    they half-remember shouldn't quietly rename someone else's long-
    standing record; renaming is what the update endpoint is for.
    """
    name, phone = name.strip(), phone.strip()
    if not name:
        raise BehdinError("Name is required")

    existing = await booking_service.get_customer_by_phone(db, phone)
    created = existing is None
    customer = existing or await booking_service.create_customer(db, phone, name)

    # Link them to this agyari, but do NOT go through
    # booking_service.ensure_agyary_customer: that stamps first_booking_at,
    # which is true when a booking is what created the relationship and a
    # lie here. Registering someone is not the same as them having booked;
    # leaving it NULL keeps "known to us" and "has booked here" distinct,
    # and the booking path fills it in when a real one arrives.
    if not await is_linked(db, agyary_id, customer.id):
        db.add(AgyaryCustomer(agyary_id=agyary_id, customer_id=customer.id))
    # ...and into this mobed's own book, which is what the behdin list reads.
    await claim(db, user_id, customer.id)
    await db.flush()
    return customer, created


async def update(
    db: AsyncSession, customer: Customer, *, name: str | None = None, phone: str | None = None
) -> Customer:
    """Correct a behdin's name or number.

    Moving a number onto a person who already has their own record would
    merge two histories - refused here, because that is a decision with
    consequences (whose name wins? whose saved names?) and not something to
    infer from a typo-shaped edit.
    """
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise BehdinError("Name cannot be blank")
        customer.name = cleaned

    if phone is not None:
        cleaned = phone.strip()
        if not cleaned:
            raise BehdinError("Phone cannot be blank")
        if cleaned != customer.phone:
            clash = await booking_service.get_customer_by_phone(db, cleaned)
            if clash is not None:
                raise BehdinError(
                    "Another behdin is already registered with that number. "
                    "Open their record instead of moving the number."
                )
            customer.phone = cleaned

    await db.flush()
    return customer


# ---------------------------------------------------------------------------
# Saved name pool
# ---------------------------------------------------------------------------
def saved_name_summary(row: CustomerSavedName) -> dict:
    return {
        "id": row.id,
        "section": row.section,
        "title": row.title,
        "name": row.name,
        "status": row.status,
        "pair_group": row.pair_group,
        "display_order": row.display_order,
    }


async def list_saved_names(db: AsyncSession, customer_id: int) -> list[dict]:
    """The whole pool, both sections, in the order it's meant to be read."""
    rows = (
        await db.execute(
            select(CustomerSavedName)
            .where(CustomerSavedName.customer_id == customer_id)
            .order_by(
                CustomerSavedName.section,
                CustomerSavedName.pair_group,
                CustomerSavedName.display_order,
            )
        )
    ).scalars()
    return [saved_name_summary(r) for r in rows]


def validate_section_names(section: str, names: list[dict]) -> list[dict]:
    """Check a replacement section before it goes near the database.

    The one rule worth enforcing hard is that a 'pair' group holds exactly
    two names of the same status. ``complete_pairs`` already filters broken
    groups out when offering saved names back to a behdin, which means a
    half-pair written here doesn't error - it silently stops being offered,
    and the behdin quietly loses a name they thought they'd saved. Better
    to refuse to write it.
    """
    if section == "farmayeshne":
        for n in names:
            if n.get("pair_group") is not None:
                raise BehdinError("Farmayeshne names are singles and cannot belong to a pair")
            if n.get("status") != "living":
                raise BehdinError("Farmayeshne names are the living family - status must be 'living'")
        return names

    groups: dict[int, list[dict]] = {}
    for n in names:
        group = n.get("pair_group")
        if group is None:
            raise BehdinError("Every pair name must carry a pair_group")
        groups.setdefault(group, []).append(n)
    for group, members in groups.items():
        if len(members) != 2:
            raise BehdinError(
                f"A pair is exactly two names - pair {group} has {len(members)}"
            )
        if members[0].get("status") != members[1].get("status"):
            raise BehdinError(f"Both names in pair {group} must share the same status")
    return names


async def replace_section(
    db: AsyncSession, customer_id: int, section: str, names: list[dict]
) -> list[dict]:
    """Replace one section of the pool wholesale.

    Section-at-a-time rather than row-at-a-time because that is the shape
    the invariants live at: whether a pair is complete is a property of the
    set, not of a row, and 'New set' is already how the WhatsApp side
    thinks about this (booking_service.replace_saved_section, reused here
    rather than reimplemented).
    """
    validate_section_names(section, names)
    await booking_service.replace_saved_section(db, customer_id, section, names)
    await db.flush()
    return await list_saved_names(db, customer_id)


async def delete_saved_name(db: AsyncSession, customer_id: int, row_id: int) -> bool:
    """Remove a saved name; a paired one takes its partner with it.

    Deleting one half of a pair would leave exactly the orphan that
    ``complete_pairs`` exists to hide, so the pair goes as a unit - which
    is also what someone removing a departed couple from their list means.
    """
    row = await db.get(CustomerSavedName, row_id)
    if row is None or row.customer_id != customer_id:
        return False

    if row.section == "pair" and row.pair_group is not None:
        await db.execute(
            delete(CustomerSavedName).where(
                CustomerSavedName.customer_id == customer_id,
                CustomerSavedName.section == "pair",
                CustomerSavedName.pair_group == row.pair_group,
            )
        )
    else:
        await db.delete(row)
    await db.flush()
    return True
