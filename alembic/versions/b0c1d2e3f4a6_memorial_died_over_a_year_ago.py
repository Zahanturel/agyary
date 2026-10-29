"""Memorials for someone who died more than a year ago

Revision ID: b0c1d2e3f4a6
Revises: a9b0c1d2e3f4
Create Date: 2026-10-29 00:00:00.000000

Most behdins whose prayers a mobed keeps are old people, long departed, whose
monthly and yearly prayers have run for years. Their death is given by Roj and
Mah alone; the date and year stored for them are stand-ins that only place the
monthly and yearly days, so the memorial says so and they are never shown.
Existing memorials are all false (their dates are real).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b0c1d2e3f4a6"
down_revision: Union[str, None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memorials",
        sa.Column("died_over_a_year_ago", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("memorials", "died_over_a_year_ago")
