"""agyary status (unclaimed/active) + auto_booking_enabled

Revision ID: a1b2c3d4e5f6
Revises: 55a2a2c34be8
Create Date: 2026-07-25 00:00:00.000000

Mobed-only v0: distinguish a seeded-but-unclaimed agyari from one a real
mobed has set up. 'status' is separate from is_active on purpose (existence
vs having-been-set-up are different facts). Existing rows default to
'active' via server_default, so nothing already in the DB is treated as an
unclaimed seed entry. auto_booking_enabled is schema-only this pass (the
parked WhatsApp behdin self-service toggle) - added now to avoid a second
agyari migration later.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '55a2a2c34be8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agyaries",
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
    )
    op.add_column(
        "agyaries",
        sa.Column(
            "auto_booking_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_agyaries_status"), "agyaries", "status IN ('unclaimed', 'active')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_agyaries_status"), "agyaries", type_="check")
    op.drop_column("agyaries", "auto_booking_enabled")
    op.drop_column("agyaries", "status")
