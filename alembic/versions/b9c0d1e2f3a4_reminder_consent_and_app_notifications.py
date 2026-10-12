"""reminder consent, STOP, and in-app notifications

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-10-12 00:00:00.000000

A mobed turns WhatsApp reminders on for a behdin after asking them in person
(user_customers.reminders_enabled). A behdin who replies STOP is recorded on
the person (customers.reminders_stopped_at), switched off for every mobed who
had them on, and the mobed is told through app_notifications the next time
they open the app. A reminder is sent at most once per memorial observance,
enforced by a partial unique index on notifications.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_customers",
        sa.Column("reminders_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "user_customers",
        sa.Column("reminders_enabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "customers",
        sa.Column("reminders_stopped_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "notifications",
        sa.Column("memorial_observance_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_notifications_memorial_observance_id_memorial_observances"),
        "notifications", "memorial_observances",
        ["memorial_observance_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "uq_notifications_memorial_reminder", "notifications", ["memorial_observance_id"],
        unique=True, postgresql_where=sa.text("notification_type = 'memorial_reminder'"),
    )

    op.create_table(
        "app_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("agyary_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_app_notifications_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["agyary_id"], ["agyaries.id"], name=op.f("fk_app_notifications_agyary_id_agyaries")
        ),
    )
    op.create_index("idx_app_notifications_user", "app_notifications", ["user_id", "expires_at"])


def downgrade() -> None:
    op.drop_index("idx_app_notifications_user", table_name="app_notifications")
    op.drop_table("app_notifications")
    op.drop_index("uq_notifications_memorial_reminder", table_name="notifications")
    op.drop_constraint(
        op.f("fk_notifications_memorial_observance_id_memorial_observances"),
        "notifications", type_="foreignkey",
    )
    op.drop_column("notifications", "memorial_observance_id")
    op.drop_column("customers", "reminders_stopped_at")
    op.drop_column("user_customers", "reminders_enabled_at")
    op.drop_column("user_customers", "reminders_enabled")
