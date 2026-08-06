"""move tandarosti ceremony names from 'pair' to 'farmayeshne'

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-06 00:00:00.000000

Tandarosti names are the living family the machi is being performed for,
which is precisely what the 'farmayeshne' section means. They were being
written as section='pair' with pair_group=NULL - pair-section rows that
aren't in a pair - on the reasoning that machis have no farmayeshne
section.

That was inconsistent in two directions. The saved-name pool has always
stored these very same names as 'farmayeshne'
(flows/machi.py's replace_saved_section call), so a name silently changed
section on its way from the pool onto the ceremony. And every consumer that
groups pair rows by pair_group had to carry a special case for a NULL
group that means "not actually a pair".

Scope is deliberately narrow: only rows belonging to a tandarosti machi,
only in the 'pair' section, only with a NULL pair_group. Patet pairs (which
are real pairs, with a group) and every booking row are untouched.

Note for reviewers: this changes printed slip output for tandarosti
machis. formatting.names_block lists farmayeshne rows under a
"Farmayeshne:" heading, so those names now print with that label where
before they printed bare. The label is accurate - it is what the section
means - but it is a visible change on paper.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TANDAROSTI_SINGLES = """
    machi_id IS NOT NULL
    AND pair_group IS NULL
    AND machi_id IN (SELECT id FROM machis WHERE purpose = 'tandarosti')
"""


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE ceremony_names
           SET section = 'farmayeshne'
         WHERE section = 'pair'
           AND {_TANDAROSTI_SINGLES}
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE ceremony_names
           SET section = 'pair'
         WHERE section = 'farmayeshne'
           AND {_TANDAROSTI_SINGLES}
        """
    )
