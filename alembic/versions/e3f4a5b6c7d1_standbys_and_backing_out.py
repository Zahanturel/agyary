"""Standbys and backing out: a mobed going who can no longer go, and a standby asked again

DECISIONS D10, changed 21 Nov 2026 (owner, second round); R3.1 step 5b.

``prayer_callout_answers``:

- ``backed_out_at`` / ``backed_out_by_user_id``: someone going said they can no
  longer go ("I can't go any more" in the app or on WhatsApp, or the panthaky
  marking it on the board). Only someone going (``picked_at``) can; they keep
  ``picked_at`` as history but no longer hold a place.
- ``reask_token`` (unique, unguessable), ``reasked_at``: a standby asked again
  when a place opened; ``reask_answer`` / ``reask_answered_at``: their first
  answer to it (yes or no); ``reask_passed_at``: when the asking moved on past
  them (their no, or 30 minutes without an answer).

Every row from before keeps what it had, with all of these empty (D8).

Revision ID: e3f4a5b6c7d1
Revises: d2e3f4a5b6c0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f4a5b6c7d1"
down_revision: Union[str, None] = "d2e3f4a5b6c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "prayer_callout_answers"
# The checks, frozen here as they were when this ran.
CHECKS = {
    "backed_out_was_going": "backed_out_at IS NULL OR picked_at IS NOT NULL",
    "reasked": "(reask_token IS NULL) = (reasked_at IS NULL)",
    "reask_answer": "reask_answer IN ('yes', 'no')",
    "reask_answered": "(reask_answer IS NULL) = (reask_answered_at IS NULL)",
    "reask_answer_asked": "reask_answer IS NULL OR reasked_at IS NOT NULL",
    "reask_passed_asked": "reask_passed_at IS NULL OR reasked_at IS NOT NULL",
}


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("backed_out_at", sa.DateTime(timezone=True)))
    op.add_column(TABLE, sa.Column("backed_out_by_user_id", sa.BigInteger()))
    op.create_foreign_key(
        op.f("fk_prayer_callout_answers_backed_out_by_user_id_users"), TABLE, "users",
        ["backed_out_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column(TABLE, sa.Column("reask_token", sa.String(40)))
    op.create_unique_constraint(op.f("uq_prayer_callout_answers_reask_token"), TABLE, ["reask_token"])
    op.add_column(TABLE, sa.Column("reasked_at", sa.DateTime(timezone=True)))
    op.add_column(TABLE, sa.Column("reask_answer", sa.String(5)))
    op.add_column(TABLE, sa.Column("reask_answered_at", sa.DateTime(timezone=True)))
    op.add_column(TABLE, sa.Column("reask_passed_at", sa.DateTime(timezone=True)))
    for name, sql in CHECKS.items():
        op.create_check_constraint(op.f(f"ck_prayer_callout_answers_{name}"), TABLE, sql)


def downgrade() -> None:
    for name in reversed(CHECKS):
        op.drop_constraint(op.f(f"ck_prayer_callout_answers_{name}"), TABLE, type_="check")
    # Before this there was no way to say someone going can no longer go: they read as
    # not going (a yes without a place), the nearest there was, and their row is kept (D8).
    op.execute(f"UPDATE {TABLE} SET picked_at = NULL WHERE backed_out_at IS NOT NULL")
    op.drop_column(TABLE, "reask_passed_at")
    op.drop_column(TABLE, "reask_answered_at")
    op.drop_column(TABLE, "reask_answer")
    op.drop_column(TABLE, "reasked_at")
    op.drop_constraint(op.f("uq_prayer_callout_answers_reask_token"), TABLE, type_="unique")
    op.drop_column(TABLE, "reask_token")
    op.drop_constraint(op.f("fk_prayer_callout_answers_backed_out_by_user_id_users"), TABLE, type_="foreignkey")
    op.drop_column(TABLE, "backed_out_by_user_id")
    op.drop_column(TABLE, "backed_out_at")
