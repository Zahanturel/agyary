"""Integration-test fixtures: real Postgres (agyary_test database).

Each test gets a clean schema (truncate-all) and a seeded demo agyary.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

# The mobed auth layer signs JWTs with jwt_secret_key; the repo ships it empty.
# Set a test value before any get_settings() call so the suite runs green under
# a plain `uv run pytest` (an OS env var overrides the empty .env entry).
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import agyary.models  # noqa: F401 - register models on Base.metadata
from agyary.core import config
from agyary.core.database import Base
from agyary.services import wa_login

TEST_DATABASE_URL = "postgresql+asyncpg://agyary:agyary@localhost:5432/agyary_test"

_schema_ready = False


@pytest.fixture
async def db():
    """A session on the test database with a clean, seeded schema."""
    global _schema_ready
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        if not _schema_ready:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            _schema_ready = True
        else:
            table_list = ", ".join(t.name for t in Base.metadata.sorted_tables)
            await conn.execute(text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"))

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seeded(db):
    """Demo agyary + panthaky + mobed + services; returns ids/phones."""
    from tests.seed_demo import seed

    await seed(db)
    return {
        "agyary_id": 1,
        "panthaky_phone": "+919800000001",
        "mobed_phone": "+919800000002",
    }


# --- Sign-in ----------------------------------------------------------------
# There is one way in: the mobed messages us a code and the webhook learns
# their number off a payload Meta signed. The helpers below drive that whole
# path rather than minting a JWT directly, so every test that logs in also
# proves sign-in still works - which matters more now that it is the only
# door and there is no fallback behind it.
WA_SIGNIN_NUMBER = "+919800000000"
WA_APP_SECRET = "test-app-secret"
WA_VERIFY_TOKEN = "verify-me"


@pytest.fixture(autouse=True)
def _whatsapp_configured(monkeypatch):
    """The webhook fails closed on a blank app secret, so every test that
    signs in needs these set. Cleared both sides because get_settings is
    lru_cached and would otherwise leak one test's config into the next."""
    monkeypatch.setenv("WHATSAPP_SIGNIN_NUMBER", WA_SIGNIN_NUMBER)
    monkeypatch.setenv("WHATSAPP_APP_SECRET", WA_APP_SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", WA_VERIFY_TOKEN)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def signed_inbound(code: str, phone: str) -> tuple[bytes, dict]:
    """A webhook delivery shaped and signed the way Meta sends one.

    The sender's number lives in the body, not in anything the caller
    supplied - which is the whole security claim of this path, so the
    helper never lets a test hand the number in by another route.
    """
    message = {
        "type": "text",
        "from": phone.lstrip("+"),
        "text": {"body": f"{wa_login.MESSAGE_PREFIX} {code}"},
    }
    raw = json.dumps({"entry": [{"changes": [{"value": {"messages": [message]}}]}]}).encode()
    digest = hmac.new(WA_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"x-hub-signature-256": f"sha256={digest}", "content-type": "application/json"}


async def sign_in(client, phone: str, name: str = "Er. Test Mobed") -> dict:
    """Full sign-in: start, signed webhook delivery, poll, name if new.

    Returns the session body. ``name`` is only used on a phone's first ever
    sign-in - a returning one keeps the stored name, and changing it is a
    PATCH /auth/me, not a side effect of logging in.
    """
    started = await client.post("/api/mobed/auth/wa/start")
    assert started.status_code == 200, started.text

    raw, headers = signed_inbound(started.json()["code"], phone)
    hook = await client.post("/webhooks/whatsapp", content=raw, headers=headers)
    assert hook.status_code == 200, hook.text

    body = (await client.get("/api/mobed/auth/wa/poll")).json()
    if body.get("status") == "needs_name":
        done = await client.post("/api/mobed/auth/wa/complete", json={"name": name})
        assert done.status_code == 200, done.text
        body = done.json()
    assert body.get("status") == "signed_in", body
    return body


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """The login rate limiter (api/rate_limit.py) keeps its counters in a
    module-level dict, keyed by client IP - every test hits it from the
    same in-process ASGI transport, so without a reset here, the third or
    fourth test to log in would 429 the rest of the suite. Real deployments
    have real distinct client IPs; this is purely a test-isolation fix."""
    from agyary.api import rate_limit

    rate_limit._hits.clear()
    yield
    rate_limit._hits.clear()


@pytest.fixture
async def client(db):
    """httpx client hitting the FastAPI app in-process (no real server, no
    lifespan - bare ASGITransport never fires startup/shutdown, so the send
    worker's background tasks never start here). get_db is overridden to
    the same test-database session used by other fixtures, so route
    handlers and test assertions share one transaction."""
    from httpx import ASGITransport, AsyncClient

    from agyary.api.main import app
    from agyary.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
