"""Phone number validation for the mobed PWA API.

Behdins (and some mobeds) can be from any country - the fire-temple list
itself spans India, Iran, Pakistan, Canada, the UK, Hong Kong. The frontend
shows an editable country-code box (defaulting to 91/India, since ~99% of
mobeds are Indian) next to a local-number box, composing a general E.164
string (see static/mobed/js/util.js's phoneField/readPhone helpers). This module is the
single place that resulting shape is validated server-side, reused as a
Pydantic field type rather than a regex repeated per model.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator

# E.164: '+' then 8-15 digits total (a 1-3 digit country code plus a
# national number), first digit after '+' non-zero.
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")

# Country calling codes worth recognising, longest first so "+971" is not read
# as "+9". Only used to spot a trunk "0" typed after the code, which is how
# most people write a local number ("098765 43210") and which E.164 forbids.
# Kept in step with KNOWN_COUNTRY_CODES in static/mobed/js/util.js.
_KNOWN_COUNTRY_CODES = (
    "971", "852", "966", "968", "965", "974",
    "91", "98", "92", "94", "44", "61", "64", "65", "86", "81", "82",
    "49", "33", "39", "34", "27", "20", "60", "66", "63",
    "1", "7",
)


def normalize_phone(value: str) -> str:
    """The one stored shape of a phone number.

    A phone number IS a behdin's identity (customers.phone is unique), so two
    spellings of one number are two people to the database. This removes the
    spellings that differ only in how somebody typed them: spaces, dashes and
    brackets, and a trunk 0 after the country code. It does not validate -
    that is _validate_phone's job, run on the result.
    """
    cleaned = re.sub(r"[\s\-().]", "", value.strip())
    if not cleaned.startswith("+"):
        return cleaned
    digits = cleaned[1:]
    for code in _KNOWN_COUNTRY_CODES:
        if digits.startswith(code):
            national = digits[len(code):].lstrip("0")
            return "+" + code + national
    return cleaned


def _validate_phone(value: str) -> str:
    value = normalize_phone(value)
    if not _E164_RE.match(value):
        raise ValueError("Phone number must be in international format, e.g. +919876543210")
    return value


def _validate_optional_phone(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_phone(value)


Phone = Annotated[str, AfterValidator(_validate_phone)]
OptionalPhone = Annotated[str | None, AfterValidator(_validate_optional_phone)]
