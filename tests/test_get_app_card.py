"""Who sees which "Get the app" card under the sign-in card (js/install.js).

Android phones get the APK, iPhones and iPads the Add to Home Screen steps (an
iPad asking for desktop sites says it is a Mac, and is still an iPad), and
nobody gets the card inside the installed app. Run under Node, like the
session tests; skipped where Node is not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL_JS = ROOT / "src" / "agyary" / "api" / "static" / "mobed" / "js" / "install.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node is not installed")

ANDROID_CHROME = ("Mozilla/5.0 (Linux; Android 14; SM-A146B) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/131.0.0.0 Mobile Safari/537.36")
ANDROID_SAMSUNG = ("Mozilla/5.0 (Linux; Android 14; SAMSUNG SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile Safari/537.36")
ANDROID_IN_APP = ("Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230805.001; wv) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.230 Mobile Safari/537.36 Instagram 312.0")
IPHONE_SAFARI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
                 "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1")
IPHONE_CHROME = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
                 "(KHTML, like Gecko) CriOS/131.0.6778.73 Mobile/15E148 Safari/604.1")
MAC_SAFARI = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
              "Version/18.1 Safari/605.1.15")
WINDOWS_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/131.0.0.0 Safari/537.36")


def _node(script: str) -> object:
    done = subprocess.run(
        [NODE, "--no-warnings", "--input-type=module", "-e", script],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def _run(expression: str) -> object:
    return _node(f"""
const m = await import({json.dumps(INSTALL_JS.resolve().as_uri())});
console.log(JSON.stringify({expression}));
""")


def test_each_phone_gets_its_own_way_to_install():
    cases = [
        (ANDROID_CHROME, 0, "android"),
        (ANDROID_SAMSUNG, 5, "android"),
        (ANDROID_IN_APP, 5, "android"),
        (IPHONE_SAFARI, 5, "ios"),
        (IPHONE_CHROME, 5, "ios"),
        (MAC_SAFARI, 5, "ios"),     # an iPad asking for the desktop site
        (MAC_SAFARI, 0, "other"),   # a real Mac
        (WINDOWS_CHROME, 0, "other"),
        ("", 0, "other"),
    ]
    got = _run("[" + ", ".join(f"m.detectPlatform({json.dumps(ua)}, {tp})" for ua, tp, _ in cases) + "]")
    assert got == [want for _, _, want in cases]


def test_another_apps_browser_is_told_apart_from_chrome():
    """Instagram's own browser usually cannot download; Chrome (and the Chrome
    tabs WhatsApp opens links in) can."""
    got = _run(f"[m.inWebView({json.dumps(ANDROID_IN_APP)}), m.inWebView({json.dumps(ANDROID_CHROME)}), "
               f"m.inWebView({json.dumps(IPHONE_SAFARI)})]")
    assert got == [True, False, False]


def test_the_card_is_never_shown_inside_the_installed_app():
    got = _run("""[
      m.runningAsApp({}),
      m.runningAsApp({ standalone: true }),
      m.runningAsApp({ displayMode: true }),
      m.runningAsApp({ referrer: "android-app://com.gotiadarian.mobeddiary/" }),
      m.runningAsApp({ referrer: "https://www.google.com/" }),
      m.runningAsApp({ standalone: undefined }),
    ]""")
    assert got == [False, True, True, True, False, False]


def test_the_button_points_at_the_server_route():
    """The address the card links to is the one the server answers
    (tests/test_android_app.py follows it to the file)."""
    assert _run("m.APK_URL") == "/download/android"
