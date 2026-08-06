"""user_preferences: per-user calendar/language display settings

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-06 00:00:00.000000

Which calendars a person wants shown side by side, which Parsi system the
Roj/Mah reading defaults to, and what language they read.

Explicitly NOT Agyary.calendar_system, which stays exactly as it is. That
field decides which Parsi reckoning gets stamped onto a ceremony record and
is part of the historical record; this is display chrome for one person's
screen. Conflating them would let a view toggle rewrite what a booking
means.

A missing row is a valid state ("hasn't chosen anything"), so nothing is
backfilled - the API serves the same defaults the column defaults carry,
and a row appears the first time someone saves a preference.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "visible_calendar_systems",
            sa.ARRAY(sa.String(length=20)),
            server_default=sa.text("ARRAY['gregorian','shenshai']::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "default_secondary_system",
            sa.String(length=10),
            server_default="shenshai",
            nullable=False,
        ),
        sa.Column("display_language", sa.String(length=10), server_default="en", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "visible_calendar_systems <@ ARRAY['gregorian','shenshai','kadmi','fasli']::varchar[]",
            name=op.f("ck_user_preferences_visible_calendar_systems"),
        ),
        sa.CheckConstraint(
            "array_length(visible_calendar_systems, 1) >= 1",
            name=op.f("ck_user_preferences_at_least_one_visible"),
        ),
        sa.CheckConstraint(
            "default_secondary_system IN ('shenshai', 'kadmi', 'fasli')",
            name=op.f("ck_user_preferences_default_secondary_system"),
        ),
        sa.CheckConstraint(
            "display_language IN ('en', 'gu')", name=op.f("ck_user_preferences_display_language")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_preferences_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_preferences")),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
