"""Joining another agyari needs its panthaky's confirmation (DECISIONS D10, owner
22 Nov 2026, from the security pass).

Joining stays open (D1.4) and never grants anyone's behdins (D2). But a mobed
who joins a fire temple gets its prayer requests, is asked in its call-outs and
is on its Mobeds page as one of its mobeds only once confirmed: the admin's
approval of a new sign-up confirms the fire temple they signed up at; a later
join waits for its confirmed panthaky (with none in the app, the admin); the one
who adds a brand-new fire temple is confirmed for it; an admin is confirmed
wherever they are a member; memberships from before stay confirmed (the
migration, tests/test_migrations_run.py). Outbound HTTP is mocked; nothing is
sent.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select, update

from agyary.core import config
from agyary.models import (
    Agyary,
    AgyaryUser,
    Customer,
    FuneralRecord,
    FuneralRequest,
    FuneralRequestBook,
    FuneralRequestRecipient,
    User,
)
from agyary.services import funeral_whatsapp as fw
from agyary.services import panthaky, prayer_callout, standbys
from tests.conftest import sign_in
from tests.funeral_helpers import agyari, auth, form, manager, member
from tests.test_prayer_callout import (
    ADMIN,
    LISTED,
    LIVE,
    MOBED,
    PANTHAKY,
    RECORDS,
    SECOND,
    Meta,
    _answers,
    _as,
    _list,
    _send,
    _signed_tap,
)
from tests.test_standbys import _all_set, _reasks

LATE, NEW, OTHER = "+919822200401", "+919822200402", "+919822200403"
REQUESTS = "/api/mobed/requests"
LATE_NAME = "Er. Late Joiner"


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


@pytest.fixture
def admin_phone(monkeypatch):
    monkeypatch.setenv("ADMIN_PHONES", ADMIN)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def _membership(db, user_id: int, agyary_id: int) -> AgyaryUser:
    return (await db.execute(select(AgyaryUser).where(
        AgyaryUser.user_id == user_id, AgyaryUser.agyary_id == agyary_id
    ).execution_options(populate_existing=True))).scalar_one()


async def _user(db, phone) -> User:
    return (await db.execute(select(User).where(User.phone == phone))).scalar_one()


async def _join(client, aid, headers, role="mobed"):
    r = await client.post(f"/api/mobed/agyaries/{aid}/join", json={"claimed_role": role}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _approve(client, admin, user_id) -> None:
    r = await client.post(f"/api/mobed/admin/mobeds/{user_id}/access", json={"access": "on"}, headers=admin)
    assert r.status_code == 200, r.text


async def _later_join(client, db, aid, *, phone=LATE, name=LATE_NAME) -> tuple[dict, int, int]:
    """A real later join: they sign up and wait, choose a fire temple of their own
    (Elsewhere), the admin approves them, and then they join ``aid`` from Settings.
    Returns (their headers, their id, Elsewhere's id)."""
    body = await sign_in(client, phone, name, approve=False)
    headers = auth(body)
    elsewhere = await agyari(db, "Elsewhere Agyari (test)", None)
    await db.commit()
    await _join(client, elsewhere.id, headers)
    await _approve(client, await _as(client, ADMIN), body["user"]["id"])
    await _join(client, aid, headers)
    return headers, body["user"]["id"], elsewhere.id


# --- Who is confirmed -------------------------------------------------------------------

async def test_the_admins_approval_confirms_the_fire_temples_signed_up_at(client, db, seeded, admin_phone):
    aid = seeded["agyary_id"]
    body = await sign_in(client, NEW, "Er. New Mobed", approve=False)
    uid = body["user"]["id"]
    other = await agyari(db, "Second Choice Agyari (test)", None)
    await db.commit()
    await _join(client, aid, auth(body))
    await _join(client, other.id, auth(body))
    for at in (aid, other.id):
        assert (await _membership(db, uid, at)).requests_confirmed_at is None
    s = config.get_settings()
    assert not await panthaky.is_request_member(db, s, aid, uid)

    admin = await _as(client, ADMIN)
    await _approve(client, admin, uid)
    admin_id = (await _user(db, ADMIN)).id
    for at in (aid, other.id):
        m = await _membership(db, uid, at)
        assert m.requests_confirmed_at is not None and m.requests_confirmed_by_user_id == admin_id
        assert m.requests_off_at is None
        assert await panthaky.is_request_member(db, s, at, uid)
    # The fire temple with no panthaky now reaches them; the seeded one still goes to its panthaky.
    assert [u.id for u in await panthaky.request_recipients(db, s, other.id)] == [uid]

    # Turned off and on again later is not an approval: nothing more is confirmed.
    third = await agyari(db, "Third Agyari (test)", None)
    await db.commit()
    await _join(client, third.id, auth(body))
    for access in ("off", "on"):
        r = await client.post(f"/api/mobed/admin/mobeds/{uid}/access", json={"access": access}, headers=admin)
        assert r.status_code == 200, r.text
    assert (await _membership(db, uid, third.id)).requests_confirmed_at is None


async def test_a_later_join_is_not_confirmed_and_joining_still_grants_no_behdins(client, db, seeded, admin_phone):
    aid = seeded["agyary_id"]
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins", json={"name": "Kias's Behdin", "phone": "+919822200499"},
                          headers=await _as(client, MOBED))
    assert r.status_code == 200, r.text
    headers, uid, elsewhere = await _later_join(client, db, aid)
    s = config.get_settings()
    assert (await _membership(db, uid, elsewhere)).requests_confirmed_at is not None
    late = await _membership(db, uid, aid)
    assert late.is_active and late.role == "mobed" and late.requests_confirmed_at is None
    assert panthaky.request_state(s, late, await _user(db, LATE)) == panthaky.REQUESTS_WAITING
    assert not await panthaky.is_request_member(db, s, aid, uid)

    # Joining works as before (D1.4): the fire temple is theirs in Settings, their own book is theirs.
    me = (await client.get("/api/mobed/auth/me", headers=headers)).json()
    assert [a["id"] for a in me["agyaries"]] == [elsewhere, aid]
    # ...and grants nobody's behdins (D2).
    listed = (await client.get(f"/api/mobed/agyaries/{aid}/behdins", headers=headers)).json()
    assert "Kias's Behdin" not in json.dumps(listed)


async def test_the_one_who_adds_a_fire_temple_is_confirmed_for_it(client, db, seeded):
    body = await sign_in(client, NEW, "Er. Founder")
    r = await client.post("/api/mobed/agyaries", json={"name": "Brand New Agiary", "city": "Pune"},
                          headers=auth(body))
    assert r.status_code == 200, r.text
    aid, uid = r.json()["agyary"]["id"], body["user"]["id"]
    m = await _membership(db, uid, aid)
    assert m.requests_confirmed_at is not None and m.requests_confirmed_by_user_id == uid
    assert [u.id for u in await panthaky.request_recipients(db, config.get_settings(), aid)] == [uid]


async def test_an_admin_is_confirmed_wherever_they_are_a_member(client, db, seeded, admin_phone):
    other = await agyari(db, "Admin's Second Agyari (test)", None)
    await db.commit()
    admin = await _as(client, ADMIN)
    await _join(client, other.id, admin)
    uid = (await _user(db, ADMIN)).id
    assert (await _membership(db, uid, other.id)).requests_confirmed_at is None
    s = config.get_settings()
    assert await panthaky.is_request_member(db, s, other.id, uid)
    assert (await panthaky.reach_of(db, s, [other.id]))[other.id] == panthaky.REACH_MOBEDS


async def test_the_owners_confirmation_as_panthaky_confirms_them_for_requests(client, db, seeded, admin_phone):
    aid = seeded["agyary_id"]
    headers, uid, _ = await _later_join(client, db, aid)
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == uid, AgyaryUser.agyary_id == aid)
                     .values(claimed_role="panthaky", claimed_at=datetime.now(timezone.utc)))
    await db.commit()
    r = await client.post(f"/api/mobed/admin/mobeds/{uid}/panthaky", json={"agyary_id": aid, "decision": "confirm"},
                          headers=await _as(client, ADMIN))
    assert r.status_code == 200, r.text
    m = await _membership(db, uid, aid)
    assert m.role == "panthaky" and m.requests_confirmed_at is not None
    # Made a mobed again, they stay one of its mobeds for requests.
    r = await client.post(f"/api/mobed/admin/mobeds/{uid}/panthaky", json={"agyary_id": aid, "decision": "remove"},
                          headers=await _as(client, ADMIN))
    assert r.status_code == 200, r.text
    assert await panthaky.is_request_member(db, config.get_settings(), aid, uid)


# --- What not confirmed means --------------------------------------------------------------

async def test_a_later_join_gets_no_request_no_call_out_and_is_not_on_the_board_or_the_list(
    client, db, seeded, meta, pushes, live,
):
    aid = seeded["agyary_id"]
    late, uid, _ = await _later_join(client, db, aid)
    rid, res, _ = await _send(client, db, aid, mobeds_wanted=2)
    # Asked at Send (Everyone at once): the app mobed confirmed from before, never the late joiner.
    assert res["callout"]["asked_in_app"] == 1
    assert LATE not in await _answers(db) and MOBED in await _answers(db)
    reached = set((await db.execute(select(FuneralRequestRecipient.user_id).where(
        FuneralRequestRecipient.funeral_request_id == rid))).scalars())
    assert uid not in reached
    assert not [m for m in meta.sent if m.get("to", "").lstrip("+") == LATE.lstrip("+")]

    # Not in their Requests tab: no count, no card, no answer.
    assert (await client.get(f"{REQUESTS}/count", headers=late)).json() == {"waiting": 0}
    assert (await client.get(REQUESTS, headers=late)).json()["waiting"] == []
    assert (await client.get(f"{REQUESTS}/{rid}", headers=late)).status_code == 404
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=late)
    assert r.status_code == 404

    # Not on the board, not on the Mobeds list, and a call cannot give them a place.
    panthaky_h = await _as(client, PANTHAKY)
    board = (await client.get(f"{REQUESTS}/{rid}/board", headers=panthaky_h)).json()
    assert LATE_NAME not in [m["name"] for m in board["mobeds"]] and LATE not in json.dumps(board)
    page = (await client.get(_list(aid), headers=panthaky_h)).json()
    assert LATE_NAME not in [m["name"] for m in page["mobeds"]]
    r = await client.post(f"{REQUESTS}/{rid}/call-result", json={"key": f"u{uid}", "result": "going"},
                          headers=panthaky_h)
    assert r.status_code == 400 and "not on Goti Adarian's list" in r.json()["detail"]
    # Ask everyone does not reach them either.
    await client.post(f"{REQUESTS}/{rid}/ask-everyone", headers=panthaky_h)
    assert LATE not in await _answers(db)
    assert uid not in set((await db.execute(select(FuneralRequestRecipient.user_id).where(
        FuneralRequestRecipient.funeral_request_id == rid))).scalars())


async def test_with_nobody_confirmed_a_fire_temple_has_nobody_for_requests(client, db, seeded, pushes):
    lonely = await agyari(db, "Lonely Agyari (test)", (18.96, 72.81))
    await member(db, lonely, OTHER, name="Er. Not Confirmed", confirmed=False)
    await db.commit()
    s = config.get_settings()
    assert (await panthaky.reach_of(db, s, [lonely.id]))[lonely.id] == panthaky.REACH_NOBODY
    assert await panthaky.request_recipients(db, s, lonely.id) == []
    mgr, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(), headers=mgr)).json()["record"]
    r = await client.post(f"{RECORDS}/{rec['id']}/requests", headers=mgr,
                          json={"agyary_id": lonely.id, "family_agreed": True})
    assert r.status_code == 409 and "Nobody at Lonely Agyari (test) uses Mobed Diary yet" in r.json()["detail"]


async def test_one_taken_off_since_cannot_answer_and_gets_no_book_or_name_at_all_set(client, db, seeded, pushes):
    aid = seeded["agyary_id"]
    kias = await _user(db, MOBED)
    mobed = await _as(client, MOBED)
    rid, _, mgr = await _send(client, db, aid, mobeds_wanted=2)
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=mobed)
    assert r.status_code == 200, r.text
    # Taken off the list (straight in the database here: the routes free their place, which
    # tests further down prove); they still hold the place on this request.
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == kias.id)
                     .values(requests_off_at=datetime.now(timezone.utc)))
    await db.commit()
    r = await client.post(f"{REQUESTS}/{rid}/self", headers=await _as(client, PANTHAKY))
    assert r.status_code == 200, r.text
    board = r.json()
    assert board["status"] == "all_set"
    assert [g["name"] for g in board["all_set"]["going"]] == ["Er. Hormuz Dadachanji"]
    books = (await db.execute(select(FuneralRequestBook.user_id).where(
        FuneralRequestBook.funeral_request_id == rid))).scalars().all()
    assert kias.id not in books
    card = (await client.get(f"{REQUESTS}/{rid}", headers=mobed)).json()["request"]
    assert card["all_set"] is None

    # A second request reached them before they were taken off: no count, no answer.
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == kias.id).values(requests_off_at=None))
    await db.commit()
    rid2, _, _ = await _send(client, db, aid, mgr)
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == kias.id)
                     .values(requests_off_at=datetime.now(timezone.utc)))
    await db.commit()
    assert (await client.get(f"{REQUESTS}/count", headers=mobed)).json() == {"waiting": 0}
    card = (await client.get(f"{REQUESTS}/{rid2}", headers=mobed)).json()["request"]
    assert card["my_answer"]["may_answer"] is False
    r = await client.post(f"{REQUESTS}/{rid2}/answer", json={"answer": "yes"}, headers=mobed)
    assert r.status_code == 409
    assert r.json()["detail"] == prayer_callout.not_on_the_list_words(await db.get(Agyary, aid))
    assert r.json()["detail"] == "You are not on Goti Adarian's list for prayer requests, so you cannot answer for it."


# --- The panthaky confirms, on the Mobeds page ------------------------------------------

def _member_url(aid, uid, what) -> str:
    return f"/api/mobed/agyaries/{aid}/members/{uid}/{what}"


async def _notes(db, phone, kind) -> list:
    from agyary.models import AppNotification

    user = await _user(db, phone)
    return list((await db.execute(select(AppNotification).where(
        AppNotification.user_id == user.id, AppNotification.kind == kind).order_by(AppNotification.id))).scalars())


async def test_the_panthaky_is_told_of_a_later_join_and_confirms_them(client, db, seeded, admin_phone, pushes):
    aid = seeded["agyary_id"]
    late, uid, _ = await _later_join(client, db, aid)
    hormuz = await _user(db, PANTHAKY)
    (note,) = await _notes(db, PANTHAKY, "member_joined")
    assert (note.title, note.body, note.link) == (
        "Er. Late Joiner has joined Goti Adarian", "Confirm them on Mobeds to send them prayer requests.", "#/mobeds")
    (push,) = [p for p in pushes if p["tag"].startswith("member-joined")]
    assert push["to"] == [hormuz.id] and push["title"] == note.title and push["body"] == note.body
    assert LATE[3:] not in json.dumps(push)
    # Nobody else: not the mobed there, not the admin (who approved them already).
    assert await _notes(db, MOBED, "member_joined") == [] and await _notes(db, ADMIN, "member_joined") == []

    panthaky_h = await _as(client, PANTHAKY)
    page = (await client.get(_list(aid), headers=panthaky_h)).json()
    assert [(w["id"], w["name"]) for w in page["joined"]["waiting"]] == [(uid, LATE_NAME)]
    assert page["joined"]["off"] == []
    # Their number is nowhere on the page until they are confirmed.
    assert LATE[3:] not in json.dumps(page)

    # Only that fire temple's confirmed panthaky (or the admin): to anyone else it does not exist.
    other = await agyari(db, "Other Agyari (test)", None)
    await member(db, other, OTHER, "panthaky", name="Er. Other Panthaky")
    await db.commit()
    for phone in (MOBED, OTHER):
        for what in ("confirm", "off", "on"):
            r = await client.post(_member_url(aid, uid, what), headers=await _as(client, phone))
            assert r.status_code == 404 and r.json()["detail"] == "That list could not be found.", (phone, what)
    for what in ("confirm", "off", "on"):
        assert (await client.post(_member_url(aid, uid, what), headers=late)).status_code == 404
    # Someone who is not an app mobed there is not found either.
    r = await client.post(_member_url(aid, (await _user(db, OTHER)).id, "confirm"), headers=panthaky_h)
    assert r.status_code == 404 and r.json()["detail"] == "That mobed could not be found at this fire temple."
    assert (await _membership(db, uid, aid)).requests_confirmed_at is None

    r = await client.post(_member_url(aid, uid, "confirm"), headers=panthaky_h)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["done"]["message"] == "Er. Late Joiner is confirmed: they will now get prayer requests."
    assert got["joined"] == {"waiting": [], "off": []}
    (row,) = [m for m in got["mobeds"] if m["kind"] == "app" and m["id"] == uid]
    assert row["phone"] == LATE and row["may_take_off"] is True
    m = await _membership(db, uid, aid)
    assert m.requests_confirmed_at is not None and m.requests_confirmed_by_user_id == hormuz.id
    (told,) = await _notes(db, LATE, "requests_confirmed")
    assert (told.title, told.body) == (
        "Confirmed for prayer requests", "Goti Adarian has confirmed you: you will now get its prayer requests.")
    r = await client.post(_member_url(aid, uid, "confirm"), headers=panthaky_h)
    assert r.status_code == 409 and r.json()["detail"] == "Er. Late Joiner is on the list already."

    # And now a request reaches them.
    rid, res, _ = await _send(client, db, aid)
    assert res["callout"]["asked_in_app"] == 2
    assert (await client.get(f"{REQUESTS}/{rid}", headers=late)).status_code == 200


async def test_not_one_of_ours_take_off_the_list_and_put_back(client, db, seeded, admin_phone, pushes):
    aid = seeded["agyary_id"]
    panthaky_h = await _as(client, PANTHAKY)
    late, uid, _ = await _later_join(client, db, aid)
    r = await client.post(_member_url(aid, uid, "off"), headers=panthaky_h)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["done"]["message"] == "Er. Late Joiner is off the list."
    assert got["joined"]["waiting"] == [] and [o["name"] for o in got["joined"]["off"]] == [LATE_NAME]
    assert LATE[3:] not in json.dumps(got)
    m = await _membership(db, uid, aid)
    assert m.is_active and m.requests_off_at is not None and m.requests_off_by_user_id == (await _user(db, PANTHAKY)).id
    # Still a member, as before: only prayer requests are not theirs. They are told, in plain words.
    me = (await client.get("/api/mobed/auth/me", headers=late)).json()
    assert aid in [a["id"] for a in me["agyaries"]]
    assert await _notes(db, LATE, "requests_confirmed") == []
    (told,) = await _notes(db, LATE, "requests_taken_off")
    assert told.body == ("The panthaky of Goti Adarian has not added you to its list for prayer requests. "
                         "You remain at Goti Adarian in Mobed Diary.")
    (push,) = [p for p in pushes if p["tag"].startswith("requests-taken-off")]
    assert push["to"] == [uid] and push["body"] == told.body and push["title"] == told.title
    assert PANTHAKY[3:] not in json.dumps(push) and LATE[3:] not in told.body
    for what, words in (("off", "Er. Late Joiner is off the list already."),
                        ("confirm", "Er. Late Joiner is off the list. Tap Put back to send them prayer requests.")):
        r = await client.post(_member_url(aid, uid, what), headers=panthaky_h)
        assert r.status_code == 409 and r.json()["detail"] == words
    assert len(await _notes(db, LATE, "requests_taken_off")) == 1   # already off: nothing more is said
    # Joining again changes nothing, and tells nobody again.
    await _join(client, aid, late)
    assert (await _membership(db, uid, aid)).requests_off_at is not None
    assert len(await _notes(db, PANTHAKY, "member_joined")) == 1

    r = await client.post(_member_url(aid, uid, "on"), headers=panthaky_h)
    assert r.status_code == 200, r.text
    assert r.json()["done"]["message"] == "Er. Late Joiner is back on the list: they will get prayer requests."
    assert r.json()["joined"] == {"waiting": [], "off": []}
    assert await panthaky.is_request_member(db, config.get_settings(), aid, uid)
    assert len(await _notes(db, LATE, "requests_confirmed")) == 1
    r = await client.post(_member_url(aid, uid, "on"), headers=panthaky_h)
    assert r.status_code == 409 and r.json()["detail"] == "Er. Late Joiner is not off the list."

    # One of its mobeds from before can be taken off the list too; a panthaky cannot be.
    kias = await _user(db, MOBED)
    page = (await client.get(_list(aid), headers=panthaky_h)).json()
    rows = {m["name"]: m for m in page["mobeds"] if m["kind"] == "app"}
    assert rows["Er. Pervez Kias"]["may_take_off"] is True and rows["Er. Hormuz Dadachanji"]["may_take_off"] is False
    r = await client.post(_member_url(aid, kias.id, "off"), headers=panthaky_h)
    assert r.status_code == 200, r.text
    assert "Er. Pervez Kias" not in [m["name"] for m in r.json()["mobeds"]]
    (kias_told,) = await _notes(db, MOBED, "requests_taken_off")
    assert kias_told.body == ("The panthaky of Goti Adarian has taken you off its list for prayer requests. "
                              "You remain at Goti Adarian in Mobed Diary.")
    assert len([p for p in pushes if p["tag"].startswith("requests-taken-off")]) == 2
    r = await client.post(_member_url(aid, (await _user(db, PANTHAKY)).id, "off"), headers=await _as(client, ADMIN))
    assert r.status_code == 409 and r.json()["detail"] == (
        "Er. Hormuz Dadachanji is a panthaky of Goti Adarian, so they stay on the list.")
    rid, res, _ = await _send(client, db, aid)
    assert res["callout"]["asked_in_app"] == 1      # the late joiner, put back; not Kias
    assert MOBED not in await _answers(db)


async def test_a_number_added_by_hand_goes_off_the_list_with_them(client, db, seeded, admin_phone, pushes):
    aid = seeded["agyary_id"]
    panthaky_h = await _as(client, PANTHAKY)
    r = await client.post(_list(aid), json={"name": "Er. Listed First", "phone": LATE, "agreed": True},
                          headers=panthaky_h)
    assert r.status_code == 200, r.text
    _, uid, _ = await _later_join(client, db, aid)
    page = (await client.get(_list(aid), headers=panthaky_h)).json()
    # Until confirmed they are on the list as the panthaky added them, and waiting apart.
    assert [m["name"] for m in page["mobeds"] if m["kind"] == "contact"] == ["Er. Listed First"]
    assert [w["id"] for w in page["joined"]["waiting"]] == [uid]
    r = await client.post(_list(aid), json={"name": "Er. Again", "phone": LATE, "agreed": True}, headers=panthaky_h)
    assert r.status_code == 409 and r.json()["detail"] == (
        "Er. Late Joiner has joined Goti Adarian in Mobed Diary. Tap Confirm to send them prayer requests.")
    r = await client.post(_member_url(aid, uid, "off"), headers=panthaky_h)
    assert r.status_code == 200, r.text
    assert [m for m in r.json()["mobeds"] if m["kind"] == "contact"] == []
    r = await client.post(_list(aid), json={"name": "Er. Again", "phone": LATE, "agreed": True}, headers=panthaky_h)
    assert r.status_code == 409 and r.json()["detail"] == (
        "Er. Late Joiner is off the list. Tap Put back to send them prayer requests.")


async def test_with_no_panthaky_the_admin_is_told_and_confirms_on_admin_mobeds(client, db, seeded, admin_phone, pushes):
    lonely = await agyari(db, "Lonely Agyari (test)", None)
    await member(db, lonely, OTHER, name="Er. Already There")
    await db.commit()
    late, uid, _ = await _later_join(client, db, lonely.id)
    admin = await _as(client, ADMIN)
    admin_id = (await _user(db, ADMIN)).id
    (note,) = await _notes(db, ADMIN, "member_joined")
    assert note.title == "Er. Late Joiner has joined Lonely Agyari (test)" and note.link == "#/admin/mobeds"
    assert note.body == ("Lonely Agyari (test) has no panthaky in the app. "
                         "Confirm them on the Mobeds page to send them prayer requests.")
    (push,) = [p for p in pushes if p["tag"].startswith("member-joined")]
    assert push["to"] == [admin_id] and push["body"] == "Confirm them on the Mobeds page to send them prayer requests."
    assert await _notes(db, OTHER, "member_joined") == []

    listed = (await client.get("/api/mobed/admin/mobeds", headers=admin)).json()["mobeds"]
    (row,) = [m for m in listed if m["id"] == uid]
    there = {t["name"]: t for t in row["memberships"]}
    assert there["Lonely Agyari (test)"]["requests"] == "waiting"
    assert there["Lonely Agyari (test)"]["has_panthaky"] is False
    assert there["Elsewhere Agyari (test)"]["requests"] == "confirmed"
    goti = [t for m in listed for t in m["memberships"] if t["name"] == "Goti Adarian"]
    assert goti and all(t["has_panthaky"] for t in goti)

    url = f"/api/mobed/admin/mobeds/{uid}/requests"
    # Only the admin.
    r = await client.post(url, json={"agyary_id": lonely.id, "action": "confirm"}, headers=await _as(client, OTHER))
    assert r.status_code == 404
    for action, state, words in (
            ("off", "off", "Er. Late Joiner is off the list."),
            ("on", "confirmed", "Er. Late Joiner is back on the list: they will get prayer requests.")):
        r = await client.post(url, json={"agyary_id": lonely.id, "action": action}, headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["requests"] == state and r.json()["done"]["message"] == words
    r = await client.post(url, json={"agyary_id": lonely.id, "action": "confirm"}, headers=admin)
    assert r.status_code == 409
    r = await client.post(url, json={"agyary_id": 999999, "action": "confirm"}, headers=admin)
    assert r.status_code == 404
    assert [u.id for u in await panthaky.request_recipients(db, config.get_settings(), lonely.id)] == [
        (await _user(db, OTHER)).id, uid]
    m = await _membership(db, uid, lonely.id)
    assert m.requests_confirmed_by_user_id == admin_id


async def test_a_sign_up_still_waiting_tells_no_panthaky_and_is_confirmed_by_the_approval(
    client, db, seeded, admin_phone, pushes,
):
    aid = seeded["agyary_id"]
    body = await sign_in(client, NEW, "Er. New Mobed", approve=False)
    await _join(client, aid, auth(body))
    assert await _notes(db, PANTHAKY, "member_joined") == []
    page = (await client.get(_list(aid), headers=await _as(client, PANTHAKY))).json()
    assert [w["name"] for w in page["joined"]["waiting"]] == ["Er. New Mobed"]
    await _approve(client, await _as(client, ADMIN), body["user"]["id"])
    page = (await client.get(_list(aid), headers=await _as(client, PANTHAKY))).json()
    assert page["joined"]["waiting"] == [] and "Er. New Mobed" in [m["name"] for m in page["mobeds"]]


# --- A place held is freed as Can't go frees it (lead's decision, 22 Nov 2026) ----------

async def _departed(db, rid) -> str:
    request = await db.get(FuneralRequest, rid, populate_existing=True)
    return fw.departed(await db.get(FuneralRecord, request.funeral_record_id))


def _sent_to(meta, phone) -> list[dict]:
    return [m for m in meta.sent if m.get("to", "").lstrip("+") == phone.lstrip("+")]


async def test_taking_off_someone_going_frees_their_place_and_the_standby_is_asked(
    client, db, seeded, meta, pushes, live,
):
    aid = seeded["agyary_id"]
    rid, _ = await _all_set(client, db, aid)      # Er. Listed and Kias going, Er. Second on standby
    kias, hormuz = await _user(db, MOBED), await _user(db, PANTHAKY)
    (book,) = (await db.execute(select(FuneralRequestBook).where(
        FuneralRequestBook.funeral_request_id == rid, FuneralRequestBook.user_id == kias.id))).scalars()
    asked, to_kias = len(_reasks(meta, SECOND)), len(_sent_to(meta, MOBED))

    r = await client.post(_member_url(aid, kias.id, "off"), headers=await _as(client, PANTHAKY))
    assert r.status_code == 200, r.text
    departed = await _departed(db, rid)
    assert r.json()["done"]["message"] == (
        f"Er. Pervez Kias is off the list. Their place for {departed} is open again. We have asked Er. Second.")
    request = await db.get(FuneralRequest, rid, populate_existing=True)
    assert request.status == "waiting" and request.all_set_at is not None
    row = (await _answers(db))[MOBED]
    assert row.backed_out_at is not None and row.backed_out_by_user_id == hormuz.id
    assert len(_reasks(meta, SECOND)) == asked + 1
    # Their own book keeps the family (D8), and nothing more goes to them.
    assert (await db.get(Customer, book.customer_id)).is_active is True
    assert len(_sent_to(meta, MOBED)) == to_kias
    # The panthaky saw it on screen, so is not told again.
    assert await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED) == []

    # The standby says yes: all set again, without them.
    await _signed_tap(client, SECOND, f"pca:{(await _answers(db))[SECOND].reask_token}:y")
    assert (await db.get(FuneralRequest, rid, populate_existing=True)).status == "all_set"
    board = (await client.get(f"{REQUESTS}/{rid}/board", headers=await _as(client, PANTHAKY))).json()
    assert [g["name"] for g in board["all_set"]["going"]] == ["Er. Listed", "Er. Second"]


async def test_removing_a_mobed_added_by_hand_frees_their_place(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    rid, _ = await _all_set(client, db, aid, standby=False)
    listed = (await _answers(db))[LISTED]
    r = await client.delete(f"{_list(aid)}/{listed.contact_id}", headers=await _as(client, PANTHAKY))
    assert r.status_code == 200, r.text
    departed = await _departed(db, rid)
    assert r.json()["done"]["message"] == (
        f"Er. Listed is off the list. Their place for {departed} is open again. "
        "Nobody is on the waiting list: please find someone.")
    assert (await _answers(db))[LISTED].backed_out_at is not None
    assert (await db.get(FuneralRequest, rid, populate_existing=True)).status == "waiting"
    # Removing one who holds no place says only that.
    r = await client.post(_list(aid), json={"name": "Er. Third", "phone": OTHER, "agreed": True},
                          headers=await _as(client, PANTHAKY))
    added = r.json()["added"]
    r = await client.delete(f"{_list(aid)}/{added}", headers=await _as(client, PANTHAKY))
    assert r.json()["done"] == {"message": "Er. Third is off the list.", "places_freed": 0}


async def test_switching_off_someone_going_frees_their_place_and_the_panthaky_is_told(
    client, db, seeded, meta, pushes, live,
):
    aid = seeded["agyary_id"]
    rid, _ = await _all_set(client, db, aid)
    kias = await _user(db, MOBED)
    admin = await _as(client, ADMIN)
    admin_id = (await _user(db, ADMIN)).id
    r = await client.post(f"/api/mobed/admin/mobeds/{kias.id}/access", json={"access": "off"}, headers=admin)
    assert r.status_code == 200, r.text
    departed = await _departed(db, rid)
    assert r.json()["access"] == "off"
    assert r.json()["freed"] == f"Their place for {departed} is open again. We have asked Er. Second."
    row = (await _answers(db))[MOBED]
    assert row.backed_out_at is not None and row.backed_out_by_user_id == admin_id
    (note,) = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert note.title == "Er. Pervez Kias can't go; we have asked Er. Second"
    # Turned on again, nothing more is freed or said.
    r = await client.post(f"/api/mobed/admin/mobeds/{kias.id}/access", json={"access": "on"}, headers=admin)
    assert r.status_code == 200 and r.json()["freed"] is None
    r = await client.post(f"/api/mobed/admin/mobeds/{kias.id}/access", json={"access": "off"}, headers=admin)
    assert r.json()["freed"] is None


# --- Erasing a number, or deleting an account, reopens the place held (owner, 24 Nov 2026) ---

async def test_erasing_a_going_mobeds_number_reopens_their_place_without_naming_them(
    client, db, seeded, meta, pushes, live,
):
    from agyary.services import erasure

    aid = seeded["agyary_id"]
    rid, _ = await _all_set(client, db, aid)      # Er. Listed and Kias going, Er. Second on standby
    asked = len(_reasks(meta, SECOND))
    await erasure.erase_number(db, MOBED)
    await db.commit()
    request = await db.get(FuneralRequest, rid, populate_existing=True)
    assert request.status == "waiting"
    answers = await _answers(db)
    assert answers[MOBED].backed_out_at is not None and answers[MOBED].backed_out_by_user_id is None
    assert answers[LISTED].backed_out_at is None            # a mobed not going is unaffected
    assert len(_reasks(meta, SECOND)) == asked + 1
    (note,) = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert note.title == "A mobed can't go; we have asked Er. Second"
    opened = [p for p in pushes if "place" in p["tag"] and p["title"].startswith("A mobed can't go")]
    assert opened and "Kias" not in json.dumps([note.title, note.body, opened])
    # Again: nothing more is asked or said.
    await erasure.erase_number(db, MOBED)
    await db.commit()
    assert len(_reasks(meta, SECOND)) == asked + 1
    assert len(await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)) == 1


async def test_deleting_an_account_reopens_the_place_held_and_a_failure_does_not_stop_it(
    client, db, seeded, meta, pushes, live, monkeypatch,
):
    from agyary.services import account

    aid = seeded["agyary_id"]
    rid, _ = await _all_set(client, db, aid)
    kias = await _user(db, MOBED)
    await account.delete_account(db, kias)
    await db.commit()
    assert (await db.get(FuneralRequest, rid, populate_existing=True)).status == "waiting"
    (note,) = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert note.title == "A mobed can't go; we have asked Er. Second" and "Kias" not in note.body
    assert await db.scalar(select(User).where(User.phone == MOBED)) is None


async def test_a_failure_in_reopening_does_not_stop_the_erasing(client, db, seeded, meta, pushes, live, monkeypatch):
    from agyary.services import account

    await _all_set(client, db, seeded["agyary_id"])

    async def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(standbys, "ask_standbys", boom)
    await account.delete_account(db, await _user(db, MOBED))     # does not raise
    await db.commit()
    assert await db.scalar(select(User).where(User.phone == MOBED)) is None
