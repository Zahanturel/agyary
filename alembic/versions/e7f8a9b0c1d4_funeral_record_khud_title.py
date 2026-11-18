"""A funeral record's departed may have the title Khud

DECISIONS D10, changed 19 Nov 2026 (owner, after trying it): the departed's
title offers Khud too, like the rest of the app. Only the check on
``funeral_records.departed_title`` changes.

The downgrade has no Khud: a record saved with it keeps its death and family
(D8) and is called Behdin, the title the form starts with.

Revision ID: e7f8a9b0c1d4
Revises: d6e7f8a9b0c2
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e7f8a9b0c1d4"
down_revision: Union[str, None] = "d6e7f8a9b0c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_funeral_records_departed_title"), "funeral_records", type_="check")
    op.create_check_constraint(
        op.f("ck_funeral_records_departed_title"), "funeral_records",
        "departed_title IN ('ervad', 'osta', 'osti', 'behdin', 'khud')",
    )


def downgrade() -> None:
    op.execute("UPDATE funeral_records SET departed_title = 'behdin' WHERE departed_title = 'khud'")
    op.drop_constraint(op.f("ck_funeral_records_departed_title"), "funeral_records", type_="check")
    op.create_check_constraint(
        op.f("ck_funeral_records_departed_title"), "funeral_records",
        "departed_title IN ('ervad', 'osta', 'osti', 'behdin')",
    )
