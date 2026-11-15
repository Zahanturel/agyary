"""What the Android app (a Trusted Web Activity) needs from the site.

Google Play wraps the PWA; Android opens it full-screen only if the site's
/.well-known/assetlinks.json names the app and its signing key. The manifest
needs PNG icons (a maskable one too), and the start URL must work signed out.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from agyary.core import config

STATIC = Path(__file__).resolve().parent.parent / "src" / "agyary" / "api" / "static"
APK = STATIC / "android" / "mobed-diary.apk"


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


# --- "Download the app", on the sign-in page of an Android phone ---------------

async def test_the_download_button_gets_the_app(client):
    """The page links to /download/android. It points at the APK under a name
    that changes with every build (Cloudflare keeps .apk files at the edge),
    and the file comes as a download, named for the phone's Downloads."""
    r = await client.get("/download/android", follow_redirects=False)
    assert r.status_code == 307 and r.headers["cache-control"] == "no-store"
    where = r.headers["location"]
    assert re.fullmatch(r"/download/mobed-diary-[0-9a-f]{12}\.apk", where), where

    apk = await client.get(where)
    assert apk.status_code == 200
    assert apk.headers["content-type"] == "application/vnd.android.package-archive"
    assert apk.headers["content-disposition"] == 'attachment; filename="Mobed-Diary.apk"'
    assert "immutable" in apk.headers["cache-control"]
    assert apk.content == APK.read_bytes()

    head = await client.head(where)
    assert head.status_code == 200 and int(head.headers["content-length"]) == APK.stat().st_size


async def test_an_old_download_address_gives_the_current_app(client):
    current = (await client.get("/download/android", follow_redirects=False)).headers["location"]
    r = await client.get("/download/mobed-diary-000000000000.apk", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == current


def _length_prefixed(buf: bytes, at: int) -> tuple[bytes, int]:
    n = int.from_bytes(buf[at:at + 4], "little")
    return buf[at + 4:at + 4 + n], at + 4 + n


def _signing_certificates(apk: bytes) -> list[bytes]:
    """The X.509 certificates in an APK's v2/v3 signature block (what Android
    checks, and what asset links must name)."""
    end = apk.rfind(b"PK\x05\x06")
    directory = int.from_bytes(apk[end + 16:end + 20], "little")
    assert apk[directory - 16:directory] == b"APK Sig Block 42", "the APK is not v2/v3 signed"
    # The block's size (which leaves out its own first 8 bytes), the ID-value
    # pairs, the size again and the magic, just before the central directory.
    size = int.from_bytes(apk[directory - 24:directory - 16], "little")
    pairs = apk[directory - size:directory - 24]
    certs: list[bytes] = []
    at = 0
    while at < len(pairs):
        length = int.from_bytes(pairs[at:at + 8], "little")
        kind = int.from_bytes(pairs[at + 8:at + 12], "little")
        if kind in (0x7109871A, 0xF05368C0):  # v2, v3
            signers, _ = _length_prefixed(pairs[at + 12:at + 8 + length], 0)
            s = 0
            while s < len(signers):
                signer, s = _length_prefixed(signers, s)
                signed, _ = _length_prefixed(signer, 0)
                _digests, c = _length_prefixed(signed, 0)
                chain, _ = _length_prefixed(signed, c)
                k = 0
                while k < len(chain):
                    cert, k = _length_prefixed(chain, k)
                    certs.append(cert)
        at += 8 + length
    return certs


def test_the_apk_on_offer_is_the_app_signed_with_the_key_asset_links_name():
    """A different build (a debug one, another key) would still install, but it
    would open with a browser bar, and could not update the copy mobeds already
    have from the WhatsApp group."""
    data = APK.read_bytes()
    # "About 2 MB", as the card says.
    assert 1_000_000 < len(data) < 3_000_000
    manifest = zipfile.ZipFile(io.BytesIO(data)).read("AndroidManifest.xml")
    package = config.get_settings().android_package_name
    assert package.encode("utf-16-le") in manifest or package.encode() in manifest

    allowed = {p.strip().replace(":", "").lower()
               for p in config.get_settings().android_cert_fingerprints.split(",") if p.strip()}
    certs = _signing_certificates(data)
    assert certs, "no signing certificate found"
    for cert in certs:
        assert hashlib.sha256(cert).hexdigest() in allowed


async def test_the_iphone_home_screen_icon_is_served_and_solid(client):
    """iOS paints a transparent corner black, so its icon fills the square."""
    page = (await client.get("/mobed")).text
    assert '<link rel="apple-touch-icon" href="/mobed-icon-180.png">' in page
    r = await client.get("/mobed-icon-180.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    png = r.content
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and png[12:16] == b"IHDR"
    width, height = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    colour_type = png[25]
    assert (width, height) == (180, 180)
    assert colour_type == 2, "the icon must be RGB with no transparency"
