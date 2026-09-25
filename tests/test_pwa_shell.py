"""Each PWA's service worker must list every module its app actually loads.

The shell is cached by an explicit list (there is no build step to generate
one). A module missing from it works online and then fails offline with a
module-resolution error and a blank screen - the worst way to find out. Both
apps share most modules, so adding one for a feature in one app and forgetting
the other's worker is the easy mistake this catches.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).parent.parent / "src" / "agyary" / "api" / "static"
JS_ROOT = STATIC / "mobed" / "js"

APPS = {
    "mobed": ("mobed-sw.js", "main.js"),
    "machi": ("machi-sw.js", "machi_main.js"),
}

_IMPORT = re.compile(r"""(?:from\s+|import\s*\(\s*)["'](\.{1,2}/[^"']+\.js)["']""")


def _shell_files(sw: str) -> set[str]:
    body = (STATIC / sw).read_text(encoding="utf-8")
    listed = body[body.index("SHELL_FILES = ["):]
    listed = listed[: listed.index("];")]
    return set(re.findall(r'"([^"]+)"', listed))


def _reachable(entry: str) -> set[Path]:
    seen: set[Path] = set()
    todo = [JS_ROOT / entry]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        for rel in _IMPORT.findall(path.read_text(encoding="utf-8")):
            todo.append((path.parent / rel).resolve())
    return seen


@pytest.mark.parametrize("app", APPS)
def test_service_worker_caches_every_module_the_app_loads(app):
    sw, entry = APPS[app]
    shell = _shell_files(sw)
    needed = {"/mobed-app/js/" + p.relative_to(JS_ROOT.resolve()).as_posix() for p in _reachable(entry)}
    missing = sorted(needed - shell)
    assert not missing, f"{sw} does not cache: {missing}"


@pytest.mark.parametrize("app", APPS)
def test_every_cached_path_exists(app):
    sw, _ = APPS[app]
    for path in _shell_files(sw):
        if path.startswith("/mobed-app/"):
            assert (STATIC / "mobed" / path.removeprefix("/mobed-app/")).exists(), path
