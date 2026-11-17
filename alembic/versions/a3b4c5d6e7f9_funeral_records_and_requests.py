"""Funeral records and their requests to fire temples

DECISIONS D10, Phase 2 Step 4. ``funeral_records``: a death recorded by a
funeral place's manager - the departed's name as it is prayed, the death (date
and its Roj, Mah and year in the family's calendar, given either way, D5), four
days or one, the bungli, the Geh-saarnu (day and geh), the Uthamna (day and
time), how many mobeds, the family's preferred fire temple, and one family
contact. No cause of death, age, address, certificate, ID number or how the
body goes. Kept like every record (D8); who made it is cleared if their
account goes.

``funeral_requests``: a record sent to one fire temple. waiting, accepted,
declined, withdrawn or taken; one waiting per record (a partial unique index);
the time the family agreed to share their name and number is required.
``funeral_request_recipients``: who was asked.

Revision ID: a3b4c5d6e7f9
Revises: f1a2b3c4d5e7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f9"
down_revision: Union[str, None] = "f1a2b3c4d5e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "funeral_records",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("funeral_place_id", sa.BigInteger(), nullable=False),
        sa.Column("departed_title", sa.String(10), nullable=False),
        sa.Column("departed_name", sa.String(80), nullable=False),
        sa.Column("departed_parent_name", sa.String(80)),
        sa.Column("death_date", sa.Date(), nullable=False),
        sa.Column("death_given_by", sa.String(10), nullable=False),
        sa.Column("death_roj", sa.SmallInteger(), nullable=False),
        sa.Column("death_mah", sa.SmallInteger(), nullable=False),
        sa.Column("death_year", sa.Integer(), nullable=False),
        sa.Column("calendar_system", sa.String(10), nullable=False),
        sa.Column("obsequies", sa.String(10), nullable=False),
        sa.Column("bungli", sa.String(80)),
        sa.Column("geh_saarnu_date", sa.Date()),
        sa.Column("geh_saarnu_geh", sa.SmallInteger()),
        sa.Column("uthamna_date", sa.Date()),
        sa.Column("uthamna_time", sa.Time()),
        sa.Column("mobeds_wanted", sa.SmallInteger()),
        sa.Column("preferred_agyary_id", sa.BigInteger()),
        sa.Column("family_contact_name", sa.String(100), nullable=False),
        sa.Column("family_contact_phone", sa.String(20), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["funeral_place_id"], ["funeral_places.id"],
            name=op.f("fk_funeral_records_funeral_place_id_funeral_places"),
        ),
        sa.ForeignKeyConstraint(
            ["preferred_agyary_id"], ["agyaries.id"], name=op.f("fk_funeral_records_preferred_agyary_id_agyaries"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL",
            name=op.f("fk_funeral_records_created_by_user_id_users"),
        ),
        sa.CheckConstraint(
            "departed_title IN ('ervad', 'osta', 'osti', 'behdin')", name=op.f("ck_funeral_records_departed_title"),
        ),
        sa.CheckConstraint(
            "death_given_by IN ('date', 'roj_mah')", name=op.f("ck_funeral_records_death_given_by"),
        ),
        sa.CheckConstraint(
            "calendar_system IN ('shenshai', 'kadmi', 'fasli')", name=op.f("ck_funeral_records_calendar_system"),
        ),
        sa.CheckConstraint("obsequies IN ('four_days', 'one_day')", name=op.f("ck_funeral_records_obsequies")),
        sa.CheckConstraint("death_mah BETWEEN 1 AND 13", name=op.f("ck_funeral_records_death_mah")),
        sa.CheckConstraint("death_roj BETWEEN 1 AND 30", name=op.f("ck_funeral_records_death_roj")),
        sa.CheckConstraint(
            "(geh_saarnu_date IS NULL AND geh_saarnu_geh IS NULL)"
            " OR (geh_saarnu_date IS NOT NULL AND geh_saarnu_geh IS NOT NULL AND geh_saarnu_geh BETWEEN 1 AND 5)",
            name=op.f("ck_funeral_records_geh_saarnu"),
        ),
        sa.CheckConstraint(
            "uthamna_time IS NULL OR uthamna_date IS NOT NULL", name=op.f("ck_funeral_records_uthamna"),
        ),
        sa.CheckConstraint(
            "mobeds_wanted IS NULL OR mobeds_wanted BETWEEN 1 AND 20", name=op.f("ck_funeral_records_mobeds_wanted"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_funeral_records")),
    )
    op.create_index("idx_funeral_records_place", "funeral_records", ["funeral_place_id", "created_at"])

    op.create_table(
        "funeral_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("funeral_record_id", sa.BigInteger(), nullable=False),
        sa.Column("agyary_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(10), server_default="waiting", nullable=False),
        sa.Column("family_share_agreed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_by_user_id", sa.BigInteger()),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by_user_id", sa.BigInteger()),
        sa.Column("accepted_by_user_id", sa.BigInteger()),
        sa.Column("decline_reason", sa.String(200)),
        sa.ForeignKeyConstraint(
            ["funeral_record_id"], ["funeral_records.id"],
            name=op.f("fk_funeral_requests_funeral_record_id_funeral_records"),
        ),
        sa.ForeignKeyConstraint(["agyary_id"], ["agyaries.id"], name=op.f("fk_funeral_requests_agyary_id_agyaries")),
        sa.ForeignKeyConstraint(
            ["sent_by_user_id"], ["users.id"], ondelete="SET NULL",
            name=op.f("fk_funeral_requests_sent_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="SET NULL",
            name=op.f("fk_funeral_requests_decided_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"], ["users.id"], ondelete="SET NULL",
            name=op.f("fk_funeral_requests_accepted_by_user_id_users"),
        ),
        sa.CheckConstraint(
            "status IN ('waiting', 'accepted', 'declined', 'withdrawn', 'taken')",
            name=op.f("ck_funeral_requests_status"),
        ),
        sa.CheckConstraint("(status = 'waiting') = (decided_at IS NULL)", name=op.f("ck_funeral_requests_decided")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_funeral_requests")),
    )
    op.create_index(
        "uq_funeral_requests_one_waiting", "funeral_requests", ["funeral_record_id"], unique=True,
        postgresql_where=sa.text("status = 'waiting'"),
    )
    op.create_index("idx_funeral_requests_record", "funeral_requests", ["funeral_record_id", "sent_at"])
    op.create_index("idx_funeral_requests_agyary", "funeral_requests", ["agyary_id", "status"])

    op.create_table(
        "funeral_request_recipients",
        sa.Column("funeral_request_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["funeral_request_id"], ["funeral_requests.id"], ondelete="CASCADE",
            name=op.f("fk_funeral_request_recipients_funeral_request_id_funeral_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_funeral_request_recipients_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("funeral_request_id", "user_id", name=op.f("pk_funeral_request_recipients")),
    )
    op.create_index("idx_funeral_request_recipients_user", "funeral_request_recipients", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_funeral_request_recipients_user", table_name="funeral_request_recipients")
    op.drop_table("funeral_request_recipients")
    op.drop_index("idx_funeral_requests_agyary", table_name="funeral_requests")
    op.drop_index("idx_funeral_requests_record", table_name="funeral_requests")
    op.drop_index("uq_funeral_requests_one_waiting", table_name="funeral_requests")
    op.drop_table("funeral_requests")
    op.drop_index("idx_funeral_records_place", table_name="funeral_records")
    op.drop_table("funeral_records")
