"""A fire temple's own list of mobeds, and the panthaky's call-outs

DECISIONS D10 (18 Nov 2026), Phase 2 Step 5c. ``agyary_mobed_contacts``: mobeds
a confirmed panthaky added by name and number, each with the tick that they
agreed to get WhatsApp messages from Mobed Diary about prayers (when, by whom),
one row per fire temple and number. The fire temple's approved mobeds in the
app are on its list without a row here.

``prayer_callouts``: a panthaky asking them, for an accepted request, whether
they can pray. ``prayer_callout_answers``: who was asked, with an unguessable
token for the quick-reply buttons, their answer (yes / no, once), who was
picked and when the details or the "enough mobeds" reply went.

Revision ID: d6e7f8a9b0c2
Revises: c5d6e7f8a9b1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b0c2"
down_revision: Union[str, None] = "c5d6e7f8a9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agyary_mobed_contacts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("agyary_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_by_user_id", sa.BigInteger()),
        sa.Column("user_id", sa.BigInteger()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agyary_id"], ["agyaries.id"], name=op.f("fk_agyary_mobed_contacts_agyary_id_agyaries")),
        sa.ForeignKeyConstraint(
            ["consent_by_user_id"], ["users.id"], ondelete="SET NULL",
            name=op.f("fk_agyary_mobed_contacts_consent_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL", name=op.f("fk_agyary_mobed_contacts_user_id_users"),
        ),
        sa.CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name=op.f("ck_agyary_mobed_contacts_phone_e164")),
        sa.UniqueConstraint("agyary_id", "phone", name="uq_agyary_mobed_contacts_agyary_phone"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agyary_mobed_contacts")),
    )
    op.create_index("idx_agyary_mobed_contacts_phone", "agyary_mobed_contacts", ["phone"])

    op.create_table(
        "prayer_callouts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("funeral_request_id", sa.BigInteger(), nullable=False),
        sa.Column("agyary_id", sa.BigInteger(), nullable=False),
        sa.Column("sent_by_user_id", sa.BigInteger()),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("asked", sa.Integer(), server_default="0", nullable=False),
        sa.Column("picked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["funeral_request_id"], ["funeral_requests.id"],
            name=op.f("fk_prayer_callouts_funeral_request_id_funeral_requests"),
        ),
        sa.ForeignKeyConstraint(["agyary_id"], ["agyaries.id"], name=op.f("fk_prayer_callouts_agyary_id_agyaries")),
        sa.ForeignKeyConstraint(
            ["sent_by_user_id"], ["users.id"], ondelete="SET NULL", name=op.f("fk_prayer_callouts_sent_by_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prayer_callouts")),
    )
    op.create_index("idx_prayer_callouts_request", "prayer_callouts", ["funeral_request_id"])

    op.create_table(
        "prayer_callout_answers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("callout_id", sa.BigInteger(), nullable=False),
        sa.Column("contact_id", sa.BigInteger()),
        sa.Column("user_id", sa.BigInteger()),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column("token", sa.String(40), nullable=False),
        sa.Column("answer", sa.String(5)),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column("picked_at", sa.DateTime(timezone=True)),
        sa.Column("picked_by_user_id", sa.BigInteger()),
        sa.Column("details_sent_at", sa.DateTime(timezone=True)),
        sa.Column("enough_sent_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["callout_id"], ["prayer_callouts.id"], ondelete="CASCADE",
            name=op.f("fk_prayer_callout_answers_callout_id_prayer_callouts"),
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["agyary_mobed_contacts.id"], ondelete="SET NULL",
            name=op.f("fk_prayer_callout_answers_contact_id_agyary_mobed_contacts"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL", name=op.f("fk_prayer_callout_answers_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["picked_by_user_id"], ["users.id"], ondelete="SET NULL",
            name=op.f("fk_prayer_callout_answers_picked_by_user_id_users"),
        ),
        sa.CheckConstraint("answer IN ('yes', 'no')", name=op.f("ck_prayer_callout_answers_answer")),
        sa.CheckConstraint("(answer IS NULL) = (answered_at IS NULL)", name=op.f("ck_prayer_callout_answers_answered")),
        sa.CheckConstraint("picked_at IS NULL OR answer = 'yes'", name=op.f("ck_prayer_callout_answers_picked_said_yes")),
        sa.CheckConstraint("contact_id IS NULL OR user_id IS NULL", name=op.f("ck_prayer_callout_answers_one_kind")),
        sa.UniqueConstraint("token", name=op.f("uq_prayer_callout_answers_token")),
        sa.UniqueConstraint("callout_id", "phone", name="uq_prayer_callout_answers_callout_phone"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prayer_callout_answers")),
    )
    op.create_index("idx_prayer_callout_answers_callout", "prayer_callout_answers", ["callout_id"])


def downgrade() -> None:
    op.drop_index("idx_prayer_callout_answers_callout", table_name="prayer_callout_answers")
    op.drop_table("prayer_callout_answers")
    op.drop_index("idx_prayer_callouts_request", table_name="prayer_callouts")
    op.drop_table("prayer_callouts")
    op.drop_index("idx_agyary_mobed_contacts_phone", table_name="agyary_mobed_contacts")
    op.drop_table("agyary_mobed_contacts")
