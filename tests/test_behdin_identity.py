"""R4.0 step 1: the behdin app's identity (docs/behdin-r4-0-design.md).

A new number signing in at the behdin app is a 'behdin', on, whatever SIGNUP_MODE
says; a mobed and a manager sign in and use /api/behdin with their roles; a
behdin is refused every route of the mobed app (the walk below goes through all
of them); the two apps keep their sign-in in cookies of their own.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select, update

from agyary.api.routes import mobed as mobed_routes
from agyary.core import config
from agyary.models import User
from tests import test_funeral_managers as fm
from tests.conftest import sign_in, signed_inbound

PERSON = "+919911100077"


@pytest.fixture
def invite_only(monkeypatch):
    monkeypatch.setenv("SIGNUP_MODE", "invite")
    monkeypatch.setenv("SIGNUP_ALLOWLIST", "")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def behdin_sign_in(client, phone: str, name: str = "Test Person") -> dict:
    started = await client.post("/api/behdin/auth/wa/start")
    assert started.status_code == 200, started.text
    raw, headers = signed_inbound(started.json()["code"], phone)
    assert (await client.post("/webhooks/whatsapp", content=raw, headers=headers)).status_code == 200
    body = (await client.get("/api/behdin/auth/wa/poll")).json()
    if body.get("status") == "needs_name":
        done = await client.post("/api/behdin/auth/wa/complete", json={"name": name})
        assert done.status_code == 200, done.text
        body = done.json()
    assert body.get("status") == "signed_in", body
    return body


def auth(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['access_token']}"}


async def test_a_new_number_becomes_a_behdin_even_when_sign_up_is_by_invite(client, db, invite_only):
    body = await behdin_sign_in(client, PERSON)
    assert body["user"]["account_kind"] == "behdin" and body["user"]["roles"] == ["behdin"]
    row = (await db.execute(select(User).where(User.phone == PERSON))).scalar_one()
    assert (row.account_kind, row.access) == ("behdin", "on")
    me = await client.get("/api/behdin/me", headers=auth(body))
    assert me.status_code == 200
    assert me.json() == {
        "id": row.id, "name": "Test Person", "account_kind": "behdin", "roles": ["behdin"],
        "role_access": {"behdin": "on"}, "app_version": "r4.0",
    }


async def test_the_mobed_app_still_turns_an_uninvited_number_away(client, db, invite_only):
    started = await client.post("/api/mobed/auth/wa/start")
    raw, headers = signed_inbound(started.json()["code"], "+919911100066")
    await client.post("/webhooks/whatsapp", content=raw, headers=headers)
    r = await client.get("/api/mobed/auth/wa/poll")
    assert r.status_code == 403


async def test_a_mobed_and_a_manager_use_the_behdin_app_with_their_roles(client, db, seeded):
    body = await sign_in(client, seeded["mobed_phone"])
    behdin = await behdin_sign_in(client, seeded["mobed_phone"])
    assert behdin["user"]["account_kind"] == "mobed" and behdin["user"]["roles"] == ["behdin", "mobed"]
    me = (await client.get("/api/behdin/me", headers=auth(behdin))).json()
    assert me["role_access"] == {"behdin": "on", "mobed": "on"}
    assert (await client.get("/api/mobed/auth/me", headers=auth(body))).status_code == 200

    headers, _ = await fm._manager(client, db, seeded, access="pending")
    me = (await client.get("/api/behdin/me", headers=headers)).json()
    # A manager still waiting for approval is not refused by the behdin app.
    assert me["roles"] == ["behdin", "funeral_manager"]
    assert me["role_access"] == {"behdin": "on", "funeral_manager": "pending"}


async def test_a_mobed_who_is_off_still_has_the_behdin_app_but_a_behdin_who_is_off_does_not(client, db, seeded):
    mobed = await sign_in(client, seeded["mobed_phone"])
    await db.execute(update(User).where(User.id == mobed["user"]["id"]).values(access="off"))
    await db.commit()
    assert (await client.get("/api/behdin/me", headers=auth(mobed))).status_code == 200

    person = await behdin_sign_in(client, PERSON)
    await db.execute(update(User).where(User.id == person["user"]["id"]).values(access="off"))
    await db.commit()
    r = await client.get("/api/behdin/me", headers=auth(person))
    assert r.status_code == 403 and r.json()["detail"] == mobed_routes.BEHDIN_OFF


async def test_a_behdin_reaches_none_of_the_mobed_app(client, db, seeded):
    person = await behdin_sign_in(client, PERSON)
    headers = auth(person)
    closed = sorted(
        c for c in fm._api_calls() - fm.NO_SESSION - {("POST", "/api/mobed/auth/become-mobed")}
        if not c[1].startswith(fm.PUBLIC_PREFIXES) and not c[1].startswith("/api/behdin/")
    )
    assert len(closed) > 60 and ("GET", "/api/mobed/auth/me") in closed
    for method, path in closed:
        url = re.sub(r"\{[^}]+\}", "1", path)
        r = await client.request(method, url, json={}, headers=headers)
        if path.startswith("/api/mobed/admin/"):
            assert r.status_code in (403, 404), (method, path, r.status_code)
            continue
        assert r.status_code == 403, (method, path, r.status_code, r.text)
        assert r.json()["detail"] == mobed_routes.NOT_FOR_BEHDINS, (method, path)
        assert r.headers["X-Account-Kind"] == "behdin", (method, path)


def test_every_behdin_route_is_built_on_the_person_dependency():
    from agyary.api.main import app

    calls = {(m, r.path): r for r in fm._routes(app.routes) for m in r.methods - {"HEAD"}
             if r.path.startswith("/api/behdin/")}
    assert len(calls) >= 15

    def uses(dependant, targets) -> bool:
        return any(d.call in targets or uses(d, targets) for d in dependant.dependencies)

    mobed_deps = {mobed_routes.get_signed_in_account, mobed_routes.get_signed_in_user,
                  mobed_routes.get_current_user, mobed_routes.get_current_account}
    person = {mobed_routes.get_current_person, mobed_routes.get_signed_in_person}
    for (method, path), route in calls.items():
        assert not uses(route.dependant, mobed_deps), (method, path)
        if "/auth/" in path and "sessions" not in path:
            continue                  # signing in reads no session
        assert uses(route.dependant, person), (method, path)


async def test_behdin_routes_work_for_every_kind(client, db, seeded):
    people = {
        "behdin": await behdin_sign_in(client, PERSON),
        "mobed": await behdin_sign_in(client, seeded["mobed_phone"]),
    }
    manager_headers, _ = await fm._manager(client, db, seeded)
    for kind, headers in [(k, auth(b)) for k, b in people.items()] + [("manager", manager_headers)]:
        assert (await client.get("/api/behdin/me", headers=headers)).status_code == 200, kind
        assert (await client.get("/api/behdin/me/preferences", headers=headers)).status_code == 200, kind
        assert (await client.get("/api/behdin/me/person-names", headers=headers)).status_code == 200, kind
        assert (await client.get("/api/behdin/me/push", headers=headers)).status_code == 200, kind
        r = await client.patch("/api/behdin/me", json={"name": f"Renamed {kind}"}, headers=headers)
        assert r.status_code == 200 and r.json()["name"] == f"Renamed {kind}", kind
        assert (await client.post("/api/behdin/auth/sessions/sign-out-others", headers=headers)).status_code == 200
    assert (await client.get("/api/behdin/me")).status_code == 401
    r = await client.patch("/api/behdin/me", json={"name": "  "}, headers=auth(people["behdin"]))
    assert r.status_code == 400


async def test_the_two_apps_keep_their_sign_in_apart_and_either_can_be_left(client, db, seeded):
    await sign_in(client, seeded["mobed_phone"])
    mobed_cookie = client.cookies.get("refresh_token")
    assert mobed_cookie
    behdin = await behdin_sign_in(client, seeded["mobed_phone"])
    behdin_cookie = client.cookies.get("behdin_refresh_token")
    assert behdin_cookie and behdin_cookie != mobed_cookie
    assert client.cookies.get("refresh_token") == mobed_cookie
    # Each refreshes from its own cookie.
    assert (await client.post("/api/behdin/auth/refresh")).status_code == 200
    assert (await client.post("/api/mobed/auth/refresh")).status_code == 200
    # Signing out of the behdin app leaves the mobed one signed in.
    assert (await client.post("/api/behdin/auth/logout")).status_code == 200
    assert (await client.post("/api/behdin/auth/refresh")).status_code == 401
    assert (await client.post("/api/mobed/auth/refresh")).status_code == 200
    assert behdin["user"]["roles"] == ["behdin", "mobed"]


async def test_a_behdin_can_delete_their_account(client, db, invite_only):
    body = await behdin_sign_in(client, PERSON)
    r = await client.request("DELETE", "/api/behdin/account", json={"confirm": False}, headers=auth(body))
    assert r.status_code == 400
    r = await client.request("DELETE", "/api/behdin/account", json={"confirm": True}, headers=auth(body))
    assert r.status_code == 200 and r.json() == {"deleted": True}
    assert (await db.execute(select(User).where(User.phone == PERSON))).first() is None
    assert (await client.get("/api/behdin/me", headers=auth(body))).status_code == 401


async def test_the_admin_lists_mobeds_and_managers_only_and_counts_behdins_apart(client, db, seeded, monkeypatch):
    monkeypatch.setenv("ADMIN_PHONES", seeded["panthaky_phone"])
    config.get_settings.cache_clear()
    try:
        await behdin_sign_in(client, PERSON)
        admin = await sign_in(client, seeded["panthaky_phone"])
        r = await client.get("/api/mobed/admin/mobeds", headers=auth(admin))
        assert r.status_code == 200
        kinds = {m["account_kind"] for m in r.json()["mobeds"]}
        assert kinds <= {"mobed", "funeral_manager"} and PERSON not in {m["phone"] for m in r.json()["mobeds"]}
        assert r.json()["waiting"] == sum(1 for m in r.json()["mobeds"] if m["access"] == "pending")
    finally:
        config.get_settings.cache_clear()


async def test_a_code_sent_to_a_new_number_is_sent_for_the_behdin_app_only(client, db, invite_only, monkeypatch):
    monkeypatch.setenv("OTP_MODE", "live")
    config.get_settings.cache_clear()
    from agyary.services import bot_check

    async def fine(*a, **k):
        return True

    monkeypatch.setattr(bot_check, "verify", fine)
    monkeypatch.setattr(bot_check, "configured", lambda s: True)
    r = await client.post("/api/behdin/auth/otp/request", json={"phone": PERSON, "turnstile_token": "x"})
    assert r.status_code == 200, r.text
    code = r.json().get("debug_code")
    assert code, "a number with no account is sent a code by the behdin app, not suppressed"
    r = await client.post("/api/behdin/auth/otp/verify", json={"phone": PERSON, "code": code})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "needs_name"
    r = await client.post("/api/behdin/auth/wa/complete", json={"name": "Test Person"})
    assert r.json()["user"]["account_kind"] == "behdin"


async def test_an_admin_who_signs_in_first_at_the_behdin_app_is_a_mobed_not_a_behdin(client, db, seeded, invite_only, monkeypatch):
    monkeypatch.setenv("ADMIN_PHONES", "+919911100055")
    config.get_settings.cache_clear()
    body = await behdin_sign_in(client, "+919911100055", "Owner")
    assert body["user"]["account_kind"] == "mobed" and body["user"]["roles"] == ["behdin", "mobed"]
    row = (await db.execute(select(User).where(User.phone == "+919911100055"))).scalar_one()
    assert (row.account_kind, row.access) == ("mobed", "on")


async def test_a_behdin_becomes_a_waiting_mobed_and_the_admins_are_told(client, db, seeded, monkeypatch):
    from agyary.models import AppNotification

    monkeypatch.setenv("ADMIN_PHONES", seeded["panthaky_phone"])
    config.get_settings.cache_clear()
    pushed = []

    async def capture(db, settings, user_ids, **kw):
        pushed.append({"to": list(user_ids), **kw})
        return 0

    from agyary.services import web_push

    monkeypatch.setattr(web_push, "send_to_users", capture)
    admin = await sign_in(client, seeded["panthaky_phone"])
    person = await behdin_sign_in(client, PERSON)
    headers = auth(person)

    r = await client.get("/api/mobed/auth/me", headers=headers)
    assert r.status_code == 403 and r.headers["X-Account-Kind"] == "behdin"
    r = await client.post("/api/mobed/auth/become-mobed", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["account_kind"] == "mobed" and r.json()["access"] == "pending"
    row = (await db.execute(select(User).where(User.phone == PERSON))).scalar_one()
    assert (row.account_kind, row.access) == ("mobed", "pending") and row.access_changed_at is not None

    (note,) = (await db.execute(
        select(AppNotification).where(AppNotification.kind == "mobed_request", AppNotification.user_id == admin["user"]["id"])
    )).scalars()
    assert "Test Person" in note.body and PERSON in note.body
    assert pushed and pushed[0]["to"] == [admin["user"]["id"]]

    # Still a person in the behdin app, with the mobed role waiting.
    me = (await client.get("/api/behdin/me", headers=headers)).json()
    assert me["roles"] == ["behdin", "mobed"] and me["role_access"]["mobed"] == "pending"
    # And the mobed app lets them choose a fire temple like any waiting mobed.
    assert (await client.get("/api/mobed/auth/me", headers=headers)).json()["access"] == "pending"
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)
    assert r.status_code == 200, r.text
    # A second ask is refused, as is one from a mobed or a manager.
    assert (await client.post("/api/mobed/auth/become-mobed", headers=headers)).status_code == 409
    mobed = await sign_in(client, seeded["mobed_phone"])
    assert (await client.post("/api/mobed/auth/become-mobed", headers=auth(mobed))).status_code == 409
    assert (await client.post("/api/mobed/auth/become-mobed")).status_code == 401
