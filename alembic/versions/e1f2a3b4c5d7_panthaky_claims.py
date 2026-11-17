"""agyary_users: what a person says they are at a fire temple, and the owner's decision

DECISIONS D10's safeguard: sign-up asks "mobed or panthaky", and the answer is
only a claim. ``claimed_role`` ("mobed" / "panthaky") and ``claimed_at`` hold
it; ``role`` is not touched. The owner's decision on the panthaky role
("confirmed", "declined", "removed"), when, and by which admin (cleared if that
admin's account goes) are kept beside it. A claim and its time are set together
or not at all, and so are a decision and its time.

Every existing membership starts with no claim and no decision; nothing is
filled here, and no role changes.

Revision ID: e1f2a3b4c5d7
Revises: d0e1f2a3b4c6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d7"
down_revision: Union[str, None] = "d0e1f2a3b4c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agyary_users", sa.Column("claimed_role", sa.String(20)))
    op.add_column("agyary_users", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.add_column("agyary_users", sa.Column("claim_decision", sa.String(20)))
    op.add_column("agyary_users", sa.Column("claim_decided_at", sa.DateTime(timezone=True)))
    op.add_column("agyary_users", sa.Column("claim_decided_by_user_id", sa.BigInteger()))
    op.create_foreign_key(
        op.f("fk_agyary_users_claim_decided_by_user_id_users"), "agyary_users", "users",
        ["claim_decided_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_agyary_users_claimed_role"), "agyary_users", "claimed_role IN ('mobed', 'panthaky')"
    )
    op.create_check_constraint(
        op.f("ck_agyary_users_claim_decision"), "agyary_users",
        "claim_decision IN ('confirmed', 'declined', 'removed')",
    )
    op.create_check_constraint(
        op.f("ck_agyary_users_claimed_at"), "agyary_users", "(claimed_role IS NULL) = (claimed_at IS NULL)"
    )
    op.create_check_constraint(
        op.f("ck_agyary_users_claim_decided_at"), "agyary_users",
        "(claim_decision IS NULL) = (claim_decided_at IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_agyary_users_claim_decided_at"), "agyary_users", type_="check")
    op.drop_constraint(op.f("ck_agyary_users_claimed_at"), "agyary_users", type_="check")
    op.drop_constraint(op.f("ck_agyary_users_claim_decision"), "agyary_users", type_="check")
    op.drop_constraint(op.f("ck_agyary_users_claimed_role"), "agyary_users", type_="check")
    op.drop_constraint(
        op.f("fk_agyary_users_claim_decided_by_user_id_users"), "agyary_users", type_="foreignkey"
    )
    op.drop_column("agyary_users", "claim_decided_by_user_id")
    op.drop_column("agyary_users", "claim_decided_at")
    op.drop_column("agyary_users", "claim_decision")
    op.drop_column("agyary_users", "claimed_at")
    op.drop_column("agyary_users", "claimed_role")
