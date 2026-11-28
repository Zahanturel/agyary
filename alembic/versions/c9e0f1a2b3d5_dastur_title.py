"""Dastur is a title a name can carry

The four lists of allowed titles (saved names, a ceremony's names, a person's names, a Doongerwadi
record's departed) gain 'dastur', the high priest (owner, 29 Nov 2026). The downgrade calls a Dastur
Ervad, the nearest rank, and keeps every name and record: nothing is deleted (D8).

Revision ID: c9e0f1a2b3d5
Revises: b8d9e0f1a2c4
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c9e0f1a2b3d5"
down_revision: Union[str, None] = "b8d9e0f1a2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, constraint name)
LISTS = (
    ("customer_saved_names", "title", "ck_customer_saved_names_title"),
    ("ceremony_names", "title", "ck_ceremony_names_title"),
    ("person_names", "departed_title", "ck_person_names_departed_title"),
    ("funeral_records", "departed_title", "ck_funeral_records_departed_title"),
)
BEFORE = "'khud', 'osta', 'osti', 'ervad', 'behdin'"
AFTER = "'dastur', " + BEFORE


def _swap(titles: str) -> None:
    for table, column, name in LISTS:
        op.drop_constraint(op.f(name), table, type_="check")
        op.create_check_constraint(op.f(name), table, f"{column} IN ({titles})")


def upgrade() -> None:
    _swap(AFTER)


def downgrade() -> None:
    for table, column, _ in LISTS:
        op.execute(f"UPDATE {table} SET {column} = 'ervad' WHERE {column} = 'dastur'")
    _swap(BEFORE)
