"""whatsapp outbox send-worker columns

Revision ID: b851d2238381
Revises: 95e8e63f8bc9
Create Date: 2026-07-22 16:51:46.954727

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b851d2238381'
down_revision: Union[str, None] = '95e8e63f8bc9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_messages",
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_wa_messages_outbox_pending",
        "whatsapp_messages",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("direction = 'outbound' AND status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_wa_messages_outbox_pending",
        table_name="whatsapp_messages",
        postgresql_where=sa.text("direction = 'outbound' AND status = 'pending'"),
    )
    op.drop_column("whatsapp_messages", "next_attempt_at")
    op.drop_column("whatsapp_messages", "attempts")
