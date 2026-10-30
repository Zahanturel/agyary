"""Remember, for a while, the numbers whose accounts were deleted

Revision ID: e6f7a8b9c0d2
Revises: c1d2e3f4a5b7
Create Date: 2026-10-30 12:00:00.000000

Every limit on what an account may send is counted from rows that deleting the
account also removed, so deleting it and signing up again started afresh (audit
30 Oct 2026, SEC-02). This holds a one-way digest of the number, never the
number itself, and each row is swept once its cooldown has passed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d2"
down_revision: Union[str, None] = "c1d2e3f4a5b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deleted_accounts",
        sa.Column("phone_hmac", sa.String(length=64), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("phone_hmac", name=op.f("pk_deleted_accounts")),
    )


def downgrade() -> None:
    op.drop_table("deleted_accounts")
