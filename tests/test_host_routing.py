"""There is one app, whatever the hostname.

Machi is a tab of the Mobed Diary, not an app of its own, so a bare hostname -
mobed.gotiadarian.com, the apex, a staging domain, a machine name - lands in
the same place. (The old machi.gotiadarian.com host is gone from the app; if its
DNS record is still there it simply opens the same thing.)
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "host",
    ["mobed.gotiadarian.com", "machi.gotiadarian.com", "gotiadarian.com", "localhost:8000", "127.0.0.1:8000"],
)
async def test_every_host_lands_in_the_app(client, host):
    r = await client.get("/", headers={"Host": host}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/mobed"


async def test_the_redirect_is_temporary(client):
    """301 would be cached by browsers indefinitely and outlive any change
    to where the app lives."""
    r = await client.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.status_code != 301


async def test_privacy_policy_is_public_on_every_host(client):
    """Meta will not publish the app without a policy URL, and its reviewer
    is not going to sign in with WhatsApp to reach one. So this has to answer
    200 with no session, no cookie and no JavaScript, on whichever hostname
    the reviewer happens to use."""
    for host in ("machi.gotiadarian.com", "mobed.gotiadarian.com", "gotiadarian.com"):
        r = await client.get("/privacy", headers={"Host": host})
        assert r.status_code == 200, host
        assert r.headers["content-type"].startswith("text/html")
        body = r.text
        assert "<script" not in body.lower(), "must render without JavaScript"
        # The two disclosures that make it a policy rather than a page.
        assert "Meta" in body and "mailto:" in body


async def test_the_policy_says_what_the_app_really_does_and_deletion_is_public(client):
    """It must match the app (PV-1): reminders to families with their consent,
    STOP, and how to delete. And Google Play needs a deletion page anyone can
    read without signing in."""
    policy = (await client.get("/privacy")).text
    for fact in ("agreed", "STOP", "Delete my account", "Cloudflare", "/delete-account"):
        assert fact in policy, fact
    assert "never send" not in policy.lower()
    page = await client.get("/delete-account", headers={"Host": "mobed.gotiadarian.com"})
    assert page.status_code == 200 and "<script" not in page.text.lower()
    assert "Delete everything" in page.text and "contact@gotiadarian.com" in page.text


async def test_the_app_is_reachable_by_path_on_any_host_and_machi_has_no_app_of_its_own(client):
    """An installed PWA opens its start_url directly. The separate Machi app,
    its manifest and its service worker are gone."""
    for host in ("mobed.gotiadarian.com", "machi.gotiadarian.com"):
        assert (await client.get("/mobed", headers={"Host": host})).status_code == 200, host
    for path in ("/machi", "/machi-manifest.json", "/machi-sw.js"):
        assert (await client.get(path)).status_code == 404, path
