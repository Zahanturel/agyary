"""Funeral places, their managers, and what kind of account a person has

DECISIONS D10, Phase 2 Step 3. ``funeral_places``: a Doongerwadi, prayer hall
or aramgah, added only by an admin (name, kind, town, address, who runs it, an
optional map position, on or off; never deleted, D8). The admin who added it
is kept, and cleared if their account goes. ``funeral_place_managers``: who
manages which place (role "manager" for now).

``users.account_kind``: "mobed" or "funeral_manager", one per person. The
server default is "mobed", so every existing account stays a mobed's and
nothing about it changes.

Revision ID: f1a2b3c4d5e7
Revises: e1f2a3b4c5d7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e7"
down_revision: Union[str, None] = "e1f2a3b4c5d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The same text as models/funeral_place.py FUNERAL_LOCATION_CHECK.
LOCATION_CHECK = (
    "(latitude IS NULL AND longitude IS NULL)"
    " OR (latitude IS NOT NULL AND longitude IS NOT NULL"
    " AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)"
)


def upgrade() -> None:
    op.add_column("users", sa.Column("account_kind", sa.String(20), server_default="mobed", nullable=False))
    op.create_check_constraint(
        op.f("ck_users_account_kind"), "users", "account_kind IN ('mobed', 'funeral_manager')"
    )

    op.create_table(
        "funeral_places",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("address", sa.Text()),
        sa.Column("run_by", sa.String(200)),
        sa.Column("latitude", sa.Double()),
        sa.Column("longitude", sa.Double()),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL",
            name=op.f("fk_funeral_places_created_by_user_id_users"),
        ),
        sa.CheckConstraint("kind IN ('doongerwadi', 'prayer_hall', 'aramgah')", name=op.f("ck_funeral_places_kind")),
        sa.CheckConstraint(LOCATION_CHECK, name=op.f("ck_funeral_places_location")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_funeral_places")),
    )

    op.create_table(
        "funeral_place_managers",
        sa.Column("funeral_place_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(20), server_default="manager", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["funeral_place_id"], ["funeral_places.id"],
            name=op.f("fk_funeral_place_managers_funeral_place_id_funeral_places"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_funeral_place_managers_user_id_users")),
        sa.CheckConstraint("role IN ('manager')", name=op.f("ck_funeral_place_managers_role")),
        sa.PrimaryKeyConstraint("funeral_place_id", "user_id", name=op.f("pk_funeral_place_managers")),
    )
    op.create_index("idx_funeral_place_managers_user", "funeral_place_managers", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_funeral_place_managers_user", table_name="funeral_place_managers")
    op.drop_table("funeral_place_managers")
    op.drop_table("funeral_places")
    op.drop_constraint(op.f("ck_users_account_kind"), "users", type_="check")
    op.drop_column("users", "account_kind")
