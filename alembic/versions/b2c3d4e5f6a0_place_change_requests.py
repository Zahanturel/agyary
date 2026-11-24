"""place_change_requests: a manager asks to move to another place, the admin approves

Owner, 24 Nov 2026: a Doongerwadi manager cannot change their place in the
app; the manager asks and the admin approves, and nothing changes until then
(a place's family records are private, D2/D10). One row per request, kept after
it is decided. At most one is pending per manager (partial unique index).

Revision ID: b2c3d4e5f6a0
Revises: a1b2c3d4e5f9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a0"
down_revision: Union[str, None] = "a1b2c3d4e5f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "place_change_requests",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("from_place_id", sa.BigInteger()),
        sa.Column("to_place_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("decided_by_user_id", sa.BigInteger()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_place_change_requests_user_id_users")),
        sa.ForeignKeyConstraint(
            ["from_place_id"], ["funeral_places.id"], name=op.f("fk_place_change_requests_from_place_id_funeral_places"),
        ),
        sa.ForeignKeyConstraint(
            ["to_place_id"], ["funeral_places.id"], name=op.f("fk_place_change_requests_to_place_id_funeral_places"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="SET NULL",
            name=op.f("fk_place_change_requests_decided_by_user_id_users"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'declined', 'cancelled')", name=op.f("ck_place_change_requests_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_place_change_requests")),
    )
    op.create_index(
        "uq_place_change_requests_one_pending", "place_change_requests", ["user_id"], unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("idx_place_change_requests_status", "place_change_requests", ["status"])


def downgrade() -> None:
    op.drop_index("idx_place_change_requests_status", table_name="place_change_requests")
    op.drop_index("uq_place_change_requests_one_pending", table_name="place_change_requests")
    op.drop_table("place_change_requests")
