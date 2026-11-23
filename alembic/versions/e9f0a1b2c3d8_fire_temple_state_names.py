"""agyaries: the fire temple list's state names, spelled out and corrected

DECISIONS D11, the owner's word review (23 Nov 2026): the fire temple list says
Gujarat (not "Gujerat"), Rajasthan (not "Rajashtan"), Andhra Pradesh (not "A.P"
or "A.P."), Madhya Pradesh (not "MP") and Uttar Pradesh (not "UP").
scripts/data/fire_temples.json, the seed list, is corrected with this.

A fire temple has no state of its own: the seed (scripts/seed_fire_temples.py)
wrote it as the last part of the address, "Udwada Town, Gujerat", or as the
whole address when the list had no street ("Gujerat"). So the old name is
replaced only where it is that exact token: the whole address, or what follows
its last ", ". An address that merely contains the letters elsewhere is left
as it is, and so is everything else about the fire temple (its name, city,
position, set-up or claim).

The downgrade puts the old names back the same way, exact tokens only; an
"A.P." comes back as "A.P", as the seed list had it. It cannot tell an address
this changed from one a mobed had already typed with the new name, so those
change back too.

Revision ID: e9f0a1b2c3d8
Revises: d8e9f0a1b2c7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9f0a1b2c3d8"
down_revision: Union[str, None] = "d8e9f0a1b2c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (old token, new token), frozen here as they were when this ran.
UP = (("Gujerat", "Gujarat"), ("Rajashtan", "Rajasthan"), ("A.P.", "Andhra Pradesh"), ("A.P", "Andhra Pradesh"),
      ("MP", "Madhya Pradesh"), ("UP", "Uttar Pradesh"))
DOWN = (("Gujarat", "Gujerat"), ("Rajasthan", "Rajashtan"), ("Andhra Pradesh", "A.P"),
        ("Madhya Pradesh", "MP"), ("Uttar Pradesh", "UP"))

# The whole address, or its last part after ", ". None of the tokens holds a LIKE
# wildcard ("%" or "_"), so the pattern matches them literally.
WHOLE = sa.text("UPDATE agyaries SET address = :to_token WHERE address = :from_token")
LAST = sa.text("UPDATE agyaries SET address = left(address, length(address) - :cut) || :to_token"
               " WHERE address LIKE :pattern")


def _replace(pairs: tuple[tuple[str, str], ...]) -> None:
    for old, new in pairs:
        op.execute(WHOLE.bindparams(from_token=old, to_token=new))
        op.execute(LAST.bindparams(cut=len(old), to_token=new, pattern=f"%, {old}"))


def upgrade() -> None:
    _replace(UP)


def downgrade() -> None:
    _replace(DOWN)
