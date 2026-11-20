"""agyaries: how a prayer request reaches the fire temple, and the safety net

DECISIONS D10, changed 21 Nov 2026 (owner); R3.1 step 1. The panthaky chooses
on Settings -> Prayer requests: ``request_mode`` is "everyone" (every mobed on
the fire temple's list is asked on WhatsApp at Send, as before) or
"panthaky_first" (only the panthaky is told). ``request_escalate_minutes`` is
the safety net in "panthaky_first": 15, 30 or 60 minutes without the panthaky
acting, then all its mobeds are asked; NULL is Never.

Every existing fire temple reads "everyone" and Never, which is what is live
today; nothing else is filled here.

Revision ID: a9b0c1d2e3f6
Revises: f8a9b0c1d2e5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9b0c1d2e3f6"
down_revision: Union[str, None] = "f8a9b0c1d2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The same text as models/agyary.py's ESCALATE_CHECK, frozen here as it was
# when this ran.
ESCALATE_CHECK = "request_escalate_minutes IS NULL OR request_escalate_minutes IN (15, 30, 60)"


def upgrade() -> None:
    op.add_column(
        "agyaries", sa.Column("request_mode", sa.String(20), server_default="everyone", nullable=False),
    )
    op.add_column("agyaries", sa.Column("request_escalate_minutes", sa.SmallInteger()))
    op.create_check_constraint(
        op.f("ck_agyaries_request_mode"), "agyaries", "request_mode IN ('everyone', 'panthaky_first')"
    )
    op.create_check_constraint(op.f("ck_agyaries_request_escalate_minutes"), "agyaries", ESCALATE_CHECK)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_agyaries_request_escalate_minutes"), "agyaries", type_="check")
    op.drop_constraint(op.f("ck_agyaries_request_mode"), "agyaries", type_="check")
    op.drop_column("agyaries", "request_escalate_minutes")
    op.drop_column("agyaries", "request_mode")
