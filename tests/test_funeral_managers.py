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
from sqlalchemy import update

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
