"""Standbys and backing out (DECISIONS D10, changed 21 Nov 2026, second round;
docs/phase2-requests-redesign.md, "Standbys and backing out"; R3.1 step 5b).

Someone going can say they can no longer go - "I can't go any more" in the
app, the same button on their WhatsApp details (only from the number it was
sent to, once), or the panthaky marking it on the board - and then no longer
counts as going anywhere; their own book keeps the family (D8) and nothing more
is sent to them. The place reopens at once: an all-set request is waiting
again, and the panthaky is told. Refused in plain words for someone not going,
a closed request, and once the prayers have begun. Outbound HTTP is mocked
throughout.
"""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from agyary.core import config
from agyary.models import (
    Agyary,
    AppNotification,
    Booking,
    Customer,
    FuneralRecord,
    FuneralRequest,
    FuneralRequestBook,
    PrayerCalloutAnswer,
    User,
)
from agyary.services import all_set, funeral_answers, funeral_records, prayer_callout, prayer_timers, standbys
from agyary.services import funeral_whatsapp as fw
from tests.funeral_helpers import FAMILY, member
from tests.test_prayer_callout import (
    ADMIN,
    LISTED,
    LIVE,
    MOBED,
    PANTHAKY,
    SECOND,
    Meta,
    _answers,
    _as,
    _list,
    _send,
    _signed_tap,
)

REQUESTS = "/api/mobed/requests"
OTHER_MOBED, THIRD = "+919822200114", "+919822200099"
PANTHAKY_NAME, MOBED_NAME = "Er. Hormuz Dadachanji", "Er. Pervez Kias"


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


def _tomorrow() -> str:
    return (funeral_records.today_ist() + timedelta(days=1)).isoformat()


async def _listed(client, aid, panthaky, *people) -> None:
    for name, phone in people:
        r = await client.post(_list(aid), json={"name": name, "phone": phone, "agreed": True}, headers=panthaky)
        assert r.status_code == 200, r.text


async def _request(db, rid) -> FuneralRequest:
    return await db.get(FuneralRequest, rid, populate_existing=True)


async def _user(db, phone) -> User:
    return (await db.execute(select(User).where(User.phone == phone))).scalar_one()


async def _count(db, model, *where) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


async def _notes(db, phone, kind) -> list[AppNotification]:
    user = await _user(db, phone)
    return list((await db.execute(select(AppNotification).where(
        AppNotification.user_id == user.id, AppNotification.kind == kind).order_by(AppNotification.id))).scalars())


def _b(rid, what=""):
    return f"{REQUESTS}/{rid}/board" if not what else f"{REQUESTS}/{rid}/{what}"


def _no_family(text: str) -> None:
    assert FAMILY not in text and FAMILY[3:] not in text and "Test Family" not in text, text


def _to(meta, phone) -> list[dict]:
    return [m for m in meta.sent if "+" + m["to"].lstrip("+") == phone]


async def _all_set(client, db, aid, *, standby=True, third=False, **changes) -> tuple[int, dict]:
    """Everyone at once, two wanted, the prayers tomorrow: the one added by hand and the app
    mobed say yes on WhatsApp (all set), then a second added by hand (a standby), and with
    ``third`` a third after them (the next standby)."""
    panthaky = await _as(client, PANTHAKY)
    await _listed(client, aid, panthaky, ("Er. Listed", LISTED), ("Er. Second", SECOND),
                  *((("Er. Third", THIRD),) if third else ()))
    rid, _, mgr = await _send(client, db, aid, mobeds_wanted=2, geh_saarnu_date=_tomorrow(), **changes)
    answers = await _answers(db)
    await _signed_tap(client, LISTED, f"pca:{answers[LISTED].token}:y")
    await _signed_tap(client, MOBED, f"pca:{answers[MOBED].token}:y")
    assert (await _request(db, rid)).status == "all_set"
    if standby:
        await _signed_tap(client, SECOND, f"pca:{answers[SECOND].token}:y")
    if third:
        await _signed_tap(client, THIRD, f"pca:{answers[THIRD].token}:y")
    return rid, mgr


def _reasks(meta, phone) -> list[dict]:
    """The call-outs that went to ``phone`` asking again (their buttons carry the re-ask's token)."""
    name = config.get_settings().whatsapp_prayer_request_template
    return [m for m in _to(meta, phone) if m.get("type") == "template" and m["template"]["name"] == name]


def _payloads(m) -> list[str]:
    return [c["parameters"][0]["payload"] for c in m["template"]["components"] if c.get("sub_type") == "quick_reply"]


# --- Backing out, three ways ------------------------------------------------------------

async def test_an_app_mobed_going_backs_out_and_the_place_reopens(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    rid, mgr = await _all_set(client, db, aid, standby=False)
    before = await _request(db, rid)
    all_set_at, taken_at = before.all_set_at, before.taken_at
    books = {b.user_id: b for b in (await db.execute(select(FuneralRequestBook))).scalars()}
    kias = await _user(db, MOBED)
    own = await db.get(Customer, books[kias.id].customer_id)
    bookings = await _count(db, Booking, Booking.customer_id == own.id)
    sent_before = len(meta.sent)
    mobed = await _as(client, MOBED)

    # Their card offers it, naming who will be told.
    card = (await client.get(f"{REQUESTS}/{rid}", headers=mobed)).json()["request"]
    assert card["my_answer"]["may_back_out"] is True and card["my_answer"]["tell"] == PANTHAKY_NAME

    r = await client.post(f"{REQUESTS}/{rid}/back-out", headers=mobed)
    assert r.status_code == 200, r.text
    assert r.json()["done"]["message"] == f"Noted: you can't go. {PANTHAKY_NAME} has been told."
    got = r.json()["request"]
    assert got["status"] == "waiting" and got["reopened"] is True
    assert got["my_answer"]["state"] == "backed_out" and got["my_answer"]["may_back_out"] is False
    assert got["places"] == {"going": 1, "wanted": 2}
    # Nothing more for them: not the family's contact any more, though it stays in their book (D8).
    assert got["all_set"] is None

    request = await _request(db, rid)
    assert request.status == "waiting" and request.decided_at is None
    assert request.all_set_at == all_set_at and request.taken_at == taken_at
    row = (await _answers(db))[MOBED]
    assert row.backed_out_at is not None and row.backed_out_by_user_id == kias.id and row.picked_at is not None
    assert (await db.get(Customer, own.id)).is_active is True
    assert await _count(db, Booking, Booking.customer_id == own.id) == bookings
    assert await _count(db, FuneralRequestBook, FuneralRequestBook.user_id == kias.id) == 1
    # Nothing on WhatsApp to them, nor to anyone.
    assert len(meta.sent) == sent_before

    # The panthaky is told in the app and on their phone; the lock screen names only the mobed.
    (note,) = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert note.link == f"#/requests/{rid}" and MOBED_NAME in note.title
    _no_family(note.title + note.body)
    hormuz = await _user(db, PANTHAKY)
    (push,) = [p for p in pushes if p["to"] == [hormuz.id] and "can't go" in p["title"]]
    assert push["title"] == f"{MOBED_NAME} can't go" and push["url"] == f"/mobed#/requests/{rid}"
    assert "Rustom" not in push["body"] + push["title"]
    _no_family(push["body"])
    assert not await _notes(db, MOBED, standbys.KIND_PLACE_OPENED)

    # The board reads it: one going, the one who can't go, the actions back.
    board = (await client.get(_b(rid), headers=await _as(client, PANTHAKY))).json()
    assert board["status"] == "waiting" and board["reopened"] is True and board["going"] == 1
    assert [p["name"] for p in board["places"]] == ["Er. Listed"]
    assert [p["key"] for p in board["backed_out"]] == [f"u{kias.id}"]
    assert {m["key"]: m["state"] for m in board["mobeds"]}[f"u{kias.id}"] == "backed_out"
    assert board["may_confirm_short"] is True and board["ask_everyone"] is not None
    # The record stays taken for good on the manager's side.
    rec = (await funeral_records.serialize(db, [await db.get(FuneralRecord, request.funeral_record_id)]))[0]
    assert rec["may_edit"] is False and rec["may_send"] is False

    # Asked again, it is refused in plain words, and nothing changes.
    r = await client.post(f"{REQUESTS}/{rid}/back-out", headers=mobed)
    assert r.status_code == 409 and r.json()["detail"] == "You have already said you can't go."
    assert len(await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)) == 1


async def test_on_whatsapp_only_from_the_number_it_went_to_and_only_once(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    rid, mgr = await _all_set(client, db, aid, standby=False)
    listed = (await _answers(db))[LISTED]
    token = listed.token   # the app's rollbacks below forget the shared session's objects
    # The details went with the button carrying their token.
    (details,) = [m for m in _to(meta, LISTED) if m.get("type") == "template"
                  and m["template"]["name"] == config.get_settings().whatsapp_all_set_details_template]
    payload = f"pca:{token}:x"
    assert [c["parameters"][0]["payload"] for c in details["template"]["components"]
            if c.get("sub_type") == "quick_reply"] == [payload]

    # From another number: nothing.
    await _signed_tap(client, SECOND, payload)
    assert (await _answers(db))[LISTED].backed_out_at is None
    assert (await _request(db, rid)).status == "all_set"

    sent = len(meta.sent)
    await _signed_tap(client, LISTED, payload)
    row = (await _answers(db))[LISTED]
    assert row.backed_out_at is not None and row.backed_out_by_user_id is None
    assert (await _request(db, rid)).status == "waiting"
    # Thanked in a short text, inside the 24 hours the tap opened.
    (reply,) = meta.sent[sent:]
    assert reply["type"] == "text" and "+" + reply["to"].lstrip("+") == LISTED
    assert reply["text"]["body"] == fw.BACKED_OUT_TEXT
    assert len(await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)) == 1

    # A second tap changes and sends nothing.
    await _signed_tap(client, LISTED, payload)
    assert len(meta.sent) == sent + 1
    assert len(await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)) == 1
    # A made-up or a call-out button with an x changes nothing either.
    settings = config.get_settings()
    assert await prayer_callout.record_answer(db, settings, "pca:" + "z" * 24 + ":x", LISTED) == "unknown token"
    assert await prayer_callout.record_answer(db, settings, f"pca:{token}:q", LISTED) == "malformed"


async def test_the_panthaky_or_the_admin_marks_cant_go_on_the_board(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    await member(db, goti, ADMIN, name="Er. Admin Mobed")
    await db.commit()
    rid, mgr = await _all_set(client, db, aid, standby=False)
    panthaky, admin, mobed = await _as(client, PANTHAKY), await _as(client, ADMIN), await _as(client, MOBED)
    listed = (await _answers(db))[LISTED]
    key = f"c{listed.contact_id}"
    board = (await client.get(_b(rid), headers=panthaky)).json()
    assert board["may_back_out"] is True and key in [p["key"] for p in board["places"]]

    # Not a mobed, whom the board does not exist for.
    assert (await client.post(_b(rid, "cant-go"), json={"key": key}, headers=mobed)).status_code == 404
    # A wrong key is said in plain words, naming the field.
    r = await client.post(_b(rid, "cant-go"), json={"key": "x1"}, headers=panthaky)
    assert r.status_code == 400 and r.headers.get("x-field") == "key"

    sent = len(meta.sent)
    r = await client.post(_b(rid, "cant-go"), json={"key": key}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert r.json()["done"]["message"].startswith("Noted: Er. Listed can't go.")
    assert r.json()["status"] == "waiting" and [p["key"] for p in r.json()["backed_out"]] == [key]
    hormuz = await _user(db, PANTHAKY)
    row = (await _answers(db))[LISTED]
    assert row.backed_out_by_user_id == hormuz.id
    # Nothing is sent to the one who can't go; the panthaky who marked it sees it on screen.
    assert len(meta.sent) == sent
    assert not await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)

    # Twice: refused in plain words.
    r = await client.post(_b(rid, "cant-go"), json={"key": key}, headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == "Er. Listed has already said they can't go."
    # The admin can mark the other one; the panthaky is then told.
    kias = await _user(db, MOBED)
    r = await client.post(_b(rid, "cant-go"), json={"key": f"u{kias.id}"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["going"] == 0
    assert len(await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)) == 1


# --- Refused --------------------------------------------------------------------------

async def test_refused_for_someone_not_going_and_for_a_closed_request(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    await member(db, goti, OTHER_MOBED, name="Er. Late Mobed")
    await db.commit()
    rid, mgr = await _all_set(client, db, aid)
    late = await _as(client, OTHER_MOBED)
    # A late yes in the app is a standby: not going, so nothing to change.
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=late)
    assert r.status_code == 200 and r.json()["request"]["my_answer"]["state"] == "standby"
    assert r.json()["request"]["my_answer"]["may_back_out"] is False
    r = await client.post(f"{REQUESTS}/{rid}/back-out", headers=late)
    assert r.status_code == 409 and r.json()["detail"] == "You are not going for this request, so there is nothing to change."
    # Nor a standby on the board.
    second = (await _answers(db))[SECOND]
    r = await client.post(_b(rid, "cant-go"), json={"key": f"c{second.contact_id}"}, headers=await _as(client, PANTHAKY))
    assert r.status_code == 409 and r.json()["detail"] == "Er. Second is not going for this request."

    # Withdrawn: one going at a fire temple whose request is still waiting.
    panthaky = await _as(client, PANTHAKY)
    rid2, _, _ = await _send(client, db, aid, mgr, mobeds_wanted=2, geh_saarnu_date=_tomorrow())
    assert (await client.post(_b(rid2, "self"), json={}, headers=panthaky)).status_code == 200
    r = await client.post(f"/api/mobed/manager/requests/{rid2}/withdraw", headers=mgr)
    assert r.status_code == 200, r.text
    hormuz = await _user(db, PANTHAKY)
    r = await client.post(_b(rid2, "cant-go"), json={"key": f"u{hormuz.id}"}, headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == (
        "Doongerwadi (test) withdrew this request, so nothing more is needed for it.")
    assert (await _answers(db))[PANTHAKY].backed_out_at is None


async def test_refused_once_the_prayers_have_begun_and_never_for_time_without_days(client, db, seeded, meta, pushes,
                                                                                  live):
    aid = seeded["agyary_id"]
    rid, mgr = await _all_set(client, db, aid, standby=False)
    settings = config.get_settings()
    request = await _request(db, rid)
    record = await db.get(funeral_records.FuneralRecord, request.funeral_record_id)
    begins = prayer_timers.record_begins(record)
    assert begins is not None
    kias = await _user(db, MOBED)

    # A minute before: still possible (seen on the card); from the start of the geh: refused.
    assert prayer_callout.may_back_out(request, record, begins - timedelta(minutes=1)) is True
    with pytest.raises(prayer_callout.CalloutError) as refused:
        await standbys.back_out_in_app(db, settings, kias, request, now=begins)
    assert str(refused.value) == standbys.begun_words(PANTHAKY_NAME)
    await db.rollback()
    assert (await _answers(db))[MOBED].backed_out_at is None

    # On WhatsApp, told why in a short text, and nothing changes.
    listed = (await _answers(db))[LISTED]
    sent = len(meta.sent)
    outcome = await prayer_callout.record_answer(db, settings, f"pca:{listed.token}:x", LISTED,
                                                 now=begins + timedelta(hours=1))
    assert outcome.endswith("refused")
    (reply,) = meta.sent[sent:]
    assert reply["text"]["body"] == standbys.begun_words(PANTHAKY_NAME)
    assert (await _answers(db))[LISTED].backed_out_at is None
    assert (await _request(db, rid)).status == "all_set"

    # With no days given, never refused for time.
    rid2, _, _ = await _send(client, db, aid, mgr, mobeds_wanted=1, geh_saarnu_date=None, geh_saarnu_geh=None,
                             uthamna_date=None, uthamna_time=None)
    panthaky = await _as(client, PANTHAKY)
    assert (await client.post(_b(rid2, "self"), json={}, headers=panthaky)).status_code == 200
    request2 = await _request(db, rid2)
    assert request2.status == "all_set"
    hormuz = await _user(db, PANTHAKY)
    done = await standbys.mark_cant_go(db, settings, hormuz, request2, f"u{hormuz.id}",
                                       now=begins + timedelta(days=60))
    assert done["outcome"] == "backed out"
    assert (await _request(db, rid2)).status == "waiting"


# --- Going, everywhere ------------------------------------------------------------------

async def test_someone_who_backed_out_counts_as_going_nowhere(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    rid, mgr = await _all_set(client, db, aid)
    mobed = await _as(client, MOBED)
    assert (await client.post(f"{REQUESTS}/{rid}/back-out", headers=mobed)).status_code == 200
    request = await _request(db, rid)
    kias = await _user(db, MOBED)

    assert await prayer_callout._going(db, rid) == 1
    assert (await prayer_callout.summary(db, request))["going"] == 1
    assert [g["name"] for g in await all_set.going_people(db, rid)] == ["Er. Listed"]
    _, going = await all_set.book_people(db, config.get_settings(), request)
    assert kias.id not in {u.id for u in going}
    # The panthaky's contacts, still theirs as the request's panthaky, name only those going.
    hormuz = await _user(db, PANTHAKY)
    contacts = await all_set.contacts_for(db, request, hormuz)
    assert [g["name"] for g in contacts["going"]] == ["Er. Listed"]
    assert await all_set.contacts_for(db, request, kias) is None
    # The standby stays a standby; the one who backed out is neither.
    board = (await client.get(_b(rid), headers=await _as(client, PANTHAKY))).json()
    assert [s["name"] for s in board["standbys"]] == ["Er. Second"]
    assert MOBED_NAME not in [p["name"] for p in board["places"] + board["standbys"]]
    # The call-out screen reads the same, and a call cannot mark them going again by mistake.
    view = await prayer_callout.view(db, config.get_settings(), hormuz, request)
    assert view["going"] == 1
    r = await client.post(_b(rid, "call-result"), json={"key": f"u{kias.id}", "result": "going"},
                          headers=await _as(client, PANTHAKY))
    assert r.status_code == 409 and r.json()["detail"] == f"{MOBED_NAME} has said they can't go."
    # Their own answer again in the app is refused in the same words.
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=mobed)
    assert r.status_code == 409 and r.json()["detail"] == "You have said you can't go any more."
    # Their red count holds nothing for it.
    assert await funeral_answers.waiting_count(db, kias.id) == 0
    # Withdrawn later: those who said yes are told; never the one who backed out.
    sent = len(meta.sent)
    assert await prayer_callout.after_closed(db, config.get_settings(), rid) == 2
    told = {"+" + m["to"].lstrip("+") for m in meta.sent[sent:]}
    assert told == {LISTED, SECOND}


async def test_backing_out_before_all_set_tells_the_panthaky_to_find_someone(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    await _listed(client, aid, panthaky, ("Er. Listed", LISTED))
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2, geh_saarnu_date=_tomorrow())
    answers = await _answers(db)
    await _signed_tap(client, MOBED, f"pca:{answers[MOBED].token}:y")
    assert (await _request(db, rid)).status == "waiting"
    r = await client.post(f"{REQUESTS}/{rid}/back-out", headers=await _as(client, MOBED))
    assert r.status_code == 200, r.text
    assert r.json()["request"]["status"] == "waiting" and r.json()["request"]["reopened"] is False
    (note,) = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert "nobody is on standby" in note.body and "please find someone" in note.body


async def test_with_no_panthaky_the_funeral_place_is_told(client, db, seeded, meta, pushes, live):
    from sqlalchemy import update

    from agyary.models import AgyaryUser
    from tests.funeral_helpers import MANAGER

    aid = seeded["agyary_id"]
    hormuz = await _user(db, PANTHAKY)
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == hormuz.id).values(role="mobed"))
    await db.commit()
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=1, geh_saarnu_date=_tomorrow())
    mobed = await _as(client, MOBED)
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=mobed)
    assert r.status_code == 200 and r.json()["request"]["status"] == "all_set"
    r = await client.post(f"{REQUESTS}/{rid}/back-out", headers=mobed)
    assert r.status_code == 200, r.text
    assert r.json()["done"]["message"] == "Noted: you can't go. Doongerwadi (test) has been told."
    (note,) = await _notes(db, MANAGER, standbys.KIND_PLACE_OPENED)
    assert "nobody at Goti Adarian is on standby" in note.body and note.link.startswith("#/manager/record/")
    _no_family(note.title + note.body)


def test_the_payload_reads_the_three_buttons():
    token = "a" * 24
    for choice in "ynx":
        assert prayer_callout._PAYLOAD.match(f"pca:{token}:{choice}")
    assert not prayer_callout._PAYLOAD.match(f"pca:{token}:z")
    assert json.dumps(prayer_callout.back_out_payload(PrayerCalloutAnswer(token=token))) == f'"pca:{token}:x"'


# --- Standbys asked again, by themselves --------------------------------------------------

async def test_the_first_standby_is_asked_again_with_a_fresh_token_and_the_panthaky_told(client, db, seeded, meta,
                                                                                        pushes, live):
    aid = seeded["agyary_id"]
    rid, _ = await _all_set(client, db, aid, third=True)
    second = (await _answers(db))[SECOND]
    first_token = second.token
    assert second.reasked_at is None and second.reask_token is None
    hormuz = await _user(db, PANTHAKY)
    pushes.clear()
    r = await client.post(f"{REQUESTS}/{rid}/back-out", headers=await _as(client, MOBED))
    assert r.status_code == 200, r.text

    # Only the first standby, in the order they said yes; the call-out template, its buttons on a token of
    # their own that is not the first one.
    rows = await _answers(db)
    second, third = rows[SECOND], rows[THIRD]
    assert second.reasked_at is not None and third.reasked_at is None
    assert second.reask_token and second.reask_token != first_token and len(second.reask_token) >= 20
    (asked,) = [m for m in _reasks(meta, SECOND) if second.reask_token in json.dumps(m)]
    assert _payloads(asked) == [f"pca:{second.reask_token}:y", f"pca:{second.reask_token}:n"]
    assert len(_reasks(meta, THIRD)) == 1      # only the call-out at Send
    _no_family(json.dumps(asked))

    # The panthaky: "<A> can't go; we have asked <B>", in the app and on their phone.
    (note,) = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert note.title == f"{MOBED_NAME} can't go; we have asked Er. Second" and note.link == f"#/requests/{rid}"
    (push,) = [p for p in pushes if p["to"] == [hormuz.id]]
    assert (push["title"], push["body"]) == (f"{MOBED_NAME} can't go", "We have asked Er. Second.")
    board = (await client.get(_b(rid), headers=await _as(client, PANTHAKY))).json()
    assert [(s["name"], s["reask"]) for s in board["standbys"]] == [("Er. Second", "asked_again"),
                                                                    ("Er. Third", "waiting")]

    # Their first buttons count no more; another number cannot use the new ones.
    settings = config.get_settings()
    assert (await prayer_callout.record_answer(db, settings, f"pca:{first_token}:y", SECOND)).endswith(
        "already answered")
    assert (await prayer_callout.record_answer(db, settings, f"pca:{second.reask_token}:y", THIRD)).endswith(
        "not from the number asked")
    # Their yes fills the place: all set again.
    await _signed_tap(client, SECOND, f"pca:{second.reask_token}:y")
    rows = await _answers(db)
    assert rows[SECOND].reask_answer == "yes" and prayer_callout.holds_place(rows[SECOND])
    assert (await _request(db, rid)).status == "all_set"
    assert rows[THIRD].reasked_at is None and prayer_callout.is_standby(rows[THIRD])
    # A second tap changes nothing.
    assert (await prayer_callout.record_answer(db, settings, f"pca:{rows[SECOND].reask_token}:n", SECOND)
            ).endswith("not asked again")


async def test_an_app_standby_is_asked_in_the_app_and_answers_on_their_card(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    await member(db, goti, OTHER_MOBED, name="Er. App Standby")
    await db.commit()
    rid, _ = await _all_set(client, db, aid, standby=False)
    other = await _as(client, OTHER_MOBED)
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=other)
    assert r.json()["request"]["my_answer"]["state"] == "standby"
    assert r.json()["request"]["my_answer"]["reask"] == "waiting"
    assert r.json()["request"]["my_answer"]["may_answer_again"] is False
    standby = await _user(db, OTHER_MOBED)
    assert await funeral_answers.waiting_count(db, standby.id) == 0
    pushes.clear()

    # The one added by hand can't go any more (on WhatsApp): the app standby is asked in the app.
    listed = (await _answers(db))[LISTED]
    await _signed_tap(client, LISTED, f"pca:{listed.token}:x")
    (note,) = await _notes(db, OTHER_MOBED, standbys.KIND_REASK)
    assert note.title == "A place has opened" and note.link == f"#/requests/{rid}"
    _no_family(note.title + note.body)
    (push,) = [p for p in pushes if p["to"] == [standby.id]]
    assert push["title"] == "A place has opened" and "Rustom" not in push["body"]
    card = (await client.get(f"{REQUESTS}/{rid}", headers=other)).json()["request"]
    assert card["status"] == "waiting" and card["reopened"] is True
    assert card["my_answer"]["reask"] == "asked_again" and card["my_answer"]["may_answer_again"] is True
    assert await funeral_answers.waiting_count(db, standby.id) == 1
    # The panthaky is told whom.
    (told,) = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert told.title == "Er. Listed can't go; we have asked Er. App Standby"

    # Their yes on the card fills the place: all set again, and they are told so.
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=other)
    assert r.status_code == 200, r.text
    assert r.json()["done"]["message"] == prayer_callout.ALL_SET_GOING_WORDS
    assert r.json()["request"]["status"] == "all_set"
    assert r.json()["request"]["my_answer"]["state"] == "going"
    assert await funeral_answers.waiting_count(db, standby.id) == 0
    # Asked once more, it is already answered.
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "no"}, headers=other)
    assert r.status_code == 409 and r.json()["detail"] == "You have already said yes: you are going."


async def test_a_no_or_thirty_minutes_asks_the_next_once_and_none_left_tells_the_panthaky(client, db, seeded, meta,
                                                                                         pushes, live):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    aid = seeded["agyary_id"]
    rid, _ = await _all_set(client, db, aid, third=True)
    assert (await client.post(f"{REQUESTS}/{rid}/back-out", headers=await _as(client, MOBED))).status_code == 200
    second = (await _answers(db))[SECOND]
    reask = second.reask_token

    # Er. Second says no: Er. Third is asked, and the panthaky told.
    await _signed_tap(client, SECOND, f"pca:{reask}:n")
    rows = await _answers(db)
    assert rows[SECOND].reask_answer == "no" and rows[SECOND].reask_passed_at is not None
    third = rows[THIRD]
    assert third.reasked_at is not None and third.reask_token
    assert [m for m in _reasks(meta, THIRD) if third.reask_token in json.dumps(m)]
    notes = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert [n.title for n in notes][-1] == "Er. Second said no; we have asked Er. Third"

    # Er. Third does not answer: nothing at 29 minutes; at 30, two loops at once move on once.
    settings = config.get_settings()
    asked_at = third.reasked_at
    assert await standbys.timed_out(db, asked_at + timedelta(minutes=29), settings, None) == 0
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    at = asked_at + standbys.REASK_WAIT
    async with factory() as one, factory() as two:
        import asyncio
        done = await asyncio.gather(standbys.timed_out(one, at, settings, None),
                                    standbys.timed_out(two, at, settings, None))
    assert sorted(done) == [0, 1]
    notes = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert len(notes) == 3
    assert notes[-1].title == "Er. Third did not answer and nobody else is on standby: please find someone"
    assert "Ask everyone, call a mobed, or pray yourself" in notes[-1].body and notes[-1].link == f"#/requests/{rid}"
    board = (await client.get(_b(rid), headers=await _as(client, PANTHAKY))).json()
    assert [(s["name"], s["reask"]) for s in board["standbys"]] == [("Er. Second", "said_no"),
                                                                    ("Er. Third", "no_answer")]
    # Once is all: the loop again finds nothing.
    assert await prayer_timers.run(db, at + timedelta(minutes=5), settings, None) == 0

    # Er. Third's late yes still counts while the place is open: all set again.
    await _signed_tap(client, THIRD, f"pca:{third.reask_token}:y")
    assert prayer_callout.holds_place((await _answers(db))[THIRD])
    assert (await _request(db, rid)).status == "all_set"


async def test_a_place_filled_meanwhile_stops_the_asking_and_a_late_yes_is_a_standby_again(client, db, seeded, meta,
                                                                                          pushes, live):
    aid = seeded["agyary_id"]
    rid, _ = await _all_set(client, db, aid, third=True)
    assert (await client.post(f"{REQUESTS}/{rid}/back-out", headers=await _as(client, MOBED))).status_code == 200
    second = (await _answers(db))[SECOND]
    reask, asked_at = second.reask_token, second.reasked_at
    # The panthaky fills it with I'll pray meanwhile: all set again.
    r = await client.post(_b(rid, "self"), json={}, headers=await _as(client, PANTHAKY))
    assert r.status_code == 200 and r.json()["status"] == "all_set", r.text
    notes = len(await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED))

    # The 30 minutes pass: nobody more is asked, nobody told.
    settings = config.get_settings()
    assert await standbys.timed_out(db, asked_at + standbys.REASK_WAIT, settings, None) == 1
    rows = await _answers(db)
    assert rows[THIRD].reasked_at is None
    assert len(await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)) == notes

    # Er. Second's late yes: a standby again, thanked with the Enough mobeds words, nothing filled.
    sent = len(meta.sent)
    await _signed_tap(client, SECOND, f"pca:{reask}:y")
    rows = await _answers(db)
    assert rows[SECOND].reask_answer == "yes" and prayer_callout.is_standby(rows[SECOND])
    assert standbys.reask_state(rows[SECOND]) == "waiting"
    (thanked,) = meta.sent[sent:]
    assert thanked["text"]["body"] == fw.ENOUGH_TEXT
    assert await prayer_callout._going(db, rid) == 2

    # When a place opens again, they are first again (they said yes before Er. Third), on a new token.
    listed = (await _answers(db))[LISTED]
    await _signed_tap(client, LISTED, f"pca:{listed.token}:x")
    rows = await _answers(db)
    assert rows[SECOND].reask_token != reask and standbys.reask_state(rows[SECOND]) == "asked_again"
    assert rows[THIRD].reasked_at is None


# --- Filled again: all set again ------------------------------------------------------------

def _templates(meta, name) -> list[dict]:
    return [m for m in meta.sent if m.get("type") == "template" and m["template"]["name"] == name]


def _body(m) -> list[str]:
    return [p["text"] for p in m["template"]["components"][0]["parameters"]]


async def test_all_set_again_tells_the_new_names_once_without_repeating_the_rest(client, db, seeded, meta, pushes,
                                                                                live):
    from tests.funeral_helpers import MANAGER

    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    await member(db, goti, OTHER_MOBED, name="Er. App Standby")
    await db.commit()
    rid, _ = await _all_set(client, db, aid, standby=False)
    other = await _as(client, OTHER_MOBED)
    assert (await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=other)).status_code == 200
    first_at = (await _request(db, rid)).all_set_at
    books_before = {b.user_id: (b.id, b.customer_id) for b in (await db.execute(select(FuneralRequestBook))).scalars()}
    kias, standby = await _user(db, MOBED), await _user(db, OTHER_MOBED)
    bookings = {uid: await _count(db, Booking, Booking.created_by_user_id == uid) for uid in books_before}
    rows = await _answers(db)
    # The details that went at the first All set are written down as gone.
    assert rows[LISTED].details_sent_at is not None and rows[MOBED].details_sent_at is not None
    sent = len(meta.sent)

    # The app mobed going can't go; the app standby is asked and says yes: all set again.
    assert (await client.post(f"{REQUESTS}/{rid}/back-out", headers=await _as(client, MOBED))).status_code == 200
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=other)
    assert r.status_code == 200 and r.json()["request"]["status"] == "all_set", r.text
    request = await _request(db, rid)
    assert request.all_set_at > first_at and request.confirmed_short is False
    new = meta.sent[sent:]

    # Template 6 only to the one now going; template 5 to the family again, with the new names;
    # 7 and 8 not again; nothing to the one who can't go.
    six = config.get_settings().whatsapp_all_set_details_template
    details = [m for m in new if m.get("type") == "template" and m["template"]["name"] == six]
    assert ["+" + m["to"].lstrip("+") for m in details] == [OTHER_MOBED]
    mobeds = "Er. Listed (+91 9822200055), Er. App Standby (+91 9822200114)"
    assert _body(details[0])[6] == mobeds
    family = [m for m in new if m.get("type") == "template" and m["template"]["name"] == "prayers_all_set_family"]
    assert len(family) == 1 and "+" + family[0]["to"].lstrip("+") == FAMILY and _body(family[0])[1] == mobeds
    assert MOBED_NAME not in json.dumps(family)
    for name in ("prayers_all_set_panthaky", "funeral_accepted_manager_v2"):
        assert len(_templates(meta, name)) == 1
    assert not [m for m in new if "+" + m["to"].lstrip("+") == MOBED]
    assert (await _answers(db))[OTHER_MOBED].details_sent_at is not None

    # A book only for the one new to it; the others' books, and the calendar, as they were.
    books = {b.user_id: (b.id, b.customer_id) for b in (await db.execute(select(FuneralRequestBook))).scalars()}
    assert set(books) == set(books_before) | {standby.id}
    assert all(books[uid] == books_before[uid] for uid in books_before)
    for uid, n in bookings.items():
        assert await _count(db, Booking, Booking.created_by_user_id == uid) == n
    assert kias.id in books

    # In the app: All set again, with the new names, to the panthaky, those going and the place.
    title = "All set again: Er. Listed and Er. App Standby are going for Behdin Rustom Jamshed"
    assert (await _notes(db, PANTHAKY, all_set.KIND_ALL_SET))[-1].title == title
    assert (await _notes(db, OTHER_MOBED, all_set.KIND_ALL_SET))[-1].title == title
    assert (await _notes(db, MANAGER, all_set.KIND_ALL_SET))[-1].title == title
    assert len(await _notes(db, MOBED, all_set.KIND_ALL_SET)) == 1        # the first one only
    assert [p for p in pushes if p["title"] == "All set again"]

    # The board and the cards read the new names; the one who can't go reads so.
    board = (await client.get(_b(rid), headers=await _as(client, PANTHAKY))).json()
    assert [g["name"] for g in board["all_set"]["going"]] == ["Er. Listed", "Er. App Standby"]
    assert [p["name"] for p in board["backed_out"]] == [MOBED_NAME]
    card = (await client.get(f"{REQUESTS}/{rid}", headers=other)).json()["request"]
    assert card["all_set"]["family_contact"]["phone"] == FAMILY
    assert [g["is_me"] for g in card["all_set"]["going"]] == [False, True]
    gone = (await client.get(f"{REQUESTS}/{rid}", headers=await _as(client, MOBED))).json()["request"]
    assert gone["all_set"] is None and gone["my_answer"]["state"] == "backed_out"
