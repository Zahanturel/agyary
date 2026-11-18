"""The family's agreement to WhatsApp messages, and who a send went to

DECISIONS D10 (its 18 Nov 2026 amendment), Phase 2 Step 5b. The manager's tick
now also says the family agreed to get WhatsApp messages about the prayers from
Mobed Diary: ``funeral_requests.family_whatsapp_agreed``, false for every
request sent before those words (so none of them is ever messaged).

``notifications.recipient_type`` gains "family" (a funeral record's family
contact) and "contact" (a mobed on a fire temple's own list, Step 5c).

Revision ID: c5d6e7f8a9b1
Revises: b4c5d6e7f8a0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b1"
down_revision: Union[str, None] = "b4c5d6e7f8a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "funeral_requests",
        sa.Column("family_whatsapp_agreed", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.drop_constraint(op.f("ck_notifications_recipient_type"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_recipient_type"), "notifications",
        "recipient_type IN ('user', 'customer', 'family', 'contact')",
    )


def downgrade() -> None:
    # Sends to a family or a listed mobed have no place in the older schema.
    op.execute("DELETE FROM notifications WHERE recipient_type IN ('family', 'contact')")
    op.drop_constraint(op.f("ck_notifications_recipient_type"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_recipient_type"), "notifications", "recipient_type IN ('user', 'customer')",
    )
    op.drop_column("funeral_requests", "family_whatsapp_agreed")
