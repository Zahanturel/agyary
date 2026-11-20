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
