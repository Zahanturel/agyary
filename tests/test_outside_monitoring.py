"""Something outside the app can tell when it, or its evening loop, has stopped (OP-2).

The app's own alerts only reach an admin who opens it. So: each pass of the
evening loop pings a heartbeat address (a Healthchecks.io check, HEARTBEAT_URL)
- "/fail" when the pass went wrong - and silence there is the alarm. And
/health?deep=1, for an uptime monitor, answers 503 unless the database answers
and the loop has run in the last few minutes. Docker keeps logs bounded.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from agyary.core import config
from agyary.services import reminder_worker

ROOT = Path(__file__).resolve().parent.parent


async def test_each_pass_pings_the_heartbeat_and_a_failed_one_says_so(monkeypatch):
    monkeypatch.setenv("HEARTBEAT_URL", "https://hc-ping.example/abc")
    config.get_settings.cache_clear()
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        await reminder_worker.ping_heartbeat(ok=True, client=c)
        await reminder_worker.ping_heartbeat(ok=False, client=c)
    assert seen == ["https://hc-ping.example/abc", "https://hc-ping.example/abc/fail"]


async def test_no_heartbeat_address_means_no_ping(monkeypatch):
    monkeypatch.setenv("HEARTBEAT_URL", "")
    config.get_settings.cache_clear()
    seen = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200))) as c:
        await reminder_worker.ping_heartbeat(ok=True, client=c)
    assert seen == []


async def test_deep_health_needs_the_database_and_a_recent_pass(client, db, monkeypatch):
    monkeypatch.setattr(reminder_worker, "last_pass_at", None)
    r = await client.get("/health?deep=1")
    assert r.status_code == 503 and r.json()["worker"] != "ok"

    monkeypatch.setattr(reminder_worker, "last_pass_at", datetime.now(timezone.utc) - timedelta(minutes=10))
    assert (await client.get("/health?deep=1")).status_code == 503

    monkeypatch.setattr(reminder_worker, "last_pass_at", datetime.now(timezone.utc))
    r = await client.get("/health?deep=1")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "ok", "worker": "ok"}

    # The plain check (the container's own) is unchanged: the web server alone.
    assert (await client.get("/health")).json() == {"status": "ok"}


def test_every_service_keeps_its_logs_bounded():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    services = re.findall(r"(?m)^  (\w+):\n", compose.split("\nvolumes:")[0])
    assert {"db", "app", "cloudflared"} <= set(services)
    assert compose.count("max-size:") >= 3 and compose.count("max-file:") >= 3
