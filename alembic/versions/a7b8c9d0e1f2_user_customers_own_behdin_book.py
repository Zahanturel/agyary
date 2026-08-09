"""user_customers: a mobed's own behdin book

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-10 00:00:00.000000

A behdin's name and phone number belong to them. They are not the shared
property of everyone who happens to work at the same fire temple, and the
behdin list must therefore be scoped to the mobed who registered or served
them - enforced in the query, not filtered in the client.

Ownership could not previously be expressed. It was inferred from
``created_by_user_id`` on machis and bookings, which says nothing about a
behdin registered ahead of any ceremony; so "my behdins" could not include
someone entered five minutes ago, and the only list that could actually be
built was the whole temple's.

The backfill reconstructs ownership from exactly that inference, which is
the best evidence available for rows that predate this table: whoever
entered a machi or booking for a behdin is taken to know them.
WhatsApp-originated ceremonies have a NULL created_by_user_id and so
produce no owner - correct, since no mobed entered them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_customers",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_customers_user_id"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name=op.f("fk_user_customers_customer_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "customer_id", name=op.f("pk_user_customers")),
    )
    op.create_index("idx_user_customers_customer", "user_customers", ["customer_id"])

    # Backfill from who entered each ceremony. UNION dedupes across the two
    # tables, and ON CONFLICT guards the case where the same pair appears in
    # both - a mobed who did a machi and a booking for the same behdin.
    op.execute(
        """
        INSERT INTO user_customers (user_id, customer_id)
        SELECT created_by_user_id, customer_id FROM machis
         WHERE created_by_user_id IS NOT NULL
        UNION
        SELECT created_by_user_id, customer_id FROM bookings
         WHERE created_by_user_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("idx_user_customers_customer", table_name="user_customers")
    op.drop_table("user_customers")
