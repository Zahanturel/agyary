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


def _validate_phone(value: str) -> str:
    if not _E164_RE.match(value):
        raise ValueError("Phone number must be in international format, e.g. +919876543210")
    return value


def _validate_optional_phone(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_phone(value)


Phone = Annotated[str, AfterValidator(_validate_phone)]
OptionalPhone = Annotated[str | None, AfterValidator(_validate_optional_phone)]
