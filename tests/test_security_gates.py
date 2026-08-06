"""Security gates that must hold regardless of what the app otherwise does.

Three separate holes, one theme - something that only ever made sense as a
development affordance was reachable (or silently forgiving) in production:

  * the web-chat simulator's unauthenticated API,
  * a blank JWT signing key signing real session tokens,
  * an edit path that quietly dropped fields it didn't render.
"""

from __future__ import annotations

import contextlib
import importlib

import pytest
from httpx import ASGITransport, AsyncClient

from agyary.core.config import Settings


# ---------------------------------------------------------------------------
# JWT signing key (1b)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_jwt_secret_refuses_to_start(blank):
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        Settings(jwt_secret_key=blank).validate_runtime_secrets()


def test_real_jwt_secret_passes():
    Settings(jwt_secret_key="a-real-key").validate_runtime_secrets()  # does not raise


# ---------------------------------------------------------------------------
# Web-chat simulator gate (1a)
# ---------------------------------------------------------------------------
def _reload_app(monkeypatch, *, debug: bool):
    """Rebuild the FastAPI app under a different APP_DEBUG.

    Router registration happens at import time (it has to - it decides
    whether the routes exist at all, not whether a request is allowed), so
    exercising the gate means re-importing the module with the setting
    changed and the settings cache cleared.
    """
    from agyary.core import config

    monkeypatch.setenv("APP_DEBUG", "true" if debug else "false")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-not-for-production")
    config.get_settings.cache_clear()
    import agyary.api.main as main_module

    importlib.reload(main_module)
    return main_module


@pytest.fixture
def app_factory(monkeypatch):
    """Yields a builder for an app at a given APP_DEBUG, and puts the
    module-level app back the way the rest of the suite expects it."""
    yield lambda debug: _reload_app(monkeypatch, debug=debug)
    from agyary.core import config

    monkeypatch.undo()
    config.get_settings.cache_clear()
    importlib.reload(importlib.import_module("agyary.api.main"))


@contextlib.asynccontextmanager
async def _client_for(app, db):
    """An in-process client against a specific app instance, sharing the
    test session the way conftest's `client` fixture does."""
    from agyary.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


async def test_chat_endpoints_gone_in_production(db, seeded, app_factory):
    """The two concrete holes: an unauthenticated caller could list every
    agyari's admin names + phone numbers, and drive the whole behdin
    conversation (read bookings, read saved names, book, cancel) for any
    phone number they typed."""
    async with _client_for(app_factory(False).app, db) as ac:
        assert (await ac.get("/api/chat/agyaries")).status_code == 404
        r = await ac.post(
            "/api/chat/messages",
            json={"agyary_id": seeded["agyary_id"], "phone_number": "+919800000009", "text": "hi"},
        )
        assert r.status_code == 404
        assert (await ac.get("/chat")).status_code == 404


async def test_chat_endpoints_still_work_in_debug(db, seeded, app_factory):
    """The simulator has to keep working where it belongs - this gate is
    about where it's reachable, not about deleting the dev tool."""
    async with _client_for(app_factory(True).app, db) as ac:
        assert (await ac.get("/api/chat/agyaries")).status_code == 200
        r = await ac.post(
            "/api/chat/messages",
            json={"agyary_id": seeded["agyary_id"], "phone_number": "+919800000009", "text": "hi"},
        )
        assert r.status_code == 200
        assert (await ac.get("/chat")).status_code == 200


async def test_mobed_api_still_served_in_production(db, app_factory):
    """The gate must be surgical - the real app keeps working."""
    async with _client_for(app_factory(False).app, db) as ac:
        assert (await ac.get("/health")).status_code == 200
        # Present and reachable (401 = the auth layer answered, not a 404).
        assert (await ac.get("/api/mobed/auth/me")).status_code == 401
        assert (await ac.get("/mobed")).status_code == 200
