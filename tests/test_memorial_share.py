"""Sharing a memorial's schedule: the PDF, the message, and sending from the
shared number. Meta is a mock transport - nothing here can reach a real number.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from agyary.core.config import Settings
from agyary.models import Customer, Notification
from agyary.services import memorial_share
from tests.test_memorial_api import PHONE, _create, _setup


def _settings(**over) -> Settings:
    base = dict(
        memorial_share_send_mode="live", reminders_allowlist="*", whatsapp_access_token="test-token",
        whatsapp_phone_number_id="555000111", whatsapp_graph_version="v99.0",
        whatsapp_share_template="memorial_schedule", whatsapp_template_language="en", jwt_secret_key="x",
    )
    return Settings(**{**base, **over})


class FakeMeta:
    def __init__(self, status=200):
        self.status, self.calls = status, []

    def client(self) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            if self.status != 200:
                return httpx.Response(self.status, json={"error": {"message": "template not approved", "code": 132001}})
            if request.url.path.endswith("/media"):
                return httpx.Response(200, json={"id": "MEDIA123"})
            return httpx.Response(200, json={"messages": [{"id": "wamid.SHARE"}]})
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _memorial(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    r = await _create(client, db, aid, cid, headers)
    assert r.status_code == 200, r.text
    return aid, cid, r.json()["id"], headers


async def test_the_pdf_is_a_pdf_with_the_name_in_it(client, db, seeded):
    aid, _cid, mid, headers = await _memorial(client, db, seeded)
    r = await client.get(f"/api/mobed/agyaries/{aid}/memorials/{mid}/schedule.pdf",
                         params={"note": "Please come at 7am"}, headers=headers)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and "attachment" in r.headers["content-disposition"]


async def test_the_message_lists_every_date_and_carries_the_note(client, db, seeded):
    aid, _cid, mid, headers = await _memorial(client, db, seeded)
    r = await client.get(f"/api/mobed/agyaries/{aid}/memorials/{mid}/share",
                         params={"note": "  Please   come at 7am "}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Memorial prayers for Dinshaw" in body["text"] and "Please come at 7am" in body["text"]
    assert body["text"].count("\n- ") >= 13        # days 1-10, Masiso and the months
    assert body["phone"] == PHONE
    # Not switched on (the default) and the family has not agreed: both are said.
    assert body["can_send"] is False and body["cannot_send_because"]


async def test_sending_from_our_number_is_refused_while_it_is_off(client, db, seeded):
    aid, _cid, mid, headers = await _memorial(client, db, seeded)
    r = await client.post(f"/api/mobed/agyaries/{aid}/memorials/{mid}/share/send", json={}, headers=headers)
    assert r.status_code == 409 and "not switched on" in r.json()["detail"]
    assert (await db.execute(select(Notification))).first() is None


async def test_another_mobed_cannot_share_this_memorial(client, db, seeded):
    from tests.test_memorial_api import OTHER_MOBED
    from tests.test_mobed_api import _member_headers
    aid, _cid, mid, _headers = await _memorial(client, db, seeded)
    other = await _member_headers(client, seeded, name="Other", phone=OTHER_MOBED)
    for path, method in ((f"/memorials/{mid}/share", "get"), (f"/memorials/{mid}/schedule.pdf", "get"),
                         (f"/memorials/{mid}/share/send", "post")):
        r = await getattr(client, method)(f"/api/mobed/agyaries/{aid}{path}", headers=other,
                                          **({"json": {}} if method == "post" else {}))
        assert r.status_code == 404, path


async def test_the_blocked_reasons_in_order(db, client, seeded):
    aid, cid, _mid, _headers = await _memorial(client, db, seeded)
    customer = await db.get(Customer, cid)
    now = datetime.now(timezone.utc)
    assert "not switched on" in await memorial_share.blocked_reason(db, _settings(memorial_share_send_mode="off"), customer, 1, now)
    assert "not set up" in await memorial_share.blocked_reason(db, _settings(whatsapp_access_token=""), customer, 1, now)
    assert "agreed" in await memorial_share.blocked_reason(db, _settings(), customer, 1, now)
    customer.reminders_enabled = True
    assert "allowed" in await memorial_share.blocked_reason(db, _settings(reminders_allowlist=""), customer, 1, now)
    assert await memorial_share.blocked_reason(db, _settings(), customer, 1, now) is None


async def test_the_pdf_goes_to_meta_as_a_document_template_and_is_recorded(db, client, seeded):
    aid, cid, mid, headers = await _memorial(client, db, seeded)
    customer = await db.get(Customer, cid)
    fake = FakeMeta()
    data = {"departed_name": "Dinshaw", "death_date": "2030-03-10", "death": {"roj": 2, "mah": 1, "year": 1}, "observances": []}
    n = await memorial_share.send_pdf(
        db, _settings(), agyary_id=aid, customer=customer, user_id=7, memorial=data, pdf=b"%PDF-test",
        filename="Memorial-prayers-Dinshaw.pdf", mobed_name="Er. Test", agyary_name="Goti Adarian", client=fake.client())
    assert n.status == "sent" and n.wa_message_id == "wamid.SHARE" and n.notification_type == "memorial_share"
    media, message = fake.calls
    assert media.url.path.endswith("/555000111/media")
    body = json.loads(message.content)
    assert body["to"] == customer.phone and body["template"]["name"] == "memorial_schedule"
    header, text = body["template"]["components"]
    assert header["parameters"][0]["document"]["id"] == "MEDIA123"
    assert [p["text"] for p in text["parameters"]] == ["Dinshaw", "Er. Test", "Goti Adarian"]


async def test_a_refusal_from_meta_is_recorded_and_raised(db, client, seeded):
    import pytest
    aid, cid, _mid, _headers = await _memorial(client, db, seeded)
    customer = await db.get(Customer, cid)
    with pytest.raises(RuntimeError, match="template not approved"):
        await memorial_share.send_pdf(
            db, _settings(), agyary_id=aid, customer=customer, user_id=7,
            memorial={"departed_name": "D"}, pdf=b"%PDF", filename="x.pdf", mobed_name="M",
            agyary_name="A", client=FakeMeta(status=400).client())
    row = (await db.execute(select(Notification))).scalar_one()
    assert row.status == "failed" and "template not approved" in row.error_message
