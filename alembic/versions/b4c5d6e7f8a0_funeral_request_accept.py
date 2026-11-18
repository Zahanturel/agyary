"""What accepting a funeral request records

DECISIONS D10 (and its 18 Nov amendment), Phase 2 Step 5. When a mobed accepts
a request they say whether the funeral place may have their name and number
(a tick, on by default): ``funeral_requests.accepter_shared_contact``. It is
set only on an accepted request (a check), and it is what the manager's screen
reads to show the number, and what the WhatsApp messages from our number
(Step 5b, not built) will read before writing to the manager.

``funeral_requests.memorial_id``: the memorial the accepter saved from it, if
they did; cleared if that memorial is deleted. Never shown to the manager (D2).

Revision ID: b4c5d6e7f8a0
Revises: a3b4c5d6e7f9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a0"
down_revision: Union[str, None] = "a3b4c5d6e7f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("funeral_requests", sa.Column("accepter_shared_contact", sa.Boolean()))
    op.add_column("funeral_requests", sa.Column("memorial_id", sa.BigInteger()))
    op.create_foreign_key(
        op.f("fk_funeral_requests_memorial_id_memorials"), "funeral_requests", "memorials",
        ["memorial_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_funeral_requests_shared_contact"), "funeral_requests",
        "accepter_shared_contact IS NULL OR status IN ('accepted', 'taken')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_funeral_requests_shared_contact"), "funeral_requests", type_="check")
    op.drop_constraint(op.f("fk_funeral_requests_memorial_id_memorials"), "funeral_requests", type_="foreignkey")
    op.drop_column("funeral_requests", "memorial_id")
    op.drop_column("funeral_requests", "accepter_shared_contact")
