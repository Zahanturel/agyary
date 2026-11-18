"""Phone notifications for admins (web push): a new mobed waiting shows on the
admin's phone even when the app is closed (DECISIONS D9).

The end-to-end test plays the phone: it makes the keys a browser would, lets
the real library encrypt and sign a notification, catches what would have gone
to the push service, and opens it with the phone's key - so what a real phone
receives is proved here, not just that something was called.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from urllib.parse import urlparse

import http_ece
import jwt
import pytest
import pywebpush
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from agyary.core import config
from agyary.models import PushSubscription
from agyary.scripts import vapid_keys
from agyary.services import web_push
from tests.conftest import sign_in
from tests.test_frontend_session import JS, NODE, STORAGE, _module, _node

ENDPOINT = "https://fcm.googleapis.com/fcm/send/test-device-1"
NEW = "+919911100088"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Phone:
    """The keys a browser makes when it subscribes."""

    def __init__(self, endpoint=ENDPOINT):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = secrets.token_bytes(16)
        self.endpoint = endpoint

    def subscription(self) -> dict:
        public = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return {"endpoint": self.endpoint, "keys": {"p256dh": _b64(public), "auth": _b64(self.auth)}}

    def open(self, body: bytes) -> dict:
        return json.loads(http_ece.decrypt(body, private_key=self.key, auth_secret=self.auth, version="aes128gcm"))


class FakePushService:
    """Stands in for Google's push service: keeps what was sent, answers `status`."""

    def __init__(self, monkeypatch, status=201):
        self.sent, self.status = [], status
        monkeypatch.setattr(pywebpush.requests, "post", self.post)

    def post(self, url, timeout=None, data=None, headers=None, **_):
        self.sent.append({"url": url, "data": data, "headers": headers})
        response = pywebpush.requests.models.Response()
        response.status_code = self.status
        response._content = b""
        return response


@pytest.fixture
def keys(monkeypatch):
    public, private = vapid_keys.make()
    monkeypatch.setenv("VAPID_PUBLIC_KEY", public)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", private)
    config.get_settings.cache_clear()
    yield public
    config.get_settings.cache_clear()


@pytest.fixture
def admin_is_panthaky(monkeypatch, seeded):
    monkeypatch.setenv("ADMIN_PHONES", seeded["panthaky_phone"])
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def _admin(client, seeded) -> dict:
    body = await sign_in(client, seeded["panthaky_phone"])
    return {"Authorization": f"Bearer {body['access_token']}"}


# --- Turning it on ------------------------------------------------------------

async def test_without_keys_the_server_says_it_is_not_set_up(client, seeded, admin_is_panthaky):
    admin = await _admin(client, seeded)
    status = (await client.get("/api/mobed/admin/push", headers=admin)).json()
    assert status == {"configured": False, "public_key": None, "devices": 0}
    r = await client.post("/api/mobed/admin/push/subscribe", json=Phone().subscription(), headers=admin)
    assert r.status_code == 409 and r.json()["detail"] == "Phone notifications are not set up on the server yet."


async def test_an_admin_turns_it_on_for_a_phone_and_off_again(client, db, seeded, admin_is_panthaky, keys):
    admin = await _admin(client, seeded)
    status = (await client.get("/api/mobed/admin/push", headers=admin)).json()
    assert status == {"configured": True, "public_key": keys, "devices": 0}
    phone = Phone()
    r = await client.post("/api/mobed/admin/push/subscribe", json=phone.subscription(), headers=admin)
    assert r.status_code == 200 and r.json()["devices"] == 1
    # The same phone again is still one phone.
    r = await client.post("/api/mobed/admin/push/subscribe", json=phone.subscription(), headers=admin)
    assert r.json()["devices"] == 1
    r = await client.post("/api/mobed/admin/push/unsubscribe", json={"endpoint": ENDPOINT}, headers=admin)
    assert r.json()["devices"] == 0


async def test_only_a_real_push_service_is_accepted(client, seeded, admin_is_panthaky, keys):
    admin = await _admin(client, seeded)
    for endpoint in ("https://evil.example/collect", "http://fcm.googleapis.com/fcm/send/x",
                     "https://fcm.googleapis.com.evil.example/x", "https://169.254.169.254/latest"):
        r = await client.post("/api/mobed/admin/push/subscribe", json=Phone(endpoint).subscription(), headers=admin)
        assert r.status_code == 400, endpoint
    for endpoint in ("https://web.push.apple.com/QA1", "https://updates.push.services.mozilla.com/wpush/v2/x",
                     "https://wns2-bl2p.notify.windows.com/w/?token=x"):
        assert web_push.allowed_endpoint(endpoint), endpoint


async def test_a_mobed_who_is_not_an_admin_cannot_use_it(client, seeded, admin_is_panthaky, keys):
    body = await sign_in(client, seeded["mobed_phone"])
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert (await client.get("/api/mobed/admin/push", headers=headers)).status_code == 404
    r = await client.post("/api/mobed/admin/push/subscribe", json=Phone().subscription(), headers=headers)
    assert r.status_code == 404


# --- What the phone receives --------------------------------------------------

async def test_a_new_mobed_waiting_reaches_the_admins_phone_encrypted_and_signed(
    client, db, seeded, admin_is_panthaky, keys, monkeypatch,
):
    admin = await _admin(client, seeded)
    phone = Phone()
    await client.post("/api/mobed/admin/push/subscribe", json=phone.subscription(), headers=admin)
    service = FakePushService(monkeypatch)

    body = await sign_in(client, NEW, "Er. Rustom Irani", approve=False)
    mobed = {"Authorization": f"Bearer {body['access_token']}"}
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=mobed)
    assert r.status_code == 200

    (sent,) = service.sent
    assert sent["url"] == ENDPOINT
    assert sent["headers"]["content-encoding"] == "aes128gcm"
    assert sent["headers"]["ttl"] == str(web_push.TTL_SECONDS)
    assert sent["headers"]["Urgency"] == "high"
    # The phone can open it, and it says the right thing.
    assert phone.open(sent["data"]) == {
        "title": "A new mobed is waiting",
        "body": "Er. Rustom Irani from Goti Adarian wants to use Mobed Diary. Tap to approve.",
        "url": "/mobed#/admin/mobeds",
        "tag": "mobed-request",
    }
    # Signed with our key, for Google's push service, naming us.
    auth = sent["headers"]["Authorization"]
    assert auth.startswith("vapid t=")
    token = auth.split("t=")[1].split(",")[0]
    k = auth.split("k=")[1].strip()
    assert k == keys
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _unb64(keys))
    claims = jwt.decode(token, public, algorithms=["ES256"], audience="https://fcm.googleapis.com")
    assert claims["sub"] == "https://mobed.gotiadarian.com"


async def test_a_phone_the_push_service_says_is_gone_is_forgotten(
    client, db, seeded, admin_is_panthaky, keys, monkeypatch,
):
    admin = await _admin(client, seeded)
    await client.post("/api/mobed/admin/push/subscribe", json=Phone().subscription(), headers=admin)
    FakePushService(monkeypatch, status=410)
    r = await client.post("/api/mobed/admin/push/test", headers=admin)
    assert r.status_code == 200 and r.json() == {"sent": 0, "devices": 0}
    assert (await db.execute(select(PushSubscription))).first() is None


async def test_a_push_service_that_fails_never_stops_the_sign_up(
    client, db, seeded, admin_is_panthaky, keys, monkeypatch,
):
    admin = await _admin(client, seeded)
    await client.post("/api/mobed/admin/push/subscribe", json=Phone().subscription(), headers=admin)

    def down(*_, **__):
        raise pywebpush.requests.ConnectionError("no route")

    monkeypatch.setattr(pywebpush.requests, "post", down)
    body = await sign_in(client, NEW, approve=False)
    mobed = {"Authorization": f"Bearer {body['access_token']}"}
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=mobed)
    assert r.status_code == 200
    # The in-app notice is there all the same, and the phone is kept for next time.
    titles = [n["title"] for n in (await client.get("/api/mobed/notifications", headers=admin)).json()]
    assert "A new mobed is waiting" in titles
    assert (await db.execute(select(PushSubscription))).first() is not None


async def test_the_test_button_reaches_the_admins_phones(client, seeded, admin_is_panthaky, keys, monkeypatch):
    admin = await _admin(client, seeded)
    phone = Phone()
    await client.post("/api/mobed/admin/push/subscribe", json=phone.subscription(), headers=admin)
    service = FakePushService(monkeypatch)
    r = await client.post("/api/mobed/admin/push/test", headers=admin)
    assert r.json() == {"sent": 1, "devices": 1}
    assert phone.open(service.sent[0]["data"])["tag"] == "push-test"


# --- Making the keys ------------------------------------------------------------

def test_the_key_maker_writes_two_lines_for_the_env_file(monkeypatch, capsys):
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "")
    config.get_settings.cache_clear()
    try:
        assert vapid_keys.main() == 0
    finally:
        config.get_settings.cache_clear()
    out = capsys.readouterr()
    lines = dict(line.split("=", 1) for line in out.out.splitlines() if "=" in line and not line.startswith("#"))
    assert set(lines) == {"VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY"}
    assert len(_unb64(lines["VAPID_PUBLIC_KEY"])) == 65 and len(_unb64(lines["VAPID_PRIVATE_KEY"])) == 32
    assert "VAPID_PRIVATE_KEY" not in out.err          # nothing secret on the screen


def test_the_key_maker_refuses_when_keys_exist(monkeypatch, capsys, keys):
    assert vapid_keys.main() == 1
    out = capsys.readouterr()
    assert out.out == "" and "already set" in out.err


# --- Every account, from Settings (D10, Phase 2 Step 4) ----------------------------

async def test_a_mobed_turns_it_on_and_a_doongerwadis_request_reaches_their_phone(
    client, db, seeded, keys, monkeypatch,
):
    """A mobed who is no admin turns notifications on from Settings; a
    Doongerwadi's request to their fire temple then reaches the phone, and
    what the phone shows says only which place asks which fire temple: no
    departed's name, no family's name or number."""
    from tests.funeral_helpers import FAMILY, form, manager

    panthaky = {"Authorization": f"Bearer {(await sign_in(client, seeded['panthaky_phone']))['access_token']}"}
    status = (await client.get("/api/mobed/me/push", headers=panthaky)).json()
    assert status == {"configured": True, "public_key": keys, "devices": 0}
    phone = Phone()
    r = await client.post("/api/mobed/me/push/subscribe", json=phone.subscription(), headers=panthaky)
    assert r.status_code == 200 and r.json()["devices"] == 1
    # The admin page is still not theirs.
    assert (await client.get("/api/mobed/admin/push", headers=panthaky)).status_code == 404

    service = FakePushService(monkeypatch)
    headers, _ = await manager(client, db)
    rec = (await client.post("/api/mobed/manager/records", json=form(), headers=headers)).json()["record"]
    r = await client.post(f"/api/mobed/manager/records/{rec['id']}/requests",
                          json={"agyary_id": seeded["agyary_id"], "family_agreed": True}, headers=headers)
    assert r.status_code == 200, r.text
    (sent,) = service.sent
    shown = phone.open(sent["data"])
    assert shown == {
        "title": "A request for prayers",
        "body": "Doongerwadi (test) asks Goti Adarian for prayers.",
        "url": "/mobed#/requests",
        "tag": f"funeral-request-{r.json()['record']['requests'][0]['id']}",
    }
    raw = str(shown)
    assert FAMILY[3:] not in raw and "Test Family" not in raw and "Rustom" not in raw

    # Their own test button, and off again.
    service.sent.clear()
    r = await client.post("/api/mobed/me/push/test", headers=panthaky)
    assert r.json() == {"sent": 1, "devices": 1} and phone.open(service.sent[0]["data"])["tag"] == "push-test"
    r = await client.post("/api/mobed/me/push/unsubscribe", json={"endpoint": ENDPOINT}, headers=panthaky)
    assert r.json()["devices"] == 0


async def test_a_manager_can_turn_it_on_too_and_only_a_real_push_service_is_taken(client, db, seeded, keys):
    from tests.funeral_helpers import manager

    headers, _ = await manager(client, db)
    assert (await client.get("/api/mobed/me/push", headers=headers)).json()["configured"] is True
    r = await client.post("/api/mobed/me/push/subscribe", json=Phone().subscription(), headers=headers)
    assert r.status_code == 200 and r.json()["devices"] == 1
    r = await client.post("/api/mobed/me/push/subscribe", json=Phone("https://evil.example/x").subscription(),
                          headers=headers)
    assert r.status_code == 400


async def test_an_account_that_is_not_on_cannot_turn_it_on_but_can_turn_it_off(client, db, seeded, keys):
    body = await sign_in(client, NEW, approve=False)
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    r = await client.post("/api/mobed/me/push/subscribe", json=Phone().subscription(), headers=headers)
    assert r.status_code == 403 and r.headers["X-Mobed-Access"] == "pending"
    assert (await client.post("/api/mobed/me/push/test", headers=headers)).status_code == 403
    r = await client.post("/api/mobed/me/push/unsubscribe", json={"endpoint": ENDPOINT}, headers=headers)
    assert r.status_code == 200 and r.json()["devices"] == 0


async def test_without_keys_settings_says_it_is_not_set_up(client, seeded):
    body = await sign_in(client, seeded["mobed_phone"])
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert (await client.get("/api/mobed/me/push", headers=headers)).json() == {
        "configured": False, "public_key": None, "devices": 0}
    r = await client.post("/api/mobed/me/push/subscribe", json=Phone().subscription(), headers=headers)
    assert r.status_code == 409


# --- The phone's side -------------------------------------------------------------

@pytest.mark.skipif(NODE is None, reason="Node is not installed")
def test_the_app_says_why_a_phone_cannot_have_notifications():
    out = _node(STORAGE + f"""
const {{ pushBlocker, keyBytes }} = await import({json.dumps(_module(JS / "push.js"))});
const ok = {{ hasServiceWorker: true, hasPushManager: true, hasNotification: true, permission: "default",
              platform: "android", asApp: false }};
console.log(JSON.stringify({{
  android: pushBlocker(ok),
  iphoneSafari: pushBlocker({{ ...ok, platform: "ios", asApp: false }}),
  iphoneApp: pushBlocker({{ ...ok, platform: "ios", asApp: true }}),
  noPush: pushBlocker({{ ...ok, hasPushManager: false }}),
  denied: pushBlocker({{ ...ok, permission: "denied" }}),
  key: Array.from(keyBytes("AQID_-8")),
}}));
""")
    assert out["android"] is None and out["iphoneApp"] is None
    assert "Add to Home Screen" in out["iphoneSafari"]
    assert "Chrome" in out["noPush"]
    assert "blocked" in out["denied"]
    assert out["key"] == [1, 2, 3, 255, 239]


def test_the_service_worker_shows_and_opens_notifications():
    sw = (JS.parent.parent / "mobed-sw.js").read_text(encoding="utf-8")
    assert 'addEventListener("push"' in sw and "showNotification" in sw
    assert 'addEventListener("notificationclick"' in sw and "openWindow" in sw
    assert '"/mobed-app/js/push.js"' in sw
    assert os.path.exists(JS.parent.parent / "mobed-icon-192.png")
    assert urlparse("/mobed#/admin/mobeds").path == "/mobed"
