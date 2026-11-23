"""Every name a mobed-app script imports from another is really exported there.

A missing export is a SyntaxError the browser raises when it loads the module graph, and then
the whole app is a blank page (24 Nov 2026: our_mobeds.js imported startOurMobed, which api.js
did not export). Node's --check does not catch it, since it reads one file at a time."""

from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "agyary" / "api" / "static" / "mobed" / "js"
IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"']([^\"']+)[\"']")
EXPORT_NAMED = re.compile(r"export\s+(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z_$][\w$]*)")
EXPORT_LIST = re.compile(r"export\s*\{([^}]*)\}")


def _exports(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    names = set(EXPORT_NAMED.findall(text))
    for group in EXPORT_LIST.findall(text):
        for part in group.split(","):
            part = part.strip()
            if part:
                names.add(part.split(" as ")[-1].strip())
    return names


def test_every_named_import_is_exported_by_the_module_it_comes_from():
    missing = []
    for path in sorted(JS.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        for names, source in IMPORT.findall(text):
            if not source.startswith("."):
                continue
            target = (path.parent / source).resolve()
            assert target.exists(), f"{path.name} imports {source}, which is not there"
            have = _exports(target)
            for raw in names.split(","):
                name = raw.strip().split(" as ")[0].strip()
                if name and name not in have:
                    missing.append(f"{path.relative_to(JS)} imports {name} from {source}")
    assert not missing, "\n".join(missing)
