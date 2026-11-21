"""A fire temple's own list of mobeds, and the call-out on WhatsApp (DECISIONS
D10, 18 Nov 2026, changed 19 Nov 2026; Phase 2 Step 5c).

Only a confirmed panthaky of that fire temple (or the admin) reaches the list or
a call-out: a mobed there, or another fire temple's panthaky, gets a 404. A
mobed added by hand needs the consent tick. The call-out goes when the request
is sent, to everyone who can be messaged except the panthaky: STOP'd numbers
and switched-off accounts are listed with the reason and never asked, and
nobody is asked twice for one request. It carries no family details, and its
buttons carry an unguessable token: a forged or unknown token, or a tap from
another number, changes nothing, and only the first tap counts. The first yeses,
up to the number wanted (2 if not given), go and get the details; a later yes is
thanked; a withdrawn or declined request is told to those who said yes, inside
24 hours. A call-out that breaks never stops the request. Outbound HTTP is
mocked throughout.
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
from agyary.models import (
    Agyary,
    AgyaryUser,
    AppNotification,
    FuneralRequest,
    PrayerCallout,
    PrayerCalloutAnswer,
    ReminderOptOut,
    User,
)
from agyary.services import funeral_whatsapp as fw
from agyary.services import prayer_callout, request_settings
from tests.conftest import WA_APP_SECRET, sign_in
from tests.funeral_helpers import FAMILY, agyari, auth, form, manager, member

RECORDS = "/api/mobed/manager/records"
PANTHAKY, MOBED, ADMIN = "+919800000001", "+919800000002", "+919800000003"
LISTED, STOPPED, OFF, SECOND = "+919822200055", "+919822200066", "+919822200077", "+919822200088"
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


async def _send(client, db, aid, mgr=None, **changes) -> tuple[int, dict, dict]:
    """A record sent to the fire temple: the call-out goes now (19 Nov 2026)."""
    if mgr is None:
        mgr, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(**changes), headers=mgr)).json()["record"]
    r = await client.post(f"{RECORDS}/{rec['id']}/requests", headers=mgr,
                          json={"agyary_id": aid, "family_agreed": True, "family_whatsapp_agreed": True})
    assert r.status_code == 200, r.text
    return r.json()["record"]["requests"][0]["id"], r.json(), mgr


async def _answers(db) -> dict[str, PrayerCalloutAnswer]:
    return {a.phone: a for a in (await db.execute(select(PrayerCalloutAnswer)
                                                   .execution_options(populate_existing=True))).scalars()}


async def _notes(db, phone, kind) -> list[AppNotification]:
    user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
    return list((await db.execute(select(AppNotification).where(
        AppNotification.user_id == user.id, AppNotification.kind == kind).order_by(AppNotification.id))).scalars())


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
    # The Mobeds page shows an app mobed's number (owner, 21 Nov 2026; tests/test_mobeds_page.py).
    assert names["Er. Pervez Kias"]["phone"] == MOBED
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



async def test_switched_off_nothing_goes_at_send_and_the_screens_say_why(client, db, seeded, meta, pushes):
    rid, res, _ = await _send(client, db, seeded["agyary_id"])
    # Nothing on WhatsApp; the app mobed is asked in the app all the same (R3.1 step 4).
    assert res["callout"] == {"state": "sent", "asked": 0, "asked_in_app": 1,
                              "message": f"1 mobed of Goti Adarian was asked in the app. {fw.OFF_WORDS}"}
    assert meta.sent == []
    (row,) = (await _answers(db)).values()
    assert row.phone == MOBED and row.how == "app" and row.answer is None
    panthaky = await _as(client, PANTHAKY)
    view = (await client.get(f"/api/mobed/requests/{rid}/callout", headers=panthaky)).json()
    assert view["whatsapp"] == {"on": False, "why_not": fw.OFF_WORDS}
    assert view["open"] is True and view["going"] == 0 and view["wanted"] == 5
    assert [(p["name"], p["asked"], p["answer"]) for p in view["asked"]] == [("Er. Pervez Kias", None, None)]
    assert FAMILY not in json.dumps(view) and "Test Family" not in json.dumps(view)
    r = await client.post(f"/api/mobed/requests/{rid}/callout", json={"who": [view["candidates"][0]["key"]]},
                          headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == fw.OFF_WORDS
    assert meta.sent == []
    # The request's own page shows the panthaky the call-out while it waits.
    page = (await client.get(f"/api/mobed/requests/{rid}", headers=panthaky)).json()["request"]
    assert page["may_call_out"] is True and page["callout"] == {"asked": 1, "yes": 0, "going": 0, "wanted": 5}
    assert page["callout_whatsapp"]["on"] is False
    # Not the panthaky: 404.
    r = await client.get(f"/api/mobed/requests/{rid}/callout", headers=await _as(client, MOBED))
    assert r.status_code == 404


async def test_the_call_out_goes_at_send_and_the_first_yes_goes(client, db, seeded, meta, pushes, live, caplog):
    caplog.set_level(logging.DEBUG)
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    for name, phone in (("Er. Listed", LISTED), ("Er. Stopped", STOPPED)):
        r = await client.post(_list(aid), json={"name": name, "phone": phone, "agreed": True}, headers=panthaky)
        assert r.status_code == 200, r.text
    db.add(ReminderOptOut(phone=STOPPED, stopped_at=datetime.now(timezone.utc)))
    from agyary.models import Agyary
    await member(db, await db.get(Agyary, aid), OFF, access="off", name="Er. Switched Off")
    await db.commit()

    rid, res, _ = await _send(client, db, aid, mobeds_wanted=1)
    assert res["callout"]["state"] == "sent" and res["callout"]["asked"] == 2
    assert res["callout"]["message"] == "1 mobed of Goti Adarian was asked in the app, and 2 on WhatsApp."
    # Not the panthaky (the request is in their app, and it asks the mobeds to tell them),
    # not a STOP'd number, not an account that is off.
    asked = meta.templates("prayer_request_mobeds_v2")
    assert sorted(m["to"] for m in asked) == sorted([MOBED, LISTED])
    for m in asked:
        body = [p["text"] for p in m["template"]["components"][0]["parameters"]]
        assert body[0] == "Goti Adarian" and body[1] == "Behdin Rustom Jamshed" and body[2] == "Doongerwadi (test)"
        assert body[5] == "Er. Hormuz Dadachanji" and len(body) == 6
        assert FAMILY.lstrip("+") not in json.dumps(m) and "Test Family" not in json.dumps(m)
        buttons = [c for c in m["template"]["components"] if c["type"] == "button"]
        assert [b["sub_type"] for b in buttons] == ["quick_reply", "quick_reply"]
    answers = await _answers(db)
    for a in answers.values():
        assert len(a.token) >= 20 and str(a.id) != a.token
    kias, listed = answers[MOBED], answers[LISTED]
    payload = next(m for m in asked if m["to"] == MOBED)["template"]["components"][1]["parameters"][0]["payload"]
    assert payload == f"pca:{kias.token}:y"

    # Each is asked once per request; those who could not be asked say why.
    view = (await client.get(f"/api/mobed/requests/{rid}/callout", headers=panthaky)).json()
    by_name = {c["name"]: c for c in view["candidates"]}
    assert by_name["Er. Pervez Kias"]["asked_already"] and by_name["Er. Listed"]["asked_already"]
    assert not by_name["Er. Stopped"]["may_ask"] and "STOP" in by_name["Er. Stopped"]["why_not"]
    assert not by_name["Er. Switched Off"]["may_ask"] and "switched off" in by_name["Er. Switched Off"]["why_not"]
    r = await client.post(f"/api/mobed/requests/{rid}/callout", json={"who": [by_name["Er. Pervez Kias"]["key"]]},
                          headers=panthaky)
    assert r.status_code == 400 and "asked already" in r.json()["detail"]

    # Forged, unknown, or from another number: nothing changes.
    meta.sent.clear()
    await _signed_tap(client, MOBED, "pca:" + "x" * 24 + ":y")
    await _signed_tap(client, MOBED, f"pca:{kias.token}:maybe")
    await _signed_tap(client, LISTED, f"pca:{kias.token}:y")
    assert (await _answers(db))[MOBED].answer is None and meta.sent == []

    # The first yes goes, and the panthaky is told; nobody is sent the details at a yes (R3.1:
    # they go only at All set). One wanted, so the request is all set.
    pushes.clear()
    await _signed_tap(client, MOBED, f"pca:{kias.token}:y")
    await _signed_tap(client, MOBED, f"pca:{kias.token}:n")        # only the first tap counts
    # Only the All set messages (templates 5-8, tests/test_all_set.py): no old details, no reply.
    assert {m["template"]["name"] for m in meta.sent} == {
        "prayers_all_set_family", "prayer_details_mobed_v3", "prayers_all_set_panthaky", "funeral_accepted_manager_v2"}
    meta.sent.clear()
    kias = (await _answers(db))[MOBED]
    assert kias.answer == "yes" and kias.how == "whatsapp" and kias.picked_at is not None
    assert kias.details_sent_at is None
    (going,) = await _notes(db, PANTHAKY, prayer_callout.KIND_GOING)
    assert going.title == "Er. Pervez Kias is going (1 of 1)"
    assert going.body == "Er. Pervez Kias said yes on WhatsApp for the prayers for Behdin Rustom Jamshed: 1 of 1 going."
    assert going.link == f"#/requests/{rid}/callout"
    # (The All set notices that follow are tests/test_all_set.py's.)
    (push,) = [p for p in pushes if p["title"] != "All set"]
    assert push["title"] == "Er. Pervez Kias is going (1 of 1)"
    assert "Rustom" not in push["body"] and "Family" not in push["body"]
    (mine,) = await _notes(db, MOBED, prayer_callout.KIND_MY_YES)
    assert mine.title == "You are going to pray" and mine.body == prayer_callout.GOING_WORDS
    row = await db.get(FuneralRequest, rid, populate_existing=True)
    assert row.status == "all_set" and row.all_set_at is not None and row.decided_at == row.all_set_at

    # Enough are going (one wanted): the next yes is a standby, thanked in WhatsApp's window.
    meta.sent.clear()
    await _signed_tap(client, LISTED, f"pca:{listed.token}:y")
    assert meta.templates("prayer_details_mobed_v2") == []
    (text,) = meta.texts()
    assert text["to"] == LISTED and text["text"]["body"] == fw.ENOUGH_TEXT == (
        "Thank you. Enough mobeds are going this time. If a place opens, we may ask you again.")
    listed = (await _answers(db))[LISTED]
    assert listed.answer == "yes" and listed.picked_at is None and listed.enough_sent_at is not None
    (also,) = await _notes(db, PANTHAKY, prayer_callout.KIND_YES)
    assert also.title == "Er. Listed also said yes" and "standby" in also.body
    assert len([p for p in pushes if p["title"] != "All set"]) == 1     # no phone notification for it

    view = (await client.get(f"/api/mobed/requests/{rid}/callout", headers=panthaky)).json()
    people = {p["name"]: p for p in view["asked"]}
    assert view["going"] == 1 and view["wanted"] == 1 and view["open"] is False
    assert people["Er. Pervez Kias"]["going"] and people["Er. Pervez Kias"]["details"] is None
    assert not people["Er. Pervez Kias"]["may_resend"]
    assert not people["Er. Listed"]["going"] and people["Er. Listed"]["enough"]["state"] == "Sent"
    page = (await client.get(f"/api/mobed/requests/{rid}", headers=panthaky)).json()["request"]
    assert page["status"] == "all_set" and page["callout"] == {"asked": 2, "yes": 2, "going": 1, "wanted": 1}
    assert "family_contact" not in page
    for number in (PANTHAKY, MOBED, LISTED, FAMILY, STOPPED):
        assert number not in caplog.text and number.lstrip("+") not in caplog.text


async def test_two_go_when_nobody_said_how_many_and_after_accepting_too(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    for name, phone in (("Er. Listed", LISTED), ("Er. Second", SECOND)):
        r = await client.post(_list(aid), json={"name": name, "phone": phone, "agreed": True}, headers=panthaky)
        assert r.status_code == 200, r.text
    rid, res, _ = await _send(client, db, aid, mobeds_wanted=None)
    assert res["callout"]["asked"] == 3
    # The panthaky accepts in the app; the mobeds' answers still count.
    r = await client.post(f"/api/mobed/requests/{rid}/accept", json={"share_contact": False}, headers=panthaky)
    assert r.status_code == 200, r.text
    meta.sent.clear()
    answers = await _answers(db)
    for phone in (SECOND, MOBED, LISTED):
        await _signed_tap(client, phone, f"pca:{answers[phone].token}:y")
    # Nobody going is sent the details at a yes (R3.1); the third is a standby.
    assert meta.templates("prayer_details_mobed_v2") == []
    assert [m["to"] for m in meta.texts()] == [LISTED]
    answers = await _answers(db)
    assert [p for p in (SECOND, MOBED, LISTED) if answers[p].picked_at] == [SECOND, MOBED]
    view = (await client.get(f"/api/mobed/requests/{rid}/callout", headers=panthaky)).json()
    assert view["wanted"] == prayer_callout.DEFAULT_WANTED == 2 and view["going"] == 2
    # Accepted the old way before R3.1: it keeps its state when its places fill (D8).
    assert (await db.get(FuneralRequest, rid, populate_existing=True)).status == "accepted"


async def test_details_that_did_not_go_can_be_sent_again_but_never_twice(client, db, seeded, meta, pushes, live):
    from agyary.models import Notification
    from agyary.services import guardrails

    rid, _, _ = await _send(client, db, seeded["agyary_id"])
    panthaky = await _as(client, PANTHAKY)
    answer = (await _answers(db))[MOBED]
    meta.sent.clear()
    await _signed_tap(client, MOBED, f"pca:{answer.token}:y")
    again = f"/api/mobed/requests/{rid}/callout/details-again"
    # Going since R3.1: no details were tried, so there is nothing to send again before All set.
    view = (await client.get(f"/api/mobed/requests/{rid}/callout", headers=panthaky)).json()
    (person,) = view["asked"]
    assert person["going"] and not person["may_resend"] and person["details"] is None
    r = await client.post(again, headers=panthaky)
    assert r.status_code == 200 and r.json()["done"] == {"tried": 0, "sent": 0} and meta.sent == []

    # One going from before R3.1 whose details were tried while sending was paused.
    db.add(Notification(agyary_id=seeded["agyary_id"], recipient_phone=MOBED, recipient_type="user",
                        recipient_id=answer.user_id, notification_type=fw.TYPE_DETAILS,
                        template_name="prayer_details_mobed_v2", status="failed",
                        error_message=f"Not sent: {fw.PAUSED}",
                        template_params={"request": str(rid), "answer": str(answer.id), "to": "going"}))
    await guardrails.pause(db, config.get_settings(), "test pause")
    await db.commit()
    view = (await client.get(f"/api/mobed/requests/{rid}/callout", headers=panthaky)).json()
    (person,) = view["asked"]
    assert person["going"] and person["may_resend"] and "paused" in person["details"]["why"]
    r = await client.post(again, headers=panthaky)
    assert r.status_code == 409 and "paused" in r.json()["detail"]
    await guardrails.resume(db)
    await db.commit()
    r = await client.post(again, headers=panthaky)
    assert r.status_code == 200 and r.json()["done"] == {"tried": 1, "sent": 1}
    assert len(meta.templates("prayer_details_mobed_v2")) == 1 and not r.json()["asked"][0]["may_resend"]
    r = await client.post(again, headers=panthaky)
    assert r.json()["done"] == {"tried": 0, "sent": 0} and len(meta.templates("prayer_details_mobed_v2")) == 1
    # Nobody else's: a mobed of the fire temple cannot.
    assert (await client.post(again, headers=await _as(client, MOBED))).status_code == 404


async def test_withdrawing_tells_those_who_said_yes_inside_24_hours(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    for name, phone in (("Er. Listed", LISTED), ("Er. Second", SECOND)):
        await client.post(_list(aid), json={"name": name, "phone": phone, "agreed": True}, headers=panthaky)
    # Three wanted: two yeses leave it waiting, so the place can withdraw it.
    rid, _, mgr = await _send(client, db, aid, mobeds_wanted=3)
    answers = await _answers(db)
    await _signed_tap(client, MOBED, f"pca:{answers[MOBED].token}:y")
    await _signed_tap(client, LISTED, f"pca:{answers[LISTED].token}:y")
    # The listed mobed answered over a day ago: WhatsApp no longer lets us write to them.
    await db.execute(update(PrayerCalloutAnswer).where(PrayerCalloutAnswer.id == answers[LISTED].id)
                     .values(answered_at=datetime.now(timezone.utc) - timedelta(hours=25)))
    await db.commit()
    meta.sent.clear()
    r = await client.post(f"/api/mobed/manager/requests/{rid}/withdraw", headers=mgr)
    assert r.status_code == 200, r.text
    assert [(m["to"], m["text"]["body"]) for m in meta.texts()] == [(MOBED, fw.WITHDRAWN_TEXT)]
    # A yes after it is withdrawn is told so, and nobody more goes.
    meta.sent.clear()
    await _signed_tap(client, SECOND, f"pca:{answers[SECOND].token}:y")
    assert [(m["to"], m["text"]["body"]) for m in meta.texts()] == [(SECOND, fw.WITHDRAWN_TEXT)]
    assert (await _answers(db))[SECOND].picked_at is None
    # Closed: nobody more is asked, and the screen says it is closed.
    view = (await client.get(f"/api/mobed/requests/{rid}/callout", headers=panthaky)).json()
    assert view["open"] is False and view["candidates"] == []
    assert {p["name"]: (p["withdrawn_note"] or {}).get("state") for p in view["asked"]} == {
        "Er. Pervez Kias": "Sent", "Er. Listed": None, "Er. Second": "Sent"}
    r = await client.post(f"/api/mobed/requests/{rid}/callout", json={"who": ["u1"]}, headers=panthaky)
    assert r.status_code == 409 and "closed" in r.json()["detail"]


async def test_declining_tells_them_too(client, db, seeded, meta, pushes, live):
    rid, _, _ = await _send(client, db, seeded["agyary_id"])
    await _signed_tap(client, MOBED, f"pca:{(await _answers(db))[MOBED].token}:y")
    meta.sent.clear()
    r = await client.post(f"/api/mobed/requests/{rid}/decline", json={"reason": None},
                          headers=await _as(client, PANTHAKY))
    assert r.status_code == 200, r.text
    assert [(m["to"], m["text"]["body"]) for m in meta.texts()] == [(MOBED, fw.WITHDRAWN_TEXT)]


async def test_a_call_out_that_breaks_never_stops_the_request(client, db, seeded, meta, pushes, live, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("something unexpected")

    monkeypatch.setattr(prayer_callout, "_ask", boom)
    rid, res, _ = await _send(client, db, seeded["agyary_id"])
    assert res["callout"]["state"] == "failed" and "could not be asked" in res["callout"]["message"]
    assert res["record"]["requests"][0]["status"] == "waiting" and res["asked"] == 1
    assert (await db.get(FuneralRequest, rid)).status == "waiting"


# --- R3.1 step 2: the way the panthaky chose, at Send ------------------------------

async def _way(db, agyary_id: int, mode: str, minutes: int | None = None) -> None:
    a = await db.get(Agyary, agyary_id)
    a.request_mode, a.request_escalate_minutes = mode, minutes
    await db.commit()


async def _callouts(db) -> list[PrayerCallout]:
    return list((await db.execute(select(PrayerCallout))).scalars())


async def test_the_way_is_come_to_me_first_only_with_a_confirmed_panthaky_whose_access_is_on(db, seeded):
    settings = config.get_settings()
    goti = await db.get(Agyary, seeded["agyary_id"])
    assert await request_settings.way_for(db, settings, goti) == "everyone"      # the default
    await _way(db, goti.id, "panthaky_first", 30)
    assert await request_settings.way_for(db, settings, goti) == "panthaky_first"
    # Only mobeds there, or one who says they are the panthaky but is not confirmed:
    # Everyone at once, whatever the setting.
    only = await agyari(db, "Mobeds Only Agyari (test)", None)
    only.request_mode = "panthaky_first"
    await member(db, only, "+919822200111")
    claimed = await member(db, only, "+919822200112")
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == claimed.id)
                     .values(claimed_role="panthaky", claimed_at=datetime.now(timezone.utc)))
    await db.commit()
    assert await request_settings.way_for(db, settings, only) == "everyone"
    # The panthaky's access switched off (D9): nobody there to choose, so Everyone at once.
    await db.execute(update(User).where(User.phone == PANTHAKY).values(access="off"))
    await db.commit()
    assert await request_settings.way_for(db, settings, goti) == "everyone"


async def test_everyone_at_once_keeps_the_call_out_at_send(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    await _way(db, aid, "everyone", 15)          # the minutes matter only in Come to me first
    rid, res, _ = await _send(client, db, aid)
    assert res["callout"] == {"state": "sent", "asked": 1, "asked_in_app": 1,
                              "message": "1 mobed of Goti Adarian was asked in the app, and 1 on WhatsApp."}
    assert [m["to"] for m in meta.templates("prayer_request_mobeds_v2")] == [MOBED]
    assert len(await _callouts(db)) == 1


async def test_come_to_me_first_tells_only_the_panthaky_and_asks_nobody_at_send(client, db, seeded, meta, pushes,
                                                                               live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    r = await client.post(_list(aid), json={"name": "Er. Listed", "phone": LISTED, "agreed": True}, headers=panthaky)
    assert r.status_code == 200, r.text
    await _way(db, aid, "panthaky_first", 30)
    rid, res, _ = await _send(client, db, aid)
    # The manager's screen says so, and never that mobeds were asked.
    assert res["callout"] == {"state": "panthaky_first", "asked": 0, "asked_in_app": 0,
                              "message": "Sent to the panthaky of Goti Adarian. They choose who to ask."}
    assert res["asked"] == 1 and res["record"]["requests"][0]["status"] == "waiting"
    assert meta.sent == [] and await _callouts(db) == [] and await _answers(db) == {}
    # The request reaches the confirmed panthaky, as before.
    (note,) = await _notes(db, PANTHAKY, "funeral_request")
    assert "Goti Adarian" in note.body
    assert await _notes(db, MOBED, "funeral_request") == []
    assert [p["to"] for p in pushes] == [[(await db.execute(select(User.id).where(User.phone == PANTHAKY))).scalar_one()]]
    # The panthaky chooses who to ask: everyone on the list is still there to ask.
    view = (await client.get(f"/api/mobed/requests/{rid}/callout", headers=panthaky)).json()
    assert view["asked"] == [] and {c["name"] for c in view["candidates"] if c["may_ask"]} == {
        "Er. Pervez Kias", "Er. Listed"}
    key = next(c["key"] for c in view["candidates"] if c["name"] == "Er. Pervez Kias")
    r = await client.post(f"/api/mobed/requests/{rid}/callout", json={"who": [key]}, headers=panthaky)
    assert r.status_code == 200 and r.json()["asked_now"] == 1
    assert [m["to"] for m in meta.templates("prayer_request_mobeds_v2")] == [MOBED]


async def test_come_to_me_first_with_two_panthakys_says_panthakys(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    await member(db, await db.get(Agyary, aid), "+919822200113", role="panthaky", name="Er. Second Panthaky")
    await _way(db, aid, "panthaky_first")
    _, res, _ = await _send(client, db, aid)
    assert res["callout"]["message"] == "Sent to the panthakys of Goti Adarian. They choose who to ask."
    assert res["asked"] == 2 and meta.sent == []


async def test_come_to_me_first_with_no_confirmed_panthaky_on_is_everyone_at_once(client, db, seeded, meta, pushes,
                                                                                 live):
    # A fire temple of mobeds only: the request reaches them, and they are asked on WhatsApp at once.
    only = await agyari(db, "Mobeds Only Agyari (test)", None)
    only.request_mode, only.request_escalate_minutes = "panthaky_first", 15
    await member(db, only, "+919822200111", name="Er. Only One")
    await member(db, only, "+919822200112", name="Er. Only Two")
    await db.commit()
    _, res, mgr = await _send(client, db, only.id)
    assert res["asked"] == 2
    # They had the request in the app from Send (no panthaky): asked on WhatsApp only now.
    assert res["callout"] == {"state": "sent", "asked": 2, "asked_in_app": 0,
                              "message": "2 mobeds of Mobeds Only Agyari (test) were asked on WhatsApp."}
    assert sorted(m["to"] for m in meta.templates("prayer_request_mobeds_v2")) == ["+919822200111", "+919822200112"]

    # Goti Adarian, Come to me first, with its only panthaky switched off (D9): the same.
    meta.sent.clear()
    await _way(db, seeded["agyary_id"], "panthaky_first", 15)
    await db.execute(update(User).where(User.phone == PANTHAKY).values(access="off"))
    await db.commit()
    _, res, _ = await _send(client, db, seeded["agyary_id"], mgr)
    assert res["callout"]["state"] == "sent" and res["callout"]["asked"] == 1
    assert [m["to"] for m in meta.templates("prayer_request_mobeds_v2")] == [MOBED]
    body = [p["text"] for p in meta.templates("prayer_request_mobeds_v2")[0]["template"]["components"][0]["parameters"]]
    assert body[5] == "Goti Adarian"      # nothing under the account that is off


async def test_a_way_that_cannot_be_read_never_stops_the_request(client, db, seeded, meta, pushes, live,
                                                                monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("something unexpected")

    monkeypatch.setattr(request_settings, "way_for", boom)
    rid, res, _ = await _send(client, db, seeded["agyary_id"])
    assert res["callout"]["state"] == "failed" and "could not be asked" in res["callout"]["message"]
    assert (await db.get(FuneralRequest, rid)).status == "waiting" and meta.sent == []
