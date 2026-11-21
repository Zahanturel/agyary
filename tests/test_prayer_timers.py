"""The safety net in Come to me first (DECISIONS D10, changed 21 Nov 2026;
R3.1 step 2), and the one-minute loop that runs it.

When the panthaky chose "if I haven't acted in 15 min / 30 min / 1 hour, ask
all our mobeds", the loop asks everyone on WhatsApp - as Everyone at once does
at Send - once that long has passed with the request still waiting and the
panthaky not having acted: never before, never twice (two loops at once
included), never under Never, never once the panthaky switched to Everyone at
once, asked by hand, accepted or declined, nor once the request was withdrawn.
When nobody can be asked it is still done once, and the panthaky is told what
happened, in the app and on their phone, with nothing about the family. D9:
nothing goes to or under an account that is not on. The loop runs the timers
on every tick whatever the hour, and a failure there never stops the evening
jobs, nor theirs the timers. Outbound HTTP is mocked throughout.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, time, timedelta

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from agyary.core import config
from agyary.core.config import Settings
from agyary.models import Agyary, FuneralRequest, PrayerCallout, User
from agyary.services import funeral_whatsapp as fw
from agyary.services import prayer_timers, reminder_sender, reminder_worker, reminders
from tests.funeral_helpers import FAMILY, member
from tests.test_prayer_callout import (
    LISTED,
    LIVE,
    MOBED,
    OFF,
    PANTHAKY,
    Meta,
    _answers,
    _as,
    _list,
    _notes,
    _send,
    _way,
)

IST = reminder_sender.IST


@pytest.fixture
def meta(monkeypatch):
    fake = Meta()
    monkeypatch.setattr(fw, "make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
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


@pytest.fixture(autouse=True)
def no_still_short(monkeypatch):
    """These are the safety net's tests. "Still short", which the same tick runs
    (and which a request here, its Geh-saarnu today, could be due for), has its
    own in tests/test_all_set.py; so has "No answer yet", which a request here
    nobody answers is due for after an hour, in tests/test_manager_r31.py."""
    async def nothing(*a, **kw):
        return 0

    monkeypatch.setattr(prayer_timers, "still_short", nothing)
    monkeypatch.setattr(prayer_timers, "no_answer", nothing)


async def _come_to_me_first(client, db, aid, minutes=30, mgr=None) -> tuple[int, datetime, dict]:
    """A request sent to Goti Adarian in Come to me first: nobody is asked at Send."""
    await _way(db, aid, "panthaky_first", minutes)
    rid, res, mgr = await _send(client, db, aid, mgr)
    assert res["callout"]["state"] == "panthaky_first"
    return rid, (await db.get(FuneralRequest, rid)).sent_at, mgr


async def _tick(db, at: datetime) -> int:
    return await prayer_timers.run(db, at, config.get_settings(), None)


async def _request(db, rid) -> FuneralRequest:
    return await db.get(FuneralRequest, rid, populate_existing=True)


def _asked(meta) -> list[str]:
    return sorted(m["to"] for m in meta.templates("prayer_request_mobeds_v2"))


async def _uid(db, phone) -> int:
    return (await db.execute(select(User.id).where(User.phone == phone))).scalar_one()


async def test_it_asks_everyone_once_when_the_minutes_have_passed(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    r = await client.post(_list(aid), json={"name": "Er. Listed", "phone": LISTED, "agreed": True}, headers=panthaky)
    assert r.status_code == 200, r.text
    rid, sent_at, _ = await _come_to_me_first(client, db, aid, 30)
    assert meta.sent == [] and pushes[-1]["to"] == [await _uid(db, PANTHAKY)]
    pushes.clear()

    # Not before.
    assert await _tick(db, sent_at + timedelta(minutes=29, seconds=59)) == 0
    assert meta.sent == [] and (await _request(db, rid)).escalated_at is None

    # Then everyone on the list, as at Send in Everyone at once: the app mobed in the app
    # (R3.1 step 4) and on WhatsApp, and the one added by hand on WhatsApp.
    at = sent_at + timedelta(minutes=30)
    assert await _tick(db, at) == 1
    assert _asked(meta) == sorted([MOBED, LISTED])
    for m in meta.templates("prayer_request_mobeds_v2"):
        body = [p["text"] for p in m["template"]["components"][0]["parameters"]]
        assert body[5] == "Er. Hormuz Dadachanji" and FAMILY.lstrip("+") not in json.dumps(m)
    assert (await _request(db, rid)).escalated_at == at
    assert set(await _answers(db)) == {MOBED, LISTED}

    # The panthaky is told, in the app and on their phone; nothing about the family.
    (note,) = await _notes(db, PANTHAKY, prayer_timers.KIND_ESCALATED)
    assert note.title == "All your mobeds were asked"
    assert note.body == ("Nobody had answered the request from Doongerwadi (test) for Behdin Rustom Jamshed in "
                         "30 minutes, so Mobed Diary asked all your mobeds. "
                         "1 mobed of Goti Adarian was asked in the app, and 2 on WhatsApp.")
    assert note.link == f"#/requests/{rid}/callout" and note.agyary_id == aid
    request_push, push = pushes
    assert request_push["to"] == [await _uid(db, MOBED)] and request_push["title"] == "A request for prayers"
    (asked_in_app,) = await _notes(db, MOBED, "funeral_request")
    assert asked_in_app.link == "#/requests"
    assert push["to"] == [await _uid(db, PANTHAKY)] and push["title"] == "All your mobeds were asked"
    assert push["body"] == ("Nobody had answered the request from Doongerwadi (test) in 30 minutes, "
                            "so Mobed Diary asked all your mobeds.")
    assert push["url"] == f"/mobed#/requests/{rid}/callout"
    for text in (note.title, note.body, push["title"], push["body"]):
        assert FAMILY not in text and FAMILY[3:] not in text and "Test Family" not in text
    assert "Rustom" not in push["body"]
    assert await _notes(db, MOBED, prayer_timers.KIND_ESCALATED) == []

    # Never twice.
    meta.sent.clear()
    for later in (31, 60, 600):
        assert await _tick(db, sent_at + timedelta(minutes=later)) == 0
    assert meta.sent == [] and len(await _notes(db, PANTHAKY, prayer_timers.KIND_ESCALATED)) == 1
    assert len(pushes) == 2


async def test_nothing_once_the_panthaky_acted_or_the_request_stopped_waiting(client, db, seeded, meta, pushes,
                                                                              live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    # The panthaky asked a mobed by hand.
    asked_rid, sent_at, mgr = await _come_to_me_first(client, db, aid, 15)
    view = (await client.get(f"/api/mobed/requests/{asked_rid}/callout", headers=panthaky)).json()
    r = await client.post(f"/api/mobed/requests/{asked_rid}/callout", json={"who": [view["candidates"][0]["key"]]},
                          headers=panthaky)
    assert r.status_code == 200 and r.json()["asked_now"] == 1
    # Accepted, declined, withdrawn.
    accepted, _, _ = await _come_to_me_first(client, db, aid, 15, mgr)
    r = await client.post(f"/api/mobed/requests/{accepted}/accept", json={"share_contact": False}, headers=panthaky)
    assert r.status_code == 200, r.text
    declined, _, _ = await _come_to_me_first(client, db, aid, 15, mgr)
    r = await client.post(f"/api/mobed/requests/{declined}/decline", json={"reason": None}, headers=panthaky)
    assert r.status_code == 200, r.text
    withdrawn, _, _ = await _come_to_me_first(client, db, aid, 15, mgr)
    r = await client.post(f"/api/mobed/manager/requests/{withdrawn}/withdraw", headers=mgr)
    assert r.status_code == 200, r.text

    meta.sent.clear()
    pushes.clear()
    assert await _tick(db, sent_at + timedelta(hours=2)) == 0
    assert meta.sent == [] and pushes == []
    for rid in (asked_rid, accepted, declined, withdrawn):
        assert (await _request(db, rid)).escalated_at is None
    assert len(list((await db.execute(select(PrayerCallout))).scalars())) == 1      # the panthaky's own
    assert await _notes(db, PANTHAKY, prayer_timers.KIND_ESCALATED) == []


async def test_never_or_everyone_at_once_when_it_looks_does_nothing(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    settings_url = f"/api/mobed/agyaries/{aid}/request-settings"
    rid, sent_at, _ = await _come_to_me_first(client, db, aid, None)       # Never, the default
    assert await _tick(db, sent_at + timedelta(days=1)) == 0

    # The safety net turned on afterwards, then the panthaky switched to Everyone at once.
    r = await client.put(settings_url, json={"mode": "panthaky_first", "escalate_minutes": 60}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert await _tick(db, sent_at + timedelta(minutes=45)) == 0           # read as it is now: 60 minutes
    r = await client.put(settings_url, json={"mode": "everyone", "escalate_minutes": 60}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert await _tick(db, sent_at + timedelta(hours=2)) == 0
    assert meta.sent == [] and (await _request(db, rid)).escalated_at is None

    # And back to Come to me first: the setting as it is when the timer looks.
    r = await client.put(settings_url, json={"mode": "panthaky_first", "escalate_minutes": 60}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert await _tick(db, sent_at + timedelta(hours=2)) == 1
    assert _asked(meta) == [MOBED]


async def test_with_whatsapp_off_it_is_done_once_and_the_panthaky_told_why(client, db, seeded, meta, pushes):
    aid = seeded["agyary_id"]
    rid, sent_at, mgr = await _come_to_me_first(client, db, aid, 15)
    pushes.clear()
    at = sent_at + timedelta(minutes=15)
    assert await _tick(db, at) == 1
    assert meta.sent == [] and (await _request(db, rid)).escalated_at == at
    # The app mobed is asked in the app all the same (R3.1 step 4).
    (note,) = await _notes(db, PANTHAKY, prayer_timers.KIND_ESCALATED)
    assert note.title == "All your mobeds were asked"
    assert note.body == ("Nobody had answered the request from Doongerwadi (test) for Behdin Rustom Jamshed in "
                         "15 minutes, so Mobed Diary asked all your mobeds. "
                         f"1 mobed of Goti Adarian was asked in the app. {fw.OFF_WORDS}")
    assert [p["to"] for p in pushes] == [[await _uid(db, MOBED)], [await _uid(db, PANTHAKY)]]
    assert await _tick(db, at + timedelta(minutes=1)) == 0
    assert len(await _notes(db, PANTHAKY, prayer_timers.KIND_ESCALATED)) == 1 and len(pushes) == 2

    # Nobody in the app to ask either: still done once, and the panthaky is told why.
    await db.execute(update(User).where(User.phone == MOBED).values(access="off"))
    await db.commit()
    rid, sent_at, _ = await _come_to_me_first(client, db, aid, 15, mgr)
    pushes.clear()
    at = sent_at + timedelta(minutes=15)
    assert await _tick(db, at) == 1
    note = (await _notes(db, PANTHAKY, prayer_timers.KIND_ESCALATED))[-1]
    assert note.title == "Your mobeds could not be asked" and note.link == f"#/requests/{rid}"
    assert note.body == ("Nobody had answered the request from Doongerwadi (test) for Behdin Rustom Jamshed in "
                         "15 minutes, so Mobed Diary tried to ask all your mobeds. "
                         f"{fw.OFF_WORDS} Please open the request to find mobeds.")
    (push,) = pushes
    assert push["body"] == ("Nobody had answered the request from Doongerwadi (test) in 15 minutes, "
                            "and Mobed Diary could not ask your mobeds.")


async def test_nothing_goes_to_or_under_an_account_that_is_not_on(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    await member(db, await db.get(Agyary, aid), OFF, access="off", name="Er. Switched Off")
    await db.commit()
    rid, sent_at, mgr = await _come_to_me_first(client, db, aid, 15)
    # The panthaky's access is switched off before the minutes pass.
    await db.execute(update(User).where(User.phone == PANTHAKY).values(access="off"))
    await db.commit()
    pushes.clear()
    assert await _tick(db, sent_at + timedelta(minutes=15)) == 1
    assert _asked(meta) == [MOBED]                     # not the account that is off, nor the panthaky
    body = [p["text"] for p in meta.templates("prayer_request_mobeds_v2")[0]["template"]["components"][0]["parameters"]]
    assert body[5] == "Goti Adarian"                  # not under the panthaky who is off
    assert await _notes(db, PANTHAKY, prayer_timers.KIND_ESCALATED) == []
    # Only the mobed asked is woken, with the request itself; not the panthaky who is off.
    assert [(p["to"], p["title"]) for p in pushes] == [([await _uid(db, MOBED)], "A request for prayers")]

    # Nobody left who can be asked: still done once, and nobody asked.
    await db.execute(update(User).where(User.phone == MOBED).values(access="off"))
    await db.execute(update(User).where(User.phone == PANTHAKY).values(access="on"))
    await db.commit()
    meta.sent.clear()
    rid, sent_at, _ = await _come_to_me_first(client, db, aid, 15, mgr)
    pushes.clear()
    assert await _tick(db, sent_at + timedelta(minutes=15)) == 1
    assert meta.sent == [] and (await _request(db, rid)).escalated_at is not None
    (note,) = await _notes(db, PANTHAKY, prayer_timers.KIND_ESCALATED)
    assert note.title == "Your mobeds could not be asked"
    assert "Nobody on Goti Adarian's list of mobeds could be asked on WhatsApp." in note.body


async def test_two_loops_at_the_same_moment_ask_once(client, db, seeded, meta, pushes, live):
    rid, sent_at, _ = await _come_to_me_first(client, db, seeded["agyary_id"], 30)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    at = sent_at + timedelta(minutes=30)
    async with factory() as one, factory() as two:
        done = await asyncio.gather(prayer_timers.run(one, at, config.get_settings(), None),
                                    prayer_timers.run(two, at, config.get_settings(), None))
    assert sorted(done) == [0, 1]
    assert _asked(meta) == [MOBED]
    assert len(list((await db.execute(select(PrayerCallout))).scalars())) == 1
    assert len(await _notes(db, PANTHAKY, prayer_timers.KIND_ESCALATED)) == 1


# --- The one-minute loop -------------------------------------------------------------

def _quiet_settings(**over) -> Settings:
    """No evening job sends anything; the Doongerwadi's WhatsApp as the test says."""
    return Settings(**{**dict(jwt_secret_key="x", reminders_send_mode="off", daily_report_send_mode="off"), **over})


async def test_the_loop_runs_the_safety_net_at_three_in_the_morning(client, db, seeded, pushes, monkeypatch):
    rid, _, _ = await _come_to_me_first(client, db, seeded["agyary_id"], 30)
    three_am = datetime.combine(datetime.now(IST).date(), time(3, 0), tzinfo=IST)
    await db.execute(update(FuneralRequest).where(FuneralRequest.id == rid)
                     .values(sent_at=three_am - timedelta(minutes=30)))
    await db.commit()
    monkeypatch.setattr(reminder_worker, "get_settings", lambda: _quiet_settings(
        funeral_whatsapp_mode="live", whatsapp_access_token="test-token", whatsapp_phone_number_id="555",
        reminders_allowlist="*"))
    fake = Meta()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as http:
        report = await reminder_worker.tick(now=three_am, client=http, session_factory=factory)
    assert (report.closing, report.planned, report.sent) == (0, 0, 0)        # no evening job at 3 am
    assert [m["to"] for m in fake.templates("prayer_request_mobeds_v2")] == [MOBED]
    assert (await _request(db, rid)).escalated_at == three_am


async def test_the_loop_calls_the_timers_on_every_tick_whatever_the_hour(db, monkeypatch):
    calls = []

    async def timers(db_, now, settings, client):
        calls.append(now)
        return 0

    monkeypatch.setattr(prayer_timers, "run", timers)
    monkeypatch.setattr(reminder_worker, "get_settings", lambda: _quiet_settings())
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    day = datetime.now(IST).date()
    moments = [datetime.combine(day, time(h, m), tzinfo=IST) for h, m in ((3, 0), (12, 1), (19, 30), (23, 59))]
    for at in moments:
        await reminder_worker.tick(now=at, session_factory=factory)
    assert calls == moments


async def test_a_timer_that_breaks_never_stops_the_evening_jobs_nor_they_the_timers(db, monkeypatch, caplog):
    caplog.set_level(logging.ERROR)
    closing, timed = [], []

    async def broken(*a, **kw):
        raise RuntimeError("something unexpected")

    async def closing_notices(db_, now):
        closing.append(now)
        return 0

    monkeypatch.setattr(reminder_worker, "get_settings", lambda: _quiet_settings())
    monkeypatch.setattr(prayer_timers, "run", broken)
    monkeypatch.setattr(reminders, "notify_closing_tomorrow", closing_notices)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    evening = datetime.combine(datetime.now(IST).date(), time(19, 30), tzinfo=IST)
    report = await reminder_worker.tick(now=evening, session_factory=factory)
    assert closing == [evening] and report.closing == 0
    assert "Prayer request timers failed" in caplog.text

    # The other way round: the timers ran before the evening job broke.
    async def timers(db_, now, settings, client):
        timed.append(now)
        return 0

    monkeypatch.setattr(prayer_timers, "run", timers)
    monkeypatch.setattr(reminders, "notify_closing_tomorrow", broken)
    with pytest.raises(RuntimeError):
        await reminder_worker.tick(now=evening, session_factory=factory)
    assert timed == [evening]
