"""trigram index on agyary name

Revision ID: 55a2a2c34be8
Revises: f2968639bc39
Create Date: 2026-07-23 14:22:02.014797

Mobed onboarding needs fuzzy agyari search (the mobed types their agyari's
name, per doc 05). Reuses the exact same trigram approach already used for
customer search (idx_customers_name_trgm) - pg_trgm is already enabled by
the initial migration, so this just adds the matching index on agyaries.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55a2a2c34be8'
down_revision: Union[str, None] = 'f2968639bc39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_agyaries_name_trgm",
        "agyaries",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "idx_agyaries_name_trgm",
        table_name="agyaries",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
