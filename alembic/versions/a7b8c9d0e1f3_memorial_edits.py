"""memorials can be edited: one date moved or removed, or the whole memorial re-worked

A memorial now remembers what it needs to be re-worked later without undoing the
mobed's own changes:

- ``memorials.start_from``: nothing is booked before this date (a family arriving
  late, or a death more than a year ago, which runs from the day it was made).
- ``memorials.removed_codes``: the dates the mobed took out, on the review screen
  or one at a time afterwards, so a re-work does not bring them back. NULL for a
  memorial saved before this: both are then worked out from its dates the first
  time it is edited (services/memorials.edit_basis).
- ``memorial_observances.moved_by_hand``: the mobed moved this date to another
  day; a re-work leaves it where they put it.

Revision ID: a7b8c9d0e1f3
Revises: e6f7a8b9c0d2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f3"
down_revision: Union[str, None] = "e6f7a8b9c0d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("memorials", sa.Column("start_from", sa.Date()))
    op.add_column("memorials", sa.Column("removed_codes", postgresql.JSONB()))
    op.add_column(
        "memorial_observances",
        sa.Column("moved_by_hand", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("memorial_observances", "moved_by_hand")
    op.drop_column("memorials", "removed_codes")
    op.drop_column("memorials", "start_from")
