"""Minimal in-process rate limiter for unauthenticated endpoints.

No Redis, no external state - the app runs as a single uvicorn process
(Dockerfile has no --workers flag), so an in-memory counter is consistent
and sufficient at alpha scale.

Guards the unauthenticated sign-in endpoints (routes/mobed.py's
/auth/wa/*). Sign-in asks the caller for no phone number at all, so there
is no number list to walk here - what is left to cap is volume: minting
attempts faster than a human could send them, and polling. The poll limit
is deliberately loose (the browser polls every two seconds by design) and
the start limit tight.
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

    An IP limit stops one caller doing something many times; keying on
    the subject instead stops many callers doing it to one subject. Use
    this whenever the thing being protected is not the caller.
    """
    now = time.monotonic()
    cutoff = now - window_seconds
    hits = [t for t in _hits[key] if t > cutoff]
    if len(hits) >= max_requests:
        raise HTTPException(status_code=429, detail="Too many attempts, please wait and try again")
    hits.append(now)
    _hits[key] = hits
