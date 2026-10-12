"""login_otps: six digit sign-in codes sent over WhatsApp

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-10-12 00:00:00.000000

Only a salted digest of each code is stored. Rows are counted to cap how many
codes go to one phone, from one place, and overall.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c0d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_otps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("salt", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_new_number", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("requester", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("wa_message_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_login_otps_phone", "login_otps", ["phone", "created_at"])
    op.create_index("idx_login_otps_created", "login_otps", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_login_otps_created", table_name="login_otps")
    op.drop_index("idx_login_otps_phone", table_name="login_otps")
    op.drop_table("login_otps")
