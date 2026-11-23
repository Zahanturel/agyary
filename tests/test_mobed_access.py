"""A mobed's access (DECISIONS D9): a new sign-up waits for an admin's
approval, and an admin can turn any mobed off and on again.

Waiting or off, a mobed can see who they are, choose a fire temple and delete
their account - nothing else - and nothing is sent under their account.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from agyary.core import config
from agyary.models import AppNotification, Notification, User
from agyary.services import daily_report, reminder_sender
from tests.conftest import sign_in
from tests.test_daily_report import EVENING
from tests.test_daily_report import _settings as _report_settings
from tests.test_daily_report import _setup as _report_setup
from tests.test_reminder_sender import FakeMeta, _scenario, _settings

NEW = "+919911100077"


@pytest.fixture
def admin_is_panthaky(monkeypatch, seeded):
    """The seeded panthaky is the admin."""
    monkeypatch.setenv("ADMIN_PHONES", seeded["panthaky_phone"])
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def _new_mobed(client, name="Er. Rustom Irani", phone=NEW) -> dict:
    """A brand-new sign-up, left as the app leaves it: waiting."""
    body = await sign_in(client, phone, name, approve=False)
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


async def _admin(client, seeded) -> dict:
    body = await sign_in(client, seeded["panthaky_phone"])
    return {"Authorization": f"Bearer {body['access_token']}"}


async def _user(db, phone=NEW) -> User:
    return (await db.execute(select(User).where(User.phone == phone))).scalar_one()


# --- A new sign-up waits ----------------------------------------------------

async def test_a_new_sign_up_is_waiting_and_can_only_choose_a_fire_temple(client, db, seeded, admin_is_panthaky):
    headers, user = await _new_mobed(client)
    assert user["access"] == "pending"
    me = await client.get("/api/mobed/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["access"] == "pending"

    # Choosing a fire temple is part of signing up.
    assert (await client.get("/api/mobed/agyaries/search?q=Goti")).status_code == 200
    joined = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)
    assert joined.status_code == 200, joined.text
    assert joined.json()["user"]["access"] == "pending"
    assert (await client.get("/api/mobed/me/preferences", headers=headers)).status_code == 200

    # Everything else is refused, and the app is told why in a header it reads.
    for path in ("/api/mobed/my-day", f"/api/mobed/agyaries/{seeded['agyary_id']}/behdins", "/api/mobed/notifications"):
        r = await client.get(path, headers=headers)
        assert r.status_code == 403, path
        assert r.headers["X-Mobed-Access"] == "pending"
        assert r.json()["detail"] == "Your account is waiting for approval."
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/behdins",
                          json={"name": "Delzeen Test", "phone": "+919822233344"}, headers=headers)
    assert r.status_code == 403


async def test_the_admins_are_told_once_the_fire_temple_is_chosen(client, db, seeded, admin_is_panthaky):
    admin = await _admin(client, seeded)
    headers, user = await _new_mobed(client)
    notes = lambda: db.execute(select(AppNotification).where(AppNotification.kind == "mobed_request"))  # noqa: E731
    assert (await notes()).first() is None          # signed in, no temple yet: not finished
    await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)
    await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)   # again: not told twice
    (note,) = (await notes()).scalars().all()
    panthaky = await _user(db, seeded["panthaky_phone"])
    assert note.user_id == panthaky.id
    assert "Er. Rustom Irani" in note.body and NEW in note.body and "Goti Adarian" in note.body
    assert note.link == "#/admin/mobeds"
    assert (note.expires_at - note.created_at).days == 7
    # And it is in the admin's notifications.
    titles = [n["title"] for n in (await client.get("/api/mobed/notifications", headers=admin)).json()]
    assert "A new mobed is waiting" in titles


async def test_a_new_temple_made_while_signing_up_also_tells_the_admins(client, db, seeded, admin_is_panthaky):
    headers, _ = await _new_mobed(client)
    r = await client.post("/api/mobed/agyaries", json={"name": "Banaji Atash Behram", "city": "Mumbai"}, headers=headers)
    assert r.status_code == 200, r.text
    (note,) = (await db.execute(select(AppNotification).where(AppNotification.kind == "mobed_request"))).scalars().all()
    assert "Banaji Atash Behram" in note.body


async def test_an_admin_signing_up_is_on_at_once(client, db, monkeypatch):
    monkeypatch.setenv("ADMIN_PHONES", NEW)
    config.get_settings.cache_clear()
    try:
        _, user = await _new_mobed(client)
        assert user["access"] == "on"
        assert (await _user(db)).access == "on"
    finally:
        config.get_settings.cache_clear()


async def test_accounts_from_before_approval_are_on(db, seeded):
    users = (await db.execute(select(User))).scalars().all()
    assert users and all(u.access == "on" for u in users)


# --- The admin's switch -----------------------------------------------------

async def test_the_admin_approves_and_the_mobed_is_in_and_told(client, db, seeded, admin_is_panthaky):
    admin = await _admin(client, seeded)
    headers, user = await _new_mobed(client)
    await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)

    listed = (await client.get("/api/mobed/admin/mobeds", headers=admin)).json()
    assert listed["waiting"] == 1
    first = listed["mobeds"][0]
    assert (first["id"], first["access"], first["phone"], first["agyaries"]) == (
        user["id"], "pending", NEW, ["Goti Adarian"])
    assert (await client.get("/api/mobed/admin/overview", headers=admin)).json()["mobeds_waiting"] == 1

    r = await client.post(f"/api/mobed/admin/mobeds/{user['id']}/access", json={"access": "on"}, headers=admin)
    assert r.status_code == 200 and r.json()["access"] == "on"
    assert (await client.get("/api/mobed/my-day", headers=headers)).status_code == 200
    assert (await client.get("/api/mobed/auth/me", headers=headers)).json()["access"] == "on"
    titles = [n["title"] for n in (await client.get("/api/mobed/notifications", headers=headers)).json()]
    assert titles == ["You can now use Mobed Diary"]
    assert (await _user(db)).access_changed_at is not None


async def test_turning_a_mobed_off_and_on_again(client, db, seeded, admin_is_panthaky):
    admin = await _admin(client, seeded)
    mobed = await _user(db, seeded["mobed_phone"])
    body = await sign_in(client, seeded["mobed_phone"])
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert (await client.get("/api/mobed/my-day", headers=headers)).status_code == 200

    r = await client.post(f"/api/mobed/admin/mobeds/{mobed.id}/access", json={"access": "off"}, headers=admin)
    assert r.status_code == 200 and r.json()["access"] == "off"
    refused = await client.get("/api/mobed/my-day", headers=headers)
    assert refused.status_code == 403 and refused.headers["X-Mobed-Access"] == "off"
    me = (await client.get("/api/mobed/auth/me", headers=headers)).json()
    assert me["access"] == "off" and me["agyaries"]        # still signed in, nothing lost

    r = await client.post(f"/api/mobed/admin/mobeds/{mobed.id}/access", json={"access": "on"}, headers=admin)
    assert r.json()["access"] == "on"
    assert (await client.get("/api/mobed/my-day", headers=headers)).status_code == 200
    titles = [n["title"] for n in (await client.get("/api/mobed/notifications", headers=headers)).json()]
    assert titles == ["Your access is back on"]


async def test_an_admin_cannot_be_turned_off(client, db, seeded, admin_is_panthaky):
    admin = await _admin(client, seeded)
    me = await _user(db, seeded["panthaky_phone"])
    r = await client.post(f"/api/mobed/admin/mobeds/{me.id}/access", json={"access": "off"}, headers=admin)
    assert r.status_code == 400 and r.json()["detail"] == "An admin cannot be turned off."
    # Even stored as off, an admin is on (the owner can never lock themselves out).
    await db.execute(update(User).where(User.id == me.id).values(access="off"))
    await db.commit()
    assert (await client.get("/api/mobed/admin/mobeds", headers=admin)).status_code == 200


async def test_only_on_or_off_can_be_set(client, db, seeded, admin_is_panthaky):
    admin = await _admin(client, seeded)
    mobed = await _user(db, seeded["mobed_phone"])
    r = await client.post(f"/api/mobed/admin/mobeds/{mobed.id}/access", json={"access": "pending"}, headers=admin)
    assert r.status_code == 422
    r = await client.post("/api/mobed/admin/mobeds/999999/access", json={"access": "on"}, headers=admin)
    assert r.status_code == 404


async def test_a_mobed_who_is_not_an_admin_cannot_see_or_change_anyone(client, db, seeded, admin_is_panthaky):
    body = await sign_in(client, seeded["mobed_phone"])
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert (await client.get("/api/mobed/admin/mobeds", headers=headers)).status_code == 404
    other = await _user(db, seeded["panthaky_phone"])
    r = await client.post(f"/api/mobed/admin/mobeds/{other.id}/access", json={"access": "off"}, headers=headers)
    assert r.status_code == 404


async def test_a_waiting_mobed_can_still_delete_their_account(client, db, seeded):
    headers, _ = await _new_mobed(client)
    r = await client.post("/api/mobed/auth/account/delete", json={"confirm": True}, headers=headers)
    assert r.status_code == 200 and r.json()["deleted"] is True


# --- Nothing is sent under an account that is off ---------------------------

async def _switch(db, phone, access):
    await db.execute(update(User).where(User.phone == phone).values(access=access))
    await db.commit()


async def test_no_reminder_is_planned_for_a_mobed_who_is_off(client, db, seeded):
    from tests.test_mobed_api import NEW_MOBED_PHONE

    *_, now = await _scenario(client, db, seeded)
    await _switch(db, NEW_MOBED_PHONE, "off")
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 0
    await _switch(db, NEW_MOBED_PHONE, "on")
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 1


async def test_a_reminder_planned_before_the_mobed_was_turned_off_is_not_sent(client, db, seeded):
    from tests.test_mobed_api import NEW_MOBED_PHONE

    *_, now = await _scenario(client, db, seeded)
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 1
    await db.commit()
    await _switch(db, NEW_MOBED_PHONE, "off")
    meta = FakeMeta()
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now, _settings())
    assert report.sent == 0 and report.missed == 1 and meta.calls == []
    (n,) = (await db.execute(select(Notification))).scalars().all()
    assert n.status == "failed" and n.error_message == "The mobed was switched off before it was sent"


async def test_no_daily_report_for_a_mobed_who_is_off(client, db, seeded):
    from tests.test_mobed_api import NEW_MOBED_PHONE

    await _report_setup(client, db, seeded)
    await _switch(db, NEW_MOBED_PHONE, "off")
    assert await daily_report.run(db, EVENING, _report_settings(daily_report_send_mode="off")) == 0
    await _switch(db, NEW_MOBED_PHONE, "on")
    assert await daily_report.run(db, EVENING, _report_settings(daily_report_send_mode="off")) == 1
