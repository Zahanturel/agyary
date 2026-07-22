"""Regex-based ceremony name parser (v2: regex, NOT an LLM).

Input format - one name per line, or comma-separated (the v2 spec writes
pairs as "Er. Zahan, Er. Meherzad")::

    Ervad Meherzad
    Osti Farzin, Khud Zahan
    Er. Kaikhushru (D)

- Titles: er / er. / ervad, behdin, osta, osti, khud (case-insensitive).
  A missing title defaults to behdin.
- ``(D)`` or ``(departed)`` marks a departed name.
"""

from __future__ import annotations

import re

from agyary.messaging.types import ParsedName

MAX_NAME_LENGTH = 200

_TITLE_ALIASES = {
    "er": "ervad",
    "er.": "ervad",
    "ervad": "ervad",
    "behdin": "behdin",
    "osta": "osta",
    "osti": "osti",
    "khud": "khud",
}

_LINE_RE = re.compile(
    r"""^\s*
    (?:(?P<title>er\.|er|ervad|behdin|osta|osti|khud)\s+)?   # optional title
    (?P<name>.+?)                                            # the name itself
    (?:\s*\(\s*(?P<departed>d|departed)\s*\))?               # optional (D)
    \s*$""",
    re.IGNORECASE | re.VERBOSE,
)


# A lone departed marker is not a name ("Behdin (D)" leaves only "(D)").
# Parens are required: a bare initial like "Er. D" is a legitimate name.
_BARE_MARKER_RE = re.compile(r"^\(\s*(d|departed)\s*\)$", re.IGNORECASE)

# Split on commas, but not inside parentheses ("Roshan (nee Mehta, Surat)").
_COMMA_SPLIT_RE = re.compile(r",(?![^()]*\))")

# Recognized title keywords, used to find the second name in a comma-less
# pair line ("Ervad Zahan Ervad Meherzad" -> split before the 2nd "Ervad").
_TITLE_KEYWORD_RE = re.compile(
    r"\b(?:er\.|er|ervad|behdin|osta|osti|khud)\b", re.IGNORECASE
)


def parse_name_line(line: str) -> ParsedName | None:
    """Parse a single line; returns None for blank/unusable lines."""
    match = _LINE_RE.match(line)
    if not match:
        return None
    raw_name = match.group("name").strip(" \t,.-")
    if not raw_name or _BARE_MARKER_RE.match(raw_name):
        return None
    title_token = (match.group("title") or "behdin").lower()
    return ParsedName(
        title=_TITLE_ALIASES[title_token],
        name=raw_name[:MAX_NAME_LENGTH],
        departed=match.group("departed") is not None,
    )


def parse_names(text: str) -> list[ParsedName]:
    """Parse a whole message: names split on newlines and top-level commas."""
    names = []
    for line in text.splitlines():
        for segment in _COMMA_SPLIT_RE.split(line):
            parsed = parse_name_line(segment)
            if parsed:
                names.append(parsed)
    return names


def parse_pair_line(line: str) -> tuple[ParsedName, ParsedName] | None:
    """Resolve ONE line to exactly two titled names, or None if it can't.

    One line = one pair (not "consecutive lines pair up"). Two ways to
    resolve a line:
      - a top-level comma splits it into the two names: "Er. Zahan, Er.
        Meherzad".
      - with no comma, the line is split just before the 2nd occurrence of
        a recognized title keyword: "Ervad Zahan Ervad Meherzad" or "Behdin
        Roshan Behdin Dinshaw".
    Anything else (not exactly two comma segments, or fewer than two title
    keywords with no comma, or either half not parsing as a name) is
    unresolvable and returns None - callers must not guess.
    """
    segments = [seg for seg in _COMMA_SPLIT_RE.split(line) if seg.strip()]
    if len(segments) == 2:
        first, second = segments
    elif len(segments) == 1:
        matches = list(_TITLE_KEYWORD_RE.finditer(segments[0]))
        if len(matches) < 2:
            return None
        split_at = matches[1].start()
        first, second = segments[0][:split_at], segments[0][split_at:]
    else:
        return None

    name1 = parse_name_line(first)
    name2 = parse_name_line(second)
    if name1 is None or name2 is None:
        return None
    return name1, name2
