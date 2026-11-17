"""The fire temple's map in the app (D10): Leaflet from our own folder, loaded
only where a map is shown, OpenStreetMap's tiles the one outside address the
page may load (and only as images), and the phone's location allowed for our
own page only."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agyary.api.main import OSM_TILES

STATIC = Path(__file__).parent.parent / "src" / "agyary" / "api" / "static"
MOBED = STATIC / "mobed"
VENDOR = MOBED / "vendor" / "leaflet"

# Leaflet 1.9.4 as published (cdnjs / unpkg); a changed byte is not Leaflet 1.9.4.
LEAFLET_FILES = {
    "leaflet.js": (147552, "db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a"),
    "leaflet.css": (14806, "a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6"),
    "images/marker-icon.png": (1466, "574c3a5cca85f4114085b6841596d62f00d7c892c7b03f28cbfa301deb1dc437"),
    "images/marker-icon-2x.png": (2464, "00179c4c1ee830d3a108412ae0d294f55776cfeb085c60129a39aa6fc4ae2528"),
    "images/marker-shadow.png": (618, "264f5c640339f042dd729062cfc04c17f8ea0f29882b538e3848ed8f10edb4da"),
}


def _directives(csp: str) -> dict[str, str]:
    return {part.strip().split(" ", 1)[0]: part.strip() for part in csp.split(";") if part.strip()}


async def test_the_map_tiles_may_load_as_images_and_nothing_else_from_outside(client):
    h = (await client.get("/mobed")).headers
    d = _directives(h["content-security-policy"])
    assert OSM_TILES == "https://tile.openstreetmap.org"
    assert d["img-src"] == f"img-src 'self' data: {OSM_TILES}"
    for name in ("script-src", "connect-src", "style-src", "font-src", "default-src", "frame-src"):
        assert "openstreetmap" not in d[name], name
    assert d["script-src"] == "script-src 'self'" and d["connect-src"] == "connect-src 'self'"


async def test_the_phones_location_is_allowed_for_our_own_page_only(client):
    policy = (await client.get("/mobed")).headers["permissions-policy"]
    assert "geolocation=(self)" in policy
    assert "camera=()" in policy and "microphone=()" in policy and "payment=()" in policy


async def test_leaflet_is_ours_unchanged_and_served(client):
    for rel, (size, digest) in LEAFLET_FILES.items():
        data = (VENDOR / rel).read_bytes()
        assert len(data) == size and hashlib.sha256(data).hexdigest() == digest, rel
        r = await client.get(f"/mobed-app/vendor/leaflet/{rel}")
        assert r.status_code == 200 and r.content == data, rel
    assert (await client.get("/mobed-app/vendor/leaflet/leaflet.js")).headers["content-type"].startswith(
        ("application/javascript", "text/javascript"))
    assert (await client.get("/mobed-app/vendor/leaflet/images/marker-icon.png")).headers["content-type"] == "image/png"
    # Nothing else was brought in with it.
    present = {p.relative_to(VENDOR).as_posix() for p in VENDOR.rglob("*") if p.is_file()}
    assert present == set(LEAFLET_FILES) | {"LICENSE"}


def test_leaflet_loads_only_where_a_map_is_shown():
    """Not on every page load: the shell does not include it, and only the
    picker module asks for it."""
    assert "leaflet" not in (MOBED / "index.html").read_text(encoding="utf-8").lower()
    users = [p.relative_to(MOBED).as_posix() for p in (MOBED / "js").rglob("*.js")
             if "vendor/leaflet" in p.read_text(encoding="utf-8")]
    assert users == ["js/location_picker.js"]
    picker = (MOBED / "js" / "location_picker.js").read_text(encoding="utf-8")
    assert f'"{OSM_TILES}/{{z}}/{{x}}/{{y}}.png"' in picker
    # OpenStreetMap's attribution is shown on the map, as its licence requires.
    assert "openstreetmap.org/copyright" in picker and "OpenStreetMap</a> contributors" in picker
    sw = (STATIC / "mobed-sw.js").read_text(encoding="utf-8")
    assert "/mobed-app/js/location_picker.js" in sw and "/mobed-app/js/screens/agyari_location.js" in sw
    assert '"/mobed-app/vendor/leaflet' not in sw


def test_the_address_search_goes_through_our_server():
    picker = (MOBED / "js" / "location_picker.js").read_text(encoding="utf-8")
    api = (MOBED / "js" / "api.js").read_text(encoding="utf-8")
    assert "nominatim" not in picker.lower() and "nominatim" not in api.lower()
    assert 'get(`/places/search?q=${encodeURIComponent(q)}`)' in api
