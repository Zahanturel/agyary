"""WhatsApp from Mobed Diary's number about a prayer request (DECISIONS D10 and
its 18 Nov 2026 amendments; docs/phase2-whatsapp-templates.md; Step 5b; R3.1).

Templates 1-3 went on accepting, before R3.1. The Accept is gone (R3.1 step 7),
so nothing sends them any more (tests/test_funeral_accept.py), and a request
accepted the old way still reads what went then: sent, not sent and why,
nothing while sending was off, or nothing because the accepter did not share
their number, and a note when the family had not agreed. The family is messaged
only with the manager's tick (its words since 18 Nov). Every message that goes
now - the call-out, and All set's templates 5-8 (tests/test_all_set.py) - keeps
to the same safeguards, tried here through All set: the day's limits (and the
admins told), a send that fails never undoes the All set, a name that breaks
the rules is not sent and says why, and no phone number reaches the rows or the
logs. Outbound HTTP is mocked throughout.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select, update

from agyary.core import config
from agyary.models import AppNotification, FuneralRequest, Notification, User
from agyary.services import funeral_whatsapp as fw
from agyary.services import guardrails
from tests.conftest import sign_in
from tests.funeral_helpers import FAMILY, accepted_the_old_way, auth, form, manager

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


async def _pray(client, rid) -> dict:
    """The panthaky's "I'll pray" on a request wanting one mobed: it is all set."""
    headers = auth(await sign_in(client, PANTHAKY))
    r = await client.post(f"{REQUESTS}/{rid}/self", json={}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "all_set"
    return r.json()


async def _rows(db) -> list[Notification]:
    """What All set wrote down (templates 5-8)."""
    return list((await db.execute(select(Notification).where(Notification.notification_type.in_(fw.ALL_SET_TYPES))
                                  .order_by(Notification.id))).scalars().all())


def _all_set_sent(meta) -> list[dict]:
    return [m for m in meta.sent if m.get("type") == "template" and m["template"]["name"] != "prayer_request_mobeds_v2"]


def _old_row(rid: int, aid: int, kind: str, to: str, status: str, error: str | None = None) -> Notification:
    """A message sent on accepting, before R3.1, as accepting wrote it down (never a number)."""
    now = datetime.now(timezone.utc)
    return Notification(agyary_id=aid, recipient_phone={"family": FAMILY, "accepter": PANTHAKY}.get(to, MANAGER),
                        recipient_type="family" if to == "family" else "user", recipient_id=1, notification_type=kind,
                        template_name=kind, template_params={"1": "Behdin Rustom Jamshed", "4": fw.HIDDEN,
                                                             "request": str(rid), "to": to},
                        scheduled_at=now, created_at=now, status=status, error_message=error)


async def test_one_accepted_the_old_way_still_reads_what_went_then(client, db, seeded, meta, pushes):
    aid = seeded["agyary_id"]
    rid = await _sent(client, db, aid)
    await accepted_the_old_way(db, rid, PANTHAKY, book=False)
    headers = auth(await sign_in(client, PANTHAKY))

    async def whatsapp(request_id: int) -> dict:
        return (await client.get(f"{REQUESTS}/{request_id}", headers=headers)).json()["request"]["whatsapp"]

    # Nothing went (sending was off then): it says the messages start once Meta approves them.
    got = await whatsapp(rid)
    assert got["state"] == "off" and got["message"] == fw.OFF_WORDS and got["items"] == []
    assert got["family_note"] is None

    # What went, as accepting wrote it down: to the manager, to them and to the family.
    for kind, to, status in ((fw.TYPE_MANAGER, "manager", "delivered"), (fw.TYPE_DETAILS, "accepter", "read"),
                             (fw.TYPE_FAMILY, "family", "sent")):
        db.add(_old_row(rid, aid, kind, to, status))
    await db.commit()
    got = await whatsapp(rid)
    assert got["state"] == "sent"
    assert got["message"] == "WhatsApp messages sent from Mobed Diary to the manager, you and the family."
    assert [(i["to"], i["state"]) for i in got["items"]] == [("manager", "Delivered"), ("accepter", "Read"),
                                                              ("family", "Sent")]

    # One that did not go says why.
    await db.execute(update(Notification).where(Notification.notification_type == fw.TYPE_FAMILY).values(
        status="failed", error_message="Not sent: they replied STOP to Mobed Diary, so nothing more goes to them"))
    await db.commit()
    got = await whatsapp(rid)
    assert got["state"] == "failed"
    assert got["message"] == ("The WhatsApp message to the family could not be sent: they replied STOP to Mobed "
                              "Diary, so nothing more goes to them.")

    # Accepted without sharing their number: nothing went, and nothing is said.
    mgr, _ = await manager(client, db, phone="+919911100072", name="Second Manager")
    rid2 = await _sent(client, db, aid, mgr=mgr)
    await accepted_the_old_way(db, rid2, PANTHAKY, share=False, book=False)
    assert (await whatsapp(rid2))["state"] == "not_shared"
    # The manager's tick did not say the family agreed: noted.
    rid3 = await _sent(client, db, aid, whatsapp_agreed=False, mgr=mgr, departed_name="Dinshaw")
    await accepted_the_old_way(db, rid3, PANTHAKY, book=False)
    assert "did not include their agreement" in (await whatsapp(rid3))["family_note"]
    assert meta.sent == []


async def test_the_new_tick_is_stored_and_an_old_app_never_agrees_for_the_family(client, db, seeded, pushes):
    rid = await _sent(client, db, seeded["agyary_id"])
    assert (await db.get(FuneralRequest, rid)).family_whatsapp_agreed is True
    mgr, _ = await manager(client, db, phone="+919911100072", name="Second Manager")
    rid2 = await _sent(client, db, seeded["agyary_id"], whatsapp_agreed=False, mgr=mgr)
    row = await db.get(FuneralRequest, rid2)
    await db.refresh(row)
    assert row.family_whatsapp_agreed is False


async def test_live_no_phone_number_reaches_the_rows_or_the_logs(client, db, seeded, meta, pushes, live, caplog):
    caplog.set_level(logging.DEBUG)
    rid = await _sent(client, db, seeded["agyary_id"], mobeds_wanted=1)
    await _pray(client, rid)
    assert {m["template"]["name"] for m in _all_set_sent(meta)} == {
        "prayers_all_set_family", "prayer_details_mobed_v3", "funeral_accepted_manager_v2"}
    # Templates 1-3 are never sent any more.
    assert not {"funeral_accepted_manager", "prayer_details_mobed_v2", "prayers_mobed_family"} & {
        m["template"]["name"] for m in _all_set_sent(meta)}
    rows = await _rows(db)
    assert len(rows) == 3 and all(n.status == "sent" for n in rows)
    for n in rows:
        assert not any(p.lstrip("+") in str(v) for v in n.template_params.values() for p in (PANTHAKY, FAMILY))
        assert n.template_params["request"] == str(rid)
    for number in (PANTHAKY, FAMILY, MANAGER):
        assert number not in caplog.text and number.lstrip("+") not in caplog.text


async def test_the_daily_limit_stops_sends_and_tells_the_admins(client, db, seeded, meta, pushes, live, monkeypatch):
    # Two: the call-out at sending takes one (to the one mobed there), All set the other.
    monkeypatch.setenv("FUNERAL_WHATSAPP_DAILY_CAP", "2")
    config.get_settings.cache_clear()
    await sign_in(client, ADMIN)
    rid = await _sent(client, db, seeded["agyary_id"], mobeds_wanted=1)
    assert len(meta.sent) == 1
    await _pray(client, rid)
    assert len(_all_set_sent(meta)) == 1
    rows = await _rows(db)
    assert len(rows) == 3 and [n.status for n in rows].count("sent") == 1
    assert all("limit" in n.error_message for n in rows if n.status == "failed")
    admin = (await db.execute(select(User).where(User.phone == ADMIN))).scalar_one()
    alerts = (await db.execute(select(AppNotification).where(AppNotification.user_id == admin.id,
                                                              AppNotification.title == fw.CAP_TITLE))).scalars().all()
    assert len(alerts) == 1


@pytest.mark.parametrize("failure", ["timeout", "refused", "crash"])
async def test_all_set_never_fails_because_a_send_fails(client, db, seeded, meta, pushes, live, monkeypatch, failure):
    rid = await _sent(client, db, seeded["agyary_id"], mobeds_wanted=1)
    if failure == "timeout":
        meta.fail = httpx.ReadTimeout("slow")
    elif failure == "refused":
        meta.status = 400
    else:
        async def boom(*a, **kw):
            raise RuntimeError("something unexpected")
        monkeypatch.setattr(fw, "deliver", boom)
    body = await _pray(client, rid)
    assert body["status"] == "all_set" and [p["name"] for p in body["places"]] == ["Er. Hormuz Dadachanji"]
    assert (await db.get(FuneralRequest, rid, populate_existing=True)).status == "all_set"
    rows = await _rows(db)
    if failure == "timeout":
        assert rows and all("may or may not have been sent" in n.error_message for n in rows)
    if failure == "refused":
        # A template Meta will not take pauses everything, as for reminders.
        assert rows and all(n.status == "failed" for n in rows)
        assert await guardrails.paused_reason(db)
    if failure == "crash":
        assert rows == []


async def test_a_name_that_breaks_the_rules_is_not_sent_and_says_why(client, db, seeded, meta, pushes, live):
    rid = await _sent(client, db, seeded["agyary_id"], mobeds_wanted=1)
    await db.execute(update(User).where(User.phone == PANTHAKY).values(name="Er. Visit spam.com"))
    await db.commit()
    await _pray(client, rid)
    # Each of them names the panthaky going, so none went, and each says why.
    assert _all_set_sent(meta) == []
    rows = await _rows(db)
    assert len(rows) == 3 and all(n.status == "failed" and "link" in n.error_message for n in rows)
