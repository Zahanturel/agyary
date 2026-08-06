"""agyary_invites: invite-based role provisioning

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-06 00:00:00.000000

Until now every membership was created by ensure_agyary_membership with
role hardcoded to 'mobed', so the panthaky and caretaker values in the
users.role CHECK constraint existed but were unreachable in practice.

This table is the path to them: an existing admin names a phone number and
a role, and whoever proves possession of that phone through the normal OTP
login picks the membership up at that role. Addressed to a phone rather
than a user id because the invitee usually has no User row yet - being
invited is often how they first arrive.

No data migration accompanies this. Promoting an existing member to
panthaky means picking one out of a list of phone numbers, which is a
judgment call, not something a migration should decide. Instead the invite
endpoint treats "this agyari has no admin yet" as a bootstrap case: any
active member may issue the first invite, and the bootstrap closes
permanently once an admin exists.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agyary_invites",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("agyary_id", sa.BigInteger(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("invited_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "role IN ('panthaky', 'mobed', 'caretaker')", name=op.f("ck_agyary_invites_role")
        ),
        sa.ForeignKeyConstraint(["agyary_id"], ["agyaries.id"], name=op.f("fk_agyary_invites_agyary_id")),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"], ["users.id"], name=op.f("fk_agyary_invites_invited_by_user_id")
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_by_user_id"], ["users.id"], name=op.f("fk_agyary_invites_redeemed_by_user_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agyary_invites")),
    )
    # At most one live invite per (agyari, phone): re-inviting the same
    # number replaces the pending one rather than stacking a second, so the
    # role that applies at redemption is never ambiguous.
    op.create_index(
        "uq_agyary_invites_pending",
        "agyary_invites",
        ["agyary_id", "phone"],
        unique=True,
        postgresql_where=sa.text("redeemed_at IS NULL AND revoked_at IS NULL"),
    )
    op.create_index(
        "idx_agyary_invites_phone",
        "agyary_invites",
        ["phone"],
        postgresql_where=sa.text("redeemed_at IS NULL AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_agyary_invites_phone", table_name="agyary_invites")
    op.drop_index("uq_agyary_invites_pending", table_name="agyary_invites")
    op.drop_table("agyary_invites")
