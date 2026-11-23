"""person_names: the departed's names that follow a person, by phone number

DECISIONS D12, "Departed names for the family" (owner, 24 Nov 2026): when a
Doongerwadi manager records a death, the departed's name and the father's or
husband's name are kept for the family contact's number, newest first, so later
bookings and slips offer them first. One number is one person with many roles.

Readable only by the account that signs in with that number; never by another
mobed, a manager or an admin screen. One row per death record (an edit changes
that record's own row); the record going leaves the row (SET NULL).

Revision ID: a1b2c3d4e5f9
Revises: e9f0a1b2c3d8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f9"
down_revision: Union[str, None] = "e9f0a1b2c3d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "person_names",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("departed_title", sa.String(10), nullable=False),
        sa.Column("departed_name", sa.String(80), server_default="", nullable=False),
        sa.Column("departed_parent_name", sa.String(80)),
        sa.Column("source", sa.String(20), server_default="death_record", nullable=False),
        sa.Column("source_record_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_record_id"], ["funeral_records.id"], ondelete="SET NULL",
            name=op.f("fk_person_names_source_record_id_funeral_records"),
        ),
        sa.CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name=op.f("ck_person_names_phone_e164")),
        sa.CheckConstraint(
            "departed_title IN ('ervad', 'osta', 'osti', 'behdin', 'khud')", name=op.f("ck_person_names_departed_title"),
        ),
        sa.CheckConstraint("source IN ('death_record')", name=op.f("ck_person_names_source")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_names")),
    )
    op.create_index("idx_person_names_phone", "person_names", ["phone"])
    op.create_index("idx_person_names_record", "person_names", ["source_record_id"])


def downgrade() -> None:
    op.drop_index("idx_person_names_record", table_name="person_names")
    op.drop_index("idx_person_names_phone", table_name="person_names")
    op.drop_table("person_names")
