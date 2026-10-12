"""What stops a new account using our WhatsApp account against strangers
(docs/DECISIONS.md D1).

Free text that reaches the paid template - the temple's name, the service names,
the departed's name - is checked where it is typed and again before sending:
bounded length, no links, no @-handles, no long runs of digits. At most one
automatic reminder goes to a number on any day, however many memorials or mobeds
it has. And an account in its first week can send only a handful a day unless
the owner has vouched for it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, update

from agyary.models import Agyary, Notification, User
from agyary.services import reminder_sender, template_text
from tests.test_mobed_api import _member_headers
from tests.test_reminder_sender import DEATH, _evening, _settings


# --- The text rules ---------------------------------------------------------

@pytest.mark.parametrize("ok", [
    "Seth B. M. Patel Agiary", "Er. Pervez Kias", "Agiary No. 2", "Afringan", "Banaji Atash Behram",
    "Dae-Pa-Adar Jashan", "Mrs. Dinaz (Dina) Irani",
])
def test_ordinary_names_pass(ok):
    assert template_text.problem(ok, max_len=80) is None


@pytest.mark.parametrize("bad", [
    "Visit https://x.example", "see www.example.com", "go to evil.example.com", "join bit.ly/abc",
    "dm @scammer", "call 98765 43210", "+91-98765-43210", "pay 1234567",
    "x" * 81,
])
def test_links_handles_numbers_and_overlong_text_are_refused(bad):
    assert template_text.problem(bad, max_len=80)


# --- Where it is typed ---------------------------------------------------------

async def test_a_new_temple_service_or_departed_name_with_a_link_is_refused(client, db, seeded):
    aid = seeded["agyary_id"]
    h = await _member_headers(client, seeded)
    r = await client.post("/api/mobed/agyaries", headers=h, json={"name": "Visit evil.example.com", "city": "X"})
    assert r.status_code == 400 and "link" in r.json()["detail"]
    r = await client.post(f"/api/mobed/agyaries/{aid}/services", headers=h, json={"name": "call 98765 43210"})
    assert r.status_code == 400 and "number" in r.json()["detail"]
    r = await client.post(f"/api/mobed/agyaries/{aid}/memorials/preview", headers=h, json={
        "departed_name": "msg @scammer", "death_date": DEATH.isoformat(), "opening": "tenth_only"})
    assert r.status_code == 400 and "@" in r.json()["detail"]


# --- Before sending ---------------------------------------------------------

async def _family(client, aid, headers, phone, *, name="Family", departed="Ardeshir Mehta"):
    cid = (await client.post(f"/api/mobed/agyaries/{aid}/behdins", headers=headers,
                             json={"name": name, "phone": phone})).json()["id"]
    sid = next(s["id"] for s in (await client.get(f"/api/mobed/agyaries/{aid}/services", headers=headers)).json()
               if s["name"] == "Afringan")
    made = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials", headers=headers, json={
        "departed_name": departed, "death_date": DEATH.isoformat(), "opening": "tenth_only",
        "monthly": {"count": 2}, "service_ids": [sid]})
    assert made.status_code == 200, made.text
    r = await client.put(f"/api/mobed/agyaries/{aid}/behdins/{cid}/reminders", headers=headers, json={"enabled": True})
    assert r.status_code == 200, r.text
    first = next(o for o in made.json()["observances"] if o["day_number"] > 10)
    return cid, _evening(date.fromisoformat(first["date"]) - timedelta(days=1))


async def _age_accounts(db, now: datetime, days: int) -> None:
    """Make every account ``days`` old as of the evening being planned."""
    await db.execute(update(User).values(created_at=now - timedelta(days=days)))
    await db.commit()


async def _rows(db):
    return (await db.execute(select(Notification).order_by(Notification.id))).scalars().all()


async def test_text_that_slipped_in_earlier_is_not_sent(client, db, seeded):
    aid = seeded["agyary_id"]
    h = await _member_headers(client, seeded)
    _, now = await _family(client, aid, h, "+919944401101")
    await _age_accounts(db, now, 365)
    # A temple name from before the rules, straight into the database.
    await db.execute(update(Agyary).where(Agyary.id == aid).values(name="Goti Adarian www.evil.example"))
    await db.commit()
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 0
    await db.commit()
    [n] = await _rows(db)
    assert n.status == "failed" and "cannot be sent automatically" in n.error_message
    notes = (await client.get("/api/mobed/notifications", headers=h)).json()
    assert any(x["kind"] == "reminder_failed" for x in notes)


async def test_one_automatic_reminder_per_number_per_day(client, db, seeded):
    aid = seeded["agyary_id"]
    phone = "+919944401102"
    mine = await _member_headers(client, seeded)
    theirs = await _member_headers(client, seeded, name="Colleague", phone="+919944401103")
    _, now = await _family(client, aid, mine, phone, departed="First Departed")
    await _family(client, aid, theirs, phone, name="Same Family", departed="Second Departed")
    await _age_accounts(db, now, 365)

    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 1
    await db.commit()
    # Planning again (the loop asks every minute) changes nothing.
    assert await reminder_sender.plan_tomorrow(db, now + timedelta(minutes=1), _settings()) == 0
    await db.commit()
    rows = await _rows(db)
    assert sorted(r.status for r in rows) == ["failed", "pending"]
    assert "one automatic reminder" in next(r for r in rows if r.status == "failed").error_message


async def test_a_new_account_sends_only_a_few_a_day_until_vouched_for(client, db, seeded):
    aid = seeded["agyary_id"]
    h = await _member_headers(client, seeded)
    now = None
    for i in range(7):
        _, now = await _family(client, aid, h, f"+91994440120{i}")
    await _age_accounts(db, now, 2)       # two days old

    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 5
    await db.commit()
    assert [r.status for r in await _rows(db)].count("failed") == 2

    # The same account, vouched for by the owner, may send them all.
    await db.execute(Notification.__table__.delete())
    await db.commit()
    me = (await db.execute(select(User).where(User.name == "New Mobed"))).scalar_one()
    vouched = _settings(reminders_vouched=me.phone)
    assert await reminder_sender.plan_tomorrow(db, now, vouched) == 7
