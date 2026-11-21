"""funeral_requests: when the funeral place was told nobody has answered in an hour

DECISIONS D10, changed 21 Nov 2026 (owner, third round); R3.1 step 6. If
nobody at the fire temple has answered or taken a request an hour after it was
sent, the one-minute loop (services/prayer_timers.py) tells the funeral
place's managers "No answer yet from <agyari>", once. ``no_answer_alert_at``
is when it did (claimed before anyone is told, so two loops or a restart never
tell twice); NULL means it has not. It is never before the request was sent.

Every request from before reads NULL: nothing else is filled here.

Revision ID: f4a5b6c7d8e2
Revises: e3f4a5b6c7d1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4a5b6c7d8e2"
down_revision: Union[str, None] = "e3f4a5b6c7d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "funeral_requests"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("no_answer_alert_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        op.f("ck_funeral_requests_no_answer_after_sent"), TABLE,
        "no_answer_alert_at IS NULL OR no_answer_alert_at >= sent_at",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_funeral_requests_no_answer_after_sent"), TABLE, type_="check")
    op.drop_column(TABLE, "no_answer_alert_at")
