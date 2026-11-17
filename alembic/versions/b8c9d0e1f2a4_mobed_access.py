"""a mobed's access to the app: waiting for approval, on, or off

``users.access`` is the owner's one switch per mobed (docs/DECISIONS.md D9).
A new sign-up starts "pending" and can do nothing but choose a fire temple until
an admin approves it; "off" is a mobed the owner has switched off. Everyone who
already has an account is "on", so nobody using the app today is locked out.
``users.access_changed_at`` is when an admin last changed it.

Revision ID: b8c9d0e1f2a4
Revises: a7b8c9d0e1f3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a4"
down_revision: Union[str, None] = "a7b8c9d0e1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("access", sa.String(10), server_default="on", nullable=False))
    op.add_column("users", sa.Column("access_changed_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(op.f("ck_users_access"), "users", "access IN ('pending', 'on', 'off')")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_access"), "users", type_="check")
    op.drop_column("users", "access_changed_at")
    op.drop_column("users", "access")
