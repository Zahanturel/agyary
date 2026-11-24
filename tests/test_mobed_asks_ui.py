"""The mobed app's side of asks from people (R4.2): the files are wired in, and the words a mobed
reads never name the other app."""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "src" / "agyary" / "api" / "static"
JS = STATIC / "mobed" / "js"
NEW_FILES = [JS / "asks_section.js", JS / "screens" / "ask_settings.js"]


def test_new_files_are_in_the_shell_and_the_cache_was_bumped():
    worker = (STATIC / "mobed-sw.js").read_text(encoding="utf-8")
    assert "/mobed-app/js/asks_section.js" in worker
    assert "/mobed-app/js/screens/ask_settings.js" in worker
    assert 'CACHE_NAME = "mobed-shell-v104"' in worker


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
        assert "Parsi" not in text and not re.search(r"behdin app", text, re.I), path.name


def test_accept_says_what_it_does_and_the_reason_is_short():
    section = (JS / "asks_section.js").read_text(encoding="utf-8")
    assert "name and number will be added to your" in section
    assert 'maxlength="100"' in section
