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
from agyary.models import Agyary, AgyaryUser, FuneralRequestBook, FuneralRequestRecipient, User
from agyary.services import funeral_whatsapp as fw
from agyary.services import panthaky, prayer_callout
from tests.conftest import sign_in
from tests.funeral_helpers import agyari, auth, form, manager, member
from tests.test_prayer_callout import ADMIN, LIVE, MOBED, PANTHAKY, RECORDS, Meta, _answers, _as, _list, _send

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
