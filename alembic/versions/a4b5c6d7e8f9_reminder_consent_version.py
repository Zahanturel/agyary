"""reminder consent: which words were read to the family

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-10-13 00:00:00.000000

customers.reminders_consent_version keeps which version of the consent words
the mobed read out when the family agreed (RM-6). Agreements recorded before
this have none, which is the truth: the words were not recorded then.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("reminders_consent_version", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "reminders_consent_version")
