"""users: the daily report switch

A boolean on each user, off for everyone: a mobed turns it on in Settings to be told,
the evening before, what is on their day tomorrow. Additive only.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("daily_report", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("users", "daily_report")
