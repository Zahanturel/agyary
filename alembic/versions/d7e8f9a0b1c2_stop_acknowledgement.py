"""stop acknowledgement: when the one kind reply to a STOP went

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-10-14 00:00:00.000000

A family's first STOP gets one short reply naming their mobed. Kept on the
opt-out row, so a number that had already stopped never gets a second, and the
day's replies can be counted against their own cap.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reminder_opt_outs", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("reminder_opt_outs", "acknowledged_at")
