"""memorials: Parabs by number, and the 5th to 9th days

Parabs can now be chosen as a number of Parabs instead of a number of years
(parab_count; memorials saved earlier keep parab_years). The opening gains
'days_5_to_9'.

Revision ID: b0c1d2e3f4a5
Revises: a0b1c2d3e4f5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, None] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPENINGS_NEW = "'days_1_to_10', 'tenth_only', 'none', 'days_5_to_9'"
OPENINGS_OLD = "'days_1_to_10', 'tenth_only', 'none'"


def upgrade() -> None:
    op.add_column("memorials", sa.Column("parab_count", sa.SmallInteger()))
    op.drop_constraint("ck_memorials_parab_length", "memorials", type_="check")
    op.create_check_constraint(
        "ck_memorials_parab_length", "memorials",
        "(parabs IS NULL) = (parab_years IS NULL AND parab_count IS NULL)",
    )
    op.drop_constraint("ck_memorials_opening", "memorials", type_="check")
    op.create_check_constraint("ck_memorials_opening", "memorials", f"opening IN ({OPENINGS_NEW})")


def downgrade() -> None:
    op.execute("UPDATE memorials SET opening = 'none' WHERE opening = 'days_5_to_9'")
    op.drop_constraint("ck_memorials_opening", "memorials", type_="check")
    op.create_check_constraint("ck_memorials_opening", "memorials", f"opening IN ({OPENINGS_OLD})")
    op.drop_constraint("ck_memorials_parab_length", "memorials", type_="check")
    op.drop_column("memorials", "parab_count")
    op.create_check_constraint(
        "ck_memorials_parab_length", "memorials", "(parabs IS NULL) = (parab_years IS NULL)",
    )
