"""The admin screen, the kill switch, and the browser security headers.

Access first: this page shows what sending costs and can stop it, so a mobed
who is not an admin must get nothing - not a refusal that confirms it exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agyary.core import config
from agyary.services import guardrails, reminder_sender
from tests.test_mobed_api import NEW_MOBED_PHONE, _member_headers
from tests.test_reminder_sender import _planned, _rows, _scenario, _settings

STATIC = Path(__file__).parent.parent / "src" / "agyary" / "api" / "static"


@pytest.fixture
def as_admin(monkeypatch):
    """The test mobed is an admin."""
    monkeypatch.setenv("ADMIN_PHONES", NEW_MOBED_PHONE)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


# --- Who can see it ---------------------------------------------------------

async def test_a_mobed_who_is_not_an_admin_gets_a_404_not_a_refusal(client, seeded):
    headers = await _member_headers(client, seeded)
    assert (await client.get("/api/mobed/admin/overview", headers=headers)).status_code == 404
    r = await client.post("/api/mobed/admin/reminders/pause", json={"paused": True}, headers=headers)
    assert r.status_code == 404


async def test_nobody_is_an_admin_unless_listed(client, seeded, monkeypatch):
    monkeypatch.setenv("ADMIN_PHONES", "")
    config.get_settings.cache_clear()
    try:
        headers = await _member_headers(client, seeded)
        assert (await client.get("/api/mobed/admin/overview", headers=headers)).status_code == 404
    finally:
        config.get_settings.cache_clear()


async def test_without_a_session_there_is_no_admin_screen(client, seeded):
    assert (await client.get("/api/mobed/admin/overview")).status_code in (401, 403)
    assert (await client.post("/api/mobed/admin/reminders/pause", json={"paused": True})).status_code in (401, 403)


async def test_the_app_is_told_who_is_an_admin_only_to_show_the_menu_entry(client, seeded, as_admin):
    headers = await _member_headers(client, seeded)
    assert (await client.get("/api/mobed/auth/me", headers=headers)).json()["is_admin"] is True
    other = await _member_headers(client, seeded, name="Other", phone="+919911100077")
    assert (await client.get("/api/mobed/auth/me", headers=other)).json()["is_admin"] is False


# --- What it shows ----------------------------------------------------------

async def test_the_overview_shows_the_ceilings_and_what_has_been_used(client, db, seeded, as_admin):
    headers = await _member_headers(client, seeded)
    body = (await client.get("/api/mobed/admin/overview", headers=headers)).json()
    r = body["reminders"]
    assert r["mode"] == "off" and r["paused"] is None and r["today"] == 0 and r["month"] == 0
    assert r["caps"] == {"daily": 150, "monthly": 2000, "per_mobed": 40, "per_agyary": 100}
    assert r["estimated_month_cost_inr"] == 0 and body["otp"]["mode"] == "off"
    assert body["recent_failures"] == []


async def test_it_counts_reminders_and_estimates_the_cost(client, db, seeded, as_admin, monkeypatch):
    aid, cid, headers, later, opening, now = await _planned(client, db, seeded)
    # The loop's clock and the app's are different in a test; count from the loop's.
    from datetime import datetime, timezone

    monkeypatch.setattr(
        "agyary.api.routes.admin.datetime", type("D", (), {"now": staticmethod(lambda tz=None: now.astimezone(timezone.utc))})
    )
    body = (await client.get("/api/mobed/admin/overview", headers=headers)).json()["reminders"]
    assert body["today"] == 1 and body["month"] == 1
    assert body["estimated_month_cost_inr"] == 0.14 and datetime  # one message at the configured estimate


async def test_failures_are_listed_with_the_number_masked(client, db, seeded, as_admin):
    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    await reminder_sender.plan_tomorrow(db, now, _settings(reminders_daily_cap=0))
    await db.commit()
    [row] = await _rows(db)
    assert row.status == "failed"
    failures = (await client.get("/api/mobed/admin/overview", headers=headers)).json()["recent_failures"]
    [f] = failures
    assert "daily limit" in f["reason"]
    assert f["to"] == "+91…701" and "9944400701" not in f["to"]


# --- The kill switch --------------------------------------------------------

async def test_an_admin_can_pause_and_resume_and_it_is_remembered(client, db, seeded, as_admin):
    headers = await _member_headers(client, seeded)
    r = await client.post("/api/mobed/admin/reminders/pause",
                          json={"paused": True, "reason": "Checking the bill"}, headers=headers)
    assert r.json() == {"paused": "Checking the bill"}
    db.expire_all()
    assert await guardrails.paused_reason(db) == "Checking the bill"
    overview = (await client.get("/api/mobed/admin/overview", headers=headers)).json()
    assert overview["reminders"]["paused"] == "Checking the bill"

    r = await client.post("/api/mobed/admin/reminders/pause", json={"paused": False}, headers=headers)
    assert r.json() == {"paused": None}
    db.expire_all()
    assert await guardrails.paused_reason(db) is None


async def test_pausing_without_a_reason_says_who_did_it(client, db, seeded, as_admin):
    headers = await _member_headers(client, seeded)
    r = await client.post("/api/mobed/admin/reminders/pause", json={"paused": True}, headers=headers)
    assert r.json()["paused"].startswith("Paused by ")


async def test_a_paused_system_really_sends_nothing(client, db, seeded, as_admin):
    from tests.test_reminder_sender import FakeMeta

    aid, cid, headers, later, opening, now = await _planned(client, db, seeded)
    await client.post("/api/mobed/admin/reminders/pause", json={"paused": True}, headers=headers)
    meta = FakeMeta()
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now, _settings())
    assert meta.calls == [] and report.sent == 0


async def test_the_pause_switch_cannot_be_hammered(client, db, seeded, as_admin):
    headers = await _member_headers(client, seeded)
    codes = [
        (await client.post("/api/mobed/admin/reminders/pause", json={"paused": False}, headers=headers)).status_code
        for _ in range(12)
    ]
    assert 429 in codes


# --- Browser security headers -----------------------------------------------

async def test_every_response_carries_the_security_headers(client, seeded):
    r = await client.get("/mobed")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    csp = h["content-security-policy"]
    for part in ("default-src 'self'", "script-src 'self'", "frame-ancestors 'none'", "object-src 'none'",
                 "base-uri 'none'", "connect-src 'self'"):
        assert part in csp
    assert "unsafe-eval" not in csp and "script-src 'self' 'unsafe-inline'" not in csp   # scripts stay strict
    assert "camera=()" in h["permissions-policy"] and "clipboard" not in h["permissions-policy"]


async def test_the_api_gets_them_too(client, seeded):
    assert "content-security-policy" in (await client.get("/health")).headers


async def test_https_only_is_demanded_in_production_but_not_on_a_laptop(client, seeded, monkeypatch):
    import agyary.api.main as main

    monkeypatch.setattr(main.settings, "app_debug", True)
    assert "strict-transport-security" not in (await client.get("/health")).headers
    monkeypatch.setattr(main.settings, "app_debug", False)
    assert (await client.get("/health")).headers["strict-transport-security"].startswith("max-age=")


def test_the_policy_is_safe_because_the_app_really_has_no_inline_script_or_third_parties():
    """The strict policy is only harmless while these stay true. If one stops
    being true, this fails here instead of as a blank screen on a phone."""
    pages = [*STATIC.rglob("*.html")]
    assert pages, "expected the PWA pages"
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for tag in re.findall(r"<script\b[^>]*>", text):
            assert "src=" in tag, f"{page.name}: an inline <script> would be blocked"
        assert not re.search(r"\son(click|change|input|submit|load|error)\s*=", text), f"{page.name}: inline handler"
    for js in STATIC.rglob("*.js"):
        text = js.read_text(encoding="utf-8")
        assert not re.search(r"\beval\(|new Function\(", text), f"{js.name}: eval needs unsafe-eval"
        assert not re.search(r"\son(click|change|input|submit|load|error)=\"", text), f"{js.name}: inline handler"
        # Fetches and imports must stay on our own origin (connect-src 'self').
        for url in re.findall(r"""(?:fetch|import)\(\s*["'](https?://[^"']+)""", text):
            raise AssertionError(f"{js.name}: reaches {url}, which connect-src would block")


# --- The webhook ------------------------------------------------------------

async def test_an_oversized_webhook_body_is_refused_before_anything_is_done_with_it(client, seeded):
    r = await client.post("/webhooks/whatsapp", content=b"x" * 1_100_000,
                          headers={"content-type": "application/json"})
    assert r.status_code == 413

