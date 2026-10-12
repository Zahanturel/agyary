"""Free text that ends up inside a WhatsApp message we pay to send.

The reminder template has fixed words and blanks, and three of the blanks are
filled with text a mobed typed: the fire temple's name, the service names and
the departed's name. Anyone who can sign up could otherwise use those blanks to
put a link, a handle or a phone number in front of a stranger under our name
(docs/DECISIONS.md D1). So that text is checked where it is typed, and again
just before a reminder is planned (for anything saved before these rules).

The rules are deliberately narrow - real names pass: bounded length, no links,
no @-handles, and no long runs of digits (a phone number, a payment reference).
"""

from __future__ import annotations

import re

TEMPLE_MAX = 80
SERVICE_MAX = 40
DEPARTED_MAX = 80

_LINK = re.compile(
    r"://|\bwww\.|\b[a-z0-9-]+\.(?:com|net|org|in|co|io|me|ly|info|biz|xyz|app|site|online|shop|top|"
    r"live|link|ai|gg|to|uk|us|ru|cn|tk|ml|ga|cf|gq|page|dev|club|store|website|space|click)\b",
    re.IGNORECASE,
)
_HANDLE = re.compile(r"@\w")
# Digits that run on through spaces, dashes, dots, brackets or a plus sign.
_JOINED_DIGITS = re.compile(r"(?<=\d)[\s().+-]+(?=\d)")
_DIGIT_RUN = re.compile(r"\d{6,}")


def problem(text: str, *, max_len: int) -> str | None:
    """Why ``text`` cannot go into a paid message, or None if it can."""
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) > max_len:
        return f"is too long (at most {max_len} characters)"
    if _LINK.search(cleaned):
        return "cannot contain a link or web address"
    if _HANDLE.search(cleaned):
        return "cannot contain an @-handle"
    if _DIGIT_RUN.search(_JOINED_DIGITS.sub("", cleaned)):
        return "cannot contain a phone number or a long number"
    return None


def check(text: str, what: str, *, max_len: int) -> str:
    """``text`` with its spacing tidied, or ValueError saying what is wrong."""
    why = problem(text, max_len=max_len)
    if why:
        raise ValueError(f"The {what} {why}.")
    return " ".join(str(text or "").split())
