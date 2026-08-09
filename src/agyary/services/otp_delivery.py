"""Login-OTP delivery over the WhatsApp Cloud API.

Sent as a **template**, not free text. WhatsApp only permits
business-initiated messages through a pre-approved template: a mobed
signing in has not messaged us first, so no 24-hour service window is open
and a plain text send is rejected outright. The template is an
Authentication-category one, whose body WhatsApp itself fixes - we supply
only the code.

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

Cost note: every send is a billable authentication conversation. The rate
limits on the request endpoint (api/rate_limit.py) are therefore a spend
control as well as an abuse control - see 11-mobed-app-scope.md §8.1b.
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
    return bool(
        settings.whatsapp_api_token
        and settings.whatsapp_otp_phone_number_id
        and settings.whatsapp_otp_template_name
    )


def build_template_payload(
    to: str,
    template_name: str,
    language: str,
    *,
    body_parameters: list[str] | None = None,
    copy_code: str | None = None,
) -> dict:
    """A Cloud API template-send payload.

    Shared with the smoke-test script (scripts/whatsapp_smoke_test.py), which
    sends the sample ``hello_world`` template - that has no variables, so it
    exercises credentials, endpoint and envelope without needing our own
    template to exist yet.

    ``copy_code`` fills the Authentication template's copy-code button. Such
    templates want the code twice: once in the body, once in the button.
    """
    components: list[dict] = []
    if body_parameters:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in body_parameters],
        })
    if copy_code is not None:
        components.append({
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [{"type": "text", "text": copy_code}],
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "template",
        "template": {"name": template_name, "language": {"code": language}},
    }
    if components:
        payload["template"]["components"] = components
    return payload


async def post_to_graph(payload: dict, client: httpx.AsyncClient | None = None) -> dict:
    """POST a prepared payload to the configured sending number.

    Raises OtpDeliveryError with a message safe to show a user; the
    upstream diagnostics go to the log, since a sign-in screen is a fine
    place to leak nothing at all.
    """
    settings = get_settings()
    url = (
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/"
        f"{settings.whatsapp_otp_phone_number_id}/messages"
    )
    headers = {"Authorization": f"Bearer {settings.whatsapp_api_token}"}

    owns_client = client is None
    client = client or httpx.AsyncClient()
    try:
        response = await client.post(url, json=payload, headers=headers, timeout=SEND_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "WhatsApp rejected a send: %s %s", exc.response.status_code, exc.response.text
        )
        raise OtpDeliveryError(
            "Couldn't send the sign-in code just now. Please try again in a moment."
        ) from exc
    except Exception as exc:
        logger.error("Failed to reach WhatsApp", exc_info=True)
        raise OtpDeliveryError(
            "Couldn't send the sign-in code just now. Please try again in a moment."
        ) from exc
    finally:
        if owns_client:
            await client.aclose()


async def send_login_otp(phone: str, code: str, client: httpx.AsyncClient | None = None) -> None:
    """Deliver ``code`` to ``phone``. Raises OtpDeliveryError on failure.

    With WhatsApp unconfigured this logs the code instead of sending it, but
    ONLY in debug mode - that is the local-development path, and what the
    test suite relies on. Outside debug the same situation raises: an
    unconfigured production deployment must fail visibly at the first login
    attempt rather than quietly accept OTP requests that can never arrive,
    which would lock every mobed out with no indication of why.
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

    payload = build_template_payload(
        phone,
        settings.whatsapp_otp_template_name,
        settings.whatsapp_otp_template_language,
        body_parameters=[code],
        # Only send a button component if the template actually has one -
        # WhatsApp rejects components a template doesn't define.
        copy_code=code if settings.whatsapp_otp_template_has_copy_code else None,
    )
    await post_to_graph(payload, client)
