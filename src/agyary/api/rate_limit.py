"""Minimal in-process rate limiter for unauthenticated endpoints.

No Redis, no external state - the app runs as a single uvicorn process
(Dockerfile has no --workers flag), so an in-memory counter is consistent
and sufficient at alpha scale.

Guards the OTP login endpoints (services/mobed_auth.py). The OTP's own
attempt cap protects a single issued code; this protects against the
volume attacks that sit outside any one code - scripting through phone
numbers to see which ones exist, churning fresh codes to widen the guess
space, or using our sender to flood one person's WhatsApp.
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
    enforce_key(_client_key(request, scope), max_requests=max_requests, window_seconds=window_seconds)


def enforce_key(key: str, *, max_requests: int, window_seconds: int) -> None:
    """Rate-limit on an arbitrary key rather than the caller's IP.

    Used for per-phone OTP limits: an IP limit alone stops one caller
    walking a list of numbers, but not a distributed handful of callers all
    aimed at the same person's WhatsApp. The subject being protected there
    is the phone, so the phone has to be the key.
    """
    now = time.monotonic()
    cutoff = now - window_seconds
    hits = [t for t in _hits[key] if t > cutoff]
    if len(hits) >= max_requests:
        raise HTTPException(status_code=429, detail="Too many attempts, please wait and try again")
    hits.append(now)
    _hits[key] = hits
