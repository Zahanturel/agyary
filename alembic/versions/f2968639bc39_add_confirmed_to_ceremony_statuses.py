"""add confirmed to ceremony statuses

Revision ID: f2968639bc39
Revises: b851d2238381
Create Date: 2026-07-23 05:57:05.725367

Additive CHECK-constraint value swap (per enums.py's own docstring: "adding
a value is an in-place constraint swap, never a type migration"). Adds
'confirmed' to CEREMONY_STATUSES for the redesign's auto-booked machi
status. Both machis.status and bookings.status carry the same shared
CHECK constraint (both models build it from the same CEREMONY_STATUSES
tuple), so both are updated here to keep the DB schema matching the ORM
metadata - bookings never actually take the 'confirmed' value in
application code (services keep a human accept/decline gate), but leaving
its constraint out of sync with the shared enum would just be a trap for
the next migration/autogenerate diff.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2968639bc39'
down_revision: Union[str, None] = 'b851d2238381'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_STATUSES = "'requested', 'approved', 'assigned', 'mobed_declined', 'completed', 'cancelled', 'declined', 'rescheduled'"
_NEW_STATUSES = "'requested', 'approved', 'assigned', 'mobed_declined', 'confirmed', 'completed', 'cancelled', 'declined', 'rescheduled'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_machis_status"), "machis", type_="check")
    op.create_check_constraint(op.f("ck_machis_status"), "machis", f"status IN ({_NEW_STATUSES})")
    op.drop_constraint(op.f("ck_bookings_status"), "bookings", type_="check")
    op.create_check_constraint(op.f("ck_bookings_status"), "bookings", f"status IN ({_NEW_STATUSES})")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_machis_status"), "machis", type_="check")
    op.create_check_constraint(op.f("ck_machis_status"), "machis", f"status IN ({_OLD_STATUSES})")
    op.drop_constraint(op.f("ck_bookings_status"), "bookings", type_="check")
    op.create_check_constraint(op.f("ck_bookings_status"), "bookings", f"status IN ({_OLD_STATUSES})")
