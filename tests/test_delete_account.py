"""A mobed can delete their account, and everything that is theirs goes with it (PV-2).

Google Play requires it of an app that creates accounts. The mobed's book is
private (D2), so their behdins, saved names, memorials, who the messages went
to, their machis and bookings, sessions and notices all go. A colleague's data
at the same temple is untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, text

from agyary.core.config import get_settings
from agyary.models import Customer, DeletedAccount, LoginOtp, Machi, Memorial, Notification, User
from agyary.services import account, guardrails, reminder_sender
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


async def test_deleting_an_account_does_not_reset_what_was_sent(client, db, seeded):
    """SEC-02: what went out stays counted against the overall limits, with
    everything that says who or what wiped; what had not gone out never will;
    the sign-in codes stay for their limits; and the number stays only as a digest."""
    me, headers, _colleague = await _a_full_book(client, db, seeded)
    phone = (await db.get(User, me)).phone
    planned = (await db.execute(select(Notification))).scalar_one()
    planned.status = "pending"
    sent = Notification(
        agyary_id=planned.agyary_id, recipient_phone=BEHDIN_PHONE, recipient_type="customer",
        recipient_id=planned.recipient_id, notification_type="memorial_share", template_name="memorial_schedule",
        template_params={"1": "Dinshaw Mehta", "mobed": str(me)}, status="sending", wa_message_id="wamid.X",
    )
    db.add(sent)
    db.add(LoginOtp(phone=phone, salt="y", code_hash="x", expires_at=datetime.now(timezone.utc)))
    await db.commit()
    sent_id, pending_id = sent.id, planned.id

    r = await client.post("/api/mobed/auth/account/delete", json={"confirm": True}, headers=headers)
    assert r.status_code == 200, r.text
    db.expire_all()

    assert await db.get(Notification, pending_id) is None
    kept = await db.get(Notification, sent_id)
    assert kept.recipient_phone == "" and kept.recipient_id == 0 and kept.template_params == {}
    assert kept.wa_message_id is None and kept.status == "sent"
    assert (await guardrails.usage(db, datetime.now(timezone.utc))).today == 0  # reminders only

    assert await _count(db, LoginOtp, LoginOtp.phone == phone) == 1
    digest = (await db.execute(select(DeletedAccount.phone_hmac))).scalar_one()
    assert digest == account.phone_hmac(get_settings(), phone) and phone not in digest


async def test_nothing_is_deleted_without_the_confirmation(client, db, seeded):
    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    me = (await client.get("/api/mobed/auth/me", headers=headers)).json()["id"]
    r = await client.post("/api/mobed/auth/account/delete", json={"confirm": False}, headers=headers)
    assert r.status_code == 400
    assert (await client.post("/api/mobed/auth/account/delete", json={}, headers=headers)).status_code == 422
    assert await db.get(User, me) is not None
