"""Inbound WhatsApp sign-in: the mobed messages us, and that is the only door.

Three properties carry the whole design. The caller never supplies a phone
number, so there is nothing here to enumerate. The code is a bearer token
by construction - it travels through the user's own WhatsApp - so holding
it must not be enough to collect the session it created. And the webhook
must refuse anything it cannot prove came from Meta, including when the
app secret is missing entirely.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from agyary.core import config
from agyary.models import User, WaLoginAttempt
from agyary.services import wa_login

SIGNIN_NUMBER = "+919800000000"
SENDER = "919800000055"
APP_SECRET = "test-app-secret"


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setenv("WHATSAPP_SIGNIN_NUMBER", SIGNIN_NUMBER)
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-me")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def _signed(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    digest = hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"x-hub-signature-256": f"sha256={digest}", "content-type": "application/json"}


def _inbound(code: str, sender: str = SENDER) -> dict:
    message = {"type": "text", "from": sender, "text": {"body": f"Mobed Diary sign-in: {code}"}}
    return {"entry": [{"changes": [{"value": {"messages": [message]}}]}]}


async def _start(client) -> str:
    """Open an attempt. The client keeps the wa_login cookie in its own jar,
    which is exactly how a browser holds it."""
    r = await client.post("/api/mobed/auth/wa/start")
    assert r.status_code == 200, r.text
    assert client.cookies.get("wa_login")
    return r.json()["code"]


# ---------------------------------------------------------------------------
# The code itself
# ---------------------------------------------------------------------------
def test_code_is_ten_chars_of_unambiguous_base32():
    code = wa_login.generate_code()
    assert len(code) == wa_login.CODE_LENGTH == 10
    # Crockford's alphabet: I, L, O and U are excluded, so a code read off
    # one screen and checked on another cannot be misread.
    assert not set(code) & set("ILOU")


def test_code_extraction_survives_what_users_actually_send():
    code = wa_login.generate_code()
    assert wa_login.extract_code(f"Mobed Diary sign-in: {code}") == code
    assert wa_login.extract_code(code.lower()) == code
    assert wa_login.extract_code(f"hi  {code}  please") == code
    assert wa_login.extract_code("hello") is None
    assert wa_login.extract_code("") is None


def test_wa_link_drops_the_plus_and_encodes_the_text():
    link = wa_login.build_wa_link("ABCDEFGHJK", SIGNIN_NUMBER)
    assert link.startswith("https://wa.me/919800000000?text=")
    assert "ABCDEFGHJK" in link


# ---------------------------------------------------------------------------
# The flow
# ---------------------------------------------------------------------------
async def test_start_asks_for_no_phone_number_at_all(db, client):
    """The whole point: nothing to enumerate, because the caller tells us
    nothing about who they are."""
    r = await client.post("/api/mobed/auth/wa/start")
    assert r.status_code == 200
    assert set(r.json()) == {"code", "wa_link", "expires_at"}
    row = (await db.execute(select(WaLoginAttempt))).scalar_one()
    assert row.claimed_phone is None and row.claimed_at is None


async def test_first_ever_signin_asks_for_a_name_then_completes(db, client):
    code = await _start(client)
    pending = await client.get("/api/mobed/auth/wa/poll")
    assert pending.json() == {"status": "pending"}

    raw, headers = _signed(_inbound(code))
    assert (await client.post("/webhooks/whatsapp", content=raw, headers=headers)).status_code == 200

    claimed = await client.get("/api/mobed/auth/wa/poll")
    assert claimed.json()["status"] == "needs_name"

    done = await client.post(
        "/api/mobed/auth/wa/complete", json={"name": "Er. Newcomer"}
    )
    body = done.json()
    assert body["status"] == "signed_in"
    assert body["access_token"]
    # The number came from the signed payload, never from the caller.
    assert body["user"]["phone"] == f"+{SENDER}"
    assert body["user"]["name"] == "Er. Newcomer"


async def test_returning_mobed_skips_the_name_step(db, client):
    db.add(User(name="Er. Already Here", phone=f"+{SENDER}"))
    await db.flush()

    code = await _start(client)
    raw, headers = _signed(_inbound(code))
    await client.post("/webhooks/whatsapp", content=raw, headers=headers)

    body = (await client.get("/api/mobed/auth/wa/poll")).json()
    assert body["status"] == "signed_in"
    assert body["user"]["name"] == "Er. Already Here"


async def test_attempt_is_consumed_once_a_session_exists(db, client):
    db.add(User(name="Er. Already Here", phone=f"+{SENDER}"))
    await db.flush()

    code = await _start(client)
    raw, headers = _signed(_inbound(code))
    await client.post("/webhooks/whatsapp", content=raw, headers=headers)
    await client.get("/api/mobed/auth/wa/poll")

    assert (await db.execute(select(WaLoginAttempt))).scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Security properties
# ---------------------------------------------------------------------------
async def test_the_code_alone_cannot_collect_the_session(db, client):
    """The code travels through the user's own WhatsApp, so anyone who sees
    the link holds it. Polling matches on the httpOnly cookie instead, which
    never leaves the browser that started the attempt."""
    code = await _start(client)
    raw, headers = _signed(_inbound(code))
    await client.post("/webhooks/whatsapp", content=raw, headers=headers)

    client.cookies.clear()
    assert (await client.get("/api/mobed/auth/wa/poll")).status_code == 400


async def test_webhook_rejects_an_unsigned_payload(db, client):
    code = await _start(client)
    r = await client.post(
        "/webhooks/whatsapp",
        content=json.dumps(_inbound(code)).encode(),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 401
    still = await client.get("/api/mobed/auth/wa/poll")
    assert still.json() == {"status": "pending"}


async def test_webhook_rejects_a_forged_signature(db, client):
    code = await _start(client)
    raw = json.dumps(_inbound(code)).encode()
    bad = hmac.new(b"not-the-secret", raw, hashlib.sha256).hexdigest()
    r = await client.post(
        "/webhooks/whatsapp",
        content=raw,
        headers={"x-hub-signature-256": f"sha256={bad}", "content-type": "application/json"},
    )
    assert r.status_code == 401
    still = await client.get("/api/mobed/auth/wa/poll")
    assert still.json() == {"status": "pending"}


async def test_webhook_refuses_to_run_with_no_app_secret(db, client, monkeypatch):
    """An empty secret would make the HMAC compare against an empty key and
    accept anything, so it fails closed rather than verifying nothing."""
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "")
    config.get_settings.cache_clear()
    r = await client.post(
        "/webhooks/whatsapp", content=b"{}", headers={"content-type": "application/json"}
    )
    assert r.status_code == 503


async def test_verify_handshake_needs_the_right_token(client):
    ok = await client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"},
    )
    assert ok.status_code == 200 and ok.text == "42"

    bad = await client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"},
    )
    assert bad.status_code == 403


# ---------------------------------------------------------------------------
# Claiming rules
# ---------------------------------------------------------------------------
async def test_a_replayed_delivery_does_not_reclaim(db, client):
    """Meta retries. The attempt itself is the idempotency key, which is why
    this needs no message-id dedupe table."""
    code = await _start(client)
    assert await wa_login.claim(db, code, "+919800000055") is True
    assert await wa_login.claim(db, code, "+919800000066") is False

    row = (await db.execute(select(WaLoginAttempt))).scalar_one()
    assert row.claimed_phone == "+919800000055"


async def test_an_expired_attempt_cannot_be_claimed(db, client):
    code = await _start(client)
    row = (await db.execute(select(WaLoginAttempt))).scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()

    assert await wa_login.claim(db, code, f"+{SENDER}") is False


async def test_an_unknown_code_claims_nothing(db, client):
    await _start(client)
    assert await wa_login.claim(db, "ZZZZZZZZZZ", f"+{SENDER}") is False


async def test_start_is_refused_when_no_signin_number_is_configured(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_SIGNIN_NUMBER", "")
    config.get_settings.cache_clear()
    assert (await client.post("/api/mobed/auth/wa/start")).status_code == 503
