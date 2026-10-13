"""A mobed can record that they told a family themselves.

Marked, the observance shows "You told them yourself", the planner sends
nothing for it (so the family is not told twice), and it can be taken back.
Only on the mobed's own memorials.
"""

from __future__ import annotations

from datetime import date, timedelta

from agyary.services import memorials, reminder_sender
from tests.test_mobed_api import _member_headers
from tests.test_reminder_sender import _rows, _scenario, _settings


def _url(aid, oid):
    return f"/api/mobed/agyaries/{aid}/memorial-observances/{oid}/reminded"


async def test_a_marked_observance_is_not_sent_and_the_mark_can_be_undone(client, db, seeded):
    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    oid = later[0]["id"]

    r = await client.put(_url(aid, oid), json={"reminded": True}, headers=headers)
    assert r.status_code == 200 and r.json()["reminded_by_hand_at"]
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 0
    assert await _rows(db) == []

    r = await client.put(_url(aid, oid), json={"reminded": False}, headers=headers)
    assert r.json() == {"reminded_by_hand_at": None}
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 1


async def test_the_list_shows_the_mark_and_promises_no_automatic_send(client, db, seeded):
    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    oid = later[0]["id"]
    me = (await client.get("/api/mobed/auth/me", headers=headers)).json()["id"]
    day = date.fromisoformat(later[0]["date"])

    async def item():
        items = await memorials.reminders_due(db, me, aid, day - timedelta(days=1), 3)
        return next(i for i in items if i["id"] == oid)

    assert (await item())["reminded_by_hand_at"] is None
    await client.put(_url(aid, oid), json={"reminded": True}, headers=headers)
    db.expire_all()
    marked = await item()
    assert marked["reminded_by_hand_at"] and marked["auto"] is False


async def test_only_the_mobed_whose_memorial_it_is_can_mark_it(client, db, seeded):
    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    other = await _member_headers(client, seeded, name="Colleague", phone="+919944401601")
    r = await client.put(_url(aid, later[0]["id"]), json={"reminded": True}, headers=other)
    assert r.status_code == 404
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 1
