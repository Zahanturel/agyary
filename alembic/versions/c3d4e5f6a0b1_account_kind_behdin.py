"""users.account_kind gains 'behdin' (R4.0: the behdin app)

An ordinary person who signs in at the behdin app is a 'behdin'. No data
changes: every account that exists stays a mobed or a manager.

The downgrade would have to turn behdin accounts into nothing, and deleting
data is not allowed (D8), so it refuses while any exist.

Revision ID: c3d4e5f6a0b1
Revises: b2c3d4e5f6a0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a0b1"
down_revision: Union[str, None] = "b2c3d4e5f6a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_users_account_kind"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_account_kind"), "users", "account_kind IN ('mobed', 'funeral_manager', 'behdin')"
    )


def downgrade() -> None:
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM users WHERE account_kind = 'behdin'")).scalar_one()
    if count:
        raise RuntimeError(
            f"Cannot downgrade: {count} behdin account(s) exist, and going back would have to delete or "
            "change them. Nothing is deleted by age or by downgrade (D8). Remove them deliberately first."
        )
    op.drop_constraint(op.f("ck_users_account_kind"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_account_kind"), "users", "account_kind IN ('mobed', 'funeral_manager')"
    )
