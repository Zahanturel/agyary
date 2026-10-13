"""reminded by hand: the mobed told the family themselves

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-10-14 00:10:00.000000

A mobed can mark an observance as reminded in person or from their own phone.
The evening planner then sends nothing for it, so the family is not told twice.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memorial_observances", sa.Column("reminded_by_hand_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("memorial_observances", "reminded_by_hand_at")
