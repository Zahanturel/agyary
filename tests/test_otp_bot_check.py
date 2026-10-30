"""The conditions for sending sign-in codes (docs/DECISIONS.md D1, D3).

Asking for a code makes us send a paid message to a number the caller typed, so
the bot check (Cloudflare Turnstile) must be passed for every request, and the
per-address limits are counted in the database, where a restart or a deploy
cannot reset them. A server without the check's keys sends no codes at all, and
the admin screen says the check is missing (D3, changed 30 Oct 2026).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from agyary.api import rate_limit
from agyary.core import config
from agyary.services import bot_check, otp
from tests.test_mobed_api import NEW_MOBED_PHONE, _member_headers
from tests.test_otp import Outbox
from tests.test_reminder_sender import _settings

PHONE = "+919800000002"            # the seeded mobed
NOW = datetime(2030, 3, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr(otp, "_send", box)
    return box


def _live(monkeypatch, *, turnstile: bool) -> None:
    monkeypatch.setenv("OTP_MODE", "live")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "555000111")
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site-key" if turnstile else "")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret-key" if turnstile else "")
    config.get_settings.cache_clear()


async def test_codes_need_the_bot_check_once_it_is_configured(client, db, seeded, monkeypatch, outbox):
    _live(monkeypatch, turnstile=True)

    async def fake_verify(settings, token, ip):
        return token == "passed"

    monkeypatch.setattr(bot_check, "verify", fake_verify)
    for token in (None, "failed"):
        body = {"phone": PHONE} if token is None else {"phone": PHONE, "turnstile_token": token}
        r = await client.post("/api/mobed/auth/otp/request", json=body)
        assert r.status_code == 400 and "check" in r.json()["detail"], token
    assert outbox.sent == []
    rate_limit._hits.clear()
    r = await client.post("/api/mobed/auth/otp/request", json={"phone": PHONE, "turnstile_token": "passed"})
    assert r.status_code == 200, r.text
    assert len(outbox.sent) == 1


async def test_a_server_without_the_bot_check_sends_no_codes(client, db, seeded, monkeypatch, outbox):
    """CFG-02: a rebuilt server missing its keys must not send paid messages to
    typed numbers with no check. The other sign-in still works, so it says so."""
    _live(monkeypatch, turnstile=False)
    assert (await client.get("/api/mobed/auth/options")).json() == {"otp": True, "turnstile_site_key": None}
    r = await client.post("/api/mobed/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 503 and r.json()["detail"] == otp.UNAVAILABLE
    assert outbox.sent == []


async def test_the_admin_screen_says_whether_the_bot_check_is_set_up(client, db, seeded, monkeypatch):
    monkeypatch.setenv("ADMIN_PHONES", NEW_MOBED_PHONE)
    _live(monkeypatch, turnstile=False)
    headers = await _member_headers(client, seeded)
    assert (await client.get("/api/mobed/admin/overview", headers=headers)).json()["otp"]["bot_check"] is False
    _live(monkeypatch, turnstile=True)
    assert (await client.get("/api/mobed/admin/overview", headers=headers)).json()["otp"]["bot_check"] is True


async def test_the_login_screen_gets_the_site_key_and_the_page_allows_the_check(client, monkeypatch):
    _live(monkeypatch, turnstile=True)
    options = (await client.get("/api/mobed/auth/options")).json()
    assert options == {"otp": True, "turnstile_site_key": "site-key"}
    csp = (await client.get("/mobed")).headers["content-security-policy"]
    assert "https://challenges.cloudflare.com" in csp and "frame-src" in csp

    _live(monkeypatch, turnstile=False)
    csp = (await client.get("/mobed")).headers["content-security-policy"]
    assert "challenges.cloudflare.com" not in csp


async def test_requests_from_one_address_are_limited_in_the_database(db, seeded):
    s = _settings(otp_mode="live", whatsapp_access_token="tok", otp_per_address_hourly=3)
    for i in range(3):
        await otp.request_code(db, s, f"+91994440130{i}", "203.0.113.7", None, now=NOW + timedelta(minutes=i))
    # A restart clears every in-memory counter; this one is in the database.
    rate_limit._hits.clear()
    with pytest.raises(otp.OtpError) as refused:
        await otp.request_code(db, s, "+919944401309", "203.0.113.7", None, now=NOW + timedelta(minutes=5))
    assert refused.value.status == 429
    # Another address is unaffected, and so is this one an hour later.
    await otp.request_code(db, s, "+919944401309", "198.51.100.4", None, now=NOW + timedelta(minutes=6))
    await otp.request_code(db, s, "+919944401308", "203.0.113.7", None, now=NOW + timedelta(hours=1, minutes=5))


async def test_the_check_is_verified_with_cloudflare():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        ok = b"response=good" in request.content
        return httpx.Response(200, json={"success": ok})

    s = _settings(turnstile_secret_key="secret-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await bot_check.verify(s, "good", "203.0.113.7", client=c) is True
        assert await bot_check.verify(s, "bad", "203.0.113.7", client=c) is False
        assert await bot_check.verify(s, "", "203.0.113.7", client=c) is False      # never asked
    assert len(seen) == 2
    assert str(seen[0].url) == bot_check.SITEVERIFY_URL
    assert b"secret=secret-key" in seen[0].content and b"remoteip=203.0.113.7" in seen[0].content
