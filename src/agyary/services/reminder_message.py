"""The words of a reminder, in one place.

The same message reaches a family two ways: as a wa.me message the mobed
sends from their own WhatsApp, and automatically through the WhatsApp Business
API. Meta only allows the second as an approved *template* - fixed text with
numbered blanks - so the message is built as four parts that fill either one.
That keeps what a mobed sees today exactly what the automatic sender would say.

The mobed has already booked these prayers, so a reminder never asks for
anything. It says which fire temple, when, what and for whom, and that the
family is welcome. No internal names ("day 31", "observance"), and nothing
that reads as a promotion - Meta bills a template it judges promotional at
several times the rate of a utility one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from agyary.calendar import GATHA_NAMES, MAH_NAMES, ROJ_NAMES

# The text submitted to Meta for approval, with its four numbered blanks:
#   {{1}} the fire temple   {{2}} when, e.g. "Tomorrow, Thu 15 Oct"
#   {{3}} the Parsi date    {{4}} what, for whom, and at what time
# It must not start or end with a blank, which Meta rejects.
TEMPLATE_BODY = (
    "Reminder from {{1}}.\n\n"
    "{{2}} ({{3}}): {{4}}\n\n"
    "You are welcome to attend.\n\n"
    "To stop these reminders, reply STOP."
)

# The manual message: the same, without the STOP line. A reply to a message a
# mobed sends from their own WhatsApp goes to the mobed, not to us, so "reply
# STOP" would promise something we cannot honour.
MANUAL_BODY = (
    "Reminder from {{1}}.\n\n"
    "{{2}} ({{3}}): {{4}}\n\n"
    "You are welcome to attend."
)


@dataclass(frozen=True)
class Parts:
    agyary: str
    when: str
    parsi: str
    what: str

    def as_params(self) -> list[str]:
        return [self.agyary, self.when, self.parsi, self.what]


def _tidy(text: str) -> str:
    """Meta rejects a blank containing a newline, a tab or a run of spaces."""
    return " ".join(str(text).split())


def parsi_text(obs) -> str:
    if obs.gatha_index:
        name = GATHA_NAMES[obs.gatha_index - 1] if obs.gatha_index <= len(GATHA_NAMES) else ""
        return f"Gatha {name}".strip()
    return f"Roj {ROJ_NAMES[obs.parsi_roj - 1]}, Mah {MAH_NAMES[obs.parsi_mah - 1]}"


def _list_and(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _clock(t: time) -> str:
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def build_parts(
    agyary_name: str, obs, departed: str, service_names: list[str], today: date
) -> Parts:
    """The four blanks for ``obs`` as it reads on ``today``.

    "Tomorrow" and "Today" appear only when true; a message built for a
    further-off date just gives the date, so a mobed who taps the manual
    button early never sends a "tomorrow" that is wrong.
    """
    d = obs.gregorian_date
    date_text = f"{d:%a} {d.day} {d:%b}"
    when = {0: f"Today, {date_text}", 1: f"Tomorrow, {date_text}"}.get((d - today).days, date_text)
    what = _list_and(service_names) or obs.label
    at = f" at {_clock(obs.time_of_day)}" if obs.time_of_day else ""
    return Parts(
        agyary=_tidy(agyary_name),
        when=when,
        parsi=parsi_text(obs),
        what=_tidy(f"{what} for {departed}{at}."),
    )


def render(body: str, params: list[str]) -> str:
    """Fill a body's {{n}} blanks."""
    for n, value in enumerate(params, start=1):
        body = body.replace("{{" + str(n) + "}}", value)
    return body


def manual_text(parts: Parts) -> str:
    return render(MANUAL_BODY, parts.as_params())


def template_text(parts: Parts) -> str:
    """What the family will see from the automatic sender."""
    return render(TEMPLATE_BODY, parts.as_params())
