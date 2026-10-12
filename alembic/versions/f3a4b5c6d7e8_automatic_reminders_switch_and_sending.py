"""automatic reminders: a per-account switch, and a "sending" state

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-10-13 00:00:00.000000

users.automatic_reminders is the one switch for automatic WhatsApp reminders
from an account (docs/DECISIONS.md D4): on for every existing account, as the
pilot gives everyone both ways of reminding.

notifications.status gains "sending": a reminder is marked so, and committed,
before it is handed to Meta, so one whose answer is lost is never sent again.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "status IN ('pending', 'queued', 'sent', 'delivered', 'read', 'failed')"
_NEW = "status IN ('pending', 'queued', 'sending', 'sent', 'delivered', 'read', 'failed')"


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("automatic_reminders", sa.Boolean(), server_default="true", nullable=False)
    )
    op.drop_constraint("ck_notifications_status", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_status", "notifications", _NEW)


def downgrade() -> None:
    # A reminder caught mid-send has unknown fate; the old schema calls that failed.
    op.execute("UPDATE notifications SET status = 'failed' WHERE status = 'sending'")
    op.drop_constraint("ck_notifications_status", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_status", "notifications", _OLD)
    op.drop_column("users", "automatic_reminders")
