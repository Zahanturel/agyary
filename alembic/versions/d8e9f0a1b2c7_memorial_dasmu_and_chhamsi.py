"""memorial_observances: the "Dasmi" and the "Chamsi" are now the "Dasmu" and the "Chhamsi"

DECISIONS D11, the owner's word review (23 Nov 2026): the 10th day is the
Dasmu and the six months' day the Chhamsi (calendar.memorial.NAMED_DAYS).

A memorial's day keeps its label as text, for display only: the app works by
its code ("day_10", "day_180"), and writes the label from NAMED_DAYS whenever
the memorial is worked out again. Every saved day labelled exactly "Dasmi" or
"Chamsi", past or to come, takes the new spelling. Nothing else about it
changes: not its date, its Roj and Mah, its code, its time, its notes, or
whether it was paid or the family told. The WhatsApp reminders already sent
keep the words they went with (notifications.template_params, D8).

The downgrade gives them back the old spelling, exact matches only.

Revision ID: d8e9f0a1b2c7
Revises: c7d8e9f0a1b6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8e9f0a1b2c7"
down_revision: Union[str, None] = "c7d8e9f0a1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (old label, new label), frozen here as they were when this ran.
RENAMES = (("Dasmi", "Dasmu"), ("Chamsi", "Chhamsi"))

RELABEL = sa.text("UPDATE memorial_observances SET label = :to_label WHERE label = :from_label")


def upgrade() -> None:
    for old, new in RENAMES:
        op.execute(RELABEL.bindparams(from_label=old, to_label=new))


def downgrade() -> None:
    for old, new in RENAMES:
        op.execute(RELABEL.bindparams(from_label=new, to_label=old))
