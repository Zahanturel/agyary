"""A funeral place's own book of behdins (families)

DECISIONS D10, changed 19 Nov 2026 (owner): the Doongerwadi manager keeps a
book of families - name, number and their usual agyari - private to that
funeral place. ``funeral_behdins``: one row per place and number (E.164), the
fire temple they usually go to (cleared if that fire temple goes), on or off
(removing keeps it, D8), and who added it.

Revision ID: f8a9b0c1d2e5
Revises: e7f8a9b0c1d4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1d2e5"
down_revision: Union[str, None] = "e7f8a9b0c1d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "funeral_behdins",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("funeral_place_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("usual_agyary_id", sa.BigInteger()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["funeral_place_id"], ["funeral_places.id"], name=op.f("fk_funeral_behdins_funeral_place_id_funeral_places"),
        ),
        sa.ForeignKeyConstraint(
            ["usual_agyary_id"], ["agyaries.id"], ondelete="SET NULL",
            name=op.f("fk_funeral_behdins_usual_agyary_id_agyaries"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL",
            name=op.f("fk_funeral_behdins_created_by_user_id_users"),
        ),
        sa.CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name=op.f("ck_funeral_behdins_phone_e164")),
        sa.UniqueConstraint("funeral_place_id", "phone", name="uq_funeral_behdins_place_phone"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_funeral_behdins")),
    )
    op.create_index("idx_funeral_behdins_phone", "funeral_behdins", ["phone"])


def downgrade() -> None:
    op.drop_index("idx_funeral_behdins_phone", table_name="funeral_behdins")
    op.drop_table("funeral_behdins")
