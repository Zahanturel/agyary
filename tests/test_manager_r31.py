"""The Doongerwadi's side of R3.1 (DECISIONS D10, changed 21 Nov 2026;
docs/phase2-requests-redesign.md, "The Doongerwadi's side"; R3.1 step 6).

The manager (and the admin acting for the place) reads where each request
stands in plain words: Waiting at <agyari> (Sent to the panthaky of <agyari> in
Come to me first), Finding mobeds at <agyari>: 1 of 2 going, All set at
<agyari> with the mobeds' names and the panthaky's name and number (confirmed
with fewer, or with no panthaky only the names), A place has opened (someone
going backed out), Declined by <agyari>, Nobody at <agyari> can take it, and
Withdrawn; one accepted the old way reads as before (D8). How many are going is
all the place learns while it waits: never a mobed's number, and the names and
the panthaky's contact only once it is all set.

The fire temples to choose from say their way, for the sheet before Send, and
whether WhatsApp is on; nothing else of them. "No answer yet" is told once to
the place (and the admin who sent it) an hour after a request nobody at the
fire temple has answered or taken, never once anyone did or the prayers have
begun. "Send to another agyari" is the withdraw, after which the record can be
sent again. Outbound HTTP is mocked throughout.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from agyary.core import config
from agyary.models import AppNotification, FuneralRequest, User
from agyary.services import funeral_records
from tests.funeral_helpers import agyari, form, manager, member
from tests.test_prayer_callout import ADMIN, MOBED, PANTHAKY, _as, _way

RECORDS = "/api/mobed/manager/records"
REQUESTS = "/api/mobed/requests"
HEAD, GOING = "Er. Hormuz Dadachanji", "Er. Pervez Kias"      # the seeded fire temple's
ONLY = "+919822200121"


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
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_PHONES", ADMIN)
    config.get_settings.cache_clear()
    yield ADMIN
    config.get_settings.cache_clear()


def _days(**changes) -> dict:
    """Two mobeds wanted, the Geh-saarnu the day after tomorrow: the prayers have not begun."""
    today = funeral_records.today_ist()
    return {"mobeds_wanted": 2, "geh_saarnu_date": (today + timedelta(days=2)).isoformat(),
            "uthamna_date": (today + timedelta(days=3)).isoformat(), **changes}


async def _send(client, db, aid, mgr=None, *, act=None, **changes) -> tuple[int, int, dict]:
    """(request id, record id, the manager's headers): a record sent to ``aid``."""
    if mgr is None:
        mgr, _ = await manager(client, db)
    q = f"?act_for={act}" if act else ""
    rec = (await client.post(RECORDS + q, json=form(**_days(**changes)), headers=mgr)).json()["record"]
    r = await client.post(f"{RECORDS}/{rec['id']}/requests{q}", headers=mgr,
                          json={"agyary_id": aid, "family_agreed": True, "family_whatsapp_agreed": True})
    assert r.status_code == 200, r.text
    return r.json()["record"]["requests"][0]["id"], rec["id"], mgr


async def _record(client, record_id, headers, act=None) -> dict:
    r = await client.get(f"{RECORDS}/{record_id}" + (f"?act_for={act}" if act else ""), headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["record"]


async def _latest(client, record_id, headers, act=None) -> dict:
    return (await _record(client, record_id, headers, act))["requests"][0]


async def _id(db, phone) -> int:
    return (await db.execute(select(User.id).where(User.phone == phone))).scalar_one()


async def _request(db, rid) -> FuneralRequest:
    return await db.get(FuneralRequest, rid, populate_existing=True)


async def _notes(db, phone, kind) -> list[AppNotification]:
    uid = await _id(db, phone)
    return list((await db.execute(select(AppNotification).where(
        AppNotification.user_id == uid, AppNotification.kind == kind).order_by(AppNotification.id))).scalars())


async def _yes(client, rid, phone=MOBED, answer="yes"):
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": answer}, headers=await _as(client, phone))
    assert r.status_code == 200, r.text


async def _board(client, rid, what, body=None, phone=PANTHAKY):
    r = await client.post(f"{REQUESTS}/{rid}/{what}", json=body or {}, headers=await _as(client, phone))
    assert r.status_code == 200, r.text
    return r.json()


def _no_mobed_contact(text: str) -> None:
    assert MOBED not in text and MOBED[3:] not in text, text


def _nothing_of_who(q: dict) -> None:
    """While it is not all set: how many, never who, never the panthaky's number."""
    assert q["going_names"] == [] and q["panthakys"] == []
    text = json.dumps(q)
    _no_mobed_contact(text)
    assert PANTHAKY not in text and HEAD not in text and GOING not in text, text


# --- Where it stands, in words -------------------------------------------------------------

async def test_waiting_then_finding_then_all_set_for_the_manager_and_the_acting_admin(client, db, seeded, pushes,
                                                                                    admin):
    aid = seeded["agyary_id"]
    rid, record_id, mgr = await _send(client, db, aid)
    q = await _latest(client, record_id, mgr)
    assert (q["stage"], q["headline"]) == ("waiting", "Waiting at Goti Adarian")
    assert q["going"] is None and q["wanted"] == 2 and q["may_withdraw"] is True
    assert q["no_answer_told_at"] is None and q["confirmed_short"] is False
    _nothing_of_who(q)

    # One yes: how many, not who.
    await _yes(client, rid)
    q = await _latest(client, record_id, mgr)
    assert (q["stage"], q["headline"], q["going"]) == ("finding", "Finding mobeds at Goti Adarian: 1 of 2 going", 1)
    _nothing_of_who(q)

    # The panthaky's I'll pray fills the last place: all set, with the names and the panthaky's contact.
    await _board(client, rid, "self")
    rec = await _record(client, record_id, mgr)
    q = rec["requests"][0]
    assert q["stage"] == "all_set" and q["going"] == 2 and q["may_withdraw"] is False
    assert q["headline"] == f"All set at Goti Adarian: {GOING} and {HEAD} are going"
    assert q["going_names"] == [GOING, HEAD]
    assert q["panthakys"] == [{"name": HEAD, "phone": PANTHAKY}]
    # Never a mobed's number, nor which mobed has the family in their book.
    _no_mobed_contact(json.dumps(rec))
    assert "customer" not in json.dumps(q) and "book" not in json.dumps(q)
    assert rec["may_send"] is False and rec["may_edit"] is False

    # The admin acting for the place reads the same.
    place_id = rec["funeral_place"]["id"]
    acting = await _as(client, admin)
    assert await _latest(client, record_id, acting, act=place_id) == q
    listed = (await client.get(f"{RECORDS}?act_for={place_id}", headers=acting)).json()["records"]
    assert listed[0]["requests"][0]["headline"] == q["headline"]
    # And the manager's list of records says it in the same words.
    listed = (await client.get(RECORDS, headers=mgr)).json()["records"]
    assert listed[0]["requests"][0]["headline"] == q["headline"]


async def test_come_to_me_first_reads_sent_to_the_panthaky_until_they_act(client, db, seeded, pushes):
    aid = seeded["agyary_id"]
    await _way(db, aid, "panthaky_first")
    rid, record_id, mgr = await _send(client, db, aid)
    q = await _latest(client, record_id, mgr)
    assert (q["stage"], q["headline"]) == ("panthaky_first", "Sent to the panthaky of Goti Adarian")
    _nothing_of_who(q)
    # The panthaky asks everyone: taken, finding mobeds.
    await _board(client, rid, "ask-everyone")
    q = await _latest(client, record_id, mgr)
    assert (q["stage"], q["headline"]) == ("finding", "Finding mobeds at Goti Adarian: 0 of 2 going")
    _nothing_of_who(q)


async def test_confirmed_short_reopened_and_with_no_panthaky_just_the_names(client, db, seeded, pushes):
    aid = seeded["agyary_id"]
    rid, record_id, mgr = await _send(client, db, aid)
    await _yes(client, rid)
    await _board(client, rid, "confirm-short")
    q = await _latest(client, record_id, mgr)
    assert q["stage"] == "all_set" and q["confirmed_short"] is True and (q["going"], q["wanted"]) == (1, 2)
    assert q["headline"] == f"All set at Goti Adarian: {GOING} is going (confirmed with 1 of 2)"
    assert q["panthakys"] == [{"name": HEAD, "phone": PANTHAKY}] and q["going_names"] == [GOING]

    # The mobed going can no longer go: a place has opened, and the place learns only how many.
    r = await client.post(f"{REQUESTS}/{rid}/back-out", headers=await _as(client, MOBED))
    assert r.status_code == 200, r.text
    q = await _latest(client, record_id, mgr)
    assert (q["stage"], q["headline"]) == ("reopened", "A place has opened at Goti Adarian: 0 of 2 going")
    assert q["going"] == 0 and q["may_withdraw"] is True and q["confirmed_short"] is False
    _nothing_of_who(q)

    # A fire temple with no panthaky in the app: all set reads the names and no panthaky.
    only = await agyari(db, "Mobeds Only Agyari (test)", None)
    await member(db, only, ONLY, name="Er. Only One")
    await db.commit()
    rid2, record2, _ = await _send(client, db, only.id, mgr, mobeds_wanted=1)
    assert (await _latest(client, record2, mgr))["headline"] == "Waiting at Mobeds Only Agyari (test)"
    await _yes(client, rid2, ONLY)
    q = await _latest(client, record2, mgr)
    assert q["headline"] == "All set at Mobeds Only Agyari (test): Er. Only One is going"
    assert q["going_names"] == ["Er. Only One"] and q["panthakys"] == []
    assert ONLY not in json.dumps(q) and ONLY[3:] not in json.dumps(q)


async def test_declined_nobody_withdrawn_and_accepted_the_old_way(client, db, seeded, pushes):
    aid = seeded["agyary_id"]
    rid, record_id, mgr = await _send(client, db, aid)
    r = await client.post(f"{REQUESTS}/{rid}/decline", json={"reason": "No mobed is free that day"},
                          headers=await _as(client, PANTHAKY))
    assert r.status_code == 200, r.text
    rec = await _record(client, record_id, mgr)
    q = rec["requests"][0]
    assert (q["stage"], q["headline"]) == ("declined", "Declined by Goti Adarian: No mobed is free that day")
    assert q["may_withdraw"] is False and rec["may_send"] is True
    _nothing_of_who(q)

    # At a fire temple with no panthaky, everyone asked said no.
    only = await agyari(db, "Mobeds Only Agyari (test)", None)
    await member(db, only, ONLY, name="Er. Only One")
    await db.commit()
    rid2, _, _ = await _send(client, db, only.id, mgr)
    await _yes(client, rid2, ONLY, answer="no")
    assert (await _request(db, rid2)).status == "declined"
    record2 = (await _request(db, rid2)).funeral_record_id
    q = await _latest(client, record2, mgr)
    assert (q["stage"], q["headline"]) == ("nobody", "Nobody at Mobeds Only Agyari (test) can take it")
    assert (await _record(client, record2, mgr))["may_send"] is True

    # Withdrawn.
    rid3, record3, _ = await _send(client, db, aid, mgr)
    assert (await client.post(f"/api/mobed/manager/requests/{rid3}/withdraw", headers=mgr)).status_code == 200
    q = await _latest(client, record3, mgr)
    assert (q["stage"], q["headline"], q["may_withdraw"]) == ("withdrawn", "Withdrawn from Goti Adarian", False)

    # Accepted the old way (D8): reads as before, the number only with the accepter's tick.
    rid4, record4, _ = await _send(client, db, aid, mgr)
    r = await client.post(f"{REQUESTS}/{rid4}/accept", json={"share_contact": True},
                          headers=await _as(client, PANTHAKY))
    assert r.status_code == 200, r.text
    q = await _latest(client, record4, mgr)
    assert (q["stage"], q["headline"]) == ("accepted", f"Accepted by {HEAD} of Goti Adarian")
    assert q["accepted_by"] == HEAD and q["accepter_phone"] == PANTHAKY
    assert q["going"] is None and q["going_names"] == [] and q["panthakys"] == []
