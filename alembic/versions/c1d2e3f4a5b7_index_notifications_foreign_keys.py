"""Index the send log's links to observances, machis and bookings

Revision ID: c1d2e3f4a5b7
Revises: b0c1d2e3f4a6
Create Date: 2026-10-30 00:00:00.000000

Deleting a memorial sets notifications.memorial_observance_id to NULL for each
of its dates (up to 2,500), and deleting a machi or booking checks the send log
for rows that still point at it. None of these columns had an index Postgres
could use for that (the one on memorial_observance_id is partial, for
reminders only), so each step scanned the whole send log, which is never
trimmed. With 100,000 rows, deleting a 2,500-date memorial took 74 s; with
these indexes it takes well under a second (audit 30 Oct 2026, DB-02).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b7"
down_revision: Union[str, None] = "b0c1d2e3f4a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = (
    ("idx_notifications_observance", "memorial_observance_id"),
    ("idx_notifications_machi", "machi_id"),
    ("idx_notifications_booking", "booking_id"),
)


def upgrade() -> None:
    for name, column in _INDEXES:
        op.create_index(name, "notifications", [column], unique=False,
                        postgresql_where=sa.text(f"{column} IS NOT NULL"))


def downgrade() -> None:
    for name, _column in _INDEXES:
        op.drop_index(name, table_name="notifications")
