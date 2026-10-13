"""What the Android app (a Trusted Web Activity) needs from the site.

Google Play wraps the PWA; Android opens it full-screen only if the site's
/.well-known/assetlinks.json names the app and its signing key. The manifest
needs PNG icons (a maskable one too), and the start URL must work signed out.
"""

from __future__ import annotations

import json
from pathlib import Path

from agyary.core import config

STATIC = Path(__file__).resolve().parent.parent / "src" / "agyary" / "api" / "static"


async def test_asset_links_name_the_app_and_its_keys(client, monkeypatch):
    body = (await client.get("/.well-known/assetlinks.json")).json()
    [link] = body
    assert link["relation"] == ["delegate_permission/common.handle_all_urls"]
    assert link["target"]["package_name"] == "com.gotiadarian.mobeddiary"
    [upload] = link["target"]["sha256_cert_fingerprints"]
    assert len(upload.split(":")) == 32

    # Play's own signing key is added by a setting, after the upload key.
    monkeypatch.setenv("ANDROID_CERT_FINGERPRINTS", f"{upload}, ab:cd")
    config.get_settings.cache_clear()
    try:
        prints = (await client.get("/.well-known/assetlinks.json")).json()[0]["target"]["sha256_cert_fingerprints"]
        assert prints == [upload, "AB:CD"]
    finally:
        config.get_settings.cache_clear()


async def test_the_manifest_has_png_icons_that_are_served(client):
    manifest = json.loads((STATIC / "mobed-manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == manifest["short_name"] == "Mobed Diary"
    assert manifest["start_url"] == "/mobed" and manifest["display"] == "standalone"
    pngs = [i for i in manifest["icons"] if i["type"] == "image/png"]
    assert {"192x192", "512x512"} <= {i["sizes"] for i in pngs}
    assert any(i["purpose"] == "maskable" for i in pngs)
    for icon in pngs:
        r = await client.get(icon["src"])
        assert r.status_code == 200 and r.headers["content-type"] == "image/png", icon["src"]
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert (await client.get("/anything-else.png")).status_code == 404


async def test_the_start_url_opens_signed_out(client):
    r = await client.get("/mobed")
    assert r.status_code == 200 and "mobed-manifest.json" in r.text
