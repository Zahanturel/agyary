"""The words of a reminder, in one place.

A reminder reaches a family two ways: as a wa.me message the mobed sends from
their own WhatsApp, and automatically through the WhatsApp Business API. Meta
only allows the second as an approved *template* - fixed text with numbered
blanks - so the message is built from parts that fill the manual message and
either template. Since the owner's word review (D11, 23 Nov 2026) the manual
message and template v2 greet the family ("Sahebji"); the manual message closes
with "May the ruvan of the late <departed> attain Garothman Behesht.", template
v2 does not (Meta classes well-wishes as Marketing). The live template keeps
its words until v2 is approved.

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
# It must not start or end with a blank, and Meta rejects one with too many
# blanks for its length - hence the fixed sentence in the middle.
#
# Deliberately plain and appointment-like. Meta decides the category, and it
# judged anything that invites ("We would be glad to have you there", "Please
# join us") to be Marketing, which is billed at several times the rate and may
# not be approved as Utility. The warmth lives in the mobed, not the template.
TEMPLATE_BODY = (
    "Reminder from {{1}}.\n\n"
    "This is a notice of prayers scheduled at the fire temple.\n\n"
    "When: {{2}} ({{3}})\n"
    "Prayers: {{4}}\n\n"
    "To stop these reminders, reply STOP."
)

# The next version, to be submitted to Meta as a Utility template under this
# name, in the owner's words (D11, word review of 23 Nov 2026): the family
# greeted by their name, the prayers and the day, and the closing line of
# every message the app writes; a footer saying how to stop, and a "Stop
# reminders" quick-reply button (its tap arrives as that text, which counts as
# a STOP). Its blanks are not the current template's (``Parts.params_for``):
#   {{1}} the family's name   {{2}} the fire temple   {{3}} the prayers
#   {{4}} the departed        {{5}} the day, its Roj and Mah and the time,
#   e.g. "Thu 15 Oct (Roj Hormazd, Mah Fravardin) at 9:00 am"
# One blank for the day, the Parsi date and the time, because the time is
# not always set and Meta refuses an empty blank. Fixed words between every
# two blanks, and none at the very start or end. No closing blessing: Meta's
# form warned that "May the ruvan of the late ... attain Garothman Behesht."
# makes it Marketing (well-wishes), so the owner dropped it from this template
# only, 23 Nov 2026; the manual message below keeps it. The current template keeps
# working until this one is APPROVED; then WHATSAPP_REMINDER_TEMPLATE is set to
# this name - a setting, not a deploy (each reminder is planned with the blanks
# of the template it goes on). Laid out in short lines with a blank line
# between the greeting, the prayers and the closing line, so it can be read at
# a glance (the owner, 23 Nov 2026).
TEMPLATE_V2_NAME = "memorial_reminder_v3"  # the second layout; Meta locked the name _v2 (owner, 23 Nov 2026)
TEMPLATE_V2_BODY = (
    "Sahebji {{1}},\n\n"
    "A reminder from {{2}}:\n"
    "{{3}} for {{4}} on {{5}}.\n\n"
    "The prayers are already arranged; you need not reply."
)
TEMPLATE_V2_FOOTER = "To stop these reminders, reply STOP"
TEMPLATE_V2_BUTTON = "Stop reminders"

# The manual message, which the mobed sends from their own WhatsApp, in the
# owner's words (D11, 23 Nov 2026). No STOP line: a reply to it goes to the
# mobed, not to us, so "reply STOP" would promise something we cannot honour.
CLOSING = "May the ruvan of the late {departed} attain Garothman Behesht."


@dataclass(frozen=True)
class Parts:
    agyary: str
    when: str
    parsi: str
    what: str
    # For the manual message and the reminder template v2.
    prayer: str = ""
    departed: str = ""
    day: str = ""            # "Thu 15 Oct", without "Today" or "Tomorrow"
    at: str = ""             # "9:00 am", or "" when no time is set
    family: str = ""         # the behdin's own name, as saved
    mobed: str = ""          # the mobed's own name

    def as_params(self) -> list[str]:
        """The current template's four blanks (memorial_reminder)."""
        return [self.agyary, self.when, self.parsi, self.what]

    def v2_params(self) -> list[str]:
        """The five blanks of memorial_reminder_v3, in order."""
        on = f"{self.day} ({self.parsi})" + (f" at {self.at}" if self.at else "")
        return [self.family, self.agyary, self.prayer, self.departed, on]

    def params_for(self, template_name: str) -> list[str]:
        """The blanks of the template a reminder goes out on."""
        return self.v2_params() if template_name == TEMPLATE_V2_NAME else self.as_params()


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
    agyary_name: str, obs, departed: str, service_names: list[str], today: date, *,
    family: str = "", mobed: str = "",
) -> Parts:
    """The blanks for ``obs`` as it reads on ``today``: ``family`` is the
    behdin's own name as saved, ``mobed`` the mobed's.

    "Tomorrow" and "Today" appear only when true; a message built for a
    further-off date just gives the date, so a mobed who taps the manual
    button early never sends a "tomorrow" that is wrong.
    """
    d = obs.gregorian_date
    date_text = f"{d:%a} {d.day} {d:%b}"
    when = {0: f"Today, {date_text}", 1: f"Tomorrow, {date_text}"}.get((d - today).days, date_text)
    what = _list_and(service_names) or obs.label
    clock = _clock(obs.time_of_day) if obs.time_of_day else ""
    at = f" at {clock}" if clock else ""
    return Parts(
        agyary=_tidy(agyary_name),
        when=when,
        parsi=parsi_text(obs),
        what=_tidy(f"{what} for {departed}{at}."),
        prayer=_tidy(what),
        departed=_tidy(departed),
        day=date_text,
        at=clock,
        family=_tidy(family),
        mobed=_tidy(mobed),
    )


def render(body: str, params: list[str]) -> str:
    """Fill a body's {{n}} blanks."""
    for n, value in enumerate(params, start=1):
        body = body.replace("{{" + str(n) + "}}", value)
    return body


def manual_text(parts: Parts) -> str:
    """The message the mobed sends from their own WhatsApp ("Remind on
    WhatsApp"): "Sahebji <family>, a reminder from <mobed> of <fire temple>:",
    the prayers and the day, and the closing line. "Sahebji, a reminder ..."
    when the behdin's name is blank."""
    greeting = f"Sahebji {parts.family}" if parts.family else "Sahebji"
    sender = f"{parts.mobed} of {parts.agyary}" if parts.mobed else parts.agyary
    at = f", at {parts.at}" if parts.at else ""
    return (
        f"{greeting}, a reminder from {sender}:\n\n"
        f"{parts.prayer} for {parts.departed}\n"
        f"{parts.when} ({parts.parsi}){at}\n\n"
        + CLOSING.format(departed=parts.departed)
    )


def template_body(name: str) -> str:
    """The approved body for a template name (the current one by default)."""
    return TEMPLATE_V2_BODY if name == TEMPLATE_V2_NAME else TEMPLATE_BODY


def template_text(parts: Parts, name: str = "") -> str:
    """What the family will see from the automatic sender."""
    return render(template_body(name), parts.params_for(name))
