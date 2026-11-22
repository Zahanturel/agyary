"""funeral_requests: closed because nobody at the fire temple could take it

DECISIONS D10, changed 21 Nov 2026 (owner, third round); R3.1 step 7. At a fire
temple with no panthaky in the app, a request closes as declined once everyone
asked has said no, and the funeral place reads "Nobody at <agyari> can take
it". ``nobody_could`` marks that close, instead of guessing it from nobody
being recorded as declining (a panthaky who declined and later deleted their
account must still read "Declined by <agyari>"). Only a declined request can be
so marked.

Every request from before reads false: no request closed that way was ever
live, so nothing else is filled here.

Revision ID: a5b6c7d8e9f4
Revises: f4a5b6c7d8e2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a5b6c7d8e9f4"
down_revision: Union[str, None] = "f4a5b6c7d8e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "funeral_requests"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("nobody_could", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_check_constraint(
        op.f("ck_funeral_requests_nobody_could_declined"), TABLE, "NOT nobody_could OR status = 'declined'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_funeral_requests_nobody_could_declined"), TABLE, type_="check")
    op.drop_column(TABLE, "nobody_could")
