"""The "Who will pray" board, server side (DECISIONS D10, changed 21 Nov 2026,
three rounds; docs/phase2-requests-redesign.md; R3.1 step 4).

One row per person per request, whatever the channel, and the first answer of
a person counts. A yes fills a place while one is free (in the order they
came, two at the same moment filling exactly the free places), else it is a
standby; nobody is sent the details at a yes; the last place makes the request
all set, once. Outbound HTTP is mocked throughout.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from agyary.core import config
from agyary.models import FuneralRequest
from agyary.services import all_set, prayer_callout
from agyary.services import funeral_whatsapp as fw
from tests.test_prayer_callout import (
    FAMILY,
    LISTED,
    LIVE,
    MOBED,
    PANTHAKY,
    SECOND,
    Meta,
    _answers,
    _as,
    _list,
    _notes,
    _send,
    _signed_tap,
)


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


async def _listed(client, aid, panthaky, *people) -> None:
    for name, phone in people:
        r = await client.post(_list(aid), json={"name": name, "phone": phone, "agreed": True}, headers=panthaky)
        assert r.status_code == 200, r.text


async def _request(db, rid) -> FuneralRequest:
    return await db.get(FuneralRequest, rid, populate_existing=True)


def _no_family(meta) -> None:
    text = json.dumps(meta.sent)
    assert FAMILY.lstrip("+") not in text and "Test Family" not in text


# --- Places, standbys and All set ---------------------------------------------------

async def test_yeses_fill_the_places_in_order_and_a_later_yes_is_a_standby(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    await _listed(client, aid, panthaky, ("Er. Listed", LISTED), ("Er. Second", SECOND))
    rid, res, _ = await _send(client, db, aid, mobeds_wanted=2)
    assert res["callout"]["asked"] == 3
    answers = await _answers(db)
    meta.sent.clear()
    await _signed_tap(client, LISTED, f"pca:{answers[LISTED].token}:y")
    assert (await _request(db, rid)).status == "waiting"
    await _signed_tap(client, MOBED, f"pca:{answers[MOBED].token}:y")
    # Nobody going is sent the details at a yes: they go only at All set (Step 5).
    assert meta.sent == []
    request = await _request(db, rid)
    assert request.status == "all_set" and request.all_set_at is not None
    await _signed_tap(client, SECOND, f"pca:{answers[SECOND].token}:y")
    answers = await _answers(db)
    assert answers[LISTED].picked_at < answers[MOBED].picked_at and answers[SECOND].picked_at is None
    assert answers[SECOND].answer == "yes" and answers[SECOND].how == "whatsapp"
    # Only the standby gets a word back, the "enough" text, and never the details.
    assert [(m["to"], m["text"]["body"]) for m in meta.texts()] == [(SECOND, fw.ENOUGH_TEXT)]
    assert meta.templates("prayer_details_mobed_v2") == []
    _no_family(meta)
    titles = [n.title for n in await _notes(db, PANTHAKY, prayer_callout.KIND_GOING)]
    assert titles == ["Er. Listed is going (1 of 2)", "Er. Pervez Kias is going (2 of 2)"]
    assert [p["title"] for p in pushes if "going" in p["title"]] == titles
    for p in pushes:
        assert "Rustom" not in p["body"] and "Family" not in p["body"]


async def test_the_first_answer_counts(client, db, seeded, meta, pushes, live):
    rid, _, _ = await _send(client, db, seeded["agyary_id"])
    token = (await _answers(db))[MOBED].token
    await _signed_tap(client, MOBED, f"pca:{token}:n")
    await _signed_tap(client, MOBED, f"pca:{token}:y")
    row = (await _answers(db))[MOBED]
    assert row.answer == "no" and row.picked_at is None
    assert (await _request(db, rid)).status == "waiting"     # a panthaky is there: one no closes nothing


async def test_two_yeses_at_the_same_moment_fill_exactly_the_free_places(client, db, seeded, meta, pushes, live,
                                                                         monkeypatch):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    await _listed(client, aid, panthaky, ("Er. Listed", LISTED), ("Er. Second", SECOND))
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2)
    answers = await _answers(db)
    made = []
    real = all_set.on_full

    async def counted(*a, **kw):
        made.append(await real(*a, **kw))
        return made[-1]

    monkeypatch.setattr(all_set, "on_full", counted)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    settings = config.get_settings()

    async def tap(phone):
        async with factory() as s:
            return await prayer_callout.record_answer(s, settings, f"pca:{answers[phone].token}:y", phone)

    outcomes = await asyncio.gather(*(tap(p) for p in (MOBED, LISTED, SECOND)))
    assert sum("going" in o for o in outcomes) == 2 and sum("standby" in o for o in outcomes) == 1, outcomes
    answers = await _answers(db)
    assert sum(1 for a in answers.values() if a.picked_at) == 2
    assert made.count(True) == 1
    assert (await _request(db, rid)).status == "all_set"
    assert len(await _notes(db, PANTHAKY, prayer_callout.KIND_GOING)) == 2


async def test_all_set_is_made_once_and_only_from_waiting(client, db, seeded, pushes):
    rid, _, mgr = await _send(client, db, seeded["agyary_id"])
    request = await _request(db, rid)
    settings = config.get_settings()
    assert await all_set.on_full(db, settings, request) is True
    first = request.all_set_at
    assert await all_set.on_full(db, settings, request) is False
    request = await _request(db, rid)
    assert request.status == "all_set" and request.all_set_at == first and request.decided_at == first
    # Not a request that is no longer waiting.
    rid2, _, _ = await _send(client, db, seeded["agyary_id"], mgr)
    assert (await client.post(f"/api/mobed/manager/requests/{rid2}/withdraw", headers=mgr)).status_code == 200
    assert await all_set.on_full(db, settings, await _request(db, rid2)) is False
    assert (await _request(db, rid2)).status == "withdrawn"


async def test_an_all_set_request_is_taken_for_good_on_the_managers_side(client, db, seeded, pushes):
    rid, _, mgr = await _send(client, db, seeded["agyary_id"])
    await all_set.on_full(db, config.get_settings(), await _request(db, rid))
    record_id = (await _request(db, rid)).funeral_record_id
    got = (await client.get(f"/api/mobed/manager/records/{record_id}", headers=mgr)).json()["record"]
    assert got["may_send"] is False and got["may_edit"] is False
    assert got["requests"][0]["status"] == "all_set"
    r = await client.post(f"/api/mobed/requests/{rid}/accept", json={}, headers=await _as(client, PANTHAKY))
    assert r.status_code == 409 and r.json()["detail"] == "Enough mobeds are going for this request: it is all set."
    assert len(list((await db.execute(select(FuneralRequest))).scalars())) == 1


# --- Asking everyone ------------------------------------------------------------------

ADMIN, WAITING = "+919800000003", "+919822200044"


async def _recipients(db, rid) -> set[str]:
    from agyary.models import FuneralRequestRecipient, User

    return set((await db.execute(select(User.phone).join(
        FuneralRequestRecipient, FuneralRequestRecipient.user_id == User.id)
        .where(FuneralRequestRecipient.funeral_request_id == rid))).scalars())


async def test_asking_everyone_asks_the_app_mobeds_in_the_app_even_with_whatsapp_off_and_each_once(
    client, db, seeded, meta, pushes, monkeypatch,
):
    from agyary.models import Agyary
    from tests.funeral_helpers import member, place
    from tests.test_prayer_callout import OFF, _way

    monkeypatch.setenv("ADMIN_PHONES", ADMIN)
    config.get_settings.cache_clear()
    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    await member(db, goti, OFF, access="off", name="Er. Switched Off")
    await member(db, goti, WAITING, access="pending", name="Er. Waiting")
    await member(db, goti, "+919822200113", role="panthaky", name="Er. Second Panthaky")
    await member(db, goti, ADMIN, name="Er. Admin Mobed")     # the admin, who sends acting for the place
    at = await place(db)
    await db.commit()
    panthaky = await _as(client, PANTHAKY)
    await _listed(client, aid, panthaky, ("Er. Listed", LISTED))
    await _way(db, aid, "panthaky_first")
    admin = await _as(client, ADMIN)
    from tests.funeral_helpers import form

    rec = (await client.post(f"/api/mobed/manager/records?act_for={at.id}", json=form(), headers=admin)).json()
    r = await client.post(f"/api/mobed/manager/records/{rec['record']['id']}/requests?act_for={at.id}",
                          json={"agyary_id": aid, "family_agreed": True}, headers=admin)
    assert r.status_code == 200 and r.json()["callout"]["state"] == "panthaky_first", r.text
    rid = r.json()["record"]["requests"][0]["id"]
    assert await _recipients(db, rid) == {PANTHAKY, "+919822200113"}
    pushes.clear()

    # WhatsApp is off: the app mobed whose access is on is asked in the app all the same - not the
    # panthakys (they have it), not the admin who sent it, not an account that is off or waiting (D9).
    settings = config.get_settings()
    done = await prayer_callout.ask_everyone(db, settings, rid)
    assert done == {"state": "sent", "asked": 0, "asked_in_app": 1,
                    "message": f"1 mobed of Goti Adarian was asked in the app. {fw.OFF_WORDS}"}
    assert await _recipients(db, rid) == {PANTHAKY, "+919822200113", MOBED}
    (note,) = await _notes(db, MOBED, "funeral_request")
    assert note.title == "A Doongerwadi asks for prayers" and note.link == "#/requests"
    (push,) = pushes
    assert push["title"] == "A request for prayers" and push["body"] == "Doongerwadi (test) asks Goti Adarian for prayers."
    for text in (note.body, push["body"]):
        assert FAMILY not in text and "Test Family" not in text
    rows = await _answers(db)
    assert set(rows) == {MOBED} and rows[MOBED].how == "app" and rows[MOBED].answer is None
    assert meta.sent == []
    request = await _request(db, rid)
    assert request.taken_at is None        # asking at Send or by the safety net takes nothing

    # Asked once: again, nothing more.
    done = await prayer_callout.ask_everyone(db, settings, rid)
    assert done["state"] == "off" and done["asked_in_app"] == 0 and done["message"] == (
        f"Everyone on Goti Adarian's list in Mobed Diary has been asked already. {fw.OFF_WORDS}")
    assert len(await _notes(db, MOBED, "funeral_request")) == 1 and len(pushes) == 1

    # WhatsApp on: now those who can be messaged are asked there, each once, on their own row.
    for key, value in LIVE.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    settings = config.get_settings()
    first_row = rows[MOBED]
    done = await prayer_callout.ask_everyone(db, settings, rid)
    assert done == {"state": "sent", "asked": 2, "asked_in_app": 0,
                    "message": "2 mobeds of Goti Adarian were asked on WhatsApp."}
    assert sorted(m["to"] for m in meta.templates("prayer_request_mobeds")) == sorted([MOBED, LISTED])
    rows = await _answers(db)
    assert set(rows) == {MOBED, LISTED} and rows[MOBED].id == first_row.id and rows[LISTED].how == "whatsapp"
    payload = next(m for m in meta.sent if m["to"] == MOBED)["template"]["components"][1]["parameters"][0]["payload"]
    assert payload == f"pca:{first_row.token}:y"
    done = await prayer_callout.ask_everyone(db, settings, rid)
    assert done["state"] == "none" and done["message"] == "Everyone on Goti Adarian's list of mobeds has been asked already."
    assert len(meta.templates("prayer_request_mobeds")) == 2
    _no_family(meta)


async def test_asking_everyone_asks_nobody_once_the_request_is_closed(client, db, seeded, meta, pushes):
    rid, _, mgr = await _send(client, db, seeded["agyary_id"])
    assert (await client.post(f"/api/mobed/manager/requests/{rid}/withdraw", headers=mgr)).status_code == 200
    pushes.clear()
    done = await prayer_callout.ask_everyone(db, config.get_settings(), rid)
    assert done["state"] == "closed" and "withdrew this request" in done["message"]
    assert pushes == [] and meta.sent == []


# --- The board's routes ---------------------------------------------------------------

def _b(rid, what=""):
    return f"/api/mobed/requests/{rid}/board" if not what else f"/api/mobed/requests/{rid}/{what}"


async def _first(client, db, aid, *, minutes=None, mgr=None, **changes) -> tuple[int, dict]:
    """A request sent to Goti Adarian in Come to me first: only the panthaky has it."""
    from tests.test_prayer_callout import _way

    await _way(db, aid, "panthaky_first", minutes)
    rid, res, mgr = await _send(client, db, aid, mgr, **changes)
    assert res["callout"]["state"] == "panthaky_first"
    return rid, mgr


async def _uid(db, phone) -> int:
    from agyary.models import User

    return (await db.execute(select(User.id).where(User.phone == phone))).scalar_one()


async def test_only_the_panthakys_it_reached_and_the_admin_reach_the_board(client, db, seeded, pushes, monkeypatch):
    from sqlalchemy import update

    from agyary.models import Agyary, AgyaryUser
    from tests.funeral_helpers import agyari, member

    monkeypatch.setenv("ADMIN_PHONES", ADMIN)
    config.get_settings.cache_clear()
    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    claimed = await member(db, goti, "+919822200112", name="Er. Says Panthaky")
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == claimed.id)
                     .values(claimed_role="panthaky", claimed_at=datetime.now(timezone.utc)))
    other = await agyari(db, "Other Agyari (test)", None)
    await member(db, other, "+919822200099", role="panthaky", name="Er. Other Panthaky")
    await db.commit()
    rid, mgr = await _first(client, db, aid)
    # A panthaky confirmed only after the request was sent: it did not reach them.
    late = await member(db, goti, "+919822200113", role="panthaky", name="Er. Late Panthaky")
    await db.commit()

    panthaky = await _as(client, PANTHAKY)
    r = await client.get(_b(rid), headers=panthaky)
    assert r.status_code == 200, r.text
    assert (await client.get(_b(rid), headers=await _as(client, ADMIN))).status_code == 200
    actions = (("GET", _b(rid), None), ("POST", _b(rid, "ask-everyone"), {}), ("POST", _b(rid, "self"), {}),
               ("POST", _b(rid, "call-result"), {"key": f"u{late.id}", "result": "no_answer"}))
    for phone in (MOBED, "+919822200099", "+919822200112", "+919822200113"):
        headers = await _as(client, phone)
        for method, path, body in actions:
            r = await client.request(method, path, json=body, headers=headers)
            assert r.status_code == 404 and r.json()["detail"] == "That request could not be found.", (phone, path)
    for method, path, body in actions:
        r = await client.request(method, path, json=body, headers=mgr)
        assert r.status_code == 403, (path, r.text)       # a manager's account reaches no mobed route
        r = await client.request(method, path.replace(f"/{rid}/", "/99999/"), json=body, headers=panthaky)
        assert r.status_code == 404, path                  # nor does a request that does not exist
    assert (await _request(db, rid)).taken_at is None      # nothing anyone was refused took it


async def test_the_board_shows_the_request_without_the_family_and_the_numbers_to_the_panthaky(
    client, db, seeded, pushes,
):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    await _listed(client, aid, panthaky, ("Er. Listed", LISTED))
    rid, _ = await _first(client, db, aid, mobeds_wanted=2)
    r = await client.get(_b(rid), headers=panthaky)
    board = r.json()
    assert FAMILY not in r.text and FAMILY[3:] not in r.text and "Test Family" not in r.text
    assert board["prayed_name"] == "Behdin Rustom Jamshed" and board["place"]["name"] == "Doongerwadi (test)"
    assert board["geh_saarnu"]["text"].endswith("Havan geh") and board["uthamna"]["time"] == "16:00"
    assert board["mobeds_wanted"] == 2 and board["wanted"] == 2 and board["going"] == 0
    assert board["way"] == "panthaky_first" and board["taken"] is None and board["status"] == "waiting"
    assert board["places"] == [] and board["standbys"] == [] and board["may_pray"] is True
    assert board["ask_everyone"] == {"can": True, "why_not": None}
    assert board["whatsapp"] == {"on": False, "why_not": fw.OFF_WORDS}
    by_name = {m["name"]: m for m in board["mobeds"]}
    assert set(by_name) == {"Er. Pervez Kias", "Er. Listed"}           # not the panthaky themself
    assert by_name["Er. Pervez Kias"]["phone"] == MOBED and by_name["Er. Listed"]["phone"] == LISTED
    assert by_name["Er. Pervez Kias"]["state"] == "not_asked" and by_name["Er. Pervez Kias"]["can_ask"] is True
    # WhatsApp is off: the one added by hand cannot be asked now, the app mobed can (in the app).
    assert by_name["Er. Listed"]["state"] == "not_asked" and by_name["Er. Listed"]["can_ask"] is False


async def test_ill_pray_fills_a_place_and_takes_the_request_once(client, db, seeded, pushes):
    rid, _ = await _first(client, db, seeded["agyary_id"], mobeds_wanted=2)
    panthaky = await _as(client, PANTHAKY)
    r = await client.post(_b(rid, "self"), json={}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert r.json()["done"]["message"] == "You are going: 1 of 2."
    board = r.json()
    assert [(p["name"], p["how"]) for p in board["places"]] == [("Er. Hormuz Dadachanji", "self")]
    assert board["taken"]["by"] == "Er. Hormuz Dadachanji" and board["going"] == 1
    (row,) = (await _answers(db)).values()
    uid = row.user_id
    assert row.answer == "yes" and row.how == "self" and row.recorded_by_user_id == uid and row.picked_at
    request = await _request(db, rid)
    assert request.taken_by_user_id == uid and request.status == "waiting"
    r = await client.post(_b(rid, "self"), json={}, headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == "You are already going."
    assert (await _request(db, rid)).taken_at == request.taken_at
    # They are not told of their own place.
    assert await _notes(db, PANTHAKY, prayer_callout.KIND_GOING) == []


async def test_a_calls_result_going_not_going_or_no_answer(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    await _listed(client, aid, panthaky, ("Er. Listed", LISTED), ("Er. Second", SECOND))
    rid, _ = await _first(client, db, aid, mobeds_wanted=2)
    board = (await client.get(_b(rid), headers=panthaky)).json()
    keys = {m["name"]: m["key"] for m in board["mobeds"]}
    url = _b(rid, "call-result")

    # No answer: nothing kept, but the panthaky has acted.
    r = await client.post(url, json={"key": keys["Er. Listed"], "result": "no_answer"}, headers=panthaky)
    assert r.status_code == 200 and r.json()["done"]["message"] == "Noted: Er. Listed did not answer."
    assert await _answers(db) == {} and (await _request(db, rid)).taken_at is not None
    taken = (await _request(db, rid)).taken_at

    # Not going: a no by phone.
    r = await client.post(url, json={"key": keys["Er. Second"], "result": "not_going"}, headers=panthaky)
    assert r.status_code == 200 and r.json()["done"]["message"] == "Noted: Er. Second cannot pray this time."
    second = (await _answers(db))[SECOND]
    assert second.answer == "no" and second.how == "phone" and second.contact_id and second.recorded_by_user_id

    # Going: a place, by phone; the app mobed is told in the app, nobody on WhatsApp.
    pushes.clear()
    r = await client.post(url, json={"key": keys["Er. Pervez Kias"], "result": "going"}, headers=panthaky)
    assert r.status_code == 200 and r.json()["done"]["message"] == "Er. Pervez Kias is going: 1 of 2."
    kias = (await _answers(db))[MOBED]
    assert kias.answer == "yes" and kias.how == "phone" and kias.picked_at and kias.recorded_by_user_id
    assert [(p["name"], p["how"]) for p in r.json()["places"]] == [("Er. Pervez Kias", "phone")]
    states = {m["name"]: m["state"] for m in r.json()["mobeds"]}
    assert states == {"Er. Pervez Kias": "going", "Er. Listed": "not_asked", "Er. Second": "said_no"}
    (mine,) = await _notes(db, MOBED, prayer_callout.KIND_MY_YES)
    assert mine.body == prayer_callout.GOING_WORDS
    assert meta.sent == [] and pushes == []        # the panthaky who marked it is not told of it
    assert (await _request(db, rid)).taken_at == taken

    # Their first answer counts: a second mark is "already answered".
    r = await client.post(url, json={"key": keys["Er. Second"], "result": "going"}, headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == "Er. Second has already said they cannot pray this time."
    r = await client.post(url, json={"key": keys["Er. Pervez Kias"], "result": "not_going"}, headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == "Er. Pervez Kias is already going."

    # Someone not on the list, a wrong result, or the panthaky themself: refused in plain words.
    me = await _uid(db, PANTHAKY)
    for body, field in (({"key": "u99999", "result": "going"}, "key"), ({"key": "x1", "result": "going"}, "key"),
                        ({"key": keys["Er. Listed"], "result": "maybe"}, "result"),
                        ({"key": f"u{me}", "result": "going"}, "key")):
        r = await client.post(url, json=body, headers=panthaky)
        assert r.status_code == 400 and r.headers["X-Field"] == field, (body, r.text)


async def test_ask_everyone_from_the_board_takes_it_and_then_has_nobody_left(client, db, seeded, pushes):
    rid, _ = await _first(client, db, seeded["agyary_id"])
    panthaky = await _as(client, PANTHAKY)
    r = await client.post(_b(rid, "ask-everyone"), json={}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert r.json()["done"]["asked_in_app"] == 1 and r.json()["taken"]["by"] == "Er. Hormuz Dadachanji"
    assert r.json()["ask_everyone"]["can"] is False
    assert {m["name"]: m["state"] for m in r.json()["mobeds"]} == {"Er. Pervez Kias": "asked_app"}
    assert await _recipients(db, rid) == {PANTHAKY, MOBED}
    r = await client.post(_b(rid, "ask-everyone"), json={}, headers=panthaky)
    assert r.status_code == 409 and "asked already" in r.json()["detail"]


async def test_every_board_action_takes_it_once_and_the_safety_net_then_never_fires(client, db, seeded, meta,
                                                                                   pushes, live):
    from datetime import timedelta

    from agyary.models import Agyary, User
    from agyary.services import prayer_timers
    from tests.funeral_helpers import member

    aid = seeded["agyary_id"]
    second = await member(db, await db.get(Agyary, aid), "+919822200113", role="panthaky",
                          name="Er. Second Panthaky")
    await db.commit()
    rid, _ = await _first(client, db, aid, minutes=15)
    sent_at = (await _request(db, rid)).sent_at
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    settings = config.get_settings()
    kias = await _uid(db, MOBED)

    async def no_answer(user_id):
        async with factory() as s:
            user, request = await s.get(User, user_id), await s.get(FuneralRequest, rid)
            return await prayer_callout.call_result(s, settings, user, request, f"u{kias}", "no_answer")

    first = await _uid(db, PANTHAKY)
    done = await asyncio.gather(no_answer(first), no_answer(second.id))
    assert [d["outcome"] for d in done] == ["no answer", "no answer"]
    request = await _request(db, rid)
    assert request.taken_at is not None and request.taken_by_user_id in (first, second.id)
    took = (request.taken_at, request.taken_by_user_id)
    # Later actions do not take it again.
    r = await client.post(_b(rid, "self"), json={}, headers=await _as(client, PANTHAKY))
    assert r.status_code == 200, r.text
    request = await _request(db, rid)
    assert (request.taken_at, request.taken_by_user_id) == took
    # The panthaky acted: the safety net never asks everyone.
    meta.sent.clear()
    assert await prayer_timers.run(db, sent_at + timedelta(minutes=30), settings, None) == 0
    assert meta.sent == [] and (await _request(db, rid)).escalated_at is None


async def test_once_all_set_the_board_reads_so_and_takes_no_more(client, db, seeded, pushes):
    rid, _ = await _first(client, db, seeded["agyary_id"], mobeds_wanted=1)
    panthaky = await _as(client, PANTHAKY)
    r = await client.post(_b(rid, "self"), json={}, headers=panthaky)
    assert r.json()["done"]["message"] == "You are going. All the places are filled: it is all set."
    board = r.json()
    assert board["status"] == "all_set" and board["open"] is False and board["all_set_at"]
    all_set_words = "Enough mobeds are going for this request: it is all set."
    assert board["ask_everyone"] == {"can": False, "why_not": all_set_words}
    assert FAMILY[3:] not in r.text and "Test Family" not in r.text
    key = board["mobeds"][0]["key"]
    for path, body in (("ask-everyone", {}), ("self", {}), ("call-result", {"key": key, "result": "going"})):
        r = await client.post(_b(rid, path), json=body, headers=panthaky)
        assert r.status_code == 409 and r.json()["detail"] == all_set_words, path


# --- App mobeds answer in the app too, and a fire temple with no panthaky ----------------

REQUESTS = "/api/mobed/requests"


async def test_an_app_mobed_answers_in_the_app_and_the_first_answer_counts_across_channels(
    client, db, seeded, meta, pushes, live,
):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    await _listed(client, aid, panthaky, ("Er. Listed", LISTED))
    rid, res, _ = await _send(client, db, aid, mobeds_wanted=2)
    assert res["callout"]["asked_in_app"] == 1 and res["callout"]["asked"] == 2
    mobed = await _as(client, MOBED)

    # The card: the prayers, n of N going, their own answer; no family, nobody else's number.
    card = await client.get(f"{REQUESTS}/{rid}", headers=mobed)
    assert card.status_code == 200
    q = card.json()["request"]
    assert q["places"] == {"going": 0, "wanted": 2}
    assert q["my_answer"] == {"state": "asked", "answer": None, "how": None, "may_answer": True}
    for number in (FAMILY, PANTHAKY, LISTED):
        assert number not in card.text and number[3:] not in card.text
    assert "Test Family" not in card.text and "callout" not in q

    # "I can pray": a place, how "app"; told so in the app, and the panthaky is told.
    pushes.clear()
    meta.sent.clear()
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=mobed)
    assert r.status_code == 200, r.text
    assert r.json()["done"]["message"] == prayer_callout.GOING_WORDS
    assert r.json()["request"]["my_answer"]["state"] == "going" and r.json()["request"]["places"]["going"] == 1
    row = (await _answers(db))[MOBED]
    assert row.answer == "yes" and row.how == "app" and row.picked_at is not None
    (going,) = await _notes(db, PANTHAKY, prayer_callout.KIND_GOING)
    assert going.title == "Er. Pervez Kias is going (1 of 2)" and "in the app" in going.body
    assert meta.sent == []        # no details, and no WhatsApp text for an answer in the app

    # Their WhatsApp button afterwards changes nothing; nor does a second answer in the app.
    await _signed_tap(client, MOBED, f"pca:{row.token}:n")
    assert (await _answers(db))[MOBED].answer == "yes" and meta.sent == []
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "no"}, headers=mobed)
    assert r.status_code == 409 and r.json()["detail"] == "You have already said yes: you are going."

    # The other way round: a no on WhatsApp first, then the app.
    listed = (await _answers(db))[LISTED]
    await _signed_tap(client, LISTED, f"pca:{listed.token}:n")
    assert (await _answers(db))[LISTED].answer == "no"

    # A wrong answer, the panthaky, or someone it did not reach: refused.
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "maybe"}, headers=mobed)
    assert r.status_code == 400 and r.headers["X-Field"] == "answer"
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == prayer_callout.PANTHAKY_USES_BOARD
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=await _as(client, SECOND))
    assert r.status_code == 404
    # The old Accept is for the panthaky here: a mobed answers for themselves.
    r = await client.post(f"{REQUESTS}/{rid}/accept", json={}, headers=mobed)
    assert r.status_code == 409 and "The panthaky of Goti Adarian takes this request" in r.json()["detail"]
    assert (await _request(db, rid)).status == "waiting"


async def test_a_mobeds_not_this_time_answers_only_for_them_and_a_late_yes_is_a_standby(client, db, seeded,
                                                                                        pushes):
    rid, _, mgr = await _send(client, db, seeded["agyary_id"], mobeds_wanted=1)
    mobed = await _as(client, MOBED)
    # The old Decline, used by a mobed, now means "not this time" for them only.
    r = await client.post(f"{REQUESTS}/{rid}/decline", json={"reason": "away"}, headers=mobed)
    assert r.status_code == 200, r.text
    assert r.json()["done"]["message"] == prayer_callout.NO_WORDS
    assert r.json()["request"]["status"] == "waiting" and r.json()["request"]["my_answer"]["state"] == "said_no"
    request = await _request(db, rid)
    assert request.status == "waiting" and request.decline_reason is None
    # The panthaky's "We can't take this" still closes it for the fire temple.
    panthaky = await _as(client, PANTHAKY)
    r = await client.post(f"{REQUESTS}/{rid}/decline", json={"reason": None}, headers=panthaky)
    assert r.status_code == 200 and r.json()["request"]["status"] == "declined"

    # All set: a late "I can pray" is a standby, told so in the app.
    rid, _, _ = await _send(client, db, seeded["agyary_id"], mgr, mobeds_wanted=1)
    assert (await client.post(_b(rid, "self"), json={}, headers=panthaky)).status_code == 200
    assert (await _request(db, rid)).status == "all_set"
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=mobed)
    assert r.status_code == 200 and r.json()["done"]["message"] == fw.ENOUGH_TEXT
    assert r.json()["request"]["my_answer"]["state"] == "standby"
    note = (await _notes(db, MOBED, prayer_callout.KIND_MY_YES))[-1]
    assert note.title == "Enough mobeds are going" and note.body == fw.ENOUGH_TEXT


async def test_with_no_panthaky_one_no_leaves_it_open_and_when_all_say_no_the_doongerwadi_is_told(
    client, db, seeded, pushes,
):
    from agyary.models import AppNotification
    from tests.funeral_helpers import agyari, member

    only = await agyari(db, "Mobeds Only Agyari (test)", None)
    await member(db, only, "+919822200111", name="Er. Only One")
    await member(db, only, "+919822200112", name="Er. Only Two")
    await db.commit()
    rid, res, mgr = await _send(client, db, only.id)
    assert res["asked"] == 2 and res["callout"]["asked_in_app"] == 0      # both had it from Send
    one, two = await _as(client, "+919822200111"), await _as(client, "+919822200112")

    pushes.clear()
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "no"}, headers=one)
    assert r.status_code == 200 and r.json()["request"]["status"] == "waiting"
    assert (await client.get(f"{REQUESTS}/count", headers=two)).json() == {"waiting": 1}
    assert pushes == []
    # The last no, by the old Decline: closed for that fire temple, and the Doongerwadi is told.
    r = await client.post(f"{REQUESTS}/{rid}/decline", json={}, headers=two)
    assert r.status_code == 200, r.text
    request = await _request(db, rid)
    assert request.status == "declined" and request.decided_by_user_id is None and request.decided_at
    (note,) = (await db.execute(select(AppNotification).where(
        AppNotification.kind == prayer_callout.KIND_NOBODY))).scalars().all()
    assert note.title == "Nobody at Mobeds Only Agyari (test) can take it"
    assert note.link == f"#/manager/record/{request.funeral_record_id}"
    (push,) = pushes
    assert push["title"] == "Nobody at Mobeds Only Agyari (test) can take it"
    assert "Rustom" not in push["body"] and FAMILY[3:] not in push["body"]
    got = (await client.get(f"/api/mobed/manager/records/{request.funeral_record_id}", headers=mgr)).json()["record"]
    assert got["may_send"] is True and got["requests"][0]["status"] == "declined"


async def test_with_no_panthaky_a_yes_keeps_it_open_whatever_the_others_say(client, db, seeded, pushes):
    from tests.funeral_helpers import agyari, member

    only = await agyari(db, "Mobeds Only Agyari (test)", None)
    await member(db, only, "+919822200111", name="Er. Only One")
    await member(db, only, "+919822200112", name="Er. Only Two")
    await db.commit()
    rid, _, _ = await _send(client, db, only.id, mobeds_wanted=2)
    one, two = await _as(client, "+919822200111"), await _as(client, "+919822200112")
    assert (await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=one)).status_code == 200
    assert (await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "no"}, headers=two)).status_code == 200
    assert (await _request(db, rid)).status == "waiting"
    # Nobody at a fire temple with no panthaky is told of each yes; their cards show the count.
    assert await _notes(db, "+919822200112", prayer_callout.KIND_GOING) == []
    card = (await client.get(f"{REQUESTS}/{rid}", headers=two)).json()["request"]
    assert card["places"] == {"going": 1, "wanted": 2} and card["my_answer"]["state"] == "said_no"
