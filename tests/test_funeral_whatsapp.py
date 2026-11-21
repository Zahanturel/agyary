"""WhatsApp from Mobed Diary's number when a request is accepted (DECISIONS D10
and its 18 Nov 2026 amendments; docs/phase2-whatsapp-templates.md; Step 5b).

Off by default: nothing is sent and the accepter is told it starts once Meta
approves. Live, with "Share my name and number" ticked: template 1 to the
place's managers, template 2 to the accepter, template 3 to the family only if
the manager's tick recorded their agreement and they never said STOP. Without
the share tick, nothing. The pause switch and the day's limits stop sends; a
send that fails never makes the accept fail; no phone number reaches the logs.
Outbound HTTP is mocked throughout.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select, update

from agyary.core import config
from agyary.models import AppNotification, FuneralRequest, Notification, ReminderOptOut, User
from agyary.services import funeral_whatsapp as fw
from agyary.services import guardrails
from tests.conftest import sign_in
from tests.funeral_helpers import FAMILY, auth, form, manager

RECORDS = "/api/mobed/manager/records"
REQUESTS = "/api/mobed/requests"
PANTHAKY, ADMIN = "+919800000001", "+919800000002"
MANAGER = "+919911100071"
LIVE = {
    "FUNERAL_WHATSAPP_MODE": "live", "WHATSAPP_ACCESS_TOKEN": "test-token", "WHATSAPP_PHONE_NUMBER_ID": "555",
    "REMINDERS_ALLOWLIST": "*", "ADMIN_PHONES": ADMIN,
}


class Meta:
    """Stands in for graph.facebook.com: records each message, answers as told."""

    def __init__(self):
        self.sent: list[dict] = []
        self.fail: Exception | None = None
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail is not None:
            raise self.fail
        body = json.loads(request.content)
        self.sent.append(body)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "template not approved", "code": 132001}})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{len(self.sent)}"}]})


@pytest.fixture
def meta(monkeypatch):
    fake = Meta()
    monkeypatch.setattr(fw, "make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    return fake


@pytest.fixture
def pushes(monkeypatch):
    from agyary.services import web_push

    async def capture(db, settings, user_ids, **kw):
        return 0

    monkeypatch.setattr(web_push, "send_to_users", capture)


@pytest.fixture
def live(monkeypatch):
    for key, value in LIVE.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def _sent(client, db, aid, *, whatsapp_agreed=True, mgr=None, **changes) -> int:
    if mgr is None:
        mgr, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(**changes), headers=mgr)).json()["record"]
    body = {"agyary_id": aid, "family_agreed": True}
    if whatsapp_agreed:
        body["family_whatsapp_agreed"] = True
    r = await client.post(f"{RECORDS}/{rec['id']}/requests", json=body, headers=mgr)
    assert r.status_code == 200, r.text
    return r.json()["record"]["requests"][0]["id"]


async def _accept(client, rid, share=True):
    headers = auth(await sign_in(client, PANTHAKY))
    r = await client.post(f"{REQUESTS}/{rid}/accept", json={"share_contact": share}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json(), headers


# What accepting sends. Since 19 Nov 2026 the mobeds' call-out (template 4) goes
# when the request is sent: tests/test_prayer_callout.py covers it, so it is left
# out of what is counted here.
ON_ACCEPT = (fw.TYPE_MANAGER, fw.TYPE_DETAILS, fw.TYPE_FAMILY)


async def _rows(db) -> list[Notification]:
    return list((await db.execute(select(Notification).where(Notification.notification_type.in_(ON_ACCEPT))
                                  .order_by(Notification.id))).scalars().all())


def _on_accept(meta) -> list[dict]:
    return [m for m in meta.sent if m.get("type") == "template" and m["template"]["name"] != "prayer_request_mobeds_v2"]


def _by_template(meta) -> dict:
    return {m["template"]["name"]: m for m in _on_accept(meta)}


def _body(m) -> list[str]:
    return [p["text"] for p in m["template"]["components"][0]["parameters"]]


def _buttons(m) -> list:
    # Meta does not allow buttons that link straight to WhatsApp, so these three
    # templates have none: the number in the text is tappable instead.
    return [c for c in m["template"]["components"] if c["type"] == "button"]


async def test_switched_off_nothing_is_sent_and_the_accepter_is_told_why(client, db, seeded, meta, pushes):
    rid = await _sent(client, db, seeded["agyary_id"])
    body, headers = await _accept(client, rid)
    assert meta.sent == [] and await _rows(db) == []
    assert body["whatsapp"]["state"] == "off" and body["whatsapp"]["message"] == fw.OFF_WORDS
    # The request page says the same later.
    page = (await client.get(f"{REQUESTS}/{rid}", headers=headers)).json()["request"]
    assert page["whatsapp"]["state"] == "off" and page["whatsapp"]["message"] == fw.OFF_WORDS


async def test_the_new_tick_is_stored_and_an_old_app_never_agrees_for_the_family(client, db, seeded, pushes):
    rid = await _sent(client, db, seeded["agyary_id"])
    assert (await db.get(FuneralRequest, rid)).family_whatsapp_agreed is True
    mgr, _ = await manager(client, db, phone="+919911100072", name="Second Manager")
    rid2 = await _sent(client, db, seeded["agyary_id"], whatsapp_agreed=False, mgr=mgr)
    row = await db.get(FuneralRequest, rid2)
    await db.refresh(row)
    assert row.family_whatsapp_agreed is False


async def test_live_with_share_the_three_templates_go_to_the_right_people(client, db, seeded, meta, pushes, live, caplog):
    caplog.set_level(logging.DEBUG)
    rid = await _sent(client, db, seeded["agyary_id"], uthamna_date=None, uthamna_time=None)
    body, headers = await _accept(client, rid)
    sent = _by_template(meta)
    assert set(sent) == {"funeral_accepted_manager", "prayer_details_mobed_v2", "prayers_mobed_family"}

    to_manager = sent["funeral_accepted_manager"]
    assert to_manager["to"] == MANAGER
    assert _body(to_manager) == ["Behdin Rustom Jamshed", "Er. Hormuz Dadachanji", "Goti Adarian", PANTHAKY]
    assert _buttons(to_manager) == []

    details = sent["prayer_details_mobed_v2"]
    assert details["to"] == PANTHAKY
    b = _body(details)
    # prayer_details_mobed_v2 (19 Nov 2026): six blanks, no bungli.
    assert details["template"]["name"] == "prayer_details_mobed_v2"
    assert b[0] == "Behdin Rustom Jamshed" and b[1] == "Doongerwadi (test)"
    assert b[2].endswith(", Havan geh") and b[3] == "not fixed yet"
    assert b[4:] == ["Test Family", FAMILY] and _buttons(details) == []

    family = sent["prayers_mobed_family"]
    assert family["to"] == FAMILY
    assert _body(family) == ["Behdin Rustom Jamshed", "Er. Hormuz Dadachanji", "Goti Adarian", PANTHAKY]
    assert _buttons(family) == []

    rows = await _rows(db)
    assert {(n.notification_type, n.recipient_type, n.status) for n in rows} == {
        ("funeral_accepted_manager", "user", "sent"), ("prayer_details_mobed", "user", "sent"),
        ("prayers_mobed_family", "family", "sent")}
    # The rows keep the names, never a number.
    for n in rows:
        assert fw.HIDDEN in n.template_params.values()
        assert not any(p.lstrip("+") in str(v) for v in n.template_params.values() for p in (PANTHAKY, FAMILY))
        assert n.template_params["request"] == str(rid)
    assert body["whatsapp"]["state"] == "sent"
    assert body["whatsapp"]["message"] == "WhatsApp messages sent from Mobed Diary to the manager, you and the family."
    page = (await client.get(f"{REQUESTS}/{rid}", headers=headers)).json()["request"]
    assert page["whatsapp"]["state"] == "sent"
    # No phone number in the logs.
    for number in (PANTHAKY, FAMILY, MANAGER):
        assert number not in caplog.text and number.lstrip("+") not in caplog.text


async def test_the_family_only_with_their_agreement_and_without_a_stop(client, db, seeded, meta, pushes, live):
    rid = await _sent(client, db, seeded["agyary_id"], whatsapp_agreed=False)
    body, _ = await _accept(client, rid)
    assert set(_by_template(meta)) == {"funeral_accepted_manager", "prayer_details_mobed_v2"}
    assert "did not include their agreement" in body["whatsapp"]["family_note"]

    meta.sent.clear()
    db.add(ReminderOptOut(phone="+919822200044", stopped_at=datetime.now(timezone.utc)))
    await db.commit()
    mgr, _ = await manager(client, db, phone="+919911100072", name="Second Manager")
    rec = (await client.post(RECORDS, json=form(family_contact_phone="+919822200044"), headers=mgr)).json()["record"]
    r = await client.post(f"{RECORDS}/{rec['id']}/requests", headers=mgr,
                          json={"agyary_id": seeded["agyary_id"], "family_agreed": True, "family_whatsapp_agreed": True})
    rid2 = r.json()["record"]["requests"][0]["id"]
    body, _ = await _accept(client, rid2)
    assert "prayers_mobed_family" not in _by_template(meta)
    (row,) = [n for n in await fw.rows_for(db, request_id=rid2) if n.notification_type == "prayers_mobed_family"]
    assert row.status == "failed" and "STOP" in row.error_message
    assert body["whatsapp"]["state"] == "failed" and "to the family could not be sent" in body["whatsapp"]["message"]


async def test_without_the_share_tick_nothing_goes_by_whatsapp(client, db, seeded, meta, pushes, live):
    rid = await _sent(client, db, seeded["agyary_id"])
    body, _ = await _accept(client, rid, share=False)
    assert _on_accept(meta) == [] and await _rows(db) == []
    assert body["whatsapp"]["state"] == "not_shared"


async def test_the_pause_switch_stops_every_send(client, db, seeded, meta, pushes, live):
    await guardrails.pause(db, config.get_settings(), "test pause")
    await db.commit()
    rid = await _sent(client, db, seeded["agyary_id"])
    body, _ = await _accept(client, rid)
    assert meta.sent == []
    rows = await _rows(db)
    assert len(rows) == 3 and all(n.status == "failed" and "paused" in n.error_message for n in rows)
    assert body["whatsapp"]["state"] == "failed"


async def test_the_daily_limit_stops_sends_and_tells_the_admins(client, db, seeded, meta, pushes, live, monkeypatch):
    # Two: the call-out at sending takes one (to the one mobed there), accepting the other.
    monkeypatch.setenv("FUNERAL_WHATSAPP_DAILY_CAP", "2")
    config.get_settings.cache_clear()
    await sign_in(client, ADMIN)
    rid = await _sent(client, db, seeded["agyary_id"])
    assert len(meta.sent) == 1
    await _accept(client, rid)
    assert len(_on_accept(meta)) == 1
    rows = await _rows(db)
    assert [n.status for n in rows].count("sent") == 1
    assert all("limit" in n.error_message for n in rows if n.status == "failed")
    admin = (await db.execute(select(User).where(User.phone == ADMIN))).scalar_one()
    alerts = (await db.execute(select(AppNotification).where(AppNotification.user_id == admin.id,
                                                              AppNotification.title == fw.CAP_TITLE))).scalars().all()
    assert len(alerts) == 1


@pytest.mark.parametrize("failure", ["timeout", "refused", "crash"])
async def test_accepting_never_fails_because_a_send_fails(client, db, seeded, meta, pushes, live, monkeypatch, failure):
    if failure == "timeout":
        meta.fail = httpx.ReadTimeout("slow")
    elif failure == "refused":
        meta.status = 400
    else:
        async def boom(*a, **kw):
            raise RuntimeError("something unexpected")
        monkeypatch.setattr(fw, "deliver", boom)
    rid = await _sent(client, db, seeded["agyary_id"])
    body, headers = await _accept(client, rid)
    assert body["request"]["status"] == "accepted" and body["request"]["accepted_by_me"] is True
    assert body["whatsapp"]["state"] == "failed" and "could not be sent" in body["whatsapp"]["message"]
    assert (await db.get(FuneralRequest, rid)).status == "accepted"
    if failure == "timeout":
        assert all("may or may not have been sent" in n.error_message for n in await _rows(db))
    if failure == "refused":
        # A template Meta will not take pauses everything, as for reminders.
        assert await guardrails.paused_reason(db)


async def test_a_name_that_breaks_the_rules_is_not_sent_and_says_why(client, db, seeded, meta, pushes, live):
    await db.execute(update(User).where(User.phone == PANTHAKY).values(name="Er. Visit spam.com"))
    await db.commit()
    rid = await _sent(client, db, seeded["agyary_id"])
    body, _ = await _accept(client, rid)
    # Only the details went: the other two would carry the name.
    assert set(_by_template(meta)) == {"prayer_details_mobed_v2"}
    failed = [n for n in await _rows(db) if n.status == "failed"]
    assert len(failed) == 2 and all("link" in n.error_message for n in failed)
