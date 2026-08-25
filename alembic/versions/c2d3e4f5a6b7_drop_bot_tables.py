"""Drop conversation_states and whatsapp_messages

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-08-26 00:00:00.000000

The behdin-facing WhatsApp bot is gone: the conversation flows, the text
handler, the send worker and the webhook. These two tables were its
storage and nothing else ever wrote to them.

conversation_states held one in-progress conversation per (agyari, phone)
- which flow, which step, and the partial answers - so a behdin could
reply over minutes. whatsapp_messages was the send outbox and the inbound
log, and carried the wa_message_id used to deduplicate webhook redeliveries.

Sign-in is unaffected. WhatsApp OTP stays, and it never touched either
table: services/otp_delivery.py posts to the Cloud API directly and
deliberately does not queue through the outbox, so it has no dependency
on any of this. Codes live in auth_otps, which is untouched.

No FK anywhere points at either table, so this drops cleanly.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF EXISTS for the same reason as the invites drop before it: a drop
    # that refuses to run because the thing is already absent wedges the
    # chain and helps nobody.
    op.execute("DROP INDEX IF EXISTS idx_wa_messages_wa_id")
    op.execute("DROP INDEX IF EXISTS idx_wa_messages_agyary_phone")
    op.execute("DROP TABLE IF EXISTS whatsapp_messages")
    op.execute("DROP INDEX IF EXISTS idx_conversation_states_expiry")
    op.execute("DROP TABLE IF EXISTS conversation_states")


def downgrade() -> None:
    """Recreates both tables empty. The rows are not recoverable and nothing
    reads them any more - this exists so the chain stays reversible, not
    because downgrading brings the bot back."""
    op.create_table(
        'conversation_states',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('agyary_id', sa.BigInteger(), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('flow', sa.String(length=50), nullable=False),
        sa.Column('step', sa.String(length=50), nullable=False),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_conversation_states_agyary_id_agyaries')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conversation_states')),
        sa.UniqueConstraint('agyary_id', 'phone', name='uq_conversation_states_agyary_phone'),
    )
    op.create_index('idx_conversation_states_expiry', 'conversation_states', ['expires_at'], unique=False)
    op.create_table(
        'whatsapp_messages',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('agyary_id', sa.BigInteger(), nullable=False),
        sa.Column('direction', sa.String(length=10), nullable=False),
        sa.Column('wa_phone', sa.String(length=20), nullable=False),
        sa.Column('customer_id', sa.BigInteger(), nullable=True),
        sa.Column('wa_message_id', sa.String(length=100), nullable=True),
        sa.Column('wa_timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.Column('message_type', sa.String(length=20), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('template_name', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("direction IN ('inbound', 'outbound')", name=op.f('ck_whatsapp_messages_direction')),
        sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_whatsapp_messages_agyary_id_agyaries')),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_whatsapp_messages_customer_id_customers')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_whatsapp_messages')),
    )
    op.create_index('idx_wa_messages_agyary_phone', 'whatsapp_messages', ['agyary_id', 'wa_phone', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('idx_wa_messages_wa_id', 'whatsapp_messages', ['wa_message_id'], unique=False, postgresql_where=sa.text('wa_message_id IS NOT NULL'))
