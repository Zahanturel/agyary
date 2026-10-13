"""A mobed can delete their account, and everything that is theirs goes with it (PV-2).

Google Play requires it of an app that creates accounts. The mobed's book is
private (D2), so their behdins, saved names, memorials, the messages sent to
those families, their machis and bookings, sessions and notices all go. A
colleague's data at the same temple is untouched.
"""

from __future__ import annotations

from sqlalchemy import func, select, text

from agyary.models import Customer, Machi, Memorial, Notification, User
from agyary.services import reminder_sender
from tests.test_mobed_api import _member_headers
from tests.test_reminder_sender import BEHDIN_PHONE, _scenario, _settings

COLLEAGUE_PHONE = "+919944401701"


async def _count(db, model, *where) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


async def _a_full_book(client, db, seeded):
    """The mobed has a behdin with a memorial whose reminder was planned, a
    machi and a booking; a colleague has their own behdin and machi."""
    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 1
    await db.commit()
    r = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/machi", headers=headers, json={
        "behdin_phone": BEHDIN_PHONE, "behdin_name": "Delzeen Test", "roj": 1, "mah": 1, "year": 1400,
        "geh": 1, "gregorian": "2030-08-15", "purpose": "patet",
        "names": [{"section": "pair", "title": "ervad", "name": "Dead A", "status": "departed", "pair_group": 1},
                  {"section": "pair", "title": "behdin", "name": "Dead B", "status": "departed", "pair_group": 1}],
    })
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/booking", headers=headers, json={
        "behdin_phone": BEHDIN_PHONE, "behdin_name": "Delzeen Test", "service_id": 2,
        "ceremony_datetime": "2028-03-01T10:00:00", "purpose": "khushali_nu",
        "names": [{"section": "farmayeshne", "title": "behdin", "name": "X", "status": "living", "pair_group": None}],
        "location": None, "is_offsite": False,
    })
    assert r.status_code == 200, r.text
    colleague = await _member_headers(client, seeded, name="Colleague", phone=COLLEAGUE_PHONE)
    r = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/machi", headers=colleague, json={
        "behdin_phone": "+919944401702", "behdin_name": "Colleague Family", "roj": 2, "mah": 1, "year": 1400,
        "geh": 1, "gregorian": "2030-08-16", "purpose": "patet",
        "names": [{"section": "pair", "title": "ervad", "name": "Dead C", "status": "departed", "pair_group": 1},
                  {"section": "pair", "title": "behdin", "name": "Dead D", "status": "departed", "pair_group": 1}],
    })
    assert r.status_code == 200, r.text
    me = (await client.get("/api/mobed/auth/me", headers=headers)).json()["id"]
    return me, headers, colleague


async def test_deleting_an_account_removes_everything_that_was_theirs(client, db, seeded):
    me, headers, colleague = await _a_full_book(client, db, seeded)
    assert await _count(db, Customer, Customer.owner_user_id == me) == 1

    r = await client.post("/api/mobed/auth/account/delete", json={"confirm": True}, headers=headers)
    assert r.status_code == 200 and r.json() == {"deleted": True}
    db.expire_all()

    assert await db.get(User, me) is None
    assert await _count(db, Customer, Customer.owner_user_id == me) == 0
    assert await _count(db, Memorial, Memorial.created_by_user_id == me) == 0
    assert await _count(db, Machi, Machi.created_by_user_id == me) == 0
    assert await _count(db, Notification, Notification.recipient_phone == BEHDIN_PHONE) == 0
    for table in ("user_sessions", "agyary_users", "app_notifications", "user_preferences"):
        assert (await db.execute(text(f"SELECT count(*) FROM {table} WHERE user_id = :u"), {"u": me})).scalar() == 0
    assert (await db.execute(text("SELECT count(*) FROM bookings WHERE created_by_user_id = :u"), {"u": me})).scalar() == 0

    # The old sign-in no longer works.
    assert (await client.get("/api/mobed/auth/me", headers=headers)).status_code == 401

    # The colleague's behdin and machi are untouched.
    other = (await client.get("/api/mobed/auth/me", headers=colleague)).json()["id"]
    assert await _count(db, Customer, Customer.owner_user_id == other) == 1
    assert await _count(db, Machi, Machi.created_by_user_id == other) == 1


async def test_nothing_is_deleted_without_the_confirmation(client, db, seeded):
    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    me = (await client.get("/api/mobed/auth/me", headers=headers)).json()["id"]
    r = await client.post("/api/mobed/auth/account/delete", json={"confirm": False}, headers=headers)
    assert r.status_code == 400
    assert (await client.post("/api/mobed/auth/account/delete", json={}, headers=headers)).status_code == 422
    assert await db.get(User, me) is not None
