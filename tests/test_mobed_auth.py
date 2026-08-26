"""Membership: what a self-serve join creates, and what it may not change.

The sign-in mechanics themselves live in test_wa_login.py - this file
starts from a signed-in mobed and asks what joining an agyari does to
their role. The property under test is that self-serve can only ever make
you a plain mobed, and that re-joining never quietly takes away a role
somebody else granted.
"""

from __future__ import annotations

from sqlalchemy import select

from agyary.models import AgyaryUser, User
from agyary.services import mobed_auth
from tests.conftest import sign_in

PHONE = "+919911100055"


# ---------------------------------------------------------------------------
# Membership: self-serve join, and what it may and may not change
# ---------------------------------------------------------------------------
async def _headers(client, phone=PHONE, name="Er. Test Mobed") -> dict:
    return {"Authorization": f"Bearer {(await sign_in(client, phone, name))['access_token']}"}


async def _joined_headers(client, seeded, phone=PHONE, name="Er. Test Mobed") -> dict:
    headers = await _headers(client, phone, name)
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)
    assert r.status_code == 200, r.text
    return headers


async def test_existing_admin_is_not_demoted_by_a_plain_join(db, client, seeded):
    """ensure_agyary_membership reactivates, but never demotes.

    Nothing in this app grants panthaky any more, so the only privileged
    memberships are the ones seed data and the WhatsApp flows created. A
    plain re-join must leave them alone - silently resetting one to 'mobed'
    would take away the booking-flow rights that role carries.
    """
    aid = seeded["agyary_id"]
    user = (await db.execute(select(User).where(User.phone == seeded["panthaky_phone"]))).scalar_one()
    assert (await mobed_auth.get_membership(db, aid, user.id)).role == "panthaky"

    await mobed_auth.ensure_agyary_membership(db, aid, user)
    await db.commit()
    refreshed = (
        await db.execute(
            select(AgyaryUser).where(AgyaryUser.agyary_id == aid, AgyaryUser.user_id == user.id)
        )
    ).scalar_one()
    assert refreshed.role == "panthaky"
