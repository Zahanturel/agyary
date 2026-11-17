"""agyaries: where each fire temple is on the map

For the Doongerwadi side (docs/DECISIONS.md D10): a funeral place's manager is
shown the fire temples nearest first. ``latitude`` and ``longitude`` are the
position; ``location_source`` says how good it is - "town" for the seed list's
town-level start (agyary.scripts.seed_fire_temple_locations), "pin" for one a
person put on the map. All three are set together or all empty. Who last moved
it (cleared if their account goes) and when are kept for the record.

Every existing fire temple starts with no position; nothing is filled here.

Revision ID: d0e1f2a3b4c6
Revises: c9d0e1f2a3b5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c6"
down_revision: Union[str, None] = "c9d0e1f2a3b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The same text as models/agyary.py's LOCATION_CHECK, frozen here as it was
# when this ran. IS NOT NULL is spelled out because a CHECK that comes out NULL
# passes, so a bare BETWEEN would let a half-set position through.
LOCATION_CHECK = (
    "(latitude IS NULL AND longitude IS NULL AND location_source IS NULL)"
    " OR (latitude IS NOT NULL AND longitude IS NOT NULL AND location_source IS NOT NULL"
    " AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)"
)


def upgrade() -> None:
    op.add_column("agyaries", sa.Column("latitude", sa.Double()))
    op.add_column("agyaries", sa.Column("longitude", sa.Double()))
    op.add_column("agyaries", sa.Column("location_source", sa.String(10)))
    op.add_column("agyaries", sa.Column("location_set_by_user_id", sa.BigInteger()))
    op.add_column("agyaries", sa.Column("location_set_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        op.f("fk_agyaries_location_set_by_user_id_users"), "agyaries", "users",
        ["location_set_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_agyaries_location_source"), "agyaries", "location_source IN ('town', 'pin')"
    )
    op.create_check_constraint(op.f("ck_agyaries_location"), "agyaries", LOCATION_CHECK)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_agyaries_location"), "agyaries", type_="check")
    op.drop_constraint(op.f("ck_agyaries_location_source"), "agyaries", type_="check")
    op.drop_constraint(op.f("fk_agyaries_location_set_by_user_id_users"), "agyaries", type_="foreignkey")
    op.drop_column("agyaries", "location_set_at")
    op.drop_column("agyaries", "location_set_by_user_id")
    op.drop_column("agyaries", "location_source")
    op.drop_column("agyaries", "longitude")
    op.drop_column("agyaries", "latitude")
