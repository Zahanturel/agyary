"""app_settings: switches an admin can flip at runtime

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-10-12 00:00:00.000000

Holds the reminder sending pause (the kill switch) so it survives a restart.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c0d1e2f3a4b5'
down_revision: Union[str, None] = 'b9c0d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=60), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"],
            name=op.f("fk_app_settings_updated_by_user_id_users"), ondelete="SET NULL",
        ),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
