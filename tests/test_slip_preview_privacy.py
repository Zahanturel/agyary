"""Typing a phone number must not reveal what another mobed recorded for it.

The slip preview used to look the number up across every behdin on file and
hand back the stored name and the family's saved names - their departed pairs
and living relatives - to whoever typed it, writing nothing and leaving no
trace. A number on file in someone else's book now previews exactly like a
number nobody has seen: the typed name, and no saved names.
"""

from __future__ import annotations

from tests.test_mobed_api import _member_headers

BEHDIN_PHONE = "+919944400601"
SAVED = {"Departed Father", "Departed Mother"}


async def _owners_behdin_with_saved_names(client, seeded) -> tuple[dict, int]:
    aid = seeded["agyary_id"]
    owner = await _member_headers(client, seeded)
    made = await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=owner,
                             json={"name": "Private Family", "phone": BEHDIN_PHONE})
    assert made.status_code == 200, made.text
    cid = made.json()["id"]
    r = await client.put(
        f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names/pair", headers=owner,
        json={"names": [
            {"title": "ervad", "name": "Departed Father", "status": "departed", "pair_group": 1},
            {"title": "behdin", "name": "Departed Mother", "status": "departed", "pair_group": 1},
        ]},
    )
    assert r.status_code == 200, r.text
    return owner, cid


async def _a_service(client, aid, headers) -> int:
    services = (await client.get(f"/api/mobed/agyaries/{aid}/services", headers=headers)).json()
    return next(s["id"] for s in services if s["name"] != "Machi")


def _machi(phone: str, name: str) -> dict:
    return {"behdin_phone": phone, "behdin_name": name, "roj": 1, "mah": 1, "year": 1400,
            "geh": 2, "gregorian": "2030-08-15", "purpose": "patet"}


async def test_preview_shows_a_colleague_nothing_of_another_mobeds_behdin(client, db, seeded):
    aid = seeded["agyary_id"]
    owner, _ = await _owners_behdin_with_saved_names(client, seeded)
    colleague = await _member_headers(client, seeded, name="Colleague", phone="+919944400602")
    sid = await _a_service(client, aid, colleague)
    booking = {"behdin_phone": BEHDIN_PHONE, "behdin_name": "Typed Name", "service_id": sid,
               "ceremony_datetime": "2030-01-01T10:00:00"}

    for path, payload in (("booking", booking), ("machi", _machi(BEHDIN_PHONE, "Typed Name"))):
        theirs = await client.post(f"/api/mobed/agyaries/{aid}/slip-preview/{path}",
                                   json=payload, headers=colleague)
        assert theirs.status_code == 200, theirs.text
        body = theirs.json()
        assert body["slip"]["behdin_name"] == "Typed Name", path
        assert not SAVED & {n["name"] for n in body["names"]}, path
        assert body["pool_empty"] is True, path

        # The owner's own preview is unchanged: their stored name and saved names.
        own = (await client.post(f"/api/mobed/agyaries/{aid}/slip-preview/{path}",
                                 json=payload, headers=owner)).json()
        assert own["slip"]["behdin_name"] == "Private Family", path
        assert SAVED <= {n["name"] for n in own["names"]}, path
