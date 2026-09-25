"""Store every behdin's number in one shape, and enforce it

Revision ID: f7a8b9c0d1e2
Revises: e4f5a6b7c8d9
Create Date: 2026-09-25 00:00:00.000000

A behdin is identified by their number (customers.phone is already UNIQUE),
but "unique" only compares strings. "+919876543210", "919876543210" and
"+9109876543210" are one person written three ways, and the database would
happily hold all three as three behdins - each with its own history and saved
names, and no way to notice.

This rewrites every existing number into the one stored shape (E.164 with the
"+", no spaces, no trunk 0 after the country code) and then adds a CHECK so
nothing else can be written afterwards. The API normalises on the way in
(services/phone.py); this is the backstop for any other writer.

WHAT HAPPENS TO EXISTING ROWS
  * A number that normalises to itself is untouched.
  * A bare 10-digit number starting 6-9 is taken to be Indian and gets +91,
    the same assumption the app makes when importing contacts.
  * Any other bare number just gains the "+".
  * If two rows normalise to the SAME number they are the same person entered
    twice, and merging two behdins' histories is not something a migration
    should decide. The migration STOPS, before changing anything, and lists
    the row ids. Merge them by hand, then run it again.
  * A number that still is not valid E.164 after this (too short, letters) is
    also reported and stops the migration, rather than being deleted or
    guessed at.

No row is ever deleted.

Read-only check before running this anywhere that matters:
    select id, phone from customers where phone !~ '^\\+[1-9][0-9]{7,14}$';
"""
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# A frozen copy of services/phone.normalize_phone. Migrations must not import
# application code: it changes, and this has to mean the same thing forever.
_CODES = (
    "971", "852", "966", "968", "965", "974",
    "91", "98", "92", "94", "44", "61", "64", "65", "86", "81", "82",
    "49", "33", "39", "34", "27", "20", "60", "66", "63",
    "1", "7",
)
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _normalise(value: str) -> str:
    cleaned = re.sub(r"[\s\-().]", "", value.strip())
    if not cleaned.startswith("+"):
        digits = cleaned.lstrip("0") if len(cleaned) != 10 else cleaned
        cleaned = "+91" + digits if len(digits) == 10 and digits[:1] in "6789" else "+" + digits
    digits = cleaned[1:]
    for code in _CODES:
        if digits.startswith(code):
            return "+" + code + digits[len(code):].lstrip("0")
    return cleaned


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, phone FROM customers ORDER BY id")).all()

    target = {row.id: _normalise(row.phone) for row in rows}

    invalid = sorted(i for i, p in target.items() if not _E164.match(p))
    if invalid:
        raise RuntimeError(
            "customers with a number that is not valid E.164 even after cleaning "
            f"(ids {invalid}). Fix them by hand, then re-run."
        )

    seen: dict[str, list[int]] = {}
    for i, p in target.items():
        seen.setdefault(p, []).append(i)
    clashes = sorted(ids for ids in seen.values() if len(ids) > 1)
    if clashes:
        raise RuntimeError(
            "these customers are the same number written differently and would "
            f"collide once normalised (ids {clashes}). Merge each group by hand "
            "(re-point their bookings/machis/saved names to one, delete the "
            "other), then re-run."
        )

    for row in rows:
        if target[row.id] != row.phone:
            bind.execute(
                sa.text("UPDATE customers SET phone = :p WHERE id = :i"),
                {"p": target[row.id], "i": row.id},
            )

    # Named without the "ck_customers_" prefix: the metadata naming convention
    # adds it, and passing it here too would double it.
    op.create_check_constraint(
        "phone_e164", "customers", r"phone ~ '^\+[1-9][0-9]{7,14}$'"
    )


def downgrade() -> None:
    # The normalised numbers stay as they are - the old spellings are not
    # recoverable and were never meaningful.
    op.drop_constraint("phone_e164", "customers", type_="check")
