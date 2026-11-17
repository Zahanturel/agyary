"""A Doongerwadi or prayer hall manager's account (DECISIONS D10) and a
mobed's are kept apart.

A manager reaches none of the mobed app - behdins, memorials, calendar,
bookings, machis, slips, my day, reminders, fire temples, the map search -
and a mobed none of the manager's side. The refusal is in the one dependency
every mobed route is built on, and the walk below goes through every route
the app has, so a route added later is covered without anyone remembering it.
"""

from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select, update

from agyary.api.routes import mobed as mobed_routes
from agyary.core import config
from agyary.models import AgyaryUser, FuneralPlace, FuneralPlaceManager, User
from tests.conftest import sign_in

MANAGER = "+919911100088"

# What every account has, a manager's too: who they are, their name, their
# notices, signing out other devices, deleting the account. And the manager's own.
MANAGER_MAY = {
    ("GET", "/api/mobed/auth/me"),
    ("PATCH", "/api/mobed/auth/me"),
    ("POST", "/api/mobed/auth/account/delete"),
    ("POST", "/api/mobed/auth/sessions/sign-out-others"),
    ("GET", "/api/mobed/notifications"),
    ("POST", "/api/mobed/notifications/seen"),
    ("GET", "/api/mobed/manager/place"),
}
# Signing in, and what anyone may ask without an account: no session is read.
NO_SESSION = {
    ("POST", "/api/mobed/auth/wa/start"),
    ("GET", "/api/mobed/auth/wa/poll"),
    ("POST", "/api/mobed/auth/wa/confirm"),
    ("POST", "/api/mobed/auth/wa/complete"),
    ("POST", "/api/mobed/auth/refresh"),
    ("POST", "/api/mobed/auth/logout"),
    ("GET", "/api/mobed/auth/options"),
    ("POST", "/api/mobed/auth/otp/request"),
    ("POST", "/api/mobed/auth/otp/verify"),
    ("GET", "/api/mobed/agyaries/search"),
    ("GET", "/api/mobed/reference/calendar-options"),
}
# The Parsi calendar's arithmetic, for anyone (no account, nothing stored).
PUBLIC_PREFIXES = ("/api/calendar/",)


def _routes(routes) -> list[APIRoute]:
    """Every API route the app serves, including those of included routers."""
    found = []
    for r in routes:
        if isinstance(r, APIRoute):
            found.append(r)
        elif getattr(r, "original_router", None) is not None:
            found.extend(_routes(r.original_router.routes))
        elif getattr(r, "routes", None):
            found.extend(_routes(r.routes))
    return found


def _api_calls() -> set[tuple[str, str]]:
    from agyary.api.main import app

    return {
        (m, r.path) for r in _routes(app.routes) for m in r.methods - {"HEAD"}
        if r.path.startswith("/api/")
    }


def _reads_a_session(dependant) -> bool:
    calls = {mobed_routes.get_signed_in_account, mobed_routes.get_signed_in_user}
    return any(d.call in calls or _reads_a_session(d) for d in dependant.dependencies)


@pytest.fixture
def admin_is_panthaky(monkeypatch, seeded):
    monkeypatch.setenv("ADMIN_PHONES", seeded["panthaky_phone"])
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def _place(db, name="Doongerwadi (test)") -> FuneralPlace:
    place = FuneralPlace(name=name, kind="doongerwadi", city="Mumbai")
    db.add(place)
    await db.flush()
    return place


async def _manager(client, db, seeded, *, access="on", also_at_a_temple=False) -> tuple[dict, int]:
    """A manager's account, made the way sign-up leaves one. With
    ``also_at_a_temple`` it is also given a panthaky's membership at the seeded
    fire temple - which nothing in the app does - to prove that the refusal is
    the kind of account, not a missing membership."""
    body = await sign_in(client, MANAGER, "Test Manager")
    uid = body["user"]["id"]
    place = await _place(db)
    db.add(FuneralPlaceManager(funeral_place_id=place.id, user_id=uid))
    await db.execute(update(User).where(User.id == uid).values(account_kind="funeral_manager", access=access))
    if also_at_a_temple:
        db.add(AgyaryUser(agyary_id=seeded["agyary_id"], user_id=uid, role="panthaky"))
    await db.commit()
    return {"Authorization": f"Bearer {body['access_token']}"}, place.id


def test_every_route_is_accounted_for():
    """Each API route is either closed to managers (walked below), one of the
    few every account has, or reads no session at all. A listed route that is
    gone fails here too, so the lists cannot go stale."""
    calls = _api_calls()
    assert MANAGER_MAY <= calls and NO_SESSION <= calls, (MANAGER_MAY | NO_SESSION) - calls
    from agyary.api.main import app

    by_call = {(m, r.path): r for r in _routes(app.routes) for m in r.methods}
    for call in NO_SESSION:
        assert not _reads_a_session(by_call[call].dependant), call
    for call in calls - MANAGER_MAY - NO_SESSION:
        if call[1].startswith(PUBLIC_PREFIXES):
            assert not _reads_a_session(by_call[call].dependant), call
            continue
        # Everything else reads the session through the dependency that refuses managers.
        assert _reads_a_session(by_call[call].dependant), call


async def test_a_managers_account_reaches_none_of_the_mobed_app(client, db, seeded, admin_is_panthaky):
    headers, _ = await _manager(client, db, seeded, also_at_a_temple=True)
    closed = sorted(c for c in _api_calls() - MANAGER_MAY - NO_SESSION if not c[1].startswith(PUBLIC_PREFIXES))
    assert len(closed) > 60          # the whole mobed app, not a handful
    for method, path in closed:
        url = re.sub(r"\{[^}]+\}", "1", path)
        r = await client.request(method, url, json={}, headers=headers)
        if path.startswith("/api/mobed/admin/"):
            # The admin pages answer anyone who is not an admin with the same 404.
            assert r.status_code == 404 and r.json()["detail"] == "Not found", (method, path, r.text)
        else:
            assert r.status_code == 403, (method, path, r.status_code, r.text)
            assert r.json()["detail"] == mobed_routes.NOT_FOR_MANAGERS, (method, path)
            assert r.headers["X-Account-Kind"] == "funeral_manager", (method, path)


async def test_a_manager_has_their_own_screen_and_what_every_account_has(client, db, seeded):
    headers, place_id = await _manager(client, db, seeded)
    me = (await client.get("/api/mobed/auth/me", headers=headers)).json()
    assert me["account_kind"] == "funeral_manager" and me["agyaries"] == []
    assert [p["id"] for p in me["funeral_places"]] == [place_id]
    r = await client.get("/api/mobed/manager/place", headers=headers)
    assert r.status_code == 200 and r.json()["places"][0]["name"] == "Doongerwadi (test)"
    r = await client.patch("/api/mobed/auth/me", json={"name": "Test Manager Two"}, headers=headers)
    assert r.status_code == 200 and r.json()["name"] == "Test Manager Two"
    assert (await client.get("/api/mobed/notifications", headers=headers)).status_code == 200
    assert (await client.post("/api/mobed/notifications/seen", json={}, headers=headers)).status_code == 200


async def test_a_mobed_cannot_reach_the_managers_side(client, db, seeded, admin_is_panthaky):
    for phone in (seeded["mobed_phone"], seeded["panthaky_phone"]):   # a mobed, and an admin
        body = await sign_in(client, phone)
        r = await client.get("/api/mobed/manager/place", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert r.status_code == 403 and r.json()["detail"] == mobed_routes.NOT_FOR_MOBEDS
        assert body["user"]["account_kind"] == "mobed" and body["user"]["funeral_places"] == []
    assert (await client.get("/api/mobed/manager/place")).status_code == 401


@pytest.mark.parametrize("access", ["pending", "off"])
async def test_a_manager_who_is_waiting_or_off_sees_only_the_waiting_screen(client, db, seeded, access):
    headers, _ = await _manager(client, db, seeded, access=access)
    me = await client.get("/api/mobed/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["access"] == access
    for path in ("/api/mobed/manager/place", "/api/mobed/notifications"):
        r = await client.get(path, headers=headers)
        assert r.status_code == 403 and r.headers["X-Mobed-Access"] == access, path
    # And still none of the mobed app, whatever the access.
    r = await client.get("/api/mobed/my-day", headers=headers)
    assert r.status_code == 403 and r.json()["detail"] == mobed_routes.NOT_FOR_MANAGERS


# --- Signing up as a manager ---------------------------------------------------

NEW = "+919911100099"


async def _new_account(client, phone=NEW, name="Test Manager") -> tuple[dict, dict]:
    body = await sign_in(client, phone, name, approve=False)
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


@pytest.fixture
def pushes(monkeypatch):
    sent = []

    async def capture(db, settings, user_ids, **kw):
        sent.append({"to": list(user_ids), **kw})
        return 0

    from agyary.services import web_push

    monkeypatch.setattr(web_push, "send_to_users", capture)
    return sent


async def test_a_new_account_chooses_its_place_and_waits_and_the_admins_are_told(
    client, db, seeded, admin_is_panthaky, pushes,
):
    from agyary.models import AppNotification

    admin = await sign_in(client, seeded["panthaky_phone"])
    place = await _place(db)
    off = await _place(db, "Old aramgah (test)")
    off.is_active = False
    hall = await _place(db, "Prayer hall (test)")
    hall.city = "Worli"
    await db.commit()

    headers, user = await _new_account(client)
    assert user["may_choose_kind"] is True and user["account_kind"] == "mobed" and user["access"] == "pending"

    listed = (await client.get("/api/mobed/funeral-places", headers=headers)).json()["places"]
    assert [p["name"] for p in listed] == ["Doongerwadi (test)", "Prayer hall (test)"]     # not the one turned off
    by_town = (await client.get("/api/mobed/funeral-places?q=worli", headers=headers)).json()["places"]
    assert [p["name"] for p in by_town] == ["Prayer hall (test)"]
    assert (await client.get("/api/mobed/funeral-places?q=%25", headers=headers)).json()["places"] == []

    assert (await client.post(f"/api/mobed/funeral-places/{off.id}/join", headers=headers)).status_code == 404
    r = await client.post(f"/api/mobed/funeral-places/{place.id}/join", headers=headers)
    assert r.status_code == 200, r.text
    me = r.json()["user"]
    assert me["account_kind"] == "funeral_manager" and me["access"] == "pending" and me["may_choose_kind"] is False
    assert [p["name"] for p in me["funeral_places"]] == ["Doongerwadi (test)"]

    (note,) = (await db.execute(select(AppNotification).where(AppNotification.kind == "manager_request"))).scalars()
    assert note.user_id == admin["user"]["id"] and note.title == "A new Doongerwadi manager is waiting"
    assert "Test Manager" in note.body and NEW in note.body and "Doongerwadi (test), Mumbai" in note.body
    assert note.link == "#/admin/mobeds"
    (push,) = pushes
    assert push["title"] == "A new Doongerwadi manager is waiting" and push["to"] == [admin["user"]["id"]]
    assert "Test Manager" in push["body"] and "Doongerwadi (test)" in push["body"]
    assert NEW not in push["body"] and NEW.lstrip("+") not in push["body"]      # never on the lock screen

    # Waiting: their own screen is refused for now, and nothing of a mobed's at any time.
    r = await client.get("/api/mobed/manager/place", headers=headers)
    assert r.status_code == 403 and r.headers["X-Mobed-Access"] == "pending"
    for method, path in (("POST", f"/api/mobed/agyaries/{seeded['agyary_id']}/join"),
                         ("POST", "/api/mobed/agyaries"),
                         ("POST", f"/api/mobed/funeral-places/{hall.id}/join")):
        r = await client.request(method, path, json={"name": "X", "city": "Y"}, headers=headers)
        assert r.status_code == 403 and r.json()["detail"] == mobed_routes.NOT_FOR_MANAGERS, path

    # The admin approves them with the one switch; then their screen opens.
    uid = me["id"]
    r = await client.post(f"/api/mobed/admin/mobeds/{uid}/access", json={"access": "on"},
                          headers={"Authorization": f"Bearer {admin['access_token']}"})
    assert r.status_code == 200 and r.json()["access"] == "on"
    r = await client.get("/api/mobed/manager/place", headers=headers)
    assert r.status_code == 200 and r.json()["places"][0]["id"] == place.id


async def test_an_account_that_has_chosen_is_never_asked_again(client, db, seeded, admin_is_panthaky):
    place = await _place(db)
    await db.commit()
    # A mobed at a fire temple, and an admin: neither may become a manager.
    for phone in (seeded["mobed_phone"], seeded["panthaky_phone"]):
        body = await sign_in(client, phone)
        h = {"Authorization": f"Bearer {body['access_token']}"}
        assert body["user"]["may_choose_kind"] is False
        assert (await client.get("/api/mobed/funeral-places", headers=h)).status_code == 409
        r = await client.post(f"/api/mobed/funeral-places/{place.id}/join", headers=h)
        assert r.status_code == 409 and r.json()["detail"].startswith("Your account is already set up as a mobed's.")
    # A new mobed who chose a fire temple first.
    headers, _ = await _new_account(client)
    await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", json={"claimed_role": "mobed"}, headers=headers)
    assert (await client.get("/api/mobed/auth/me", headers=headers)).json()["may_choose_kind"] is False
    assert (await client.post(f"/api/mobed/funeral-places/{place.id}/join", headers=headers)).status_code == 409
    assert (await db.execute(select(FuneralPlaceManager))).first() is None


async def test_an_old_account_that_was_on_still_waits_once_it_is_a_managers(client, db, seeded):
    """An account from before approval (on) that never chose a fire temple is
    still checked by the owner before it can be a manager's."""
    place = await _place(db)
    await db.commit()
    body = await sign_in(client, NEW)          # approved, as an old account would be
    h = {"Authorization": f"Bearer {body['access_token']}"}
    r = await client.post(f"/api/mobed/funeral-places/{place.id}/join", headers=h)
    assert r.status_code == 200 and r.json()["user"]["access"] == "pending"


async def test_an_account_that_is_off_cannot_choose(client, db, seeded):
    place = await _place(db)
    await db.commit()
    headers, user = await _new_account(client)
    await db.execute(update(User).where(User.id == user["id"]).values(access="off"))
    await db.commit()
    r = await client.post(f"/api/mobed/funeral-places/{place.id}/join", headers=headers)
    assert r.status_code == 403 and r.headers["X-Mobed-Access"] == "off"


# --- The owner's side ------------------------------------------------------------

async def test_the_admin_sees_managers_with_their_place_and_counts_what_is_in_the_app(
    client, db, seeded, admin_is_panthaky, pushes,
):
    from agyary.models import AppNotification

    admin = await sign_in(client, seeded["panthaky_phone"])
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    place = await _place(db)
    off = await _place(db, "Old aramgah (test)")
    off.is_active = False
    await db.commit()
    waiting, _ = await _new_account(client)
    await client.post(f"/api/mobed/funeral-places/{place.id}/join", headers=waiting)
    approved, user = await _new_account(client, "+919911100098", "Second Manager")
    await client.post(f"/api/mobed/funeral-places/{place.id}/join", headers=approved)
    await client.post(f"/api/mobed/admin/mobeds/{user['id']}/access", json={"access": "on"}, headers=ah)
    (note,) = (await db.execute(select(AppNotification).where(AppNotification.user_id == user["id"]))).scalars()
    assert note.title == "You're in" and note.link == "#/manager"

    data = (await client.get("/api/mobed/admin/mobeds", headers=ah)).json()
    assert data["waiting"] == 1 and data["managers_waiting"] == 1
    rows = {m["name"]: m for m in data["mobeds"]}
    assert rows["Test Manager"]["access"] == "pending" and rows["Test Manager"]["phone"] == NEW
    assert rows["Test Manager"]["account_kind"] == "funeral_manager"
    assert [p["name"] for p in rows["Test Manager"]["funeral_places"]] == ["Doongerwadi (test)"]
    assert rows["Test Manager"]["agyaries"] == [] and rows["Second Manager"]["access"] == "on"
    assert rows["Er. Pervez Kias"]["account_kind"] == "mobed" and rows["Er. Pervez Kias"]["funeral_places"] == []

    o = (await client.get("/api/mobed/admin/overview", headers=ah)).json()
    assert o["mobeds_waiting"] == 0 and o["managers_waiting"] == 1
    assert o["in_the_app"] == {
        "mobeds": {"on": 2, "pending": 0, "off": 0},
        "panthakys": 1,
        "fire_temples_in_use": 1,
        "funeral_places": {"in_use": 1, "off": 1},
        "managers": {"on": 1, "pending": 1, "off": 0},
    }
    # And on the place's own line.
    listed = (await client.get("/api/mobed/admin/funeral-places", headers=ah)).json()["places"]
    assert listed[0]["managers"] == {"on": 1, "pending": 1, "off": 0}
