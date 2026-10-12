"""Explicit behdin (customer) management, and their saved name pool.

Until now a Customer row only ever came into existence as a side effect of
saving a booking (``mobed_dashboard._resolve_customer``). That stays - a
walk-in dictated over the counter shouldn't require a separate "create the
person first" step - but it can't be the only way, because there was no
way to correct a mistyped number, or to set up a family's names ahead of
the day they book.

Scoping (docs/DECISIONS.md D2): a behdin record is one mobed's own. Two
mobeds who serve the same family each keep a record with the same number,
and nothing about one is visible to, or changeable by, the other - typing a
number a colleague already has makes a record of one's own and reveals
nothing. Within one mobed's book the number is the identity: one record per
number, however many fire temples they visit with that mobed. A record is
also reachable only through an agyari the caller is a member of, via the
agyary_customers junction.

The saved-name pool is the same ``customer_saved_names`` rows the booking
core reads and writes (booking_service.saved_pairs / saved_farmayeshne /
replace_saved_section), not a parallel copy - and, being keyed by the
record, it is that mobed's own too.
"""

from __future__ import annotations

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.messaging import booking_service
from agyary.models import (
    AgyaryCustomer,
    Booking,
    Customer,
    CustomerSavedName,
    Machi,
    Memorial,
    Payment,
    ReminderOptOut,
)


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


def owns(user_id: int, customer: Customer | None) -> bool:
    """Whether this record is in this mobed's own book."""
    return customer is not None and customer.owner_user_id == user_id


async def get_scoped(
    db: AsyncSession, agyary_id: int, customer_id: int, user_id: int
) -> Customer | None:
    """A behdin, but only if they are BOTH one of this agyari's and this
    mobed's own record, and still in their book.

    Both checks matter and neither is redundant. Agyari membership stops
    cross-tenant reads; ownership stops a mobed reading a colleague's
    behdins - names and phone numbers of people who never agreed to be
    visible to them. Enforced here rather than filtered in the UI, because
    a filtered list is not a permission.
    """
    customer = await db.get(Customer, customer_id)
    if not owns(user_id, customer) or not customer.is_active:
        return None
    if not await is_linked(db, agyary_id, customer.id):
        return None
    return customer


async def search_mine(
    db: AsyncSession, agyary_id: int, user_id: int, query: str, limit: int = 30
) -> list[Customer]:
    """This mobed's own behdins at this fire temple, optionally filtered.

    Not the temple's register. A behdin's name and phone number belong to
    them, not to everyone who happens to work at the same fire temple, so
    the list is the mobed's own records. Includes someone registered moments
    ago and never booked for - which is exactly who you are looking for right
    after adding them, and which a booking-derived list cannot see.
    """
    q = query.strip()
    stmt = (
        select(Customer)
        .join(AgyaryCustomer, AgyaryCustomer.customer_id == Customer.id)
        .where(
            AgyaryCustomer.agyary_id == agyary_id,
            Customer.owner_user_id == user_id,
            Customer.is_active.is_(True),
        )
        .order_by(Customer.name)
        .limit(limit)
    )
    if q:
        stmt = stmt.where(or_(Customer.name.ilike(f"%{q}%"), Customer.phone.ilike(f"%{q}%")))
    return list((await db.execute(stmt)).scalars())


async def resolve_own(db: AsyncSession, user_id: int, phone: str, name: str) -> tuple[Customer, bool]:
    """This mobed's record of ``phone``: the one they already have (back in
    their book if they had removed it), or a new one under the typed name.
    Returns (customer, created). Another mobed's record of the same number is
    never looked at - it is theirs, and this one is not linked to it."""
    existing = await booking_service.get_customer_by_phone(db, user_id, phone)
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            await db.flush()
        return existing, False
    return await booking_service.create_customer(db, user_id, phone, name), True


async def create_or_link(
    db: AsyncSession, agyary_id: int, user_id: int, *, name: str, phone: str
) -> tuple[Customer, bool]:
    """Register a behdin at this agyari. Returns (customer, created).

    Within one mobed's book the number is the identity, so a number they
    already have resolves to their existing record and is linked to this
    agyari rather than rejected as a duplicate - the same rule
    ``_resolve_customer`` applies on the booking path, and the reason a
    behdin who moves between temples keeps one history with their mobed.
    The stored name is left alone in that case; renaming is what the update
    endpoint is for. A number only a colleague has is a new record.
    """
    name, phone = name.strip(), phone.strip()
    if not name:
        raise BehdinError("Name is required")

    customer, created = await resolve_own(db, user_id, phone, name)

    # Link them to this agyari, but do NOT go through
    # booking_service.ensure_agyary_customer: that stamps first_booking_at,
    # which is true when a booking is what created the relationship and a
    # lie here. Registering someone is not the same as them having booked;
    # leaving it NULL keeps "known to us" and "has booked here" distinct,
    # and the booking path fills it in when a real one arrives.
    if not await is_linked(db, agyary_id, customer.id):
        db.add(AgyaryCustomer(agyary_id=agyary_id, customer_id=customer.id))
    await db.flush()
    return customer, created


async def update(
    db: AsyncSession, customer: Customer, *, name: str | None = None, phone: str | None = None
) -> Customer:
    """Correct a behdin's name or number, in this mobed's own record.

    Moving a number onto a behdin the same mobed already keeps under that
    number would merge two histories - refused here, because that is a
    decision with consequences (whose name wins? whose saved names?) and not
    something to infer from a typo-shaped edit. A colleague's record of the
    number is no obstacle and is not touched.
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
            clash = await booking_service.get_customer_by_phone(db, customer.owner_user_id, cleaned)
            if clash is not None:
                raise BehdinError(
                    "You already have a behdin with that number. "
                    "Open their record instead of moving the number."
                )
            customer.phone = cleaned
            # A number that replied STOP stays stopped under any record. (A STOP
            # already on this record is never lifted by a change of number.)
            opt_out = await db.get(ReminderOptOut, cleaned)
            if opt_out is not None and customer.reminders_stopped_at is None:
                customer.reminders_stopped_at = opt_out.stopped_at

    await db.flush()
    return customer


async def remove_from_book(db: AsyncSession, customer: Customer) -> bool:
    """Take a behdin out of this mobed's book. Returns True if the record was
    erased outright, False if it was only taken out of the list.

    Their events are kept either way - a ceremony that was performed is
    history, and a slip must still print after the behdin is gone from the
    list. That is also why the record often cannot go: bookings and machis
    point at it (customer_id is required), so it stays, unlisted and with
    reminders off, holding the number. Adding the same number again brings
    them straight back, history and all, which is the right outcome for an
    accidental delete - but reminders stay off until the mobed asks again.

    The record is erased only when nothing refers to it: no event, memorial
    or payment. Then its saved names go with it (those cascade).
    """
    references = 0
    for model in (Booking, Machi, Memorial, Payment):
        references += (
            await db.execute(
                select(func.count()).select_from(model).where(model.customer_id == customer.id)
            )
        ).scalar_one()
    if references:
        customer.is_active = False
        customer.reminders_enabled = False
        customer.reminders_enabled_at = None
        await db.flush()
        return False

    await db.execute(delete(AgyaryCustomer).where(AgyaryCustomer.customer_id == customer.id))
    await db.delete(customer)
    await db.flush()
    return True


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
    """The whole pool, both sections, in the order it's meant to be read.

    By display_order, which is the order the mobed arranged the pairs in -
    the first pair is prayed first. pair_group only says which rows belong
    together; it says nothing about which pair comes first, and ordering by it
    would silently undo any reordering."""
    rows = (
        await db.execute(
            select(CustomerSavedName)
            .where(CustomerSavedName.customer_id == customer_id)
            .order_by(CustomerSavedName.section, CustomerSavedName.display_order)
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


def _pair_key(status: str, members: list[dict]) -> tuple:
    return (status, tuple((m["title"], m["name"].strip().casefold()) for m in members))


async def merge_saved_names(db: AsyncSession, customer_id: int, names: list[dict]) -> dict:
    """Remember the names an event was booked with, without disturbing what the
    behdin already has.

    Names typed on an event's review screen used to live and die with that one
    event, so a mobed who added pairs for the same family each time started
    from nothing every time. This adds whatever is NEW to the behdin's saved
    names and leaves the rest alone: nothing is removed or reordered, a pair or
    name already saved is not added twice, and a pair dropped from one event
    (say, a single-pair Patet) stays in the family's list.
    """
    current = await list_saved_names(db, customer_id)

    have_groups: dict[int, list[dict]] = {}
    for row in current:
        if row["section"] == "pair" and row["pair_group"] is not None:
            have_groups.setdefault(row["pair_group"], []).append(row)
    have_pairs = {_pair_key(g[0]["status"], g) for g in have_groups.values() if len(g) == 2}
    have_singles = {
        (r["title"], r["name"].strip().casefold()) for r in current if r["section"] == "farmayeshne"
    }

    incoming: dict[int, list[dict]] = {}
    for row in names:
        if row.get("section") == "pair" and row.get("pair_group") is not None and row["name"].strip():
            incoming.setdefault(row["pair_group"], []).append(row)

    next_group = max(have_groups, default=0) + 1
    new_pair_rows: list[dict] = []
    added_pairs = 0
    for members in incoming.values():
        if len(members) != 2 or members[0]["status"] != members[1]["status"]:
            continue   # a half-filled pair is not something to remember
        key = _pair_key(members[0]["status"], members)
        if key in have_pairs:
            continue
        have_pairs.add(key)
        for m in members:
            new_pair_rows.append({"title": m["title"], "name": m["name"].strip(),
                                  "status": m["status"], "pair_group": next_group})
        next_group += 1
        added_pairs += 1

    new_single_rows = []
    for row in names:
        if row.get("section") != "farmayeshne" or not row["name"].strip():
            continue
        key = (row["title"], row["name"].strip().casefold())
        if key in have_singles:
            continue
        have_singles.add(key)
        new_single_rows.append({"title": row["title"], "name": row["name"].strip(),
                                "status": "living", "pair_group": None})

    def keep(section: str) -> list[dict]:
        return [
            {"title": r["title"], "name": r["name"], "status": r["status"], "pair_group": r["pair_group"]}
            for r in current if r["section"] == section
        ]

    if new_pair_rows:
        await replace_section(db, customer_id, "pair", keep("pair") + new_pair_rows)
    if new_single_rows:
        await replace_section(db, customer_id, "farmayeshne", keep("farmayeshne") + new_single_rows)
    return {"added_pairs": added_pairs, "added_names": len(new_single_rows)}


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
