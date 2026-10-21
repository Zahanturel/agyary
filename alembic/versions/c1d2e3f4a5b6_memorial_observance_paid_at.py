"""memorial dates: the mobed's paid tick

A nullable timestamp on each memorial observance: when the mobed marked that date as
paid. Additive only - existing rows are simply "not paid".

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("memorial_observances", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("memorial_observances", "paid_at")
