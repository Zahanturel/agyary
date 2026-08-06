"""Minimal in-process rate limiter for unauthenticated endpoints.

No Redis, no external state - the app runs as a single uvicorn process
(Dockerfile has no --workers flag), so an in-memory counter is consistent
and sufficient at alpha scale. This exists specifically because
/auth/login has no OTP/verification (services/mobed_auth.py's documented
accepted risk): without this, an attacker could script through phone
numbers as fast as the network allows. This doesn't change who can log in,
only how fast they can try.
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

_hits: dict[str, list[float]] = defaultdict(list)


def _client_key(request: Request, scope: str) -> str:
    # Cloudflare Tunnel/any reverse proxy sets this; falls back to the
    # direct peer address for local dev/tests.
    ip = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    if ip:
        ip = ip.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    return f"{scope}:{ip}"


def enforce(request: Request, scope: str, *, max_requests: int, window_seconds: int) -> None:
    key = _client_key(request, scope)
    now = time.monotonic()
    cutoff = now - window_seconds
    hits = [t for t in _hits[key] if t > cutoff]
    if len(hits) >= max_requests:
        raise HTTPException(status_code=429, detail="Too many attempts, please wait and try again")
    hits.append(now)
    _hits[key] = hits
