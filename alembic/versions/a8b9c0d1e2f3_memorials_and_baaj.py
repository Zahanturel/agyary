"""memorials, their observances, and Baaj in the service catalog

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-10-02 00:00:00.000000

A memorial is the set of observances a family keeps for one departed person.
Its observances are rows of their own rather than bookings: a booking has one
service, a mobed to accept it and a slip, while an observance carries any
subset of Afringan / Farokshi / Baaj and an optional time. See
docs/memorial-plan.md.

Baaj is added to the service catalog of every existing fire temple (new ones
get it from ensure_default_services). It goes in next to Farokshi, where it is
found with the other prayers, shifting later services down by one. A fire
temple that already has a service called Baaj is left alone.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BAAJ_ORDER = 4  # right after Machi, Jashan, Afringan, Farokshi


def upgrade() -> None:
    op.create_table(
        "memorials",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("agyary_id", sa.BigInteger(), sa.ForeignKey("agyaries.id"), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("departed_name", sa.String(200), nullable=False),
        sa.Column("death_gregorian", sa.Date(), nullable=False),
        sa.Column("death_roj", sa.SmallInteger(), nullable=False),
        sa.Column("death_mah", sa.SmallInteger(), nullable=False),
        sa.Column("death_year", sa.Integer(), nullable=False),
        sa.Column("calendar_system", sa.String(10), nullable=False),
        sa.Column("opening", sa.String(20), nullable=False),
        sa.Column("day_counts", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("monthly_months", sa.SmallInteger()),
        sa.Column("yearly_years", sa.SmallInteger()),
        sa.Column("parabs", sa.String(20)),
        sa.Column("parab_years", sa.SmallInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("calendar_system IN ('shenshai', 'kadmi', 'fasli')", name="ck_memorials_calendar_system"),
        sa.CheckConstraint("opening IN ('days_1_to_10', 'tenth_only')", name="ck_memorials_opening"),
        sa.CheckConstraint("parabs IS NULL OR parabs IN ('all', 'fravardin_tir')", name="ck_memorials_parabs"),
        sa.CheckConstraint("death_mah BETWEEN 1 AND 12", name="ck_memorials_death_mah"),
        sa.CheckConstraint("death_roj BETWEEN 1 AND 30", name="ck_memorials_death_roj"),
        sa.CheckConstraint("(parabs IS NULL) = (parab_years IS NULL)", name="ck_memorials_parab_length"),
        sa.CheckConstraint("monthly_months IS NULL OR monthly_months >= 1", name="ck_memorials_monthly_length"),
        sa.CheckConstraint("yearly_years IS NULL OR yearly_years >= 1", name="ck_memorials_yearly_length"),
    )
    op.create_index("idx_memorials_customer", "memorials", ["customer_id"])
    op.create_index("idx_memorials_owner", "memorials", ["created_by_user_id", "agyary_id"])

    op.create_table(
        "memorial_observances",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("memorial_id", sa.BigInteger(), sa.ForeignKey("memorials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("gregorian_date", sa.Date(), nullable=False),
        sa.Column("parsi_roj", sa.SmallInteger()),
        sa.Column("parsi_mah", sa.SmallInteger()),
        sa.Column("parsi_year", sa.Integer(), nullable=False),
        sa.Column("gatha_index", sa.SmallInteger()),
        sa.Column("time_of_day", sa.Time()),
        sa.Column("notes", sa.Text()),
        sa.UniqueConstraint("memorial_id", "code", name="uq_memorial_observance_code"),
    )
    op.create_index("idx_memorial_observances_date", "memorial_observances", ["gregorian_date"])

    op.create_table(
        "memorial_observance_services",
        sa.Column("observance_id", sa.BigInteger(),
                  sa.ForeignKey("memorial_observances.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("service_id", sa.BigInteger(), sa.ForeignKey("services.id"), primary_key=True),
    )

    # Baaj, for every fire temple that does not already list one.
    lacking = """
        FROM agyaries a
        WHERE NOT EXISTS (
            SELECT 1 FROM services s
            WHERE s.agyary_id = a.id AND lower(trim(s.name)) = 'baaj'
        )
    """
    # 999 is where custom services sit (see create_service); leave it be.
    op.execute(f"""
        UPDATE services SET display_order = display_order + 1
        WHERE display_order >= {BAAJ_ORDER} AND display_order < 999
          AND agyary_id IN (SELECT a.id {lacking})
    """)
    op.execute(f"""
        INSERT INTO services (agyary_id, name, min_mobeds, offsite_capable, is_active, display_order)
        SELECT a.id, 'Baaj', 1, true, true, {BAAJ_ORDER} {lacking}
    """)


def downgrade() -> None:
    op.drop_table("memorial_observance_services")
    op.drop_index("idx_memorial_observances_date", table_name="memorial_observances")
    op.drop_table("memorial_observances")
    op.drop_index("idx_memorials_owner", table_name="memorials")
    op.drop_index("idx_memorials_customer", table_name="memorials")
    op.drop_table("memorials")
    # Baaj is left in the catalog: a mobed may have used it since, and a
    # service in use cannot be quietly removed.
