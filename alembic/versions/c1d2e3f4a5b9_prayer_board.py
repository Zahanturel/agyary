"""The "Who will pray" board: who took a request, all set, and how each answer came

DECISIONS D10, changed 21 Nov 2026 (owner, three rounds); R3.1 step 4.

``funeral_requests``: ``taken_at`` / ``taken_by_user_id`` - the panthaky's
first action on the board (Ask everyone, I'll pray, a call's result) takes the
request for the fire temple; ``all_set_at`` - when the last place filled. The
status may now be "all_set" too; every other state stays as it was, and every
request from before keeps its state (D8).

``prayer_callout_answers``: ``how`` - how the person was asked and, once they
answer, how the answer came ("whatsapp", "app", "phone" or "self"); every row
from before was a WhatsApp call-out, so it reads "whatsapp". And
``recorded_by_user_id``: the panthaky who marked a phone answer or "I'll pray".

Revision ID: c1d2e3f4a5b9
Revises: b0c1d2e3f4a7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b9"
down_revision: Union[str, None] = "b0c1d2e3f4a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The request states as they were before and after, frozen here as they were
# when this ran (models/enums.py's REQUEST_STATUSES).
OLD_STATUSES = "status IN ('waiting', 'accepted', 'declined', 'withdrawn', 'taken')"
NEW_STATUSES = "status IN ('waiting', 'accepted', 'declined', 'withdrawn', 'taken', 'all_set')"
HOW = "how IN ('whatsapp', 'app', 'phone', 'self')"


def upgrade() -> None:
    op.add_column("funeral_requests", sa.Column("taken_at", sa.DateTime(timezone=True)))
    op.add_column("funeral_requests", sa.Column("taken_by_user_id", sa.BigInteger()))
    op.create_foreign_key(
        op.f("fk_funeral_requests_taken_by_user_id_users"), "funeral_requests", "users",
        ["taken_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column("funeral_requests", sa.Column("all_set_at", sa.DateTime(timezone=True)))
    op.drop_constraint(op.f("ck_funeral_requests_status"), "funeral_requests", type_="check")
    op.create_check_constraint(op.f("ck_funeral_requests_status"), "funeral_requests", NEW_STATUSES)

    # Every row from before reads "whatsapp" (the default fills them as the
    # column is added); the code always says how, and the default also keeps
    # the code from before this working while the new code starts.
    op.add_column(
        "prayer_callout_answers", sa.Column("how", sa.String(10), server_default="whatsapp", nullable=False),
    )
    op.create_check_constraint(op.f("ck_prayer_callout_answers_how"), "prayer_callout_answers", HOW)
    op.add_column("prayer_callout_answers", sa.Column("recorded_by_user_id", sa.BigInteger()))
    op.create_foreign_key(
        op.f("fk_prayer_callout_answers_recorded_by_user_id_users"), "prayer_callout_answers", "users",
        ["recorded_by_user_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_prayer_callout_answers_recorded_by_user_id_users"), "prayer_callout_answers",
                       type_="foreignkey")
    op.drop_column("prayer_callout_answers", "recorded_by_user_id")
    op.drop_constraint(op.f("ck_prayer_callout_answers_how"), "prayer_callout_answers", type_="check")
    op.drop_column("prayer_callout_answers", "how")

    # An all-set request had enough mobeds going: before this it reads as
    # accepted, which is the nearest state there was (D8: nothing is deleted).
    op.execute("UPDATE funeral_requests SET status = 'accepted' WHERE status = 'all_set'")
    op.drop_constraint(op.f("ck_funeral_requests_status"), "funeral_requests", type_="check")
    op.create_check_constraint(op.f("ck_funeral_requests_status"), "funeral_requests", OLD_STATUSES)
    op.drop_column("funeral_requests", "all_set_at")
    op.drop_constraint(op.f("fk_funeral_requests_taken_by_user_id_users"), "funeral_requests", type_="foreignkey")
    op.drop_column("funeral_requests", "taken_by_user_id")
    op.drop_column("funeral_requests", "taken_at")
