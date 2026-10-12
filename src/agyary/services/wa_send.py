"""A plain WhatsApp text message, inside the window a person opened.

When someone messages us, WhatsApp lets us answer with ordinary text (no
approved template) for 24 hours. The one thing this app answers is a sign-in:
the confirmation number that proves the screen that started it belongs to the
person whose phone sent the code (AU-1). Since 1 Oct 2026 such a reply costs
about as much as a utility message.

It is deliberately NOT stopped by the reminders pause: that switch exists to
stop messages to families, and an admin locked out of signing in could not lift
it. It needs the same token and number id as everything else that sends.
"""

from __future__ import annotations

import logging

import httpx

from agyary.core.config import Settings

logger = logging.getLogger(__name__)


def to_number(phone: str) -> str:
    """Always with its "+": without one, Meta prefixes our own country code (RM-8a)."""
    return phone if phone.startswith("+") else f"+{phone}"


def can_send(settings: Settings) -> bool:
    return bool(settings.whatsapp_access_token and settings.whatsapp_phone_number_id)


def _payload(phone: str, body: str) -> dict:
    return {
        "messaging_product": "whatsapp",
        "to": to_number(phone),
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }


async def send_text(settings: Settings, phone: str, body: str, client: httpx.AsyncClient | None = None) -> bool:
    """Send ``body`` to ``phone``. True if Meta accepted it; False otherwise
    (including when nothing is configured to send with) - never raises."""
    if not can_send(settings):
        return False
    url = f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{settings.whatsapp_phone_number_id}/messages"
    own = client is None
    client = client or httpx.AsyncClient(timeout=8)
    try:
        resp = await client.post(
            url, json=_payload(phone, body), headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"}
        )
        if resp.status_code != 200:
            logger.warning("A sign-in confirmation was not accepted (HTTP %s)", resp.status_code)
        return resp.status_code == 200
    except httpx.HTTPError as exc:
        logger.warning("A sign-in confirmation could not be sent: %s", exc.__class__.__name__)
        return False
    finally:
        if own:
            await client.aclose()
