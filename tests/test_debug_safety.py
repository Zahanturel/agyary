"""Debug mode hands out sessions for any number, so it must be hard to leave on.

With APP_DEBUG true, /webhooks/whatsapp/simulate signs anyone in as anyone,
an OTP code comes back in the response, cookies lose Secure and /docs is
public. So: it is off unless asked for, the example config ships it off, a
production server refuses to start with it on, and the simulate endpoint
answers only a caller on the machine itself even when it is on.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agyary.core.config import Settings

ROOT = Path(__file__).resolve().parent.parent


def test_debug_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("APP_DEBUG", raising=False)
    assert Settings(_env_file=None, jwt_secret_key="x").app_debug is False


def test_the_example_config_ships_with_debug_off():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"(?m)^APP_DEBUG=false\s*$", text)
    assert not re.search(r"(?mi)^APP_DEBUG=true\s*$", text)


KEY = "k" * 32


def test_a_production_server_refuses_to_start_in_debug():
    with pytest.raises(RuntimeError, match="APP_DEBUG"):
        Settings(_env_file=None, jwt_secret_key=KEY, app_env="production",
                 app_debug=True).validate_runtime_secrets()
    # Production without debug, and debug on a laptop, both start.
    Settings(_env_file=None, jwt_secret_key=KEY, app_env="production", app_debug=False).validate_runtime_secrets()
    Settings(_env_file=None, jwt_secret_key=KEY, app_env="development", app_debug=True).validate_runtime_secrets()


def test_a_server_whose_env_lost_app_env_refuses_debug_too(monkeypatch):
    """CFG-03: debug lets anyone sign in as anyone, so only an explicit
    APP_ENV=development allows it, and the default is not that."""
    monkeypatch.delenv("APP_ENV", raising=False)
    assert Settings(_env_file=None, jwt_secret_key=KEY).app_env == "production"
    with pytest.raises(RuntimeError, match="APP_DEBUG"):
        Settings(_env_file=None, jwt_secret_key=KEY, app_debug=True).validate_runtime_secrets()
    with pytest.raises(RuntimeError, match="APP_DEBUG"):
        Settings(_env_file=None, jwt_secret_key=KEY, app_env="staging", app_debug=True).validate_runtime_secrets()


def test_a_short_signing_key_is_refused():
    """I-3: a key that can be guessed signs tokens for anyone."""
    with pytest.raises(RuntimeError, match="too short"):
        Settings(_env_file=None, jwt_secret_key="k" * 31, app_env="production").validate_runtime_secrets()


async def test_simulate_answers_only_a_caller_on_this_machine(db, seeded):
    """Even with debug on (the suite runs with it on), a request that did not
    come from the machine itself gets the same 404 as production."""
    from agyary.api.main import app
    from agyary.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        far = ASGITransport(app=app, client=("203.0.113.9", 40000))
        async with AsyncClient(transport=far, base_url="http://test") as remote:
            r = await remote.post("/webhooks/whatsapp/simulate",
                                  json={"code": "ABCDEFGHJK", "phone": "+919944400801"})
        assert r.status_code == 404

        near = ASGITransport(app=app, client=("127.0.0.1", 40000))
        async with AsyncClient(transport=near, base_url="http://test") as local:
            r = await local.post("/webhooks/whatsapp/simulate",
                                 json={"code": "ABCDEFGHJK", "phone": "+919944400801"})
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()


async def test_outside_debug_a_failed_statement_does_not_carry_its_parameters():
    """LOG-01: an exception's text reaches the logs (logger.exception, uvicorn's
    error log), and SQLAlchemy appends every bound parameter to it. With
    hide_parameters that list is left out. (Not covered: text the driver or
    Postgres itself puts in the message, such as a unique violation's DETAIL.)"""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from agyary.core.database import engine_options
    from tests.conftest import TEST_DATABASE_URL

    settings = Settings(_env_file=None, jwt_secret_key="x", app_debug=False)
    assert engine_options(settings)["hide_parameters"] is True
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool, **engine_options(settings))
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError) as caught:
                await conn.execute(text("SELECT 1 / 0 WHERE CAST(:phone AS text) IS NOT NULL"),
                                   {"phone": "+919944400999"})
        assert "division by zero" in str(caught.value)
        assert "9944400999" not in str(caught.value)
    finally:
        await engine.dispose()
