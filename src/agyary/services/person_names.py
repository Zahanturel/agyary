"""The departed's names that follow a person, by phone number (DECISIONS D12,
"Departed names for the family", 24 Nov 2026; models/person_name.py).

Written when a Doongerwadi manager records a death (and kept in step when the
record's names or number are edited): one row per record, for the family
contact's number, if the departed's name or the father's or husband's name is
not empty. Read by exactly one reader: the account that signs in with that
number (``mine``, by the account's own phone). Nothing here takes a phone from
a caller, and no other screen may read the pool. A mobed receives names only as
copies in their own book, at All set (``copy_into_book``), for a request they
are assigned to.

Nothing is deleted because of its age (D8); only erasure and account deletion
remove rows."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.models import FuneralRecord, PersonName, User
from agyary.services import behdin_directory

SOURCE_DEATH_RECORD = "death_record"
# +999 is no country's code: a number erased from a record (services/erasure.py).
# The father's or husband's name has no title of its own on a death record.
PARENT_TITLE = "behdin"


async def sync_from_record(db: AsyncSession, record: FuneralRecord) -> None:
    """Make the record's own row say what the record says now: added if there
    is a name to keep, changed if it is there already (never a second row),
    gone if both names have been emptied. Not committed here."""
    name = (record.departed_name or "").strip()
    parent = (record.departed_parent_name or "").strip()
    row = (await db.execute(select(PersonName).where(
        PersonName.source == SOURCE_DEATH_RECORD, PersonName.source_record_id == record.id,
    ))).scalars().first()
    if (not name and not parent) or record.family_contact_phone.startswith("+999"):
        if row is not None:
            await db.delete(row)
            await db.flush()
        return
    if row is None:
        row = PersonName(source=SOURCE_DEATH_RECORD, source_record_id=record.id)
        db.add(row)
    row.phone = record.family_contact_phone
    row.departed_title = record.departed_title
    row.departed_name = name
    row.departed_parent_name = parent or None
    await db.flush()


async def mine(db: AsyncSession, user: User) -> list[PersonName]:
    """The signed-in account's own pool, by the account's own number, newest first."""
    return list((await db.execute(
        select(PersonName).where(PersonName.phone == user.phone)
        .order_by(PersonName.created_at.desc(), PersonName.id.desc())
    )).scalars().all())


def as_dict(row: PersonName) -> dict:
    return {
        "id": row.id,
        "departed_title": row.departed_title,
        "departed_name": row.departed_name,
        "departed_parent_name": row.departed_parent_name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def copy_into_book(db: AsyncSession, customer_id: int, record: FuneralRecord) -> bool:
    """The departed pair of this record, on TOP of the family's saved names in
    one mobed's OWN book (their ``customers`` record): the departed and the
    father or husband, both departed, as the first pair. Only when both names
    exist (a pair is exactly two names). A pair already saved with the same
    names stays where it is: it is not added twice, so All set running again
    changes nothing. Returns whether a pair was added. Not committed here."""
    name = (record.departed_name or "").strip()
    parent = (record.departed_parent_name or "").strip()
    if not name or not parent:
        return False
    pair = [
        {"title": record.departed_title, "name": name, "status": "departed"},
        {"title": PARENT_TITLE, "name": parent, "status": "departed"},
    ]
    current = await behdin_directory.list_saved_names(db, customer_id)
    groups: dict[int, list[dict]] = {}
    for row in current:
        if row["section"] == "pair" and row["pair_group"] is not None:
            groups.setdefault(row["pair_group"], []).append(row)
    key = behdin_directory._pair_key("departed", pair)
    if any(len(g) == 2 and behdin_directory._pair_key(g[0]["status"], g) == key for g in groups.values()):
        return False
    top = max(groups, default=0) + 1
    keep = [{"title": r["title"], "name": r["name"], "status": r["status"], "pair_group": r["pair_group"]}
            for r in current if r["section"] == "pair"]
    await behdin_directory.replace_section(
        db, customer_id, "pair", [{**p, "pair_group": top} for p in pair] + keep,
    )
    return True
