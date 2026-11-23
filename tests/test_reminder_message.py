"""The words of a reminder: what a family is told, by hand and by template."""

from __future__ import annotations

import re
from datetime import date, time, timedelta
from types import SimpleNamespace

from agyary.services import reminder_message as rm

DAY = date(2030, 3, 14)
ROJ_MAH = "Roj Hormazd, Mah Fravardin"


def _obs(at: tuple[int, int] | None = None, **over):
    base = dict(gregorian_date=DAY, label="Varsi", gatha_index=None, parsi_roj=1, parsi_mah=1,
                time_of_day=time(*at) if at else None)
    return SimpleNamespace(**{**base, **over})


def _parts(today=DAY - timedelta(days=1), services=("Afringan", "Baaj"), family="Rustom Mistry",
           mobed="Er. Jehangir Mistry", **kw):
    return rm.build_parts("Goti Adarian", _obs(**kw), "Dinshaw", list(services), today, family=family, mobed=mobed)


def test_the_manual_message_says_when_and_what_without_asking_for_anything():
    # The owner's words (D11, word review of 23 Nov 2026).
    assert rm.manual_text(_parts()) == (
        "Sahebji Rustom Mistry, a reminder from Er. Jehangir Mistry of Goti Adarian:\n\n"
        "Afringan and Baaj for Dinshaw\n"
        f"Tomorrow, Thu 14 Mar ({ROJ_MAH})\n\n"
        "May the ruvan of the late Dinshaw attain Garothman Behesht."
    )


def test_the_manual_message_without_a_behdin_name_or_a_mobed_name():
    text = rm.manual_text(_parts(family="", mobed=""))
    assert text.startswith("Sahebji, a reminder from Goti Adarian:\n\n")


def test_the_automatic_message_adds_how_to_stop():
    # The live template (memorial_reminder) keeps its words and its four blanks.
    assert rm.template_text(_parts()) == (
        "Reminder from Goti Adarian.\n\n"
        "This is a notice of prayers scheduled at the fire temple.\n\n"
        f"When: Tomorrow, Thu 14 Mar ({ROJ_MAH})\n"
        "Prayers: Afringan and Baaj for Dinshaw.\n\n"
        "To stop these reminders, reply STOP."
    )


def test_today_and_tomorrow_are_said_only_when_true():
    assert f"\nToday, Thu 14 Mar ({ROJ_MAH})" in rm.manual_text(_parts(today=DAY))
    # Further off it is just the date; no "tomorrow" that would be wrong.
    assert f"\nThu 14 Mar ({ROJ_MAH})\n" in rm.manual_text(_parts(today=DAY - timedelta(days=4)))


def test_the_time_appears_only_when_there_is_one():
    assert f"Tomorrow, Thu 14 Mar ({ROJ_MAH}), at 9:00 am\n" in rm.manual_text(
        _parts(services=["Afringan"], at=(9, 0)))
    assert ", at 5:30 pm" in rm.manual_text(_parts(at=(17, 30)))
    assert ", at 12:00 pm" in rm.manual_text(_parts(at=(12, 0)))
    assert ", at 12:05 am" in rm.manual_text(_parts(at=(0, 5)))
    assert f"({ROJ_MAH})\n\n" in rm.manual_text(_parts(services=["Afringan"]))
    # The live template's blanks, unchanged.
    assert _parts(services=["Afringan"], at=(9, 0)).what == "Afringan for Dinshaw at 9:00 am."
    assert _parts(services=["Afringan"]).what == "Afringan for Dinshaw."


def test_with_no_services_it_falls_back_to_the_observance_name():
    assert ":\n\nVarsi for Dinshaw\n" in rm.manual_text(_parts(services=[]))
    assert _parts(services=[]).what == "Varsi for Dinshaw."


def test_a_gatha_day_reads_as_a_gatha():
    assert rm.parsi_text(_obs(gatha_index=2, parsi_roj=None, parsi_mah=None)).startswith("Gatha ")


def test_the_template_has_exactly_the_four_blanks_and_neither_starts_nor_ends_with_one():
    # Meta rejects a template whose body begins or ends with a variable, and
    # one whose blanks are not numbered 1..n without a gap.
    assert sorted(set(re.findall(r"\{\{(\d+)\}\}", rm.TEMPLATE_BODY))) == ["1", "2", "3", "4"]
    assert not rm.TEMPLATE_BODY.startswith("{{") and not rm.TEMPLATE_BODY.endswith("}}")
    assert len(_parts().as_params()) == 4


def test_template_blanks_never_hold_a_newline_or_a_run_of_spaces():
    # Meta refuses those inside a variable. A name with stray whitespace is
    # tidied rather than rejected at send time.
    parts = rm.build_parts("Goti\n  Adarian", _obs(), "Din\tshaw    Mehta", ["Afringan"], DAY,
                           family="Rustom\n  Mistry")
    for value in parts.as_params() + parts.v2_params():
        assert "\n" not in value and "\t" not in value and "    " not in value
    assert parts.agyary == "Goti Adarian" and "Din shaw Mehta" in parts.what
    assert parts.family == "Rustom Mistry"


def test_the_family_never_sees_our_vocabulary():
    for text in (rm.manual_text(_parts()), rm.template_text(_parts()),
                 rm.template_text(_parts(), rm.TEMPLATE_V2_NAME)):
        lowered = text.lower()
        for word in ("observance", "booking", "booked", "arrange", "memorial", "day 3"):
            assert word not in lowered


def test_the_next_template_greets_the_family_and_ends_with_the_closing_line():
    # The owner's words (D11, 23 Nov 2026). Its blanks are its own: 1..6 in order, none
    # at the very start or end, and fixed words between every two (Meta's rules).
    blanks = re.findall(r"\{\{(\d+)\}\}", rm.TEMPLATE_V2_BODY)
    assert blanks == ["1", "2", "3", "4", "5", "6"]
    assert not rm.TEMPLATE_V2_BODY.startswith("{{") and not rm.TEMPLATE_V2_BODY.endswith("}}")
    assert not re.search(r"\}\}\s*\{\{", rm.TEMPLATE_V2_BODY)
    # Nothing that invites: Meta classed that as Marketing.
    for invitation in ("join us", "glad to have you", "welcome", "visit", "offer"):
        assert invitation not in rm.TEMPLATE_V2_BODY.lower()
    assert len(rm.TEMPLATE_V2_FOOTER) <= 60 and len(rm.TEMPLATE_V2_BUTTON) <= 25
    from agyary.services.reminders import is_stop
    assert is_stop(rm.TEMPLATE_V2_BUTTON)          # tapping the button is a STOP


def test_the_next_template_reads_in_the_owners_words():
    parts = _parts(at=(9, 0))
    assert parts.params_for(rm.TEMPLATE_V2_NAME) == [
        "Rustom Mistry", "Goti Adarian", "Afringan and Baaj", "Dinshaw", f"Thu 14 Mar ({ROJ_MAH}) at 9:00 am",
        "Dinshaw"]
    assert rm.template_text(parts, rm.TEMPLATE_V2_NAME) == (
        "Sahebji Rustom Mistry,\n\n"
        "A reminder from Goti Adarian:\n"
        f"Afringan and Baaj for Dinshaw on Thu 14 Mar ({ROJ_MAH}) at 9:00 am.\n\n"
        "May the ruvan of the late Dinshaw attain Garothman Behesht."
    )
    # No time: the day blank ends with the Parsi date (Meta refuses an empty blank).
    assert _parts().params_for(rm.TEMPLATE_V2_NAME)[4] == f"Thu 14 Mar ({ROJ_MAH})"
    # Every other template name keeps the live template's four blanks.
    assert _parts().params_for("memorial_reminder") == _parts().as_params()


def test_the_text_shown_follows_the_template_in_use():
    parts = _parts()
    assert rm.template_text(parts).endswith("reply STOP.")
    assert rm.template_text(parts, rm.TEMPLATE_V2_NAME).endswith(
        "May the ruvan of the late Dinshaw attain Garothman Behesht.")
