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
    assert (await client.get(f"{REQUESTS}/{rid}", headers=panthaky)).json()["request"]["all_set"] == got
    assert (await _books(db, rid))[PANTHAKY].user_id == hormuz.id

    # The app mobed going, on their own request card.
    card = (await client.get(f"{REQUESTS}/{rid}", headers=mobed)).json()["request"]
    assert card["all_set"]["family_contact"]["phone"] == FAMILY and card["all_set"]["is_panthaky"] is False
    assert card["all_set"]["panthakys"] == [{"name": "Er. Hormuz Dadachanji", "phone": PANTHAKY, "is_me": False}]
    assert [g["is_me"] for g in card["all_set"]["going"]] == [False, True]
    assert card["all_set"]["customer_id"] == (await _books(db, rid))[MOBED].customer_id

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
