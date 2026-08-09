"""Send one WhatsApp template and report exactly what happened.

Why this exists: a test WhatsApp Business Account cannot create templates,
so our own Authentication template can't be approved until a real phone
number is registered. But the sample ``hello_world`` template is already
approved on the test account, and sending it exercises everything
underneath our own template - the access token, the phone number ID, the
Graph endpoint, and the template-message envelope. That is the majority of
what can go wrong, and it can be checked today, for free.

    uv run python -m agyary.scripts.whatsapp_smoke_test +919800000003

The recipient must already be registered as a test recipient in the Meta
dashboard, or WhatsApp will refuse it.

Once our own template is approved, point it at that instead:

    uv run python -m agyary.scripts.whatsapp_smoke_test +91... \\
        --template mobed_diary_login_code --language en --code 123456

Failures are printed in full, unlike the deliberately vague message the
sign-in screen shows users - here the diagnostics are the point.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx

from agyary.core.config import get_settings
from agyary.services import otp_delivery


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send one WhatsApp template as a smoke test.")
    parser.add_argument("to", help="Recipient in E.164, e.g. +919800000003")
    parser.add_argument(
        "--template",
        default="hello_world",
        help="Template name (default: hello_world, the sample every test account has)",
    )
    parser.add_argument(
        "--language",
        default="en_US",
        help="Template language code - hello_world is en_US (default: en_US)",
    )
    parser.add_argument(
        "--code",
        default=None,
        help="Fill the template's body parameter with this, e.g. a 6-digit code. "
             "Omit for templates with no variables, such as hello_world.",
    )
    parser.add_argument(
        "--copy-code",
        action="store_true",
        help="Also send the code as a copy-code button parameter (Authentication "
             "templates that have that button require it).",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()

    missing = [
        name
        for name, value in (
            ("WHATSAPP_API_TOKEN", settings.whatsapp_api_token),
            ("WHATSAPP_OTP_PHONE_NUMBER_ID", settings.whatsapp_otp_phone_number_id),
        )
        if not value
    ]
    if missing:
        print(f"Not configured - set these in .env first: {', '.join(missing)}")
        return 2

    payload = otp_delivery.build_template_payload(
        args.to,
        args.template,
        args.language,
        body_parameters=[args.code] if args.code else None,
        copy_code=args.code if (args.copy_code and args.code) else None,
    )
    print("Sending from phone_number_id", settings.whatsapp_otp_phone_number_id)
    print(json.dumps(payload, indent=2))

    async with httpx.AsyncClient() as client:
        try:
            result = await otp_delivery.post_to_graph(payload, client)
        except otp_delivery.OtpDeliveryError:
            # post_to_graph logs the upstream body; that log line is the
            # useful part, so point at it rather than repeating a vague
            # user-facing string here.
            print("\nFAILED - see the logged WhatsApp response above for the reason.")
            return 1

    print("\nSent:", json.dumps(result, indent=2))
    print("\nCheck the recipient's phone. If nothing arrives despite this success,")
    print("the number is most likely not registered as a test recipient.")
    return 0


if __name__ == "__main__":
    logging_level = "INFO"
    import logging

    logging.basicConfig(level=logging_level, format="%(levelname)s %(message)s")
    sys.exit(asyncio.run(main()))
