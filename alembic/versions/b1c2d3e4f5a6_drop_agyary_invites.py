"""Drop agyary_invites

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-08-25 00:00:00.000000

The mobed app has no role management and never will - a paid agyari
management system is a separate product, to be designed once real
panthakies have been consulted. Invites were the only writer of this
table and the only path to the panthaky/caretaker roles from the app.

They also carried a live privilege-escalation hole: the issuing endpoint
treated "this agyari has no admin yet" as a bootstrap case, so at any
agyari without one, any member could POST themselves a panthaky invite
and redeem it on their next sign-in. Unreachable from the UI, but the
endpoints answered to anyone holding a session and a curl.

The roles themselves stay in the users.role CHECK constraint and still
gate the WhatsApp booking flows; only the mechanism that handed them out
is removed. Seed data and those flows remain the only things that set a
privileged role.

Existing rows go with the table. They record who invited whom, but every
redeemed invite already did its work - the membership row it created is
the durable record and is untouched here. Unredeemed ones grant nothing
once the code that reads them is gone.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("idx_agyary_invites_phone", table_name="agyary_invites")
    op.drop_index("uq_agyary_invites_pending", table_name="agyary_invites")
    op.drop_table("agyary_invites")


def downgrade() -> None:
    """Recreates the table empty. The rows are not recoverable, and nothing
    reads them any more - this exists so the chain stays reversible, not
    because downgrading restores the feature."""
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
