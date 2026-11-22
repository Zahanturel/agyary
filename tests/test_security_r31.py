"""The security pass of Phase 2 and R3.1 (22 Nov 2026): what each fix makes
true, one section per fix. Outbound HTTP is mocked throughout; nothing is sent.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select, update

from agyary.core import config
from agyary.models import Agyary, AppNotification, FuneralRecord, FuneralRequest, ReminderOptOut, User
from agyary.services import funeral_whatsapp as fw
from agyary.services import funeral_records, prayer_callout, standbys
from tests.funeral_helpers import FAMILY, agyari, form, member
from tests.test_prayer_callout import LISTED, LIVE, RECORDS, MOBED, PANTHAKY, SECOND, Meta, _answers, _as, _list, _send, _signed_tap
from tests.test_standbys import OTHER_MOBED, REQUESTS, THIRD, _all_set, _b, _reasks, _to, _tomorrow


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


KIAS = "Er. Pervez Kias"


async def _request(db, rid) -> FuneralRequest:
    return await db.get(FuneralRequest, rid, populate_existing=True)


async def _user(db, phone) -> User:
    return (await db.execute(select(User).where(User.phone == phone))).scalar_one()


async def _notes(db, phone, kind=None) -> list[AppNotification]:
    user = await _user(db, phone)
    where = [AppNotification.user_id == user.id] + ([AppNotification.kind == kind] if kind else [])
    return list((await db.execute(select(AppNotification).where(*where).order_by(AppNotification.id))).scalars())


async def _add(client, aid, headers, name, phone) -> int:
    r = await client.post(_list(aid), json={"name": name, "phone": phone, "agreed": True}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["added"]


async def _remove(client, aid, headers, contact_id) -> None:
    r = await client.delete(f"{_list(aid)}/{contact_id}", headers=headers)
    assert r.status_code == 200, r.text


def _templates(meta, phone, name) -> list[dict]:
    return [m for m in _to(meta, phone) if m.get("type") == "template" and m["template"]["name"] == name]


# --- 1. A mobed taken off the list keeps nothing of what they were sent ---------------

async def test_a_removed_mobeds_old_yes_changes_nothing_and_gets_no_reply(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    contact = await _add(client, aid, panthaky, "Er. Listed", LISTED)
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=1)
    token = (await _answers(db))[LISTED].token
    assert _templates(meta, LISTED, "prayer_request_mobeds_v2")
    await _remove(client, aid, panthaky, contact)
    rows = list((await _answers(db)).values())
    assert await prayer_callout.left_out(db, config.get_settings(), aid, rows) == {
        (await _answers(db))[LISTED].id: prayer_callout.LEFT_THE_LIST}
    sent = len(meta.sent)

    for choice in ("y", "n", "x"):
        await _signed_tap(client, LISTED, f"pca:{token}:{choice}")
    row = (await _answers(db))[LISTED]
    assert row.answer is None and row.picked_at is None and row.backed_out_at is None
    assert len(meta.sent) == sent                # nothing back to them, nothing to anyone
    request = await _request(db, rid)
    assert request.status == "waiting" and request.taken_at is None
    assert await _notes(db, PANTHAKY, "prayer_callout_going") == []
    board = (await client.get(_b(rid), headers=panthaky)).json()
    assert board["places"] == [] and board["standbys"] == []

    # Added again, they are on the list again and their button counts.
    await _add(client, aid, panthaky, "Er. Listed", LISTED)
    await _signed_tap(client, LISTED, f"pca:{token}:y")
    assert (await _answers(db))[LISTED].picked_at is not None


async def test_a_removed_standby_is_never_asked_again(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    rid, _ = await _all_set(client, db, aid)          # Er. Listed and Kias going, Er. Second on standby
    panthaky = await _as(client, PANTHAKY)
    second = (await _answers(db))[SECOND]
    await _remove(client, aid, panthaky, second.contact_id)
    board = (await client.get(_b(rid), headers=panthaky)).json()
    assert board["standbys"] == []
    asked = len(_reasks(meta, SECOND))      # the call-out at Send

    r = await client.post(f"{REQUESTS}/{rid}/back-out", headers=await _as(client, MOBED))
    assert r.status_code == 200, r.text
    assert len(_reasks(meta, SECOND)) == asked
    row = (await _answers(db))[SECOND]
    assert row.reasked_at is None and row.reask_token is None
    # The panthaky is told nobody is on standby, so they find someone.
    (note,) = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert "nobody is on standby" in note.title


async def test_a_removed_mobed_holding_a_place_is_not_named_or_sent_the_details(client, db, seeded, meta, pushes,
                                                                                live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    contact = await _add(client, aid, panthaky, "Er. Listed", LISTED)
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2)
    answers = await _answers(db)
    await _signed_tap(client, LISTED, f"pca:{answers[LISTED].token}:y")
    assert (await _answers(db))[LISTED].picked_at is not None
    await _remove(client, aid, panthaky, contact)
    meta.sent.clear()
    await _signed_tap(client, MOBED, f"pca:{answers[MOBED].token}:y")
    assert (await _request(db, rid)).status == "all_set"

    # The details only to the one going who is still on the list; nothing at all to them.
    assert _to(meta, LISTED) == []
    assert len(_templates(meta, MOBED, "prayer_details_mobed_v3")) == 1
    # Not named to the family, the panthaky or the place.
    (family,) = _templates(meta, FAMILY, "prayers_all_set_family")
    words = " ".join(p["text"] for p in family["template"]["components"][0]["parameters"])
    assert KIAS in words and "Er. Listed" not in words and LISTED[3:] not in words
    for m in meta.sent:
        assert "Er. Listed" not in str(m) and LISTED[3:] not in str(m)
    for phone in (PANTHAKY, MOBED):
        for note in await _notes(db, phone, "funeral_request_all_set"):
            assert "Er. Listed" not in note.title + note.body
    board = (await client.get(_b(rid), headers=panthaky)).json()
    assert [g["name"] for g in board["all_set"]["going"]] == [KIAS]


# --- 5. A mobed added by hand is matched to an account by their number when asked ------

async def test_a_number_that_signs_up_after_being_added_is_not_asked_while_waiting(client, db, seeded, meta, pushes,
                                                                                    live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    await _add(client, aid, panthaky, "Er. Listed", LISTED)
    # The number signs up afterwards, at another fire temple, and waits for the admin.
    elsewhere = await agyari(db, "Elsewhere Agyari (test)", None)
    await member(db, elsewhere, LISTED, access="pending", name="Er. Listed Himself")
    await db.commit()

    rid, res, mgr = await _send(client, db, aid)
    assert _to(meta, LISTED) == []
    (listed,) = [m for m in (await client.get(_list(aid), headers=panthaky)).json()["mobeds"] if m["kind"] == "contact"]
    assert listed["can_message"] is False
    board = (await client.get(_b(rid), headers=panthaky)).json()
    (row,) = [m for m in board["mobeds"] if m["kind"] == "contact"]
    assert row["can_ask"] is False and row["state"] == "not_asked"

    # Approved, they are asked like anyone; switched off again, not on the next request.
    await db.execute(update(User).where(User.phone == LISTED).values(access="on"))
    await db.commit()
    r = await client.post(_b(rid, "ask-everyone"), headers=panthaky)
    assert r.status_code == 200, r.text
    assert len(_templates(meta, LISTED, "prayer_request_mobeds_v2")) == 1
    await db.execute(update(User).where(User.phone == LISTED).values(access="off"))
    await db.commit()
    assert (await client.post(f"/api/mobed/manager/requests/{rid}/withdraw", headers=mgr)).status_code == 200
    await _send(client, db, aid, mgr)
    assert len(_templates(meta, LISTED, "prayer_request_mobeds_v2")) == 1


async def test_a_standby_whose_number_has_an_account_waiting_is_not_asked_again(client, db, seeded, meta, pushes,
                                                                                 live):
    aid = seeded["agyary_id"]
    rid, _ = await _all_set(client, db, aid)          # Er. Second on standby
    elsewhere = await agyari(db, "Elsewhere Agyari (test)", None)
    await member(db, elsewhere, SECOND, access="pending", name="Er. Second Himself")
    await db.commit()
    asked = len(_reasks(meta, SECOND))
    r = await client.post(f"{REQUESTS}/{rid}/back-out", headers=await _as(client, MOBED))
    assert r.status_code == 200, r.text
    assert len(_reasks(meta, SECOND)) == asked
    # Not asked again at all (D9: nothing to an account that is not on), so nobody is on standby.
    assert (await _answers(db))[SECOND].reasked_at is None
    (note,) = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert "nobody is on standby" in note.title


# --- 6. Adding a mobed by hand never tells the panthaky about an account -----------------

async def test_adding_a_number_says_a_stop_but_never_what_account_it_has(client, db, seeded):
    aid = seeded["agyary_id"]
    elsewhere = await agyari(db, "Elsewhere Agyari (test)", None)
    await member(db, elsewhere, LISTED, access="off", name="Er. Off Elsewhere")
    await member(db, elsewhere, SECOND, access="pending", name="Er. Waiting Elsewhere")
    db.add(ReminderOptOut(phone=THIRD, stopped_at=datetime.now(timezone.utc)))
    await db.commit()
    panthaky = await _as(client, PANTHAKY)
    for name, phone in (("Er. One", LISTED), ("Er. Two", SECOND), ("Er. Three", THIRD)):
        r = await client.post(_list(aid), json={"name": name, "phone": phone, "agreed": True}, headers=panthaky)
        assert r.status_code == 200, r.text
        words = json.dumps(r.json())
        for leak in ("switched off", "waiting for", "approval", "access", "Elsewhere"):
            assert leak not in words, (phone, leak)
    got = {m["phone"]: m for m in r.json()["mobeds"] if m["kind"] == "contact"}
    for phone in (LISTED, SECOND):
        assert got[phone]["can_message"] is False and got[phone]["stopped"] is False
        assert got[phone]["why_not"] == prayer_callout.CANNOT_ASK_NOW == "cannot be asked on WhatsApp now"
    # A STOP is said: the panthaky needs to know the number cannot be asked.
    assert got[THIRD]["stopped"] is True and "STOP" in got[THIRD]["why_not"]


# --- 3. Someone whose access is waiting or off cannot take a place -----------------------

async def test_a_mobed_waiting_for_approval_cannot_be_marked_going(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    waiting = await member(db, goti, THIRD, access="pending", name="Er. Waiting")
    off = await member(db, goti, OTHER_MOBED, access="off", name="Er. Switched Off")
    await db.commit()
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2)
    panthaky = await _as(client, PANTHAKY)
    board = (await client.get(_b(rid), headers=panthaky)).json()
    by_key = {m["key"]: m for m in board["mobeds"]}
    assert by_key[f"u{waiting.id}"]["may_place"] is False
    assert by_key[f"u{waiting.id}"]["no_place"] == "cannot be marked Going until the admin approves them"
    assert by_key[f"u{off.id}"]["may_place"] is False
    assert by_key[f"u{off.id}"]["no_place"] == "cannot be marked Going while their Mobed Diary access is switched off"
    kias = await _user(db, MOBED)
    assert by_key[f"u{kias.id}"]["may_place"] is True and by_key[f"u{kias.id}"]["no_place"] is None

    for who, words in ((waiting, "Er. Waiting cannot be marked Going until the admin approves them."),
                       (off, "Er. Switched Off cannot be marked Going while their Mobed Diary access is switched off.")):
        r = await client.post(_b(rid, "call-result"), json={"key": f"u{who.id}", "result": "going"}, headers=panthaky)
        assert r.status_code == 409 and r.json()["detail"] == words
    assert board["places"] == [] and (await client.get(_b(rid), headers=panthaky)).json()["places"] == []
    # What a call says otherwise is still noted.
    r = await client.post(_b(rid, "call-result"), json={"key": f"u{off.id}", "result": "not_going"}, headers=panthaky)
    assert r.status_code == 200, r.text


async def test_a_yes_on_whatsapp_from_an_account_switched_off_fills_no_place(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=1)
    token = (await _answers(db))[MOBED].token
    await db.execute(update(User).where(User.phone == MOBED).values(access="off"))
    await db.commit()
    sent = len(meta.sent)
    await _signed_tap(client, MOBED, f"pca:{token}:y")
    row = (await _answers(db))[MOBED]
    assert row.answer is None and row.picked_at is None
    assert len(meta.sent) == sent and (await _request(db, rid)).status == "waiting"


async def test_someone_going_whose_access_goes_off_is_not_named_and_their_number_goes_nowhere(client, db, seeded, meta,
                                                                                            pushes, live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    await _add(client, aid, panthaky, "Er. Listed", LISTED)
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2)
    answers = await _answers(db)
    await _signed_tap(client, MOBED, f"pca:{answers[MOBED].token}:y")
    await db.execute(update(User).where(User.phone == MOBED).values(access="off"))
    await db.commit()
    meta.sent.clear()
    await _signed_tap(client, LISTED, f"pca:{answers[LISTED].token}:y")
    assert (await _request(db, rid)).status == "all_set"
    assert _to(meta, MOBED) == []
    for m in meta.sent:
        assert MOBED[3:] not in json.dumps(m) and KIAS not in json.dumps(m)
    (family,) = _templates(meta, FAMILY, "prayers_all_set_family")
    assert "Er. Listed" in json.dumps(family)


# --- 8. The family's number stays the one their agreement was for, while a request waits --

async def test_a_waiting_requests_family_number_cannot_be_changed(client, db, seeded, meta, pushes):
    aid = seeded["agyary_id"]
    rid, res, mgr = await _send(client, db, aid)
    record_id = res["record"]["id"]
    r = await client.put(f"{RECORDS}/{record_id}", json=form(family_contact_phone="+919822200044"), headers=mgr)
    assert r.status_code == 409 and r.headers.get("x-field") == "family_contact_phone"
    assert r.json()["detail"] == funeral_records.NUMBER_LOCKED == (
        "The family agreed to share the number this request was sent with. "
        "Withdraw the request first, then change the number.")
    record = await db.get(FuneralRecord, record_id, populate_existing=True)
    assert record.family_contact_phone == FAMILY
    # Anything else can still be changed while it waits.
    r = await client.put(f"{RECORDS}/{record_id}", json=form(mobeds_wanted=3), headers=mgr)
    assert r.status_code == 200, r.text
    # Withdrawn, the number can be changed, and a new Send asks for the tick again.
    assert (await client.post(f"/api/mobed/manager/requests/{rid}/withdraw", headers=mgr)).status_code == 200
    r = await client.put(f"{RECORDS}/{record_id}", json=form(family_contact_phone="+919822200044"), headers=mgr)
    assert r.status_code == 200, r.text
    r = await client.post(f"{RECORDS}/{record_id}/requests", headers=mgr, json={"agyary_id": aid})
    assert r.status_code == 400 and r.headers.get("x-field") == "family_agreed"


# --- 4. The funeral place learns no mobed's name before All set --------------------------

async def test_the_place_is_told_counts_not_names_before_all_set(client, db, seeded, meta, pushes):
    from tests.funeral_helpers import MANAGER

    only = await agyari(db, "Mobeds Only Agyari (test)", None)
    await member(db, only, "+919822200111", name="Er. Only One")
    await member(db, only, "+919822200112", name="Er. Only Two")
    await db.commit()
    rid, _, mgr = await _send(client, db, only.id, mobeds_wanted=2, geh_saarnu_date=_tomorrow())
    one = await _as(client, "+919822200111")
    assert (await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=one)).status_code == 200
    pushes.clear()
    assert (await client.post(f"{REQUESTS}/{rid}/back-out", headers=one)).status_code == 200
    (note,) = await _notes(db, MANAGER, standbys.KIND_PLACE_OPENED)
    assert note.title == "A mobed can't go at Mobeds Only Agyari (test); 0 of 2 going"
    assert "Er. Only" not in note.title + note.body and "0 of 2 going" in note.body
    manager = await _user(db, MANAGER)
    (push,) = [p for p in pushes if p["to"] == [manager.id]]
    assert "Er. Only" not in push["title"] + push["body"] and push["title"] == "A mobed can't go"

    # All set, the place has learned who is going: someone going who backs out is named.
    two = await _as(client, "+919822200112")
    assert (await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=two)).status_code == 200
    rid2, _, _ = await _send(client, db, only.id, mgr, mobeds_wanted=1, geh_saarnu_date=_tomorrow())
    assert (await client.post(f"{REQUESTS}/{rid2}/answer", json={"answer": "yes"}, headers=two)).status_code == 200
    assert (await _request(db, rid2)).status == "all_set"
    assert (await client.post(f"{REQUESTS}/{rid2}/back-out", headers=two)).status_code == 200
    notes = await _notes(db, MANAGER, standbys.KIND_PLACE_OPENED)
    assert notes[-1].title == "Er. Only Two can't go: nobody is on standby at Mobeds Only Agyari (test)"


# --- 2. "This prayer request was withdrawn" goes only to a yes that came on WhatsApp -----

async def test_withdrawn_text_only_to_whatsapp_yeses_others_are_told_in_the_app(client, db, seeded, meta, pushes,
                                                                                live):
    from tests.test_prayer_callout import _way

    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    await _add(client, aid, panthaky, "Er. Listed", LISTED)
    await _add(client, aid, panthaky, "Er. Second", SECOND)
    await _way(db, aid, "panthaky_first")
    rid, _, mgr = await _send(client, db, aid, mobeds_wanted=5)
    kias = await _user(db, MOBED)
    # Kias marked Going after a call; the panthaky prays; Er. Second said yes on the phone.
    for key in (f"u{kias.id}", None):
        if key:
            r = await client.post(_b(rid, "call-result"), json={"key": key, "result": "going"}, headers=panthaky)
        else:
            r = await client.post(_b(rid, "self"), json={}, headers=panthaky)
        assert r.status_code == 200, r.text
    board = (await client.get(_b(rid), headers=panthaky)).json()
    second = next(m for m in board["mobeds"] if m["name"] == "Er. Second")
    r = await client.post(_b(rid, "call-result"), json={"key": second["key"], "result": "going"}, headers=panthaky)
    assert r.status_code == 200, r.text
    # Er. Listed is asked on WhatsApp and says yes there.
    assert (await client.post(_b(rid, "ask-everyone"), headers=panthaky)).status_code == 200
    await _signed_tap(client, LISTED, f"pca:{(await _answers(db))[LISTED].token}:y")
    meta.sent.clear()

    r = await client.post(f"/api/mobed/manager/requests/{rid}/withdraw", headers=mgr)
    assert r.status_code == 200, r.text
    # Only the WhatsApp yes, inside the 24 hours they opened.
    assert [(m["to"], m["text"]["body"]) for m in meta.texts()] == [(LISTED, fw.WITHDRAWN_TEXT)]
    # Kias (a yes by phone) is told in the app, once.
    notes = await _notes(db, MOBED, "funeral_request_withdrawn")
    assert len(notes) == 1 and notes[0].title == "A request for prayers was withdrawn"


async def test_withdrawn_text_never_to_an_account_switched_off(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    rid, _, mgr = await _send(client, db, aid, mobeds_wanted=3)
    await _signed_tap(client, MOBED, f"pca:{(await _answers(db))[MOBED].token}:y")
    await db.execute(update(User).where(User.phone == MOBED).values(access="off"))
    await db.commit()
    meta.sent.clear()
    assert (await client.post(f"/api/mobed/manager/requests/{rid}/withdraw", headers=mgr)).status_code == 200
    assert meta.texts() == []
