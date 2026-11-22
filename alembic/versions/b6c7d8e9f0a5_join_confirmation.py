"""agyary_users: confirmed for prayer requests, and taken off the list

DECISIONS D10 (owner, 22 Nov 2026, from the security pass): joining another
agyari needs its panthaky's confirmation. Joining stays open (D1.4), but a
membership gets the fire temple's prayer requests only once it is confirmed.

- ``requests_confirmed_at`` / ``requests_confirmed_by_user_id``: confirmed
  for prayer requests, when and by whom (cleared if that account goes);
- ``requests_off_at`` / ``requests_off_by_user_id``: taken off the list for
  prayer requests by the panthaky or the admin; they stay a member.

Who did it is kept only with when. **Every membership that exists when this
runs is confirmed** (owner: memberships from before stay confirmed), with no
one recorded as confirming it; nobody is taken off. The downgrade takes the
columns off and touches no membership.

Revision ID: b6c7d8e9f0a5
Revises: a5b6c7d8e9f4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6c7d8e9f0a5"
down_revision: Union[str, None] = "a5b6c7d8e9f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "agyary_users"
# The checks, frozen here as they were when this ran.
CHECKS = {
    "requests_confirmed_by": "requests_confirmed_by_user_id IS NULL OR requests_confirmed_at IS NOT NULL",
    "requests_off_by": "requests_off_by_user_id IS NULL OR requests_off_at IS NOT NULL",
}
BY = ("requests_confirmed_by_user_id", "requests_off_by_user_id")


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("requests_confirmed_at", sa.DateTime(timezone=True)))
    op.add_column(TABLE, sa.Column("requests_confirmed_by_user_id", sa.BigInteger()))
    op.add_column(TABLE, sa.Column("requests_off_at", sa.DateTime(timezone=True)))
    op.add_column(TABLE, sa.Column("requests_off_by_user_id", sa.BigInteger()))
    for column in BY:
        op.create_foreign_key(
            op.f(f"fk_agyary_users_{column}_users"), TABLE, "users", [column], ["id"], ondelete="SET NULL",
        )
    for name, sql in CHECKS.items():
        op.create_check_constraint(op.f(f"ck_agyary_users_{name}"), TABLE, sql)
    # Memberships from before stay confirmed (owner, 22 Nov 2026).
    op.execute("UPDATE agyary_users SET requests_confirmed_at = now()")


def downgrade() -> None:
    for name in reversed(list(CHECKS)):
        op.drop_constraint(op.f(f"ck_agyary_users_{name}"), TABLE, type_="check")
    for column in reversed(BY):
        op.drop_constraint(op.f(f"fk_agyary_users_{column}_users"), TABLE, type_="foreignkey")
    op.drop_column(TABLE, "requests_off_by_user_id")
    op.drop_column(TABLE, "requests_off_at")
    op.drop_column(TABLE, "requests_confirmed_by_user_id")
    op.drop_column(TABLE, "requests_confirmed_at")
