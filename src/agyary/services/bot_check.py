"""The bot check in front of sign-in codes: Cloudflare Turnstile.

Asking for a code makes us send a paid WhatsApp message to whatever number the
caller typed, which is exactly what a script would abuse - to spend our money,
or to flood a stranger. docs/DECISIONS.md (D1, D3) makes a bot check a condition
of sign-in by code at all: every request must carry a Turnstile token that
Cloudflare confirms, and until a site key and secret are configured codes are
not offered.

The browser shows Cloudflare's widget (usually without asking anything) and
sends the token it gets with the request; this module asks Cloudflare whether
that token is genuine, fresh and unused.
"""

from __future__ import annotations

import logging

import httpx

from agyary.core.config import Settings

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
CHALLENGE_ORIGIN = "https://challenges.cloudflare.com"


def configured(settings: Settings) -> bool:
    return bool(settings.turnstile_site_key.strip() and settings.turnstile_secret_key.strip())


async def verify(settings: Settings, token: str | None, ip: str, client: httpx.AsyncClient | None = None) -> bool:
    """Whether Cloudflare confirms ``token``. False for no token, a refusal, or
    Cloudflare being unreachable - a check that cannot be made is not passed."""
    if not token or not settings.turnstile_secret_key.strip():
        return False
    own = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        resp = await client.post(
            SITEVERIFY_URL,
            data={"secret": settings.turnstile_secret_key, "response": token, "remoteip": ip},
        )
        answer = resp.json() if resp.status_code == 200 else {}
        expected = settings.turnstile_hostname.strip()
        return answer.get("success") is True and (not expected or answer.get("hostname") == expected)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Bot check could not be verified: %s", exc.__class__.__name__)
        return False
    finally:
        if own:
            await client.aclose()
