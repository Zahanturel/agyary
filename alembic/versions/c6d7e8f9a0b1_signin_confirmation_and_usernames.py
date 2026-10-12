"""sign-in confirmation and WhatsApp usernames

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-10-13 00:00:00.000000

AU-1: wa_login_attempts.confirm_hash / confirm_attempts - the number sent back to
the phone a sign-in code came from, which the starting screen must type.

AU-4: WhatsApp may send a username id (a BSUID) instead of a phone number.
users.wa_user_id, wa_login_attempts.claimed_wa_user_id and
notifications.recipient_user_id keep those ids so a mobed, or a family's STOP,
is still recognised when the number is withheld.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("wa_login_attempts", sa.Column("claimed_wa_user_id", sa.String(length=128), nullable=True))
    op.add_column("wa_login_attempts", sa.Column("confirm_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "wa_login_attempts", sa.Column("confirm_attempts", sa.SmallInteger(), server_default="0", nullable=False)
    )
    op.add_column("users", sa.Column("wa_user_id", sa.String(length=128), nullable=True))
    op.create_unique_constraint(op.f("uq_users_wa_user_id"), "users", ["wa_user_id"])
    op.add_column("notifications", sa.Column("recipient_user_id", sa.String(length=128), nullable=True))
    op.create_index(
        "idx_notifications_recipient_user", "notifications", ["recipient_user_id"],
        postgresql_where=sa.text("recipient_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_notifications_recipient_user", table_name="notifications")
    op.drop_column("notifications", "recipient_user_id")
    op.drop_constraint(op.f("uq_users_wa_user_id"), "users", type_="unique")
    op.drop_column("users", "wa_user_id")
    op.drop_column("wa_login_attempts", "confirm_attempts")
    op.drop_column("wa_login_attempts", "confirm_hash")
    op.drop_column("wa_login_attempts", "claimed_wa_user_id")
