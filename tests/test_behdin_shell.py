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
    assert 'CACHE_NAME = "behdin-shell-v5"' in worker and '"/",' in worker


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
    assert 'CACHE_NAME = "mobed-shell-v104"' in worker
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

def test_the_agyari_screen_never_stores_logs_or_addresses_the_position():
    code = _COMMENTS.sub("", (STATIC / "behdin" / "js" / "screens" / "agyari.js").read_text(encoding="utf-8"))
    assert "navigator.geolocation.getCurrentPosition" in code
    assert not re.search(r"localStorage|sessionStorage|indexedDB|console\.|document\.cookie", code)
    api = (STATIC / "behdin" / "js" / "api.js").read_text(encoding="utf-8")
    # The position is a body field of one POST, never part of an address.
    assert 'post("/agyaries/nearby"' in api
    assert not re.search(r"`/agyaries[^`]*(lat|lng)", api)


def test_the_consent_words_are_shown_once_and_say_what_the_owner_wrote():
    code = (STATIC / "behdin" / "js" / "consent.js").read_text(encoding="utf-8")
    assert ("These dates are kept for you alone. Nobody else can see them. "
            "You can delete them any time.") in code
    assert "localStorage" in code and "dismissable: false" in code
    # Both ways of adding something wait for it.
    for name in ("event.js", "departed_form.js"):
        assert "ensureConsent()" in (STATIC / "behdin" / "js" / "screens" / name).read_text(encoding="utf-8")


def test_every_screen_of_the_calendar_work_has_its_route_and_the_new_one_comes_first():
    main = (STATIC / "behdin" / "js" / "main.js").read_text(encoding="utf-8")
    for pattern in ("#/agyari", "#/event/new", "#/event/:id", "#/departed/new", "#/departed/:id/edit", "#/departed/:id"):
        assert f'route("{pattern}"' in main, pattern
    assert main.index('route("#/event/new"') < main.index('route("#/event/:id"')
    assert main.index('route("#/departed/new"') < main.index('route("#/departed/:id"')
