"""R4.0 step 2: the behdin app's shell (docs/behdin-r4-0-design.md).

The app is a page plus ES modules with no build step, served beside Mobed Diary's and taking its
router, page helpers and form marks from /mobed-app/js/. Three things go wrong quietly there, and
each has a test: a name imported that the other module does not export (the blank app of 24 Nov
2026), a file the service worker forgot to cache (blank offline), and a route that is not served.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agyary.api.routes.behdin import APP_NAME
from agyary.core import config
from tests.test_behdin_identity import PERSON, auth, behdin_sign_in

STATIC = Path(__file__).resolve().parents[1] / "src" / "agyary" / "api" / "static"
FOLDERS = {"/behdin-app/": STATIC / "behdin", "/mobed-app/": STATIC / "mobed"}
ENTRY = "/behdin-app/js/main.js"

IMPORT_NAMED = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"']([^\"']+)[\"']")
IMPORT_ANY = re.compile(r"(?:from\s+|import\s*\(\s*)[\"']([^\"']+\.js)[\"']")
EXPORT_NAMED = re.compile(r"export\s+(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z_$][\w$]*)")
EXPORT_LIST = re.compile(r"export\s*\{([^}]*)\}")


def _file_of(url: str) -> Path:
    for prefix, folder in FOLDERS.items():
        if url.startswith(prefix):
            return folder / url.removeprefix(prefix)
    raise AssertionError(f"{url} is not under a served app folder")


def _url_of(path: Path) -> str:
    for prefix, folder in FOLDERS.items():
        if folder in path.parents:
            return prefix + path.relative_to(folder).as_posix()
    raise AssertionError(path)


def _resolve(importer: Path, source: str) -> Path:
    """The file an import names: a relative path, or an absolute one under a served folder."""
    if source.startswith("/"):
        return _file_of(source)
    return (importer.parent / source).resolve()


def _exports(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    names = set(EXPORT_NAMED.findall(text))
    for group in EXPORT_LIST.findall(text):
        names.update(part.split(" as ")[-1].strip() for part in group.split(",") if part.strip())
    return names


def _behdin_files() -> list[Path]:
    return sorted((STATIC / "behdin").rglob("*.js"))


def _closure(entry_url: str) -> set[str]:
    seen: set[str] = set()
    todo = [_file_of(entry_url)]
    while todo:
        path = todo.pop()
        url = _url_of(path)
        if url in seen:
            continue
        seen.add(url)
        for source in IMPORT_ANY.findall(path.read_text(encoding="utf-8")):
            todo.append(_resolve(path, source))
    return seen


def _shell_files() -> list[str]:
    body = (STATIC / "behdin-sw.js").read_text(encoding="utf-8")
    listed = body[body.index("SHELL_FILES = ["):]
    return re.findall(r'"([^"]+)"', listed[: listed.index("];")])


def test_every_named_import_in_the_behdin_app_is_exported_by_its_module():
    missing = []
    for path in _behdin_files():
        for names, source in IMPORT_NAMED.findall(path.read_text(encoding="utf-8")):
            target = _resolve(path, source)
            assert target.exists(), f"{_url_of(path)} imports {source}, which is not there"
            have = _exports(target)
            for raw in names.split(","):
                name = raw.strip().split(" as ")[0].strip()
                if name and name not in have:
                    missing.append(f"{_url_of(path)} imports {name} from {source}")
    assert not missing, "\n".join(missing)


def test_the_service_worker_lists_every_file_the_app_loads_and_nothing_that_is_not_there():
    shell = set(_shell_files())
    assert len(shell) == len(_shell_files()), "a file is listed twice"
    loaded = _closure(ENTRY)
    assert any(u.startswith("/mobed-app/") for u in loaded), "the shared modules are not being followed"
    assert sorted(loaded - shell) == []
    # Every file of the behdin app is cached, even one nothing imports yet.
    own = {_url_of(p) for p in _behdin_files()} | {"/behdin-app/behdin.css"}
    assert sorted(own - shell) == []
    for url in shell:
        if url.startswith(tuple(FOLDERS)):
            assert _file_of(url).exists(), url


def test_the_page_and_the_worker_name_the_right_files():
    page = (STATIC / "behdin" / "index.html").read_text(encoding="utf-8")
    assert "/behdin-app/js/main.js" in page and "/behdin-manifest.json" in page
    for href in re.findall(r'(?:href|src)="(/[^"]+)"', page):
        if href.startswith(tuple(FOLDERS)):
            assert _file_of(href).exists(), href
    worker = (STATIC / "behdin-sw.js").read_text(encoding="utf-8")
    assert 'CACHE_NAME = "behdin-shell-v' in worker
    # Its own cache only: Mobed Diary's may sit on the same origin.
    assert 'k.startsWith("behdin-shell-") && k !== CACHE_NAME' in worker
    # The app is registered under its own scope, with the name coming from one place.
    main = (STATIC / "behdin" / "js" / "main.js").read_text(encoding="utf-8")
    assert 'register("/behdin-sw.js", { scope })' in main and 'location.pathname === "/" ? "/" : "/behdin"' in main
    assert 'CACHE_NAME = "behdin-shell-v10"' in worker and '"/",' in worker


async def test_every_cached_file_is_served_and_the_shell_is_never_cached_by_the_edge(client):
    for url in _shell_files():
        if url == "/":
            continue   # on a host with no BEHDIN_HOST it is a redirect; tested below, on its own host
        r = await client.get(url)
        assert r.status_code == 200, url
        # Without this Cloudflare keeps a shell file for hours after a deploy.
        if url.startswith(("/behdin", "/mobed-app")):
            assert r.headers["cache-control"] == "no-cache", url
    sw = await client.get("/behdin-sw.js")
    assert sw.status_code == 200 and sw.headers["cache-control"] == "no-cache"
    assert "javascript" in sw.headers["content-type"]


async def test_the_page_and_the_manifest_carry_the_apps_name_from_one_place(client):
    page = await client.get("/behdin")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "{{" not in page.text and f"<title>{APP_NAME}</title>" in page.text
    manifest = await client.get("/behdin-manifest.json")
    body = manifest.json()
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    assert (body["name"], body["short_name"]) == (APP_NAME, APP_NAME)
    assert (body["id"], body["start_url"], body["scope"]) == ("/behdin", "/behdin", "/behdin")
    for icon in body["icons"]:
        assert (await client.get(icon["src"])).status_code == 200, icon["src"]
    assert APP_NAME == "Parsi"
    assert "{{" not in json.dumps(body)


@pytest.fixture
def behdin_host(monkeypatch):
    monkeypatch.setenv("BEHDIN_HOST", "parsi.gotiadarian.com")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def test_the_behdin_hostname_is_the_behdin_app_at_the_root_and_every_other_host_the_mobed_app(client, behdin_host):
    own = {"Host": "parsi.gotiadarian.com"}
    r = await client.get("/", headers=own, follow_redirects=False)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert f"<title>{APP_NAME}</title>" in r.text and "{{" not in r.text
    assert r.headers["cache-control"] == "no-cache"
    # Its manifest says the app lives at "/", still named from the one place.
    body = (await client.get("/behdin-manifest.json", headers=own)).json()
    assert (body["id"], body["start_url"], body["scope"], body["name"]) == ("/", "/", "/", APP_NAME)
    # Everywhere else the manifest and the page are the /behdin ones.
    other = (await client.get("/behdin-manifest.json", headers={"Host": "localhost:8000"})).json()
    assert (other["id"], other["start_url"], other["scope"]) == ("/behdin", "/behdin", "/behdin")
    for host in ("mobed.gotiadarian.com", "localhost:8000"):
        r = await client.get("/", headers={"Host": host}, follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == "/mobed", host
    # /behdin keeps working on every host, the app's own included.
    for host in ("parsi.gotiadarian.com", "localhost:8000"):
        assert (await client.get("/behdin", headers={"Host": host})).status_code == 200, host


async def test_with_no_behdin_hostname_set_the_root_is_the_mobed_app(client):
    assert config.get_settings().behdin_host == ""
    r = await client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/mobed"


async def test_today_gives_the_parsi_date_to_any_signed_in_person(client):
    person = await behdin_sign_in(client, PERSON)
    r = await client.get("/api/behdin/today", headers=auth(person))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gregorian_date"] and body["calendar"] == "shenshai"
    assert body["roj_name"] and body["mah_name"] and body["year"]
    assert (await client.get("/api/behdin/today")).status_code == 401


def test_mobed_diary_has_a_page_for_a_behdins_account_and_its_worker_keeps_the_other_apps_cache():
    mobed = STATIC / "mobed" / "js"
    main = (mobed / "main.js").read_text(encoding="utf-8")
    # The refusal of a behdin's account must reach the page, not blank the app or send it round in circles.
    assert 'route("#/become", renderBecomeMobed)' in main
    assert 'e.status === 403 && e.kind === "behdin"' in main
    assert 'if (isBehdin()) return matched.pattern === "#/become"' in main
    session = (mobed / "session.js").read_text(encoding="utf-8")
    assert 'if (isBehdin()) return "#/become";' in session
    assert "err.kind = kind;" in (mobed / "api.js").read_text(encoding="utf-8")
    assert '"/auth/become-mobed"' in (mobed / "api.js").read_text(encoding="utf-8")
    worker = (STATIC / "mobed-sw.js").read_text(encoding="utf-8")
    assert 'k.startsWith("mobed-shell-") && k !== CACHE_NAME' in worker
    assert 'CACHE_NAME = "mobed-shell-v113"' in worker
    assert "/mobed-app/js/screens/become_mobed.js" in worker


# --- The two apps never see each other (owner's decision, 25 Nov 2026) ---------------------------

_COMMENTS = re.compile(r"/\*.*?\*/|<!--.*?-->|(?<![:\"'\w])//[^\n]*", re.S)
# Code, not words a person reads: file paths of the shared folders, a header name, and the titles
# (Er, Ervad, Mobed...) stripped from the front of a typed name.
_NOT_WORDS = re.compile(r"/mobed-[\w./-]*|X-Mobed-Access|NAME_PREFIXES = new Set\(\[[^\]]*\]")


def test_nothing_in_the_behdin_app_names_or_links_to_mobed_diary():
    found = []
    for path in sorted((STATIC / "behdin").rglob("*")):
        if not path.is_file() or path.suffix not in {".js", ".html", ".css"}:
            continue
        text = _NOT_WORDS.sub("", _COMMENTS.sub("", path.read_text(encoding="utf-8")))
        if re.search(r"mobed", text, re.I) or re.search(r'href="/mobed', text):
            found.append(path.relative_to(STATIC).as_posix())
    assert not found, f"these show or link to the other app: {found}"
    assert not (STATIC / "behdin" / "js" / "screens" / "become_mobed.js").exists()


def test_what_a_parsi_user_can_be_told_by_the_server_never_names_the_other_app():
    from agyary.api.routes import mobed as mobed_routes
    assert "mobed" not in mobed_routes.BEHDIN_OFF.lower()
    assert "behdin" not in mobed_routes.BEHDIN_OFF.lower()


def test_mobed_diarys_page_for_an_account_that_is_not_a_mobeds_never_names_the_parsi_app():
    page = (STATIC / "mobed" / "js" / "screens" / "become_mobed.js").read_text(encoding="utf-8")
    assert not re.search(r"parsi|behdin app|/behdin", page, re.I)
    assert "This number is not set up as a mobed's" in page and "Ask to become a mobed" in page
    from agyary.api.routes import mobed as mobed_routes
    assert mobed_routes.NOT_FOR_BEHDINS == (
        "This part of Mobed Diary is for mobeds. This number is not set up as a mobed's."
    )



# --- R4.1: what a person keeps for themselves ------------------------------------------------------

def test_the_fire_temple_screens_pick_by_town_and_never_use_a_position():
    code = _COMMENTS.sub("", (STATIC / "behdin" / "js" / "screens" / "picker.js").read_text(encoding="utf-8"))
    assert "getTowns" in code and "findAgyaries" in code
    assert not re.search(r"geolocation|localStorage|sessionStorage|indexedDB|console\.|document\.cookie", code)
    api = (STATIC / "behdin" / "js" / "api.js").read_text(encoding="utf-8")
    assert 'post("/agyaries/find"' in api and 'get("/agyaries/towns")' in api
    assert "/agyaries/nearby" not in api and "/asking" not in api


def test_every_screen_of_the_calendar_work_has_its_route_and_the_new_one_comes_first():
    main = (STATIC / "behdin" / "js" / "main.js").read_text(encoding="utf-8")
    for pattern in ("#/agyari", "#/event/new", "#/event/:id", "#/departed/new", "#/departed/:id/edit", "#/departed/:id"):
        assert f'route("{pattern}"' in main, pattern
    assert main.index('route("#/event/new"') < main.index('route("#/event/:id"')
    assert main.index('route("#/departed/new"') < main.index('route("#/departed/:id"')


# --- R4.2: asking an agyari for a prayer -----------------------------------------------------------

def test_the_ask_screens_have_their_routes_and_the_longer_one_comes_first():
    main = (STATIC / "behdin" / "js" / "main.js").read_text(encoding="utf-8")
    for pattern in ("#/request", "#/asks", "#/asks/:id/another", "#/asks/:id"):
        assert f'route("{pattern}"' in main, pattern
    assert main.index('route("#/asks/:id/another"') < main.index('route("#/asks/:id"')
    assert "syncBell" in main
    shell = set(_shell_files())
    for name in ("screens/request.js", "screens/requests.js", "screens/picker.js", "notices.js", "push.js"):
        assert f"/behdin-app/js/{name}" in shell, name


def test_the_request_flow_is_what_when_send_and_calls_the_new_api():
    flow = (STATIC / "behdin" / "js" / "screens" / "request.js").read_text(encoding="utf-8")
    assert 'const STEPS = ["what", "when", "send"]' in flow
    assert "Your name and number go to the panthaky only if they accept." in flow
    assert "(estimate)" in flow and "Don't repeat" in flow and "Every month, on the same Roj" in flow
    assert "/mobed-app/js/repeat.js" in flow
    api = (STATIC / "behdin" / "js" / "api.js").read_text(encoding="utf-8")
    for call in ('post("/me/asks"', "/me/asks/${id}/cancel", "/me/asks/${id}/ask-another", 'get("/notifications")',
                 'post("/notifications/seen"', "/agyaries/${agyaryId}/offering", 'get("/me/push")',
                 'post("/me/push/subscribe"'):
        assert call in api, call


def test_phone_notifications_are_asked_once_and_the_worker_shows_and_opens_them():
    code = (STATIC / "behdin" / "js" / "push.js").read_text(encoding="utf-8")
    assert "Allow notifications?" in code and "You will be told when a fire temple answers." in code
    assert "Not now" in code and "localStorage" in code
    worker = (STATIC / "behdin-sw.js").read_text(encoding="utf-8")
    assert 'addEventListener("push"' in worker and 'addEventListener("notificationclick"' in worker
    assert "behdin-icon-192.png" in worker


def test_the_bell_is_asked_on_focus_and_every_minute_and_the_page_has_one():
    code = (STATIC / "behdin" / "js" / "notices.js").read_text(encoding="utf-8")
    assert "EVERY_MS = 60000" in code and "visibilitychange" in code and '"focus"' in code
    page = (STATIC / "behdin" / "index.html").read_text(encoding="utf-8")
    assert 'id="bellBtn"' in page and 'id="bellBadge"' in page


async def test_the_parsi_app_has_its_own_icons_and_never_the_mobed_ones(client):
    page = (await client.get("/behdin")).text
    manifest = (await client.get("/behdin-manifest.json")).text
    assert "mobed-icon" not in page and "mobed-icon" not in manifest
    for name in ("behdin-icon-180.png", "behdin-icon-192.png", "behdin-icon-512.png", "behdin-icon-maskable-512.png"):
        res = await client.get("/" + name)
        assert res.status_code == 200 and res.headers["content-type"] == "image/png"


async def test_the_redirect_from_the_root_is_never_kept_by_a_browser(client):
    res = await client.get("/", follow_redirects=False)
    assert res.status_code == 307 and res.headers["cache-control"] == "no-store"


# --- Clean-up (25 Nov 2026): one calendar, the community's own words ----------------------------------

def test_the_parsi_calendar_is_the_shared_calendar_module_and_there_is_no_second_grid():
    code = (STATIC / "behdin" / "js" / "screens" / "calendar.js").read_text(encoding="utf-8")
    assert '"/mobed-app/js/calendar.js"' in code and "renderCalendar" in code and "useCalendarDeps" in code
    assert "cal-grid" not in code and "cal-cell" not in (STATIC / "behdin" / "behdin.css").read_text(encoding="utf-8")
    shared = (STATIC / "mobed" / "js" / "calendar.js").read_text(encoding="utf-8")
    assert "export function useCalendarDeps" in shared
    main = (STATIC / "behdin" / "js" / "main.js").read_text(encoding="utf-8")
    assert 'route("#/calendar/:mode/:date"' in main
    page = (STATIC / "behdin" / "index.html").read_text(encoding="utf-8")
    assert 'id="fab"' in page and "Add an event" in page


def test_the_new_event_screen_has_the_one_choice_of_kind_and_the_install_card_is_on_sign_in():
    event = (STATIC / "behdin" / "js" / "screens" / "event.js").read_text(encoding="utf-8")
    for kind in ("Prayers for the departed", "New event"):
        assert kind in event
    assert "Add a departed" not in (STATIC / "behdin" / "js" / "screens" / "calendar.js").read_text(encoding="utf-8")
    assert not (STATIC / "behdin" / "js" / "consent.js").exists()
    login = (STATIC / "behdin" / "js" / "screens" / "login.js").read_text(encoding="utf-8")
    menu = (STATIC / "behdin" / "js" / "screens" / "menu.js").read_text(encoding="utf-8")
    assert "addGetApp(mainEl)" in login and "paintInstall" not in menu and "mInstall" not in menu


_BANNED = re.compile(r"(?<![\w/.#$@-])(agyari|agiary)(?!\w)|namaste", re.I)


def test_banned_words_are_nowhere_in_what_a_person_reads_in_either_app():
    """D11 (22 Nov 2026): no "Namaste", and "fire temple", never "agyari" or "agiary". Comments are left out, and so
    is a bare quoted code word ("agyari" as a value the server uses). Identifiers and addresses do not match."""
    found = []
    for path in sorted(STATIC.rglob("*")):
        if not path.is_file() or path.suffix not in {".js", ".html"}:
            continue
        text = _COMMENTS.sub("", path.read_text(encoding="utf-8"))
        for m in _BANNED.finditer(text):
            before, after = text[m.start() - 1: m.start()], text[m.end(): m.end() + 1]
            if before in "\"'" and after in "\"'":
                continue
            found.append(f"{path.relative_to(STATIC).as_posix()}: {text[max(0, m.start() - 30): m.end() + 30]!r}")
    assert not found, chr(10).join(found)
