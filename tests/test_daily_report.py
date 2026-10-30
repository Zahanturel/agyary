"""The daily report: the evening before, what is on a mobed's day tomorrow.

In the app for any mobed who turned it on; on WhatsApp too only in live mode. Meta is a
mock transport - nothing here can reach a real number.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import httpx
from sqlalchemy import select

from agyary.core.config import Settings
from agyary.messaging.geh_times import IST
from agyary.models import AppNotification, Notification, User
from agyary.services import daily_report
from tests.test_behdin_and_preferences import _add_machi
from tests.test_behdin_delete import _add, _book
from tests.test_mobed_api import NEW_MOBED_PHONE, _member_headers

EVENING = datetime.combine(date(2027, 7, 31), time(20, 30), IST)   # the booking is on 2027-08-01


def _settings(**over) -> Settings:
    base = dict(
        daily_report_send_mode="live", reminders_allowlist="*", whatsapp_access_token="test-token",
        whatsapp_phone_number_id="555000111", whatsapp_graph_version="v99.0",
        whatsapp_daily_report_template="daily_report", whatsapp_template_language="en", jwt_secret_key="x",
    )
    return Settings(**{**base, **over})


class FakeMeta:
    def __init__(self, status=200):
        self.status, self.calls = status, []

    def client(self) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            if self.status != 200:
                return httpx.Response(self.status, json={"error": {"message": "template missing", "code": 132001}})
            return httpx.Response(200, json={"messages": [{"id": "wamid.REPORT"}]})
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _user(db) -> User:
    return (await db.execute(select(User).where(User.phone == NEW_MOBED_PHONE))).scalar_one()


async def _setup(client, db, seeded, *, on=True):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    await _add(client, aid, headers)
    await _book(client, aid, headers)       # 2027-08-01 10:00, "Delete Behdin"
    if on:
        r = await client.put("/api/mobed/me/daily-report", json={"enabled": True}, headers=headers)
        assert r.status_code == 200 and r.json()["daily_report"] is True
    return aid, headers


async def _notes(db):
    return (await db.execute(select(AppNotification).where(AppNotification.kind == "daily_report"))).scalars().all()


async def test_it_is_off_until_the_mobed_turns_it_on(client, db, seeded):
    await _setup(client, db, seeded, on=False)
    assert (await _user(db)).daily_report is False
    assert await daily_report.run(db, EVENING, _settings(daily_report_send_mode="off")) == 0
    assert await _notes(db) == []


async def test_the_mobed_can_switch_it_on_and_off(client, db, seeded):
    aid, headers = await _setup(client, db, seeded)
    r = await client.put("/api/mobed/me/daily-report", json={"enabled": False}, headers=headers)
    assert r.json()["daily_report"] is False
    assert await daily_report.run(db, EVENING, _settings(daily_report_send_mode="off")) == 0


async def test_tomorrow_is_listed_in_the_app_once(client, db, seeded):
    await _setup(client, db, seeded)
    s = _settings(daily_report_send_mode="off")
    assert await daily_report.run(db, EVENING, s) == 1
    assert await daily_report.run(db, EVENING + timedelta(minutes=5), s) == 0      # not twice
    (note,) = await _notes(db)
    assert "1 thing on your day: 1 service" in note.body
    assert "10:00 AM" in note.body and "Delete Behdin" in note.body
    assert note.link == "#/calendar/day/2027-08-01"
    assert (await db.execute(select(Notification))).first() is None     # WhatsApp is off


async def test_an_empty_tomorrow_sends_nothing(client, db, seeded):
    await _setup(client, db, seeded)
    day_before_nothing = EVENING + timedelta(days=3)
    assert await daily_report.run(db, day_before_nothing, _settings(daily_report_send_mode="off")) == 0
    assert await _notes(db) == []


async def test_machis_and_memorial_days_are_listed_too_and_payment_is_not(client, db, seeded):
    aid, headers = await _setup(client, db, seeded)
    r = await _add_machi(client, aid, headers, "patet",
                         [{"section": "pair", "title": "khud", "name": "A", "status": "departed", "pair_group": 1},
                          {"section": "pair", "title": "khud", "name": "B", "status": "departed", "pair_group": 1}])
    assert r.status_code == 200, r.text
    # the machi helper books 2027-06-15; list that day
    s = _settings(daily_report_send_mode="off")
    assert await daily_report.run(db, datetime.combine(date(2027, 6, 14), time(20, 30), IST), s) == 1
    notes = await _notes(db)
    assert any("Machi (Patet)" in n.body and "Tandarosti Family" in n.body for n in notes)
    assert not any("paid" in n.body.lower() for n in notes)


async def test_whatsapp_goes_through_the_template_in_live_mode(client, db, seeded):
    await _setup(client, db, seeded)
    meta = FakeMeta()
    assert await daily_report.run(db, EVENING, _settings(), meta.client()) == 1
    (call,) = meta.calls
    body = json.loads(call.content)
    assert body["to"] == NEW_MOBED_PHONE and body["template"]["name"] == "daily_report"
    texts = [p["text"] for p in body["template"]["components"][0]["parameters"]]
    assert texts[0] == "Sun 1 Aug" and texts[1] == "1 thing on your day" and "Delete Behdin" in texts[2]
    assert "\n" not in "".join(texts)                       # a template variable cannot hold a line break
    (row,) = (await db.execute(select(Notification))).scalars().all()
    assert row.status == "sent" and row.wa_message_id == "wamid.REPORT" and row.notification_type == "daily_report"
    assert len(await _notes(db)) == 1                       # the app copy is there too


async def test_a_refused_whatsapp_is_recorded_not_retried_and_the_app_copy_stays(client, db, seeded):
    await _setup(client, db, seeded)
    meta = FakeMeta(status=400)
    assert await daily_report.run(db, EVENING, _settings(), meta.client()) == 1
    assert await daily_report.run(db, EVENING + timedelta(minutes=1), _settings(), meta.client()) == 0
    assert len(meta.calls) == 1
    (row,) = (await db.execute(select(Notification))).scalars().all()
    assert row.status == "failed" and "template missing" in row.error_message
    assert len(await _notes(db)) == 1


async def test_a_long_list_is_cut_for_whatsapp_and_says_so():
    items = [daily_report.Item(EVENING + timedelta(minutes=i), "booking", f"{i:02d}:00 AM Afringan - Family number {i}")
             for i in range(60)]
    params = daily_report.whatsapp_params(date(2027, 8, 1), items)
    assert len(params["3"]) < 900 and "more, see the app" in params["3"] and "\n" not in params["3"]


async def test_the_evening_worker_makes_the_report_in_its_window_only(client, db, seeded, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from agyary.services import reminder_worker

    await _setup(client, db, seeded)
    await db.commit()
    monkeypatch.setattr(reminder_worker, "get_settings", lambda: _settings(daily_report_send_mode="off"))
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    await reminder_worker.tick(now=EVENING.replace(hour=15), session_factory=factory)     # before 8 pm
    await db.rollback()
    assert await _notes(db) == []

    await reminder_worker.tick(now=EVENING, session_factory=factory)
    await db.rollback()
    assert len(await _notes(db)) == 1

    await reminder_worker.tick(now=EVENING.replace(hour=23), session_factory=factory)     # after the cutoff: no second
    await db.rollback()
    assert len(await _notes(db)) == 1
