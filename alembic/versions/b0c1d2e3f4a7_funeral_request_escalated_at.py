"""funeral_requests: when the safety net asked all the mobeds

DECISIONS D10, changed 21 Nov 2026 (owner); R3.1 step 2. In Come to me first,
if the panthaky has not acted within the minutes they chose, the one-minute
loop (services/prayer_timers.py) asks all the fire temple's mobeds on WhatsApp,
once. ``escalated_at`` is when it did (claimed before anything is sent, so two
loops or a restart never ask twice); NULL means it has not.

Every request from before reads NULL: the safety net is new, and nothing else
is filled here.

Revision ID: b0c1d2e3f4a7
Revises: a9b0c1d2e3f6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4a7"
down_revision: Union[str, None] = "a9b0c1d2e3f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("funeral_requests", sa.Column("escalated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("funeral_requests", "escalated_at")
