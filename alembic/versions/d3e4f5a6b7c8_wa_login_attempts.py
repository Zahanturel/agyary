"""wa_login_attempts: inbound-WhatsApp sign-in

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-26 00:00:00.000000

Backs the reverse of the OTP flow. Instead of the caller claiming a phone
number and us sending a code to it, we mint a code attached to nobody, the
mobed sends it to us from their own WhatsApp, and the webhook learns the
number from the signed payload.

Nothing in this table identifies a person until claimed_phone is written,
and rows are short-lived - ten minutes by default, swept whenever a new
attempt starts. It is a queue of half-finished sign-ins, not a record of
anything.

Two unique columns rather than one because the code and the poll secret do
different jobs. The code is a bearer token by construction: it travels
through a wa.me link and the user's own WhatsApp, so anyone who sees it can
send it. The poll secret never leaves the originating browser's httpOnly
cookie, and polling matches on its digest - so holding the code is not
enough to collect the session that code created.

auth_otps is untouched. The outbound path stays as a fallback until this
one has proven itself against a real number.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'wa_login_attempts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=16), nullable=False),
        sa.Column('poll_secret_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('claimed_phone', sa.String(length=20), nullable=True),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_wa_login_attempts')),
        sa.UniqueConstraint('code', name=op.f('uq_wa_login_attempts_code')),
        sa.UniqueConstraint('poll_secret_hash', name=op.f('uq_wa_login_attempts_poll_secret_hash')),
    )
    op.create_index('idx_wa_login_attempts_expiry', 'wa_login_attempts', ['expires_at'], unique=False)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wa_login_attempts_expiry")
    op.execute("DROP TABLE IF EXISTS wa_login_attempts")
