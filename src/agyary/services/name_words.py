"""The first name of a person, for "Sahebji <first name>," (D11 and the owner's
24 Nov 2026 rule: a mobed AND a behdin are greeted by their first name only, never
first and middle name; the full name stays wherever it is shown as data)."""

from __future__ import annotations

# Titles typed before a name, left out of "Sahebji <first name>": the same list as
# util.js NAME_PREFIXES (compared without dots, in any case): Parsi titles only
# (owner's word review, 23 Nov 2026), so no Shri or Smt, and "Dastur" is a surname
# ("Dasturji" is the title).
NAME_PREFIXES = frozenset({"er", "ervad", "mobed", "mobedji", "dasturji", "dr", "behdin",
                           "osta", "osti", "khud", "khurd", "mr", "mrs", "ms"})


def first_name(full: str | None) -> str:
    """The first name, as util.js firstName: a title typed before it ("Er.",
    "Ervad", "Dasturji", ...) is skipped, and the whole name is used when
    nothing else is left."""
    words = str(full or "").split()
    i = 0
    while i < len(words) and words[i].replace(".", "").lower() in NAME_PREFIXES:
        i += 1
    return words[i] if i < len(words) else " ".join(words)
