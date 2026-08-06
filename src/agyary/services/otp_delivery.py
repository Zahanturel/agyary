"""Login-OTP delivery over the WhatsApp Cloud API.

Deliberately NOT routed through the durable outbox in
``messaging/send_worker.py``, for two reasons:

  * that outbox is keyed on ``agyary_id`` (NOT NULL) and sends from the
    agyari's own ``wa_phone_number_id``. A mobed logging in for the first
    time has no agyari yet - being able to search for one is what they log
    in *to do* - so there is no tenant number to send from;
  * an OTP is only useful inside its own short expiry window. The outbox's
    value is eventual delivery with backoff (retry in 5s, 20s, 60s), which
    for a code that expires in five minutes is closer to a liability than a
    feature: it would deliver a dead code minutes after the user gave up
    and requested a new one.

So this sends inline and reports success or failure to the caller, who
turns a failure into an error the user can act on ("we couldn't send the
code, try again") instead of a silent nothing.
"""

from __future__ import annotations

import logging

import httpx

from agyary.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v20.0"
SEND_TIMEOUT_SECONDS = 15.0


class OtpDeliveryError(Exception):
    """The code could not be handed to WhatsApp - safe to show the caller."""


def _configured(settings: Settings) -> bool:
    return bool(settings.whatsapp_api_token and settings.whatsapp_otp_phone_number_id)


def message_text(code: str, ttl_seconds: int) -> str:
    minutes = max(1, round(ttl_seconds / 60))
    return (
        f"{code} is your Agyary sign-in code. "
        f"It expires in {minutes} minute{'s' if minutes != 1 else ''}.\n\n"
        "If you didn't try to sign in, you can ignore this message - "
        "nobody can use this code but you."
    )


async def send_login_otp(phone: str, code: str, client: httpx.AsyncClient | None = None) -> None:
    """Deliver ``code`` to ``phone``. Raises OtpDeliveryError on failure.

    With no WhatsApp credentials configured this logs the code instead of
    sending it, but ONLY in debug mode - that is the local-development
    path, and it is also what the test suite relies on. Outside debug the
    same situation raises: an unconfigured production deployment must fail
    visibly at the first login attempt rather than quietly accept OTP
    requests that can never arrive, which would lock every mobed out with
    no indication of why.
    """
    settings = get_settings()
    if not _configured(settings):
        if settings.app_debug:
            logger.warning("WhatsApp OTP not configured - login code for %s is %s", phone, code)
            return
        raise OtpDeliveryError(
            "WhatsApp sending is not configured on this server, so the sign-in "
            "code could not be sent. Please contact the administrator."
        )

    url = (
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/"
        f"{settings.whatsapp_otp_phone_number_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": phone.lstrip("+"),
        "type": "text",
        "text": {"body": message_text(code, settings.otp_ttl_seconds)},
    }
    headers = {"Authorization": f"Bearer {settings.whatsapp_api_token}"}

    owns_client = client is None
    client = client or httpx.AsyncClient()
    try:
        response = await client.post(url, json=payload, headers=headers, timeout=SEND_TIMEOUT_SECONDS)
        response.raise_for_status()
    except Exception as exc:
        # The upstream error text can carry Meta's own diagnostics; log it,
        # but hand the caller something generic - a login screen is a fine
        # place to leak nothing at all.
        logger.error("Failed to send login OTP to %s", phone, exc_info=True)
        raise OtpDeliveryError(
            "Couldn't send the sign-in code just now. Please try again in a moment."
        ) from exc
    finally:
        if owns_client:
            await client.aclose()
