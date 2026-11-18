"""A fire temple's own list of mobeds, and the panthaky's call-out on WhatsApp
(DECISIONS D10, 18 Nov 2026; Phase 2 Step 5c).

Only a confirmed panthaky of that fire temple (or the admin) reaches the list or
a call-out: a mobed there, or another fire temple's panthaky, gets a 404. A
mobed added by hand needs the consent tick. STOP'd numbers and switched-off
accounts are listed with the reason and never asked. The call-out carries no
family details, and its buttons carry an unguessable token: a forged or unknown
token, or a tap from another number, changes nothing, and only the first tap
counts. Picking sends the details to those picked only; a yes not picked gets
the "enough" text only inside 24 hours. Outbound HTTP is mocked throughout.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, update

from agyary.core import config
from agyary.models import AppNotification, PrayerCalloutAnswer, ReminderOptOut, User
from agyary.services import funeral_whatsapp as fw
from agyary.services import prayer_callout
from tests.conftest import WA_APP_SECRET, sign_in
from tests.funeral_helpers import FAMILY, agyari, auth, form, manager, member

RECORDS = "/api/mobed/manager/records"
PANTHAKY, MOBED, ADMIN = "+919800000001", "+919800000002", "+919800000003"
LISTED, STOPPED, OFF = "+919822200055", "+919822200066", "+919822200077"
LIVE = {
    "FUNERAL_WHATSAPP_MODE": "live", "WHATSAPP_ACCESS_TOKEN": "test-token", "WHATSAPP_PHONE_NUMBER_ID": "555",
    "REMINDERS_ALLOWLIST": "*", "ADMIN_PHONES": ADMIN,
}


class Meta:
    def __init__(self):
        self.sent: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": f"wamid.c{len(self.sent)}"}]})

    def templates(self, name):
        return [m for m in self.sent if m.get("type") == "template" and m["template"]["name"] == name]

    def texts(self):
        return [m for m in self.sent if m.get("type") == "text"]


@pytest.fixture
def meta(monkeypatch):
    fake = Meta()
    monkeypatch.setattr(fw, "make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    from agyary.services import wa_send

    real = wa_send.send_text

    async def send_text(settings, phone, body, client=None):
        return await real(settings, phone, body, client=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))

    monkeypatch.setattr(wa_send, "send_text", send_text)
    return fake


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    from agyary.services import web_push

    async def capture(db, settings, user_ids, **kw):
        sent.append({"to": sorted(user_ids), **kw})
        return 0

    monkeypatch.setattr(web_push, "send_to_users", capture)
    return sent


@pytest.fixture
def live(monkeypatch):
    for key, value in LIVE.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def _list(aid):
    return f"/api/mobed/agyaries/{aid}/our-mobeds"


async def _as(client, phone, name="Er. Test Mobed"):
    return auth(await sign_in(client, phone, name))


async def _accepted(client, db, aid) -> int:
    mgr, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(), headers=mgr)).json()["record"]
    r = await client.post(f"{RECORDS}/{rec['id']}/requests", headers=mgr,
                          json={"agyary_id": aid, "family_agreed": True, "family_whatsapp_agreed": True})
    rid = r.json()["record"]["requests"][0]["id"]
    r = await client.post(f"/api/mobed/requests/{rid}/accept", json={"share_contact": False},
                          headers=await _as(client, PANTHAKY))
    assert r.status_code == 200, r.text
    return rid


async def _signed_tap(client, phone: str, payload: str):
    message = {"type": "button", "from": phone.lstrip("+"), "button": {"payload": payload, "text": "Yes, I can pray"}}
    raw = json.dumps({"entry": [{"changes": [{"value": {"messages": [message]}}]}]}).encode()
    digest = hmac.new(WA_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    r = await client.post("/webhooks/whatsapp", content=raw,
                          headers={"x-hub-signature-256": f"sha256={digest}", "content-type": "application/json"})
    assert r.status_code == 200


async def test_only_a_confirmed_panthaky_or_the_admin_sees_the_list(client, db, seeded, monkeypatch):
    aid = seeded["agyary_id"]
    monkeypatch.setenv("ADMIN_PHONES", ADMIN)
    config.get_settings.cache_clear()
    panthaky = await _as(client, PANTHAKY)
    r = await client.get(_list(aid), headers=panthaky)
    assert r.status_code == 200, r.text
    names = {m["name"]: m for m in r.json()["mobeds"]}
    assert names["Er. Pervez Kias"]["kind"] == "app" and names["Er. Pervez Kias"]["can_message"]
    assert names["Er. Pervez Kias"]["phone"] is None          # an app mobed's number is not shown
    assert names["Er. Hormuz Dadachanji"]["is_me"] and not names["Er. Hormuz Dadachanji"]["can_message"]
    assert r.json()["whatsapp"] == {"on": False, "why_not": fw.OFF_WORDS}

    # A mobed of the same fire temple, and another fire temple's panthaky: it does not exist.
    other = await agyari(db, "Other Agyari (test)", None)
    await member(db, other, "+919822200099", role="panthaky")
    await db.commit()
    for phone in (MOBED, "+919822200099"):
        headers = await _as(client, phone)
        for method, path, body in (("GET", _list(aid), None),
                                   ("POST", _list(aid), {"name": "Er. X", "phone": LISTED, "agreed": True}),
                                   ("DELETE", _list(aid) + "/1", None)):
            r = await client.request(method, path, json=body, headers=headers)
            assert r.status_code == 404, (phone, method, r.text)
    # The admin may.
    admin = await _as(client, ADMIN)
    assert (await client.get(_list(aid), headers=admin)).status_code == 200


async def test_adding_needs_the_tick_and_a_clean_name_and_removing_turns_it_off(client, db, seeded):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    r = await client.post(_list(aid), json={"name": "Er. Listed", "phone": LISTED}, headers=panthaky)
    assert r.status_code == 400 and r.headers["X-Field"] == "agreed" and "tick" in r.json()["detail"]
    r = await client.post(_list(aid), json={"name": "Visit spam.com", "phone": LISTED, "agreed": True},
                          headers=panthaky)
    assert r.status_code == 400 and r.headers["X-Field"] == "name"
    r = await client.post(_list(aid), json={"name": "Er. Kias again", "phone": MOBED, "agreed": True},
                          headers=panthaky)
    assert r.status_code == 409 and "on the list already" in r.json()["detail"]
    r = await client.post(_list(aid), json={"name": "Er. Listed", "phone": "+91 098222 00055", "agreed": True},
                          headers=panthaky)
    assert r.status_code == 200, r.text
    listed = [m for m in r.json()["mobeds"] if m["kind"] == "contact"]
    assert [(m["name"], m["phone"], m["added_by"]) for m in listed] == [("Er. Listed", LISTED, "Er. Hormuz Dadachanji")]
    r = await client.post(_list(aid), json={"name": "Er. Twice", "phone": LISTED, "agreed": True}, headers=panthaky)
    assert r.status_code == 409
    r = await client.delete(f"{_list(aid)}/{listed[0]['id']}", headers=panthaky)
    assert r.status_code == 200 and not [m for m in r.json()["mobeds"] if m["kind"] == "contact"]


async def test_switched_off_the_call_out_explains_and_sends_nothing(client, db, seeded, meta, pushes):
    rid = await _accepted(client, db, seeded["agyary_id"])
    panthaky = await _as(client, PANTHAKY)
    view = (await client.get(f"/api/mobed/requests/{rid}/callout", headers=panthaky)).json()
    assert view["whatsapp"]["on"] is False and view["whatsapp"]["why_not"] == fw.OFF_WORDS
    assert FAMILY not in json.dumps(view) and "Test Family" not in json.dumps(view)
    r = await client.post(f"/api/mobed/requests/{rid}/callout", json={"who": [view["candidates"][0]["key"]]},
                          headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == fw.OFF_WORDS
    assert meta.sent == []
    # Not the panthaky: 404, as for a request that is not accepted.
    r = await client.get(f"/api/mobed/requests/{rid}/callout", headers=await _as(client, MOBED))
    assert r.status_code == 404


async def test_the_whole_call_out(client, db, seeded, meta, pushes, live, caplog):
    caplog.set_level(logging.DEBUG)
    aid = seeded["agyary_id"]
    rid = await _accepted(client, db, aid)
    panthaky = await _as(client, PANTHAKY)
    for name, phone in (("Er. Listed", LISTED), ("Er. Stopped", STOPPED)):
        r = await client.post(_list(aid), json={"name": name, "phone": phone, "agreed": True}, headers=panthaky)
        assert r.status_code == 200, r.text
    db.add(ReminderOptOut(phone=STOPPED, stopped_at=datetime.now(timezone.utc)))
    from agyary.models import Agyary
    await member(db, await db.get(Agyary, aid), OFF, access="off", name="Er. Switched Off")
    await db.commit()
    meta.sent.clear()

    view = (await client.get(f"/api/mobed/requests/{rid}/callout", headers=panthaky)).json()
    by_name = {c["name"]: c for c in view["candidates"]}
    assert set(by_name) == {"Er. Pervez Kias", "Er. Listed", "Er. Stopped", "Er. Switched Off"}
    assert not by_name["Er. Stopped"]["may_ask"] and "STOP" in by_name["Er. Stopped"]["why_not"]
    assert not by_name["Er. Switched Off"]["may_ask"] and "switched off" in by_name["Er. Switched Off"]["why_not"]
    r = await client.post(f"/api/mobed/requests/{rid}/callout", json={"who": [by_name["Er. Stopped"]["key"]]},
                          headers=panthaky)
    assert r.status_code == 400 and meta.sent == []

    who = [by_name["Er. Pervez Kias"]["key"], by_name["Er. Listed"]["key"]]
    r = await client.post(f"/api/mobed/requests/{rid}/callout", json={"who": who}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert r.json()["asked_now"] == 2
    asked = meta.templates("prayer_request_mobeds")
    assert sorted(m["to"] for m in asked) == sorted([MOBED, LISTED])
    for m in asked:
        body = [p["text"] for p in m["template"]["components"][0]["parameters"]]
        assert body[0] == "Behdin Rustom Jamshed" and body[1] == "Doongerwadi (test)"
        assert body[4:] == ["Er. Hormuz Dadachanji", "Goti Adarian"]
        assert FAMILY.lstrip("+") not in json.dumps(m) and "Test Family" not in json.dumps(m)
        buttons = [c for c in m["template"]["components"] if c["type"] == "button"]
        assert [b["sub_type"] for b in buttons] == ["quick_reply", "quick_reply"]
    answers = {a.phone: a for a in (await db.execute(select(PrayerCalloutAnswer))).scalars()}
    for a in answers.values():
        assert len(a.token) >= 20 and str(a.id) != a.token
    kias, listed = answers[MOBED], answers[LISTED]
    payload = next(m for m in asked if m["to"] == MOBED)["template"]["components"][1]["parameters"][0]["payload"]
    assert payload == f"pca:{kias.token}:y"
    # Asking the same people again for this request is refused.
    r = await client.post(f"/api/mobed/requests/{rid}/callout", json={"who": who}, headers=panthaky)
    assert r.status_code == 400 and "asked already" in r.json()["detail"]

    # Forged, unknown, or from another number: nothing changes.
    await _signed_tap(client, MOBED, "pca:" + "x" * 24 + ":y")
    await _signed_tap(client, MOBED, f"pca:{kias.token}:maybe")
    await _signed_tap(client, LISTED, f"pca:{kias.token}:y")
    await db.refresh(kias)
    assert kias.answer is None
    # The real tap counts, once.
    await _signed_tap(client, MOBED, f"pca:{kias.token}:y")
    await _signed_tap(client, MOBED, f"pca:{kias.token}:n")
    await _signed_tap(client, LISTED, f"pca:{listed.token}:y")
    await db.refresh(kias)
    await db.refresh(listed)
    assert kias.answer == "yes" and listed.answer == "yes"
    panthaky_user = (await db.execute(select(User).where(User.phone == PANTHAKY))).scalar_one()
    notes = (await db.execute(select(AppNotification).where(AppNotification.user_id == panthaky_user.id,
                                                             AppNotification.kind == prayer_callout.KIND_YES))).scalars().all()
    assert sorted(n.title for n in notes) == ["Er. Listed can pray", "Er. Pervez Kias can pray"]
    yes_pushes = [p for p in pushes if p["tag"].startswith("callout-yes")]
    assert len(yes_pushes) == 2 and all("Rustom" not in p["body"] and "Family" not in p["body"] for p in yes_pushes)
    kias_user = (await db.execute(select(User).where(User.phone == MOBED))).scalar_one()
    assert (await db.execute(select(AppNotification).where(
        AppNotification.user_id == kias_user.id, AppNotification.kind == prayer_callout.KIND_MY_YES))).scalars().all()

    # The listed mobed answered over a day ago: too late for the "enough" text.
    await db.execute(update(PrayerCalloutAnswer).where(PrayerCalloutAnswer.id == listed.id)
                     .values(answered_at=datetime.now(timezone.utc) - timedelta(hours=25)))
    await db.commit()
    meta.sent.clear()
    r = await client.post(f"/api/mobed/requests/{rid}/callout/pick", json={"answers": [kias.id]}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert r.json()["done"] == {"picked": 1, "details_sent": 1, "enough_sent": 0, "enough_too_late": 1}
    details = meta.templates("prayer_details_mobed")
    assert [m["to"] for m in details] == [MOBED] and meta.texts() == []
    body = [p["text"] for p in details[0]["template"]["components"][0]["parameters"]]
    assert body[5:] == ["Test Family", FAMILY]
    people = {p["name"]: p for p in r.json()["asked"]}
    assert people["Er. Pervez Kias"]["picked"] and people["Er. Pervez Kias"]["details"]["state"] == "Sent"
    assert people["Er. Listed"]["enough"]["state"] == "Not told" and "24 hours" in people["Er. Listed"]["enough"]["why"]
    for number in (PANTHAKY, MOBED, LISTED, FAMILY, STOPPED):
        assert number not in caplog.text and number.lstrip("+") not in caplog.text


async def test_a_yes_not_picked_inside_the_window_is_told_enough_are_going(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    rid = await _accepted(client, db, aid)
    panthaky = await _as(client, PANTHAKY)
    r = await client.post(_list(aid), json={"name": "Er. Listed", "phone": LISTED, "agreed": True}, headers=panthaky)
    view = r.json()
    keys = [m["key"] for m in view["mobeds"] if m["can_message"]]
    r = await client.post(f"/api/mobed/requests/{rid}/callout", json={"who": keys}, headers=panthaky)
    assert r.status_code == 200, r.text
    answers = {a.phone: a for a in (await db.execute(select(PrayerCalloutAnswer))).scalars()}
    for phone, a in answers.items():
        await _signed_tap(client, phone, f"pca:{a.token}:y")
    meta.sent.clear()
    r = await client.post(f"/api/mobed/requests/{rid}/callout/pick", json={"answers": [answers[LISTED].id]},
                          headers=panthaky)
    assert r.status_code == 200, r.text
    assert [m["to"] for m in meta.templates("prayer_details_mobed")] == [LISTED]
    (text,) = meta.texts()
    assert text["to"] == MOBED and text["text"]["body"] == fw.ENOUGH_TEXT
    # Picking someone who said no (or nothing) is refused.
    r = await client.post(f"/api/mobed/requests/{rid}/callout/pick", json={"answers": [999]}, headers=panthaky)
    assert r.status_code == 400
