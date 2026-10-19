"""memorials: Roj Fravardin every month, as a repeating option

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("memorials", sa.Column("fravardin_roj_months", sa.SmallInteger()))
    op.create_check_constraint(
        "ck_memorials_fravardin_roj_length", "memorials",
        "fravardin_roj_months IS NULL OR fravardin_roj_months >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_memorials_fravardin_roj_length", "memorials", type_="check")
    op.drop_column("memorials", "fravardin_roj_months")
