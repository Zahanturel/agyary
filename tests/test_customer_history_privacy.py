"""A behdin's history is their own mobed's business, and nobody else's.

The history route answers with the behdin's name and phone number as well as
the history itself, so it must check ownership like every other behdin read -
not only filter the history down to the caller's own entries.
"""

from __future__ import annotations

from tests.conftest import sign_in
from tests.test_mobed_api import _member_headers

BEHDIN_PHONE = "+919944400501"


async def _owners_behdin(client, seeded) -> tuple[dict, int]:
    aid = seeded["agyary_id"]
    owner = await _member_headers(client, seeded)
    made = await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=owner,
                             json={"name": "Private Family", "phone": BEHDIN_PHONE})
    assert made.status_code == 200, made.text
    return owner, made.json()["id"]


async def test_history_is_only_for_the_mobed_whose_behdin_it_is(client, db, seeded):
    owner, cid = await _owners_behdin(client, seeded)

    # The owner still reads it.
    mine = await client.get(f"/api/mobed/customers/{cid}/history", headers=owner)
    assert mine.status_code == 200
    assert mine.json()["phone"] == BEHDIN_PHONE

    # A colleague at the same fire temple does not...
    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944400502")
    assert (await client.get(f"/api/mobed/customers/{cid}/history", headers=colleague)).status_code == 404

    # ...and nor does an account that belongs to no fire temple at all, counting up ids.
    body = await sign_in(client, "+919944400503", "Nobody")
    stranger = {"Authorization": f"Bearer {body['access_token']}"}
    for guess in (cid, cid + 1, 1):
        r = await client.get(f"/api/mobed/customers/{guess}/history", headers=stranger)
        assert r.status_code == 404, (guess, r.text)
        assert BEHDIN_PHONE not in r.text
