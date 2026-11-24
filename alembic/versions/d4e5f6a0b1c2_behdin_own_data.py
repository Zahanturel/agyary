"""R4.1: agyari kinds, "my agyari", and a person's own memorials and events

- ``agyaries.kind``: Atash Behram, Adaran or Dadgah, worked out from the name
  where it says so; anything else stays NULL (a person sees no tag, the admin
  can set it later).
- ``person_agyari``: the agyari a person calls theirs (one row per person).
- ``person_memorials`` and ``person_memorial_observances``: the person's own
  departed and the engine's schedule for each.
- ``person_events``: birthdays, navjotes, anniversaries.

All of it belongs to one account and goes with it (ON DELETE CASCADE). The
downgrade takes people's data off, and deleting data is not allowed (D8), so it
refuses while any row exists in those tables.

Revision ID: d4e5f6a0b1c2
Revises: c3d4e5f6a0b1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a0b1c2"
down_revision: Union[str, None] = "c3d4e5f6a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("person_agyari", "person_memorials", "person_memorial_observances", "person_events")


def upgrade() -> None:
    op.add_column("agyaries", sa.Column("kind", sa.String(20)))
    op.create_check_constraint(
        op.f("ck_agyaries_kind"), "agyaries", "kind IS NULL OR kind IN ('atash_behram', 'adaran', 'dadgah')"
    )
    op.execute(
        "UPDATE agyaries SET kind = CASE"
        " WHEN name ~* 'atash[[:space:]]+(behram|bahram)' THEN 'atash_behram'"
        " WHEN name ~* 'dadgah' THEN 'dadgah'"
        " WHEN name ~* '(adaran|agiary|agiyari)' THEN 'adaran'"
        " END"
    )

    op.create_table(
        "person_agyari",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("agyary_id", sa.BigInteger(), nullable=False),
        sa.Column("chosen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name=op.f("fk_person_agyari_user_id_users")),
        sa.ForeignKeyConstraint(["agyary_id"], ["agyaries.id"], name=op.f("fk_person_agyari_agyary_id_agyaries")),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_person_agyari")),
    )

    op.create_table(
        "person_memorials",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("departed_name", sa.String(200), nullable=False),
        sa.Column("death_gregorian", sa.Date(), nullable=False),
        sa.Column("death_roj", sa.SmallInteger(), nullable=False),
        sa.Column("death_mah", sa.SmallInteger(), nullable=False),
        sa.Column("death_year", sa.Integer(), nullable=False),
        sa.Column("died_over_a_year_ago", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("calendar_system", sa.String(10), nullable=False),
        sa.Column("opening", sa.String(20), nullable=False),
        sa.Column("day_counts", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("monthly_months", sa.SmallInteger()),
        sa.Column("yearly_years", sa.SmallInteger()),
        sa.Column("parabs", sa.String(20)),
        sa.Column("parab_years", sa.SmallInteger()),
        sa.Column("parab_count", sa.SmallInteger()),
        sa.Column("fravardin_roj_months", sa.SmallInteger()),
        sa.Column("birthday_roj", sa.SmallInteger()),
        sa.Column("birthday_mah", sa.SmallInteger()),
        sa.Column("birthday_years", sa.SmallInteger()),
        sa.Column("start_from", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name=op.f("fk_person_memorials_user_id_users")),
        sa.CheckConstraint("calendar_system IN ('shenshai', 'kadmi', 'fasli')",
                           name=op.f("ck_person_memorials_calendar_system")),
        sa.CheckConstraint("opening IN ('days_1_to_10', 'tenth_only', 'none', 'days_5_to_9')", name=op.f("ck_person_memorials_opening")),
        sa.CheckConstraint("parabs IS NULL OR parabs IN ('all', 'fravardin_tir')",
                           name=op.f("ck_person_memorials_parabs")),
        sa.CheckConstraint("death_mah BETWEEN 1 AND 13", name=op.f("ck_person_memorials_death_mah")),
        sa.CheckConstraint("death_roj BETWEEN 1 AND 30", name=op.f("ck_person_memorials_death_roj")),
        sa.CheckConstraint("(parabs IS NULL) = (parab_years IS NULL AND parab_count IS NULL)",
                           name=op.f("ck_person_memorials_parab_length")),
        sa.CheckConstraint("monthly_months IS NULL OR monthly_months >= 1",
                           name=op.f("ck_person_memorials_monthly_length")),
        sa.CheckConstraint("yearly_years IS NULL OR yearly_years >= 1", name=op.f("ck_person_memorials_yearly_length")),
        sa.CheckConstraint(
            "(birthday_roj IS NULL) = (birthday_mah IS NULL) AND (birthday_roj IS NULL) = (birthday_years IS NULL)",
            name=op.f("ck_person_memorials_birthday_whole")),
        sa.CheckConstraint("fravardin_roj_months IS NULL OR fravardin_roj_months >= 1",
                           name=op.f("ck_person_memorials_fravardin_roj_length")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_memorials")),
    )
    op.create_index("idx_person_memorials_user", "person_memorials", ["user_id"])

    op.create_table(
        "person_memorial_observances",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("memorial_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("gregorian_date", sa.Date(), nullable=False),
        sa.Column("parsi_roj", sa.SmallInteger()),
        sa.Column("parsi_mah", sa.SmallInteger()),
        sa.Column("parsi_year", sa.Integer(), nullable=False),
        sa.Column("gatha_index", sa.SmallInteger()),
        sa.ForeignKeyConstraint(["memorial_id"], ["person_memorials.id"], ondelete="CASCADE",
                                name=op.f("fk_person_memorial_observances_memorial_id_person_memorials")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name=op.f("fk_person_memorial_observances_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_memorial_observances")),
        sa.UniqueConstraint("memorial_id", "code", name=op.f("uq_person_memorial_observance_code")),
    )
    op.create_index("idx_person_memorial_observances_user_date", "person_memorial_observances",
                    ["user_id", "gregorian_date"])

    op.create_table(
        "person_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("gregorian_date", sa.Date(), nullable=False),
        sa.Column("repeats", sa.String(20), server_default="none", nullable=False),
        sa.Column("parsi_roj", sa.SmallInteger()),
        sa.Column("parsi_mah", sa.SmallInteger()),
        sa.Column("parsi_calendar", sa.String(10)),
        sa.Column("notes", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name=op.f("fk_person_events_user_id_users")),
        sa.CheckConstraint("kind IN ('birthday', 'navjote', 'anniversary', 'other')",
                           name=op.f("ck_person_events_kind")),
        sa.CheckConstraint("repeats IN ('none', 'yearly_english', 'yearly_parsi')",
                           name=op.f("ck_person_events_repeats")),
        sa.CheckConstraint(
            "(repeats = 'yearly_parsi') = (parsi_roj IS NOT NULL AND parsi_mah IS NOT NULL"
            " AND parsi_calendar IS NOT NULL)",
            name=op.f("ck_person_events_parsi_day")),
        sa.CheckConstraint("parsi_calendar IS NULL OR parsi_calendar IN ('shenshai', 'kadmi', 'fasli')",
                           name=op.f("ck_person_events_parsi_calendar")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_events")),
    )
    op.create_index("idx_person_events_user", "person_events", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    held = {t: bind.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar_one() for t in TABLES}
    if any(held.values()):
        raise RuntimeError(
            "Cannot downgrade: people's own data exists (" + ", ".join(f"{t}: {n}" for t, n in held.items() if n)
            + "), and going back would delete it. Nothing is deleted by age or by downgrade (D8). "
            "Remove it deliberately first."
        )
    op.drop_index("idx_person_events_user", table_name="person_events")
    op.drop_table("person_events")
    op.drop_index("idx_person_memorial_observances_user_date", table_name="person_memorial_observances")
    op.drop_table("person_memorial_observances")
    op.drop_index("idx_person_memorials_user", table_name="person_memorials")
    op.drop_table("person_memorials")
    op.drop_table("person_agyari")
    op.drop_constraint(op.f("ck_agyaries_kind"), "agyaries", type_="check")
    op.drop_column("agyaries", "kind")
