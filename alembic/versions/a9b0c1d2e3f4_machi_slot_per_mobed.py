"""A machi slot is each mobed's own

Revision ID: a9b0c1d2e3f4
Revises: e3f4a5b6c7d8
Create Date: 2026-10-29 00:00:00.000000

The slot rule was one active machi per geh per day per fire temple. A mobed's
machis are private to them (docs/DECISIONS.md D2), and under that rule the
second mobed to ask for a geh was told it was taken - which says a colleague
holds it. The rule becomes one per geh per day per temple per mobed.

A missing owner (created_by_user_id is nullable) is folded into one bucket
with coalesce(..., 0): NULLs are distinct in a unique index, so without it
such rows could never collide with each other.

The new rule is strictly looser than the old one, so no existing row can
violate it. Downgrading restores the old rule and fails if two mobeds have
meanwhile booked the same geh on the same day.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WHERE = "status NOT IN ('cancelled', 'declined', 'rescheduled')"


def upgrade() -> None:
    op.execute("DROP INDEX uq_machis_slot")
    op.execute(
        "CREATE UNIQUE INDEX uq_machis_slot ON machis "
        "(agyary_id, parsi_roj, parsi_mah, parsi_year, geh, (coalesce(created_by_user_id, 0))) "
        f"WHERE {_WHERE}"
    )


def downgrade() -> None:
    op.execute("DROP INDEX uq_machis_slot")
    op.execute(
        "CREATE UNIQUE INDEX uq_machis_slot ON machis "
        "(agyary_id, parsi_roj, parsi_mah, parsi_year, geh) "
        f"WHERE {_WHERE}"
    )
