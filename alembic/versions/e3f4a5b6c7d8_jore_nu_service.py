"""the "Jore nu" service, for every fire temple that has a service catalog

A prayer offered with the memorial prayers (Afringan, Farokshi, Baaj, Satum, Jashan, and now
Jore nu). Added to every fire temple that has a catalog and does not list it; a fire
temple that already has a service of that name is left alone. New fire temples get it from
DEFAULT_SERVICE_SPECS. Additive only.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # After the temple's last ordinary service; 999 is where custom services sit.
    op.execute("""
        INSERT INTO services (agyary_id, name, min_mobeds, offsite_capable, is_active, display_order)
        SELECT a.id, 'Jore nu', 1, false, true,
               COALESCE((SELECT MAX(s1.display_order) FROM services s1
                         WHERE s1.agyary_id = a.id AND s1.display_order < 999), 0) + 1
        FROM agyaries a
        WHERE EXISTS (SELECT 1 FROM services s0 WHERE s0.agyary_id = a.id)
          AND NOT EXISTS (
            SELECT 1 FROM services s
            WHERE s.agyary_id = a.id AND lower(trim(s.name)) = 'jore nu'
        )
    """)


def downgrade() -> None:
    # Left in the catalog: a mobed may have used it since, and a service in use
    # cannot be quietly removed.
    pass
