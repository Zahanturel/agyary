"""R4.2 redesign: a request follows what the fire temple does to its result

- ``service_asks.status`` may be ``cancelled_by_fire_temple`` (so the column is
  wider).
- ``service_asks.changed_at``: when the fire temple last changed the date, time
  or geh of what an accepted request made.

Revision ID: f6a0b1c2d3e4
Revises: e5f6a0b1c2d3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a0b1c2d3e4"
down_revision: Union[str, None] = "e5f6a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "status IN ('waiting', 'accepted', 'rejected', 'cancelled')"
NEW = "status IN ('waiting', 'accepted', 'rejected', 'cancelled', 'cancelled_by_fire_temple')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_service_asks_status"), "service_asks", type_="check")
    op.alter_column("service_asks", "status", type_=sa.String(30), existing_nullable=False,
                    existing_server_default="waiting")
    op.create_check_constraint(op.f("ck_service_asks_status"), "service_asks", NEW)
    op.add_column("service_asks", sa.Column("changed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    held = op.get_bind().execute(
        sa.text("SELECT count(*) FROM service_asks WHERE status = 'cancelled_by_fire_temple'")).scalar_one()
    if held:
        raise RuntimeError("Cannot downgrade: requests cancelled by a fire temple exist (D8).")
    op.drop_column("service_asks", "changed_at")
    op.drop_constraint(op.f("ck_service_asks_status"), "service_asks", type_="check")
    op.alter_column("service_asks", "status", type_=sa.String(10), existing_nullable=False,
                    existing_server_default="waiting")
    op.create_check_constraint(op.f("ck_service_asks_status"), "service_asks", OLD)
