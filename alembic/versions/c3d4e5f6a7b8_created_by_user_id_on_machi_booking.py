"""created_by_user_id on machis and bookings

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-07-26 00:00:00.000000

Records which mobed personally manually-entered a machi/booking via the
PWA's walk-in flow (mobed_dashboard.manual_add_machi /
manual_add_booking). This is the basis for "my customers" scoping: a
mobed's own behdins are the customers behind the machis/bookings they
themselves created - a customer relationship is personal to the mobed,
not to the fire temple (a mobed can serve any temple, but keeps his own
customer base). Nullable and unindexed-by-default-usage rows (WhatsApp-
originated bookings, pre-migration history) simply won't surface in that
mobed's customer search - never a correctness issue, since the customer
data itself is untouched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("machis", sa.Column("created_by_user_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_machis_created_by_user_id", "machis", "users", ["created_by_user_id"], ["id"]
    )
    op.create_index(
        "idx_machis_created_by", "machis", ["created_by_user_id"],
        postgresql_where=sa.text("created_by_user_id IS NOT NULL"),
    )

    op.add_column("bookings", sa.Column("created_by_user_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_bookings_created_by_user_id", "bookings", "users", ["created_by_user_id"], ["id"]
    )
    op.create_index(
        "idx_bookings_created_by", "bookings", ["created_by_user_id"],
        postgresql_where=sa.text("created_by_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_bookings_created_by", table_name="bookings")
    op.drop_constraint("fk_bookings_created_by_user_id", "bookings", type_="foreignkey")
    op.drop_column("bookings", "created_by_user_id")

    op.drop_index("idx_machis_created_by", table_name="machis")
    op.drop_constraint("fk_machis_created_by_user_id", "machis", type_="foreignkey")
    op.drop_column("machis", "created_by_user_id")
