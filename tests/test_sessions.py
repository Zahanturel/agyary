"""Sessions that can be ended (AU-2).

A sign-in is a session kept on the server. Its refresh token changes on every
use, and an old one coming back means it was copied: the session ends. Signing
out ends it for good, "sign out other devices" ends the rest, an admin can sign a
mobed out everywhere, and no session lives longer than a year. A refresh token
from before sessions existed is moved into one, once, on its next use - so the
deploy signs nobody out - and dies with "sign out other devices" like the rest.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from agyary.core import config
from agyary.models import User
from tests.conftest import sign_in

PHONE = "+919944401701"


async def _signed_in(client, phone=PHONE) -> tuple[str, str]:
    body = await sign_in(client, phone, "Session Mobed")
    return body["access_token"], client.cookies.get("refresh_token")


async def _refresh(client, token: str | None = None):
    if token is not None:
        client.cookies.set("refresh_token", token)
    return await client.post("/api/mobed/auth/refresh")


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_signing_out_ends_the_session_for_good(client, db, seeded):
    access, refresh = await _signed_in(client)
    assert (await client.post("/api/mobed/auth/logout")).status_code == 200
    client.cookies.clear()
    assert (await _refresh(client, refresh)).status_code == 401
    assert (await client.get("/api/mobed/auth/me", headers=_bearer(access))).status_code == 401


async def test_a_refresh_token_used_twice_ends_the_session(client, db, seeded):
    _, first = await _signed_in(client)
    r = await _refresh(client)
    assert r.status_code == 200
    second = client.cookies.get("refresh_token")
    assert second and second != first
    # The first one coming back means somebody kept a copy: the session ends...
    client.cookies.clear()
    assert (await _refresh(client, first)).status_code == 401
    # ...for the copy and for the device that had moved on alike.
    client.cookies.clear()
    assert (await _refresh(client, second)).status_code == 401


async def test_signing_out_other_devices(db, seeded):
    from agyary.api.main import app
    from agyary.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as phone, \
                AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as tablet:
            phone_access, _ = await _signed_in(phone)
            tablet_access, _ = await _signed_in(tablet)
            r = await phone.post("/api/mobed/auth/sessions/sign-out-others", headers=_bearer(phone_access))
            assert r.status_code == 200 and r.json()["signed_out"] == 1
            assert (await tablet.get("/api/mobed/auth/me", headers=_bearer(tablet_access))).status_code == 401
            assert (await _refresh(tablet)).status_code == 401
            assert (await phone.get("/api/mobed/auth/me", headers=_bearer(phone_access))).status_code == 200
            assert (await _refresh(phone)).status_code == 200
    finally:
        app.dependency_overrides.clear()


async def test_an_admin_can_sign_a_mobed_out_everywhere(client, db, seeded, monkeypatch):
    admin_phone = seeded["mobed_phone"]
    monkeypatch.setenv("ADMIN_PHONES", admin_phone)
    config.get_settings.cache_clear()
    victim_access, _ = await _signed_in(client)
    client.cookies.clear()
    admin_access = (await sign_in(client, admin_phone))["access_token"]

    r = await client.post("/api/mobed/admin/sign-out-everywhere", headers=_bearer(victim_access),
                          json={"phone": admin_phone})
    assert r.status_code == 404                              # not for a non-admin
    r = await client.post("/api/mobed/admin/sign-out-everywhere", headers=_bearer(admin_access),
                          json={"phone": PHONE})
    assert r.status_code == 200 and r.json()["signed_out"] >= 1
    assert (await client.get("/api/mobed/auth/me", headers=_bearer(victim_access))).status_code == 401


async def test_no_session_lives_longer_than_a_year(client, db, seeded):
    from agyary.models import UserSession

    await _signed_in(client)
    await db.execute(update(UserSession).values(created_at=datetime.now(timezone.utc) - timedelta(days=366)))
    await db.commit()
    assert (await _refresh(client)).status_code == 401


def _legacy_refresh(user_id: int) -> str:
    """A refresh token as issued before sessions existed: no session id, ten years."""
    settings = config.get_settings()
    payload = {"sub": str(user_id), "type": "refresh",
               "exp": datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_days)}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


async def test_a_token_from_before_sessions_is_moved_into_one(client, db, seeded):
    await _signed_in(client)
    user = (await db.execute(select(User).where(User.phone == PHONE))).scalar_one()
    legacy = _legacy_refresh(user.id)
    client.cookies.clear()
    r = await _refresh(client, legacy)
    assert r.status_code == 200
    moved = r.cookies.get("refresh_token")
    assert moved != legacy and jwt.decode(moved, options={"verify_signature": False}).get("sid")

    # "Sign out other devices" also kills any old token still out there.
    access = r.json()["access_token"]
    await client.post("/api/mobed/auth/sessions/sign-out-others", headers=_bearer(access))
    client.cookies.clear()
    assert (await _refresh(client, legacy)).status_code == 401
