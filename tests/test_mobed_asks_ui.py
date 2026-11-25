"""The mobed app's side of asks from people (R4.2): the files are wired in, and the words a mobed
reads never name the other app."""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "src" / "agyary" / "api" / "static"
JS = STATIC / "mobed" / "js"
NEW_FILES = [JS / "asks_section.js", JS / "screens" / "ask_settings.js", JS / "notify_prompt.js"]


def test_new_files_are_in_the_shell_and_the_cache_was_bumped():
    worker = (STATIC / "mobed-sw.js").read_text(encoding="utf-8")
    assert "/mobed-app/js/asks_section.js" in worker
    assert "/mobed-app/js/screens/ask_settings.js" in worker
    assert 'CACHE_NAME = "mobed-shell-v107"' in worker


def test_screens_use_the_finished_routes():
    api = (JS / "api.js").read_text(encoding="utf-8")
    for path in ("/asks-setting", "/service-prices", "/asks/${askId}/accept", "/asks/${askId}/reject",
                 "/services/${serviceId}"):
        assert path in api
    assert 'import { paintAsks } from "../asks_section.js"' in (JS / "screens" / "requests.js").read_text(encoding="utf-8")
    menu = (JS / "screens" / "menu.js").read_text(encoding="utf-8")
    assert "paintAskSettings" in menu and 'id="mAsks"' in menu
    assert "listAsks" in (JS / "requests_count.js").read_text(encoding="utf-8")


def test_the_two_apps_never_name_each_other():
    for path in NEW_FILES:
        text = path.read_text(encoding="utf-8")
        # "parsi" in lower case is only the server's field name for the Roj and Mah of a day.
        assert "Parsi" not in text and not re.search(r"behdin app|agyari|namaste", text, re.I), path.name


def test_accept_says_what_it_does_and_the_reason_is_short():
    section = (JS / "asks_section.js").read_text(encoding="utf-8")
    assert "name and number will be added to your" in section
    assert 'maxlength="100"' in section


def test_the_words_are_request_and_fire_temple_not_ask_and_agyari():
    """What a mobed reads: "Requests from people", Confirm and Decline, prices before the switch."""
    section = (JS / "asks_section.js").read_text(encoding="utf-8")
    settings = (JS / "screens" / "ask_settings.js").read_text(encoding="utf-8")
    assert "Requests from people" in section and "Requests from people" in settings
    assert ">Confirm</button>" in section and ">Decline</button>" in section and "Time open" in section
    assert "Asks from people" not in section + settings and "Take asks" not in settings
    assert settings.index("Services and prices") < settings.index("Take requests")
    assert "Enter a price for every service." in settings

def test_confirm_sends_times_and_the_notification_sheet_is_once_per_device():
    section = (JS / "asks_section.js").read_text(encoding="utf-8")
    assert "time_open" in section and "Name not known" in section and "Estimate" in section
    assert "cancelled_by_fire_temple" in section and "data-time" in section
    assert "times" in (JS / "api.js").read_text(encoding="utf-8")
    prompt = (JS / "notify_prompt.js").read_text(encoding="utf-8")
    assert "Allow notifications?" in prompt and "You will be told of new requests." in prompt
    assert "Not now" in prompt and "localStorage" in prompt
    assert "/mobed-app/js/notify_prompt.js" in (STATIC / "mobed-sw.js").read_text(encoding="utf-8")
