"""services: the standard "Wedding" and "Vandidad" are now "Lagan" and "Vendidad"

DECISIONS D11, the owner's word review (23 Nov 2026): the standard list of
ceremonies a fire temple starts with (booking_service.DEFAULT_SERVICE_SPECS)
says Lagan, not Wedding, and Vendidad, not Vandidad.

Each fire temple's service whose name is exactly the old standard name, as the
list stored it ("Wedding", "Vandidad"), takes the new one. Left as it is:

- a service a mobed named differently ("wedding", "Wedding ceremony", ...);
- a service at a fire temple that already has one by the new name, in any
  case, so that no fire temple ends up with the same ceremony twice.

Bookings, bulk batches and memorial days hold the service's id, not a copy of
its name, so every screen (past ones included) reads the new name from the
service. The WhatsApp messages already sent keep the words they went with
(notifications.template_params, D8). Nothing else changes: not the price, the
order, the dates or anything booked.

The downgrade renames them back, exact matches only and with the same care.
It cannot tell a service this renamed from one a mobed had already named
"Lagan" or "Vendidad" themselves, so those are renamed too.

Revision ID: c7d8e9f0a1b6
Revises: b6c7d8e9f0a5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b6"
down_revision: Union[str, None] = "b6c7d8e9f0a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (old standard name, new standard name), frozen here as they were when this ran.
RENAMES = (("Wedding", "Lagan"), ("Vandidad", "Vendidad"))

RENAME = sa.text(
    "UPDATE services SET name = :to_name WHERE name = :from_name AND NOT EXISTS ("
    " SELECT 1 FROM services AS other"
    " WHERE other.agyary_id = services.agyary_id AND lower(other.name) = lower(:to_name))"
)


def upgrade() -> None:
    for old, new in RENAMES:
        op.execute(RENAME.bindparams(from_name=old, to_name=new))


def downgrade() -> None:
    for old, new in RENAMES:
        op.execute(RENAME.bindparams(from_name=new, to_name=old))
