"""Lists show everything (22 Nov 2026).

A mobed added all her behdins and the Behdins tab showed only 30: the list was cut at 30 with no
word of it, and only a search found the others. The Doongerwadi's book of families stopped at
50 the same way, and the Requests tab's "Earlier" at 20. Each list now gives all of them (up to a
guard far above any real book)."""

from __future__ import annotations

from tests.funeral_helpers import manager
from tests.test_mobed_api import _member_headers

BOOK = "/api/mobed/manager/behdins"


async def test_the_behdins_tab_lists_every_behdin_not_only_the_first_30(client, db, seeded):
    aid = seeded["agyary_id"]
    me = await _member_headers(client, seeded)
    for i in range(35):
        r = await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=me,
                              json={"name": f"Behdin Family {i:02d} Mistry", "phone": f"+9198766{i:05d}"})
        assert r.status_code == 200, r.text

    listed = (await client.get(f"/api/mobed/agyaries/{aid}/behdins", headers=me)).json()
    assert len(listed) == 35
    assert [b["name"] for b in listed] == sorted(b["name"] for b in listed)
    # A search that matches more than 30 shows them all too.
    found = (await client.get(f"/api/mobed/agyaries/{aid}/behdins", params={"q": "mistry"}, headers=me)).json()
    assert len(found) == 35
    one = (await client.get(f"/api/mobed/agyaries/{aid}/behdins", params={"q": "Family 07"}, headers=me)).json()
    assert [b["name"] for b in one] == ["Behdin Family 07 Mistry"]


async def test_the_doongerwadis_book_lists_every_family_not_only_the_first_50(client, db, seeded):
    headers, _ = await manager(client, db)
    for i in range(55):
        r = await client.post(BOOK, json={"name": f"Test Family {i:02d}", "phone": f"+9198255{i:05d}"},
                              headers=headers)
        assert r.status_code == 200, r.text
    body = (await client.get(BOOK, headers=headers)).json()
    assert len(body["behdins"]) == 55 and body["more"] is False


def test_the_requests_tab_keeps_far_more_than_20_earlier_requests():
    from agyary.services import funeral_answers

    assert funeral_answers.EARLIER >= 500
