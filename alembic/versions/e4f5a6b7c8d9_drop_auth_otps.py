"""Drop auth_otps: the outbound OTP sign-in path is gone

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-08-26 00:00:00.000000

Sign-in is now only inbound: the mobed messages us a code and the webhook
learns their number off a payload Meta signed (wa_login_attempts, added in
the previous revision). The outbound half - claim a number, receive a
6-digit code, type it back - has been removed along with the routes, the
delivery service and the login screen that drove it. This table was its
only storage.

Nothing else ever read it. No FK anywhere points at it, so this drops
cleanly, and the rows it held were single-use codes with a five-minute
expiry - there was nothing durable in it to lose even before the path was
removed.

Dropping this also removes the last reason the deployment needed a
WhatsApp API token: everything that sent is gone, so the Meta App needs no
System User token and no approved Authentication template, only an app
secret to verify inbound signatures against.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF EXISTS, matching the drops before it: a drop that refuses to run
    # because the thing is already absent wedges the chain and helps nobody.
    op.execute("DROP TABLE IF EXISTS auth_otps")


def downgrade() -> None:
    """Recreates the table empty, exactly as the initial schema declared it.

    The rows are not recoverable and nothing reads them any more. This
    exists so the chain stays reversible, not because downgrading brings
    the OTP path back - the routes, the delivery service and the screen
    would all have to come back with it.
    """
    op.create_table(
        'auth_otps',
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempts', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('phone', name=op.f('pk_auth_otps')),
    )
