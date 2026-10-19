"""memorials: a birthday series, and no mandatory opening

The opening (days 1-10) is no longer offered: the Dasmi is chosen among the
named days like the Deci and Masiso, so a memorial may have no opening at all
('none'). Memorials saved with the earlier openings keep them.

A memorial may also repeat the deceased's birthday, by Roj and Mah, for some
years.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "'days_1_to_10', 'tenth_only'"
NEW = "'days_1_to_10', 'tenth_only', 'none'"


def upgrade() -> None:
    op.drop_constraint("ck_memorials_opening", "memorials", type_="check")
    op.create_check_constraint("ck_memorials_opening", "memorials", f"opening IN ({NEW})")
    op.add_column("memorials", sa.Column("birthday_roj", sa.SmallInteger()))
    op.add_column("memorials", sa.Column("birthday_mah", sa.SmallInteger()))
    op.add_column("memorials", sa.Column("birthday_years", sa.SmallInteger()))
    op.create_check_constraint(
        "ck_memorials_birthday_whole", "memorials",
        "(birthday_roj IS NULL) = (birthday_mah IS NULL) AND (birthday_roj IS NULL) = (birthday_years IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_memorials_birthday_whole", "memorials", type_="check")
    op.drop_column("memorials", "birthday_years")
    op.drop_column("memorials", "birthday_mah")
    op.drop_column("memorials", "birthday_roj")
    op.execute("UPDATE memorials SET opening = 'tenth_only' WHERE opening = 'none'")
    op.drop_constraint("ck_memorials_opening", "memorials", type_="check")
    op.create_check_constraint("ck_memorials_opening", "memorials", f"opening IN ({OLD})")
