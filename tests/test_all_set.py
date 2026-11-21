"""All set (DECISIONS D10, changed 21 Nov 2026; docs/phase2-requests-redesign.md,
"All set"; R3.1 step 5).

When the last place fills, the family goes into the own book of the panthaky
who took the request (or, if nobody did, each confirmed panthaky it reached)
and of each app mobed going: their own record of the number (the one they
have, never renamed, or a new one with reminders off), the Geh-saarnu and
Uthamna on their calendar, once, and nobody else's book touched (D2, D4). Only
those people, and only once it is all set, are given the family's contact,
the panthaky and everyone going; each links the memorial they make to their
own book. Outbound HTTP is mocked throughout.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from agyary.core import config
from agyary.models import (
    Agyary,
    Booking,
    BookingMobed,
    Customer,
    FuneralRequest,
    FuneralRequestBook,
    Memorial,
    Service,
    User,
)
from agyary.services import all_set, funeral_records, prayer_callout
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
    _way,
)

REQUESTS = "/api/mobed/requests"
OTHER_MOBED, SECOND_PANTHAKY = "+919822200114", "+919822200113"


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


async def _user(db, phone) -> User:
    return (await db.execute(select(User).where(User.phone == phone))).scalar_one()


async def _books(db, rid) -> dict[str, FuneralRequestBook]:
    rows = (await db.execute(
        select(User.phone, FuneralRequestBook).join(FuneralRequestBook, FuneralRequestBook.user_id == User.id)
        .where(FuneralRequestBook.funeral_request_id == rid).execution_options(populate_existing=True))).all()
    return {phone: book for phone, book in rows}


async def _count(db, model, *where) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


def _b(rid, what=""):
    return f"/api/mobed/requests/{rid}/board" if not what else f"/api/mobed/requests/{rid}/{what}"


def _no_family(text: str) -> None:
    assert FAMILY not in text and FAMILY[3:] not in text and "Test Family" not in text, text


async def _two_yes(client, db, aid, **changes) -> int:
    """Everyone at once, two wanted: the app mobed and one added by hand say yes on WhatsApp."""
    panthaky = await _as(client, PANTHAKY)
    await _listed(client, aid, panthaky, ("Er. Listed", LISTED), ("Er. Second", SECOND))
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2, **changes)
    answers = await _answers(db)
    await _signed_tap(client, LISTED, f"pca:{answers[LISTED].token}:y")
    assert (await _request(db, rid)).status == "waiting"
    await _signed_tap(client, MOBED, f"pca:{answers[MOBED].token}:y")
    assert (await _request(db, rid)).status == "all_set"
    return rid


# --- Whose book ----------------------------------------------------------------------

async def test_the_family_goes_into_the_panthakys_and_each_going_app_mobeds_own_book_only(
    client, db, seeded, meta, pushes, live,
):
    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    await member(db, goti, OTHER_MOBED, name="Er. Not Going")
    await db.commit()
    # The app mobed going already has the family in their book, under their own name for them;
    # another mobed there has them too.
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins", json={"name": "Their Own Name", "phone": FAMILY},
                          headers=await _as(client, MOBED))
    assert r.status_code == 200, r.text
    kias_own = r.json()["id"]
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins", json={"name": "Not Going's Name", "phone": FAMILY},
                          headers=await _as(client, OTHER_MOBED))
    not_going_own = r.json()["id"]

    rid = await _two_yes(client, db, aid)
    books = await _books(db, rid)
    # Nobody took it on the board: the panthaky it reached; and the app mobed going. Not the one
    # added by hand (no book in the app), not the mobed who did not answer.
    assert set(books) == {PANTHAKY, MOBED}
    assert books[PANTHAKY].is_panthaky is True and books[MOBED].is_panthaky is False

    hormuz, kias = await _user(db, PANTHAKY), await _user(db, MOBED)
    mine = await db.get(Customer, books[PANTHAKY].customer_id)
    assert (mine.owner_user_id, mine.phone, mine.name) == (hormuz.id, FAMILY, "Test Family")
    assert mine.reminders_enabled is False and mine.reminders_stopped_at is None
    # Their own existing record, reused and never renamed; reminders as they were.
    theirs = await db.get(Customer, books[MOBED].customer_id)
    assert theirs.id == kias_own and theirs.owner_user_id == kias.id and theirs.name == "Their Own Name"
    assert theirs.reminders_enabled is False
    assert await _count(db, Customer, Customer.phone == FAMILY) == 3

    # The Geh-saarnu and the Uthamna on each one's calendar, for their own record, at the fire temple.
    for phone, user in ((PANTHAKY, hormuz), (MOBED, kias)):
        bookings = (await db.execute(select(Booking).where(Booking.customer_id == books[phone].customer_id)
                                     .order_by(Booking.id))).scalars().all()
        assert [(await db.get(Service, b.service_id)).name for b in bookings] == ["Geh-saarnu", "Uthamna"]
        for b in bookings:
            assert b.agyary_id == aid and b.created_by_user_id == user.id and b.location == "Doongerwadi (test)"
            assert (await db.execute(select(BookingMobed.user_id).where(BookingMobed.booking_id == b.id))
                    ).scalars().all() == [user.id]
    # Nothing put in the book of the mobed not going.
    assert await _count(db, Booking, Booking.customer_id == not_going_own) == 0
    assert (await db.get(Customer, not_going_own)).name == "Not Going's Name"


async def test_the_panthaky_who_took_it_gets_the_book_and_counts_once_when_they_pray_too(
    client, db, seeded, pushes,
):
    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    await member(db, goti, SECOND_PANTHAKY, role="panthaky", name="Er. Second Panthaky")
    await db.commit()
    await _way(db, aid, "panthaky_first")
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2)
    panthaky = await _as(client, PANTHAKY)
    kias = await _user(db, MOBED)
    # The panthaky marks the mobed Going after a call (taking it), then prays themselves.
    r = await client.post(_b(rid, "call-result"), json={"key": f"u{kias.id}", "result": "going"}, headers=panthaky)
    assert r.status_code == 200, r.text
    r = await client.post(_b(rid, "self"), json={}, headers=panthaky)
    assert r.status_code == 200 and r.json()["status"] == "all_set", r.text
    books = await _books(db, rid)
    # The one who took it, once (as the panthaky, though they also pray), and the mobed going;
    # not the second panthaky it reached.
    assert set(books) == {PANTHAKY, MOBED} and books[PANTHAKY].is_panthaky is True
    hormuz = await _user(db, PANTHAKY)
    assert await _count(db, Booking, Booking.created_by_user_id == hormuz.id) == 2
    assert await _count(db, Customer, Customer.phone == FAMILY) == 2


async def test_with_nobody_taking_it_every_confirmed_panthaky_it_reached_gets_a_book(client, db, seeded, pushes):
    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    await member(db, goti, SECOND_PANTHAKY, role="panthaky", name="Er. Second Panthaky")
    await member(db, goti, "+919822200115", role="panthaky", access="off", name="Er. Panthaky Off")
    await db.commit()
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=1)
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=await _as(client, MOBED))
    assert r.status_code == 200, r.text
    books = await _books(db, rid)
    # Both confirmed panthakys whose access is on (D9: not the one switched off), and the mobed.
    assert set(books) == {PANTHAKY, SECOND_PANTHAKY, MOBED}
    assert sorted(p for p, b in books.items() if b.is_panthaky) == sorted([PANTHAKY, SECOND_PANTHAKY])


async def test_two_yeses_at_the_same_moment_set_up_each_book_once(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    await _listed(client, aid, panthaky, ("Er. Listed", LISTED))
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2)
    answers = await _answers(db)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    settings = config.get_settings()

    async def tap(phone):
        async with factory() as s:
            return await prayer_callout.record_answer(s, settings, f"pca:{answers[phone].token}:y", phone)

    await asyncio.gather(tap(MOBED), tap(LISTED))
    assert (await _request(db, rid)).status == "all_set"
    assert set(await _books(db, rid)) == {PANTHAKY, MOBED}
    assert await _count(db, FuneralRequestBook) == 2
    assert await _count(db, Customer, Customer.phone == FAMILY) == 2
    assert await _count(db, Booking) == 4
    # Asked again, nothing more is made.
    assert await all_set.on_full(db, settings, await _request(db, rid)) is False
    assert await _count(db, FuneralRequestBook) == 2 and await _count(db, Booking) == 4


async def test_a_mobed_switched_off_or_gone_from_the_fire_temple_gets_no_book(client, db, seeded, pushes):
    from sqlalchemy import update

    from agyary.models import AgyaryUser

    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    gone = await member(db, goti, OTHER_MOBED, name="Er. Gone")
    await db.commit()
    rid, _, mgr = await _send(client, db, aid, mobeds_wanted=3)
    panthaky = await _as(client, PANTHAKY)
    for phone in (MOBED, OTHER_MOBED):
        r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=await _as(client, phone))
        assert r.status_code == 200, r.text
    # Their yeses count; then one is switched off and the other leaves the fire temple, before the
    # panthaky's I'll pray fills the last place.
    await db.execute(update(User).where(User.phone == MOBED).values(access="off"))
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == gone.id).values(is_active=False))
    await db.commit()
    r = await client.post(_b(rid, "self"), json={}, headers=panthaky)
    assert r.status_code == 200 and r.json()["status"] == "all_set", r.text
    assert set(await _books(db, rid)) == {PANTHAKY}
    assert await _count(db, Customer, Customer.phone == FAMILY) == 1 and mgr


# --- Who is given the family's contact --------------------------------------------------

async def test_the_familys_contact_reaches_only_those_praying_and_only_once_all_set(
    client, db, seeded, meta, pushes, live, monkeypatch,
):
    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    await member(db, goti, SECOND_PANTHAKY, role="panthaky", name="Er. Second Panthaky")
    await member(db, goti, OTHER_MOBED, name="Er. Not Going")
    await member(db, goti, ADMIN, name="Er. Admin Mobed")
    await db.commit()
    panthaky, second = await _as(client, PANTHAKY), await _as(client, SECOND_PANTHAKY)
    mobed, not_going, admin = await _as(client, MOBED), await _as(client, OTHER_MOBED), await _as(client, ADMIN)
    await _listed(client, aid, panthaky, ("Er. Listed", LISTED))
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2)

    # Before All set: nobody, anywhere.
    assert (await client.post(_b(rid, "self"), json={}, headers=panthaky)).status_code == 200
    for headers in (panthaky, second, admin):
        r = await client.get(_b(rid), headers=headers)
        assert r.status_code == 200 and r.json()["all_set"] is None
        _no_family(r.text)
    for headers in (panthaky, mobed, not_going):
        r = await client.get(f"{REQUESTS}/{rid}", headers=headers)
        assert r.status_code == 200 and r.json()["request"]["all_set"] is None
        _no_family(r.text)
        _no_family((await client.get(REQUESTS, headers=headers)).text)

    # The not-going mobed says no; the app mobed's yes fills the last place.
    assert (await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "no"}, headers=not_going)).status_code == 200
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=mobed)
    assert r.status_code == 200 and r.json()["request"]["status"] == "all_set"
    # Their yes filled the last place: told so, not that the details are still to come.
    assert r.json()["done"]["message"] == prayer_callout.ALL_SET_GOING_WORDS

    # The panthaky who took it (by I'll pray), on the board and on their request.
    hormuz = await _user(db, PANTHAKY)
    board = (await client.get(_b(rid), headers=panthaky)).json()
    got = board["all_set"]
    assert got["family_contact"] == {"name": "Test Family", "phone": FAMILY}
    assert got["panthakys"] == [{"name": "Er. Hormuz Dadachanji", "phone": PANTHAKY, "is_me": True}]
    assert got["going"] == [{"name": "Er. Hormuz Dadachanji", "phone": PANTHAKY, "how": "self", "is_me": True},
                            {"name": "Er. Pervez Kias", "phone": MOBED, "how": "app", "is_me": False}]
    assert got["is_panthaky"] is True and got["confirmed_short"] is False and got["memorial_id"] is None
    assert got["customer_id"] == (await _books(db, rid))[PANTHAKY].customer_id
    assert got["memorial_prefill"]["name"] == "Behdin Rustom Jamshed"
    # The message their own WhatsApp opens with, to the family, in their own name.
    assert got["family_message"].startswith("Sahebji Test Family, I am Er. Hormuz Dadachanji of ")
    assert got["family_message"].endswith("May the ruvan of Behdin Rustom Jamshed attain Garothman Behesht.")
    assert (await client.get(f"{REQUESTS}/{rid}", headers=panthaky)).json()["request"]["all_set"] == got
    assert (await _books(db, rid))[PANTHAKY].user_id == hormuz.id

    # The app mobed going, on their own request card.
    card = (await client.get(f"{REQUESTS}/{rid}", headers=mobed)).json()["request"]
    assert card["all_set"]["family_contact"]["phone"] == FAMILY and card["all_set"]["is_panthaky"] is False
    assert card["all_set"]["panthakys"] == [{"name": "Er. Hormuz Dadachanji", "phone": PANTHAKY, "is_me": False}]
    assert [g["is_me"] for g in card["all_set"]["going"]] == [False, True]
    assert card["all_set"]["customer_id"] == (await _books(db, rid))[MOBED].customer_id
    assert card["all_set"]["family_message"].startswith("Sahebji Test Family, I am Er. Pervez Kias of ")

    # Nobody else: another panthaky it reached, the admin, a mobed not going - nor the manager.
    for headers in (second, admin):
        r = await client.get(_b(rid), headers=headers)
        assert r.status_code == 200 and r.json()["all_set"] is None
        _no_family(r.text)
    for headers in (second, not_going):
        r = await client.get(f"{REQUESTS}/{rid}", headers=headers)
        assert r.json()["request"]["all_set"] is None
        _no_family(r.text)
        _no_family((await client.get(REQUESTS, headers=headers)).text)
    # Nor any WhatsApp message to someone not praying: the call-out and the replies carry none of it.
    praying = {PANTHAKY, MOBED, FAMILY}
    _no_family(json.dumps([m for m in meta.sent if "+" + m["to"].lstrip("+") not in praying]))


async def test_each_one_links_the_memorial_they_make_to_their_own_book(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    rid = await _two_yes(client, db, aid)
    books = await _books(db, rid)
    baaj = (await db.execute(select(Service.id).where(Service.agyary_id == aid, Service.name == "Baaj"))).scalar_one()
    death = (await client.get(f"{REQUESTS}/{rid}", headers=await _as(client, PANTHAKY))).json()["request"]["death"]
    body = {"departed_name": "Behdin Rustom Jamshed", "death_date": death["date"], "calendar": "shenshai",
            "day_counts": [30], "service_ids": [baaj], "funeral_request_id": rid}

    made = {}
    for phone in (PANTHAKY, MOBED):
        headers = await _as(client, phone)
        r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{books[phone].customer_id}/memorials", json=body,
                              headers=headers)
        assert r.status_code == 200, r.text
        made[phone] = r.json()["id"]
        seen = (await client.get(f"{REQUESTS}/{rid}", headers=headers)).json()["request"]["all_set"]
        assert seen["memorial_id"] == made[phone]
    books = await _books(db, rid)
    assert {p: b.memorial_id for p, b in books.items()} == made
    for phone, mid in made.items():
        assert (await db.get(Memorial, mid)).created_by_user_id == (await _user(db, phone)).id
    # A second memorial changes nothing; the old single link stays empty (D8: it is for accepted ones).
    headers = await _as(client, MOBED)
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{books[MOBED].customer_id}/memorials", json=body,
                          headers=headers)
    assert r.status_code == 200
    assert (await _books(db, rid))[MOBED].memorial_id == made[MOBED]
    assert (await _request(db, rid)).memorial_id is None
    # Someone whose book it is not cannot pin theirs to it.
    other = await member(db, await db.get(Agyary, aid), OTHER_MOBED, name="Er. Not Going")
    await db.commit()
    headers = await _as(client, OTHER_MOBED)
    own = (await client.post(f"/api/mobed/agyaries/{aid}/behdins", json={"name": "Someone", "phone": "+919822200155"},
                             headers=headers)).json()["id"]
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{own}/memorials", json=body, headers=headers)
    assert r.status_code == 200
    assert await _count(db, FuneralRequestBook, FuneralRequestBook.user_id == other.id) == 0
    assert (await client.get(f"{REQUESTS}/{rid}", headers=headers)).status_code == 404


async def test_with_no_geh_saarnu_day_only_the_uthamna_goes_on_the_calendars(client, db, seeded, pushes):
    today = funeral_records.today_ist()
    rid, _, _ = await _send(client, db, seeded["agyary_id"], mobeds_wanted=1, geh_saarnu_date=None,
                            geh_saarnu_geh=None, uthamna_date=(today + timedelta(days=1)).isoformat())
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=await _as(client, MOBED))
    assert r.status_code == 200
    books = await _books(db, rid)
    assert set(books) == {PANTHAKY, MOBED}
    for b in books.values():
        bookings = (await db.execute(select(Booking).where(Booking.customer_id == b.customer_id))).scalars().all()
        assert [(await db.get(Service, x.service_id)).name for x in bookings] == ["Uthamna"]


# --- Everyone is told ------------------------------------------------------------------

async def _notes_of(db, phone, kind=all_set.KIND_ALL_SET):
    from agyary.models import AppNotification

    user = await _user(db, phone)
    return list((await db.execute(select(AppNotification).where(
        AppNotification.user_id == user.id, AppNotification.kind == kind).order_by(AppNotification.id))).scalars())


async def test_the_panthakys_the_mobeds_going_and_the_managers_are_told_without_the_family_on_the_lock_screen(
    client, db, seeded, meta, pushes, live,
):
    from tests.funeral_helpers import MANAGER

    aid = seeded["agyary_id"]
    goti = await db.get(Agyary, aid)
    await member(db, goti, SECOND_PANTHAKY, role="panthaky", name="Er. Second Panthaky")
    await db.commit()
    panthaky = await _as(client, PANTHAKY)
    await _way(db, aid, "panthaky_first")
    rid, _, mgr = await _send(client, db, aid, mobeds_wanted=2)
    # The panthaky takes it with I'll pray; the app mobed is marked going after a call: all set.
    kias = await _user(db, MOBED)
    assert (await client.post(_b(rid, "self"), json={}, headers=panthaky)).status_code == 200
    pushes.clear()
    r = await client.post(_b(rid, "call-result"), json={"key": f"u{kias.id}", "result": "going"}, headers=panthaky)
    assert r.status_code == 200 and r.json()["status"] == "all_set", r.text

    title = "All set: Er. Hormuz Dadachanji and Er. Pervez Kias are going for Behdin Rustom Jamshed"
    said = "Er. Hormuz Dadachanji and Er. Pervez Kias are going for Behdin Rustom Jamshed."
    (mine,) = await _notes_of(db, PANTHAKY)
    assert mine.title == title and mine.link == f"#/requests/{rid}"
    assert mine.body == f"{said} The family's contact and everyone going are on the request from Doongerwadi (test)."
    (other,) = await _notes_of(db, SECOND_PANTHAKY)
    assert other.body == f"{said} The request from Doongerwadi (test) is all set. Nothing more is needed from you."
    (going,) = await _notes_of(db, MOBED)
    assert going.body == (f"{said} You are going. The family's contact, the panthaky and everyone going are on "
                          "your request card.")
    (place,) = await _notes_of(db, MANAGER)
    assert place.title == title and place.link.startswith("#/manager/record/")
    assert place.body == f"Goti Adarian: {said} The panthaky is Er. Hormuz Dadachanji."
    for note in (mine, other, going, place):
        _no_family(note.title + note.body)

    # On their phones: who and where, never the departed or the family. The panthaky who marked
    # the last place sees it on screen, so their phone is not woken.
    told = [p for p in pushes if p["title"] == "All set"]
    hormuz, second = await _user(db, PANTHAKY), await _user(db, SECOND_PANTHAKY)
    to_mobeds, to_place = told
    assert to_mobeds["to"] == sorted([second.id, kias.id]) and to_mobeds["url"] == f"/mobed#/requests/{rid}"
    assert to_mobeds["body"] == "Er. Hormuz Dadachanji and Er. Pervez Kias are going for the request from Doongerwadi (test)."
    assert to_place["body"] == "Er. Hormuz Dadachanji and Er. Pervez Kias are going from Goti Adarian."
    for p in told:
        _no_family(p["body"])
        assert "Rustom" not in p["body"] and hormuz.id not in p["to"]
    assert mgr


def test_a_long_title_still_fits():
    names = [f"Er. A Very Long Mobed Name Number {i}" for i in range(5)]
    title = all_set.fit_title(f"All set: {all_set.going_words(names)} for Behdin Rustom Jamshed",
                              "All set: 5 mobeds are going for Behdin Rustom Jamshed", "All set: enough mobeds are going")
    assert title == "All set: 5 mobeds are going for Behdin Rustom Jamshed"
    assert len(all_set.fit_title("x" * 200, "y" * 130)) == all_set.TITLE_MAX


# --- On WhatsApp (templates 5-8) ----------------------------------------------------------

OLD_TEMPLATES = ("funeral_accepted_manager", "prayer_details_mobed_v2", "prayers_mobed_family")


def _body(m) -> list[str]:
    return [p["text"] for p in m["template"]["components"][0]["parameters"]]


def _buttons(m) -> list[dict]:
    return [c for c in m["template"]["components"] if c["type"] == "button"]


def _e164(m) -> str:
    return "+" + m["to"].lstrip("+")


def _to(meta, name) -> dict[str, dict]:
    return {_e164(m): m for m in meta.templates(name)}


def _times() -> tuple[str, str]:
    today = funeral_records.today_ist()

    def day(d):
        return f"{d:%a} {d.day} {d:%b}"

    return f"{day(today)}, Havan geh", f"{day(today + timedelta(days=2))}, 4:00 pm"


async def test_live_each_one_gets_their_template_with_the_blanks_in_order(client, db, seeded, meta, pushes, live):
    from agyary.models import Notification
    from tests.funeral_helpers import MANAGER

    aid = seeded["agyary_id"]
    rid = await _two_yes(client, db, aid)
    gs, ut = _times()
    mobeds = "Er. Listed (+91 9822200055), Er. Pervez Kias (+91 9800000002)"
    head = "Er. Hormuz Dadachanji (+91 9800000001)"
    for name in OLD_TEMPLATES:
        assert meta.templates(name) == []           # templates 1-3 are not sent for these

    (family,) = meta.templates("prayers_all_set_family")
    assert _e164(family) == FAMILY
    assert _body(family) == ["Behdin Rustom Jamshed", mobeds, "Goti Adarian", gs, ut, head] and _buttons(family) == []

    details = _to(meta, "prayer_details_mobed_v3")
    assert set(details) == {LISTED, MOBED}           # each going with a number, app or added by hand
    answers = await _answers(db)
    for phone, m in details.items():
        assert _body(m) == ["Behdin Rustom Jamshed", "Doongerwadi (test)", gs, ut, "Test Family", FAMILY, mobeds, head]
        (button,) = _buttons(m)
        assert button["sub_type"] == "quick_reply" and button["index"] == "0"
        assert button["parameters"] == [{"type": "payload", "payload": f"pca:{answers[phone].token}:x"}]
        assert prayer_callout.back_out_payload(answers[phone]) == f"pca:{answers[phone].token}:x"

    (to_panthaky,) = meta.templates("prayers_all_set_panthaky")
    assert _e164(to_panthaky) == PANTHAKY
    assert _body(to_panthaky) == ["Behdin Rustom Jamshed", "Doongerwadi (test)", mobeds, gs, ut, "Test Family", FAMILY]
    (to_place,) = meta.templates("funeral_accepted_manager_v2")
    assert _e164(to_place) == MANAGER
    assert _body(to_place) == ["Behdin Rustom Jamshed", "Er. Listed and Er. Pervez Kias", "Goti Adarian", head]
    for m in meta.sent:
        if m.get("type") == "template":
            for text in _body(m):
                assert "\n" not in text and "\t" not in text and "    " not in text and text.strip()

    # Each is a row, written down with the names and never a number.
    rows = (await db.execute(select(Notification).where(Notification.notification_type.in_(fw.ALL_SET_TYPES))
                             )).scalars().all()
    assert sorted(n.notification_type for n in rows) == sorted(
        ["prayers_all_set_family", "prayer_details_mobed_v3", "prayer_details_mobed_v3", "prayers_all_set_panthaky",
         "funeral_accepted_manager_v2"])
    assert all(n.status == "sent" and n.template_params["request"] == str(rid) for n in rows)
    for n in rows:
        kept = json.dumps(n.template_params)
        for number in (FAMILY, PANTHAKY, MOBED, LISTED, MANAGER):
            assert number[3:] not in kept, (n.notification_type, kept)
    family_row = next(n for n in rows if n.notification_type == "prayers_all_set_family")
    assert family_row.template_params["2"] == "Er. Listed ([number]), Er. Pervez Kias ([number])"
    assert family_row.template_params["6"] == "Er. Hormuz Dadachanji ([number])"


async def test_the_panthaky_who_prays_gets_the_details_not_the_panthakys_message(client, db, seeded, meta, pushes,
                                                                                live):
    aid = seeded["agyary_id"]
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=1)
    meta.sent.clear()
    r = await client.post(_b(rid, "self"), json={}, headers=await _as(client, PANTHAKY))
    assert r.status_code == 200 and r.json()["status"] == "all_set"
    assert meta.templates("prayers_all_set_panthaky") == []
    (details,) = meta.templates("prayer_details_mobed_v3")
    assert _e164(details) == PANTHAKY
    assert _body(details)[6:] == ["Er. Hormuz Dadachanji (+91 9800000001)"] * 2


async def test_the_family_only_with_their_agreement_and_a_stop_is_honoured(client, db, seeded, meta, pushes, live):
    from datetime import datetime, timezone

    from agyary.models import ReminderOptOut
    from tests.funeral_helpers import form, manager

    aid = seeded["agyary_id"]
    # The manager's tick did not record the family's agreement: no message to them.
    mgr, _ = await manager(client, db)
    rec = (await client.post("/api/mobed/manager/records", json=form(mobeds_wanted=1), headers=mgr)).json()["record"]
    r = await client.post(f"/api/mobed/manager/records/{rec['id']}/requests", headers=mgr,
                          json={"agyary_id": aid, "family_agreed": True})
    rid = r.json()["record"]["requests"][0]["id"]
    meta.sent.clear()
    assert (await client.post(_b(rid, "self"), json={}, headers=await _as(client, PANTHAKY))).status_code == 200
    assert meta.templates("prayers_all_set_family") == [] and meta.templates("prayer_details_mobed_v3")
    assert not await fw.rows_for(db, request_id=rid, kinds=(fw.TYPE_ALL_SET_FAMILY,))

    # A family and a mobed who replied STOP: written down, not sent.
    now = datetime.now(timezone.utc)
    db.add_all([ReminderOptOut(phone=FAMILY, stopped_at=now), ReminderOptOut(phone=MOBED, stopped_at=now)])
    await db.commit()
    rid, _, _ = await _send(client, db, aid, mgr, mobeds_wanted=1)
    meta.sent.clear()
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=await _as(client, MOBED))
    assert r.status_code == 200 and r.json()["request"]["status"] == "all_set"
    assert meta.templates("prayers_all_set_family") == [] and meta.templates("prayer_details_mobed_v3") == []
    rows = {n.notification_type: n for n in await fw.rows_for(db, request_id=rid, kinds=fw.ALL_SET_TYPES)}
    for kind in (fw.TYPE_ALL_SET_FAMILY, fw.TYPE_ALL_SET_DETAILS):
        assert rows[kind].status == "failed" and "STOP" in rows[kind].error_message
    assert rows[fw.TYPE_ALL_SET_PANTHAKY].status == "sent" and rows[fw.TYPE_ALL_SET_MANAGER].status == "sent"


async def test_switched_off_nothing_is_sent_or_written_and_paused_nothing_goes(client, db, seeded, meta, pushes,
                                                                              monkeypatch):
    from agyary.services import guardrails

    aid = seeded["agyary_id"]
    rid, _, mgr = await _send(client, db, aid, mobeds_wanted=2)
    assert (await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"},
                              headers=await _as(client, MOBED))).status_code == 200
    r = await client.post(_b(rid, "self"), json={}, headers=await _as(client, PANTHAKY))
    assert r.status_code == 200 and r.json()["status"] == "all_set"
    assert meta.sent == [] and await fw.rows_for(db, request_id=rid, kinds=fw.ALL_SET_TYPES) == []
    # Live, but paused: each is written down as not sent, and says why.
    for key, value in LIVE.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    await guardrails.pause(db, config.get_settings(), "test pause")
    await db.commit()
    rid2, _, _ = await _send(client, db, aid, mgr, mobeds_wanted=1)
    r = await client.post(_b(rid2, "self"), json={}, headers=await _as(client, PANTHAKY))
    assert r.status_code == 200 and r.json()["status"] == "all_set"
    rows = await fw.rows_for(db, request_id=rid2, kinds=fw.ALL_SET_TYPES)
    assert rows and all(n.status == "failed" and "paused" in n.error_message for n in rows)
    assert meta.sent == []


async def test_a_mobed_whose_access_is_off_is_named_but_not_messaged(client, db, seeded, meta, pushes, live):
    from sqlalchemy import update

    aid = seeded["agyary_id"]
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2)
    assert (await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"},
                              headers=await _as(client, MOBED))).status_code == 200
    await db.execute(update(User).where(User.phone == MOBED).values(access="off"))
    await db.commit()
    meta.sent.clear()
    assert (await client.post(_b(rid, "self"), json={}, headers=await _as(client, PANTHAKY))).status_code == 200
    details = _to(meta, "prayer_details_mobed_v3")
    assert set(details) == {PANTHAKY}
    assert "Er. Pervez Kias (+91 9800000002)" in _body(details[PANTHAKY])[6]
    (row,) = [n for n in await fw.rows_for(db, request_id=rid, kinds=(fw.TYPE_ALL_SET_DETAILS,))
              if n.status == "failed"]
    assert "access is not on" in row.error_message


def test_the_people_blank_is_built_by_the_server():
    people = [fw.Person("Er.  A\nName", "+919800000001"), fw.Person("Er. B", None), fw.Person("Er. C", "+14155550100")]
    sent, kept = fw.people_blank(people)
    assert sent == "Er. A Name (+91 9800000001), Er. B, Er. C (+14155550100)"
    assert kept == "Er. A Name ([number]), Er. B, Er. C ([number])"
    assert fw.people_blank([]) == ("not fixed yet", "not fixed yet")
    assert fw.names_blank(people) == "Er. A Name, Er. B and Er. C" and fw.names_blank([]) == "not fixed yet"


# --- Confirm with who's going -------------------------------------------------------------

async def test_confirm_with_whos_going_makes_it_all_set_short_the_same_way(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    await _way(db, aid, "panthaky_first")
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=3)
    panthaky = await _as(client, PANTHAKY)
    url = _b(rid, "confirm-short")
    # Nobody going yet: nothing to confirm, and nothing is taken.
    assert (await client.get(_b(rid), headers=panthaky)).json()["may_confirm_short"] is False
    r = await client.post(url, json={}, headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == prayer_callout.SHORT_NOBODY
    assert (await _request(db, rid)).taken_at is None and (await _request(db, rid)).status == "waiting"

    assert (await client.post(_b(rid, "self"), json={}, headers=panthaky)).status_code == 200
    assert (await client.get(_b(rid), headers=panthaky)).json()["may_confirm_short"] is True
    meta.sent.clear()
    r = await client.post(url, json={}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert r.json()["done"] == {"outcome": "all set, short", "message": "All set with 1 of 3 going."}
    board = r.json()
    assert board["status"] == "all_set" and board["confirmed_short"] is True and board["may_confirm_short"] is False
    assert board["all_set"]["confirmed_short"] is True and board["all_set"]["family_contact"]["phone"] == FAMILY
    request = await _request(db, rid)
    assert request.confirmed_short is True and request.all_set_at is not None
    assert set(await _books(db, rid)) == {PANTHAKY}
    (note,) = await _notes_of(db, PANTHAKY)
    assert note.body.startswith("Er. Hormuz Dadachanji is going for Behdin Rustom Jamshed, 1 of 3 wanted: "
                                "the panthaky confirmed with who is going.")
    assert {m["template"]["name"] for m in meta.sent} == {
        "prayers_all_set_family", "prayer_details_mobed_v3", "funeral_accepted_manager_v2"}
    # Once all set, it is refused in plain words.
    r = await client.post(url, json={}, headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == "Enough mobeds are going for this request: it is all set."


async def test_confirm_with_whos_going_is_for_the_panthakys_it_reached_and_the_admin_only(client, db, seeded, pushes,
                                                                                         monkeypatch):
    from tests.funeral_helpers import agyari

    monkeypatch.setenv("ADMIN_PHONES", ADMIN)
    config.get_settings.cache_clear()
    aid = seeded["agyary_id"]
    other = await agyari(db, "Other Agyari (test)", None)
    await member(db, other, "+919822200099", role="panthaky", name="Er. Other Panthaky")
    await db.commit()
    rid, _, mgr = await _send(client, db, aid, mobeds_wanted=2)
    mobed = await _as(client, MOBED)
    assert (await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=mobed)).status_code == 200
    url = _b(rid, "confirm-short")
    for headers in (mobed, await _as(client, "+919822200099")):
        r = await client.post(url, json={}, headers=headers)
        assert r.status_code == 404 and r.json()["detail"] == "That request could not be found."
    assert (await client.post(url, json={}, headers=mgr)).status_code == 403
    assert (await _request(db, rid)).status == "waiting"
    # The admin may; the admin is not the panthaky, so the family goes to the panthaky it reached.
    r = await client.post(url, json={}, headers=await _as(client, ADMIN))
    assert r.status_code == 200 and r.json()["done"]["message"] == "All set with 1 of 2 going.", r.text
    assert r.json()["all_set"] is None
    assert set(await _books(db, rid)) == {PANTHAKY, MOBED}
    # A withdrawn request is refused too.
    rid2, _, _ = await _send(client, db, aid, mgr, mobeds_wanted=2)
    assert (await client.post(f"/api/mobed/manager/requests/{rid2}/withdraw", headers=mgr)).status_code == 200
    r = await client.post(_b(rid2, "confirm-short"), json={}, headers=await _as(client, PANTHAKY))
    assert r.status_code == 409 and "withdrew this request" in r.json()["detail"]


# --- Still short: 4 hours before the Geh-saarnu --------------------------------------------

def test_when_still_short_is_due_for_each_geh_and_without_one():
    from datetime import date, datetime, time

    from agyary.services import prayer_timers as pt

    day = date(2026, 11, 23)

    def at(h, m, d=day):
        return datetime.combine(d, time(h, m), tzinfo=pt.IST)

    assert pt.short_alert_at(day, 1, None, None) == at(2, 30)        # Havan 6:30 am
    assert pt.short_alert_at(day, 2, None, None) == at(8, 30)        # Rapithwin 12:30 pm
    assert pt.short_alert_at(day, 3, day, time(16, 0)) == at(11, 30)  # Uziran 3:30 pm; the Uthamna does not count
    assert pt.short_alert_at(day, None, None, None) == at(2, 30)     # no geh: 6:30 am
    assert pt.short_alert_at(None, None, day, time(16, 0)) == at(12, 0)   # no Geh-saarnu: the Uthamna's time
    assert pt.short_alert_at(None, None, day, None) == at(2, 30)     # nor its time: 6:30 am
    assert pt.short_alert_at(None, None, None, None) is None         # neither: never


async def _short_tick(db, at) -> int:
    from agyary.services import prayer_timers

    return await prayer_timers.still_short(db, at, config.get_settings())


async def test_still_short_tells_the_panthaky_once_four_hours_before_the_geh_saarnu(client, db, seeded, pushes):
    from datetime import datetime, time

    from agyary.services import prayer_timers

    aid = seeded["agyary_id"]
    tomorrow = funeral_records.today_ist() + timedelta(days=1)
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2, geh_saarnu_date=tomorrow.isoformat(), geh_saarnu_geh=2,
                            uthamna_date=(tomorrow + timedelta(days=1)).isoformat())
    assert (await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"},
                              headers=await _as(client, MOBED))).status_code == 200
    due = datetime.combine(tomorrow, time(8, 30), tzinfo=prayer_timers.IST)
    pushes.clear()
    assert await _short_tick(db, due - timedelta(minutes=1)) == 0
    assert await _notes_of(db, PANTHAKY, prayer_timers.KIND_STILL_SHORT) == []
    # The one-minute loop's tick runs it.
    assert await prayer_timers.run(db, due, config.get_settings(), None) == 1
    assert (await _request(db, rid)).short_alert_at == due
    (note,) = await _notes_of(db, PANTHAKY, prayer_timers.KIND_STILL_SHORT)
    assert note.title == "Still 1 mobed short for Behdin Rustom Jamshed" and note.link == f"#/requests/{rid}"
    assert note.body == (f"1 of 2 going for the request from Doongerwadi (test), and the Geh-saarnu is "
                         f"{tomorrow:%a} {tomorrow.day} {tomorrow:%b}, Rapithwin geh. "
                         "Ask everyone, call a mobed, or Confirm with who's going.")
    (push,) = pushes
    assert push["to"] == [(await _user(db, PANTHAKY)).id] and push["title"] == "Still 1 mobed short"
    assert push["body"] == "The request from Doongerwadi (test): 1 of 2 going."
    for text in (note.title + note.body, push["title"] + push["body"]):
        _no_family(text)
    assert "Rustom" not in push["body"]
    assert await _notes_of(db, MOBED, prayer_timers.KIND_STILL_SHORT) == []     # only the panthaky
    # Once only.
    for later in (1, 60, 600):
        assert await _short_tick(db, due + timedelta(minutes=later)) == 0
    assert len(await _notes_of(db, PANTHAKY, prayer_timers.KIND_STILL_SHORT)) == 1 and len(pushes) == 1


async def test_still_short_at_once_when_the_request_comes_later_and_never_when_full_or_without_days(
    client, db, seeded, pushes,
):
    from datetime import datetime, time

    from sqlalchemy import update

    from agyary.models import FuneralRecord
    from agyary.services import prayer_timers

    aid = seeded["agyary_id"]
    # A Geh-saarnu whose 4 hours had begun before anyone looked (the request came late): told at
    # the first tick, as long as the prayers have not begun.
    rid, _, mgr = await _send(client, db, aid, mobeds_wanted=2)
    record_id = (await _request(db, rid)).funeral_record_id
    tomorrow = funeral_records.today_ist() + timedelta(days=1)
    await db.execute(update(FuneralRecord).where(FuneralRecord.id == record_id).values(
        geh_saarnu_date=tomorrow, geh_saarnu_geh=2))
    await db.commit()
    sent_at = (await _request(db, rid)).sent_at
    assert await _short_tick(db, datetime.combine(tomorrow, time(11, 30), tzinfo=prayer_timers.IST)) == 1
    (note,) = await _notes_of(db, PANTHAKY, prayer_timers.KIND_STILL_SHORT)
    assert note.title == "Still 2 mobeds short for Behdin Rustom Jamshed"
    assert note.body.endswith("Ask everyone, call a mobed, or pray yourself.")

    # All set: never.
    rid2, _, _ = await _send(client, db, aid, mgr, mobeds_wanted=1)
    assert (await client.post(_b(rid2, "self"), json={}, headers=await _as(client, PANTHAKY))).status_code == 200
    # No Geh-saarnu and no Uthamna: never.
    rid3, _, _ = await _send(client, db, aid, mgr, mobeds_wanted=1, geh_saarnu_date=None, geh_saarnu_geh=None,
                             uthamna_date=None, uthamna_time=None)
    far = sent_at + timedelta(days=30)
    assert await _short_tick(db, far) == 0
    assert (await _request(db, rid2)).short_alert_at is None and (await _request(db, rid3)).short_alert_at is None

    # Prayers that have already begun or passed (an old record left waiting): never, even untold.
    rid4, _, _ = await _send(client, db, aid, mgr, mobeds_wanted=1)
    record4 = (await _request(db, rid4)).funeral_record_id
    yesterday = funeral_records.today_ist() - timedelta(days=1)
    await db.execute(update(FuneralRecord).where(FuneralRecord.id == record4).values(
        geh_saarnu_date=yesterday, geh_saarnu_geh=1))
    await db.commit()
    assert await _short_tick(db, sent_at + timedelta(seconds=30)) == 0
    assert await _short_tick(db, datetime.combine(tomorrow, time(12, 31), tzinfo=prayer_timers.IST)) == 0
    assert (await _request(db, rid4)).short_alert_at is None


async def test_with_no_confirmed_panthaky_the_funeral_place_is_told(client, db, seeded, pushes):
    from agyary.models import AppNotification
    from agyary.services import prayer_timers
    from tests.funeral_helpers import MANAGER, agyari

    only = await agyari(db, "Mobeds Only Agyari (test)", None)
    await member(db, only, "+919822200111", name="Er. Only One")
    await db.commit()
    rid, _, _ = await _send(client, db, only.id, mobeds_wanted=2)
    sent_at = (await _request(db, rid)).sent_at
    pushes.clear()
    # The form's Geh-saarnu is today, Havan (6:30 am): due from 2:30 am, and only until it begins.
    # A fixed time in that window, so the test does not depend on the hour it runs at.
    assert sent_at is not None
    assert await _short_tick(db, datetime_today_ist(3, 0)) == 1
    (note,) = await _notes_of(db, MANAGER, prayer_timers.KIND_STILL_SHORT)
    assert note.title == "Still 2 mobeds short at Mobeds Only Agyari (test) for Behdin Rustom Jamshed"
    assert note.body.startswith("0 of 2 mobeds are going from Mobeds Only Agyari (test) for Behdin Rustom Jamshed")
    assert note.body.endswith("You can withdraw the request and send it to another fire temple.")
    assert note.link == f"#/manager/record/{(await _request(db, rid)).funeral_record_id}"
    (push,) = pushes
    assert push["title"] == "Still 2 mobeds short" and "Rustom" not in push["body"]
    assert not (await db.execute(select(AppNotification).where(
        AppNotification.kind == prayer_timers.KIND_STILL_SHORT,
        AppNotification.user_id == (await _user(db, "+919822200111")).id))).scalars().all()


def datetime_today_ist(h: int, m: int):
    from datetime import datetime, time

    from agyary.services import prayer_timers

    return datetime.combine(funeral_records.today_ist(), time(h, m), tzinfo=prayer_timers.IST)


async def test_two_loops_at_the_same_moment_tell_once(client, db, seeded, pushes):
    from agyary.services import prayer_timers

    rid, _, _ = await _send(client, db, seeded["agyary_id"], mobeds_wanted=2)
    at = datetime_today_ist(3, 0)     # inside today's Havan window: from 2:30 until 6:30 am
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    settings = config.get_settings()
    async with factory() as one, factory() as two:
        done = await asyncio.gather(prayer_timers.still_short(one, at, settings),
                                    prayer_timers.still_short(two, at, settings))
    assert sorted(done) == [0, 1]
    assert len(await _notes_of(db, PANTHAKY, prayer_timers.KIND_STILL_SHORT)) == 1


async def test_confirming_takes_it_so_the_family_goes_to_the_panthaky_who_confirmed(client, db, seeded, pushes):
    aid = seeded["agyary_id"]
    await member(db, await db.get(Agyary, aid), SECOND_PANTHAKY, role="panthaky", name="Er. Second Panthaky")
    await db.commit()
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2)
    r = await client.post(f"{REQUESTS}/{rid}/answer", json={"answer": "yes"}, headers=await _as(client, MOBED))
    assert r.status_code == 200 and (await _request(db, rid)).taken_at is None
    r = await client.post(_b(rid, "confirm-short"), json={}, headers=await _as(client, SECOND_PANTHAKY))
    assert r.status_code == 200, r.text
    assert (await _request(db, rid)).taken_by_user_id == (await _user(db, SECOND_PANTHAKY)).id
    books = await _books(db, rid)
    assert set(books) == {SECOND_PANTHAKY, MOBED} and books[SECOND_PANTHAKY].is_panthaky
    assert r.json()["all_set"]["panthakys"] == [{"name": "Er. Second Panthaky", "phone": SECOND_PANTHAKY, "is_me": True}]


async def test_a_tap_still_answers_when_what_follows_it_breaks(client, db, seeded, pushes, monkeypatch):
    """Something breaking after the tap's work is done - telling everyone it is all set,
    or after someone can't go - rolls the session back; the tap still answers with the
    board or card read again, and what it did stands (never a failure on screen for it)."""
    from agyary.services import standbys

    async def boom(*a, **kw):
        raise RuntimeError("something unexpected")

    monkeypatch.setattr(all_set, "_tell", boom)
    monkeypatch.setattr(standbys, "place_opened", boom)
    aid = seeded["agyary_id"]
    tomorrow = (funeral_records.today_ist() + timedelta(days=1)).isoformat()
    panthaky, mobed = await _as(client, PANTHAKY), await _as(client, MOBED)
    hormuz, kias = await _user(db, PANTHAKY), await _user(db, MOBED)
    # I'll pray, then Can't go on the board.
    rid, _, mgr = await _send(client, db, aid, mobeds_wanted=1, geh_saarnu_date=tomorrow)
    r = await client.post(_b(rid, "self"), json={}, headers=panthaky)
    assert r.status_code == 200 and r.json()["status"] == "all_set", r.text
    r = await client.post(_b(rid, "cant-go"), json={"key": f"u{hormuz.id}"}, headers=panthaky)
    assert r.status_code == 200 and r.json()["status"] == "waiting", r.text
    # A call's Going.
    rid2, _, _ = await _send(client, db, aid, mgr, mobeds_wanted=1)
    r = await client.post(_b(rid2, "call-result"), json={"key": f"u{kias.id}", "result": "going"}, headers=panthaky)
    assert r.status_code == 200 and r.json()["status"] == "all_set", r.text
    # Confirm with who's going.
    rid3, _, _ = await _send(client, db, aid, mgr, mobeds_wanted=2)
    assert (await client.post(_b(rid3, "self"), json={}, headers=panthaky)).status_code == 200
    r = await client.post(_b(rid3, "confirm-short"), json={}, headers=panthaky)
    assert r.status_code == 200 and r.json()["status"] == "all_set", r.text
    # An app mobed's I can pray, then their I can't go any more.
    rid4, _, _ = await _send(client, db, aid, mgr, mobeds_wanted=1, geh_saarnu_date=tomorrow)
    r = await client.post(f"{REQUESTS}/{rid4}/answer", json={"answer": "yes"}, headers=mobed)
    assert r.status_code == 200 and r.json()["request"]["status"] == "all_set", r.text
    r = await client.post(f"{REQUESTS}/{rid4}/back-out", headers=mobed)
    assert r.status_code == 200 and r.json()["request"]["status"] == "waiting", r.text
    assert [(await _request(db, i)).status for i in (rid, rid2, rid3, rid4)] == [
        "waiting", "all_set", "all_set", "waiting"]
