"""All set: whose book a request put the family in, confirmed short, still short

DECISIONS D10, changed 21 Nov 2026 (owner); R3.1 step 5.

``funeral_request_books``: at All set the family goes into the own book of the
panthaky who took the request (or each confirmed panthaky it reached, if
nobody took it) and of each app mobed going - one row per person per request,
with their own record of the family (``customer_id``) and the memorial they
make from it (``memorial_id``), so each has "Make the memorial" or "Open the
memorial" for their own. ``is_panthaky``: set up as the request's panthaky.
The row goes with the request or the person's account; the record or the
memorial going (a family's erasure) leaves it empty. Requests accepted before
R3.1 keep their single ``funeral_requests.memorial_id`` (D8).

``funeral_requests.confirmed_short``: all set with fewer mobeds than wanted
("Confirm with who's going"); false for every request from before.
``funeral_requests.short_alert_at``: when "Still 1 mobed short" was told,
4 hours before the Geh-saarnu; NULL for every request from before.

Revision ID: d2e3f4a5b6c0
Revises: c1d2e3f4a5b9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c0"
down_revision: Union[str, None] = "c1d2e3f4a5b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "funeral_requests", sa.Column("confirmed_short", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("funeral_requests", sa.Column("short_alert_at", sa.DateTime(timezone=True)))

    op.create_table(
        "funeral_request_books",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("funeral_request_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger()),
        sa.Column("memorial_id", sa.BigInteger()),
        sa.Column("is_panthaky", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["funeral_request_id"], ["funeral_requests.id"], ondelete="CASCADE",
            name=op.f("fk_funeral_request_books_funeral_request_id_funeral_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_funeral_request_books_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], ondelete="SET NULL",
            name=op.f("fk_funeral_request_books_customer_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["memorial_id"], ["memorials.id"], ondelete="SET NULL",
            name=op.f("fk_funeral_request_books_memorial_id_memorials"),
        ),
        sa.UniqueConstraint("funeral_request_id", "user_id", name="uq_funeral_request_books_request_user"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_funeral_request_books")),
    )
    op.create_index("idx_funeral_request_books_user", "funeral_request_books", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_funeral_request_books_user", table_name="funeral_request_books")
    op.drop_table("funeral_request_books")
    op.drop_column("funeral_requests", "short_alert_at")
    op.drop_column("funeral_requests", "confirmed_short")
