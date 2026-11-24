"""R4.2: a person asks an agyari for a service

- ``agyaries.takes_asks``: whether people can ask this agyari in the Parsi app
  (off by default; the confirmed panthaky or the admin switches it on).
- ``service_asks``: the asks themselves. A person's own (ON DELETE CASCADE with
  their account); what an accept made in the panthaky's diary is only pointed
  at (SET NULL if that record is deleted).

The downgrade takes people's asks off, and deleting data is not allowed (D8),
so it refuses while any row exists in ``service_asks``.

Revision ID: e5f6a0b1c2d3
Revises: d4e5f6a0b1c2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5f6a0b1c2d3"
down_revision: Union[str, None] = "d4e5f6a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agyaries", sa.Column("takes_asks", sa.Boolean(), server_default="false", nullable=False))

    op.create_table(
        "service_asks",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("agyary_id", sa.BigInteger(), nullable=False),
        sa.Column("service_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(10), server_default="single", nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("ceremony_date", sa.Date(), nullable=False),
        sa.Column("geh", sa.SmallInteger()),
        sa.Column("ceremony_time", sa.Time()),
        sa.Column("venue", sa.String(10), server_default="agyari", nullable=False),
        sa.Column("area", sa.String(100)),
        sa.Column("names", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("note", sa.String(200)),
        sa.Column("repeat_pattern", sa.String(10)),
        sa.Column("repeat_count", sa.SmallInteger()),
        sa.Column("memorial_choice", postgresql.JSONB()),
        sa.Column("memorial_codes", postgresql.JSONB()),
        sa.Column("status", sa.String(10), server_default="waiting", nullable=False),
        sa.Column("reject_reason", sa.String(100)),
        sa.Column("no_answer_alert_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by_user_id", sa.BigInteger()),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("result_booking_id", sa.BigInteger()),
        sa.Column("result_machi_id", sa.BigInteger()),
        sa.Column("result_memorial_id", sa.BigInteger()),
        sa.Column("result_customer_id", sa.BigInteger()),
        sa.Column("copied_from_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name=op.f("fk_service_asks_user_id_users")),
        sa.ForeignKeyConstraint(["agyary_id"], ["agyaries.id"], name=op.f("fk_service_asks_agyary_id_agyaries")),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], name=op.f("fk_service_asks_service_id_services")),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="SET NULL",
                                name=op.f("fk_service_asks_decided_by_user_id_users")),
        sa.ForeignKeyConstraint(["result_booking_id"], ["bookings.id"], ondelete="SET NULL",
                                name=op.f("fk_service_asks_result_booking_id_bookings")),
        sa.ForeignKeyConstraint(["result_machi_id"], ["machis.id"], ondelete="SET NULL",
                                name=op.f("fk_service_asks_result_machi_id_machis")),
        sa.ForeignKeyConstraint(["result_memorial_id"], ["memorials.id"], ondelete="SET NULL",
                                name=op.f("fk_service_asks_result_memorial_id_memorials")),
        sa.ForeignKeyConstraint(["result_customer_id"], ["customers.id"], ondelete="SET NULL",
                                name=op.f("fk_service_asks_result_customer_id_customers")),
        sa.ForeignKeyConstraint(["copied_from_id"], ["service_asks.id"], ondelete="SET NULL",
                                name=op.f("fk_service_asks_copied_from_id_service_asks")),
        sa.CheckConstraint("kind IN ('single', 'repeating', 'memorial')", name=op.f("ck_service_asks_kind")),
        sa.CheckConstraint("status IN ('waiting', 'accepted', 'rejected', 'cancelled')",
                           name=op.f("ck_service_asks_status")),
        sa.CheckConstraint(
            "purpose IN ('gujrela_nu', 'khushali_nu', 'hama_anjuman', 'patet', 'tandarosti')",
            name=op.f("ck_service_asks_purpose")),
        sa.CheckConstraint("venue IN ('agyari', 'home')", name=op.f("ck_service_asks_venue")),
        sa.CheckConstraint("geh IS NULL OR geh BETWEEN 1 AND 5", name=op.f("ck_service_asks_geh")),
        sa.CheckConstraint("kind = 'memorial' OR num_nonnulls(geh, ceremony_time) = 1",
                           name=op.f("ck_service_asks_geh_or_time")),
        sa.CheckConstraint("kind = 'memorial' OR (memorial_choice IS NULL AND memorial_codes IS NULL)",
                           name=op.f("ck_service_asks_memorial_only")),
        sa.CheckConstraint("(kind = 'repeating') = (repeat_pattern IS NOT NULL)",
                           name=op.f("ck_service_asks_repeat_pattern")),
        sa.CheckConstraint("repeat_pattern IS NULL OR repeat_pattern IN ('monthly', 'yearly')",
                           name=op.f("ck_service_asks_repeat_pattern_value")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_asks")),
    )
    op.create_index("idx_service_asks_user", "service_asks", ["user_id", sa.text("created_at DESC")])
    op.create_index("idx_service_asks_agyary_status", "service_asks", ["agyary_id", "status", "created_at"])
    op.create_index(
        "idx_service_asks_no_answer", "service_asks", ["created_at"],
        postgresql_where=sa.text("status = 'waiting' AND no_answer_alert_at IS NULL"),
    )


def downgrade() -> None:
    held = op.get_bind().execute(sa.text("SELECT count(*) FROM service_asks")).scalar_one()
    if held:
        raise RuntimeError(
            "Cannot downgrade: people's asks to fire temples would be deleted (D8). "
            "Take them off by hand first if that is really wanted."
        )
    op.drop_table("service_asks")
    op.drop_column("agyaries", "takes_asks")
