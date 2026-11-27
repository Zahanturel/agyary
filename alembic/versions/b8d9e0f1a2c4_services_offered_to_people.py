"""Which services people can ask for: a flag of its own, off by default

``services.offered_to_people`` is the panthaky's list of what the Parsi app shows. It is separate from
``is_active`` (the diary's catalog), so listing or unlisting a service for people never touches the
mobed's diary. New rows are off. Fire temples already taking requests keep what people could pick
until now: their active, priced services are listed.

Revision ID: b8d9e0f1a2c4
Revises: a7c8d9e0f1b2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d9e0f1a2c4"
down_revision: Union[str, None] = "a7c8d9e0f1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("services", sa.Column("offered_to_people", sa.Boolean(), server_default="false", nullable=False))
    op.execute(
        "UPDATE services SET offered_to_people = true "
        "WHERE is_active AND default_price IS NOT NULL "
        "AND agyary_id IN (SELECT id FROM agyaries WHERE takes_asks)"
    )


def downgrade() -> None:
    op.drop_column("services", "offered_to_people")
