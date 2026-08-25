"""Which PWA a bare hostname lands in.

mobed.gotiadarian.com and machi.gotiadarian.com are one app behind one
tunnel, so the Host header is the only thing that distinguishes them. A
Cloudflare Tunnel ingress rule cannot do this: it matches on hostname and
path, it does not prepend one, so both hostnames arrive at "/".
"""

from __future__ import annotations

import pytest

from agyary.api.main import app_path_for_host


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("mobed.gotiadarian.com", "/mobed"),
        ("machi.gotiadarian.com", "/machi"),
        # Case is not significant in DNS, and browsers do send what was typed.
        ("MACHI.GOTIADARIAN.COM", "/machi"),
        ("Machi.Gotiadarian.Com", "/machi"),
        # A Host header carries the port when it is not the scheme default.
        ("machi.gotiadarian.com:8000", "/machi"),
        ("mobed.gotiadarian.com:443", "/mobed"),
        # Keyed on the leftmost label, so a staging domain works untouched.
        ("machi.staging.example.org", "/machi"),
    ],
)
def test_hostname_picks_its_app(host, expected):
    assert app_path_for_host(host) == expected


@pytest.mark.parametrize(
    "host",
    [
        "gotiadarian.com",      # the apex belongs to neither
        "www.gotiadarian.com",
        "localhost:8000",
        "127.0.0.1:8000",
        "",
        None,                    # HTTP/1.0, or a client that sent no Host
    ],
)
def test_anything_unrecognised_falls_back_to_the_mobed_app(host):
    assert app_path_for_host(host) == "/mobed"


async def test_root_redirects_by_host(client):
    r = await client.get("/", headers={"Host": "machi.gotiadarian.com"}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/machi"

    r = await client.get("/", headers={"Host": "mobed.gotiadarian.com"}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/mobed"


async def test_redirect_is_temporary_and_varies_on_host(client):
    """301 would be cached by browsers indefinitely and outlive any change
    to the mapping. Vary: Host because the response really does differ by
    it - a shared cache missing that serves one app's users the other."""
    r = await client.get("/", headers={"Host": "machi.gotiadarian.com"}, follow_redirects=False)
    assert r.status_code == 307
    assert r.status_code != 301
    assert r.headers.get("vary") == "Host"


async def test_both_shells_are_still_reachable_by_path_on_any_host(client):
    """The redirect is a convenience for a bare hostname, not the only way
    in. An installed PWA opens its start_url directly."""
    for host in ("machi.gotiadarian.com", "mobed.gotiadarian.com"):
        for path in ("/mobed", "/machi"):
            r = await client.get(path, headers={"Host": host})
            assert r.status_code == 200, f"{host}{path}"
