"""A request for prayers on the fire temple's side (DECISIONS D10 and its 18 Nov
amendment, D2, D4; Phase 2 Step 5; R3.1).

Only those asked see a request, and the family's name and number are not shown
to them. Since R3.1 step 7 there is no Accept: the board's actions are the only
way to take a request (tests/test_prayer_board.py), and the old Accept and
call-out routes are gone. A request accepted the old way before R3.1 stays (D8)
and still reads as it did: the family's contact, the message to them and the
memorial only for the one who accepted, "Accepted by <name>" for the others, and
the accepter's number for the manager only with their tick. The family going
into one person's book (put_in_book, which All set uses) sets up their own book
only - their own record of the number (reused if they have one, made if not,
reminders off, a STOP kept), the Geh-saarnu and the Uthamna on their calendar -
and never reads or touches another mobed's record of the same number. Declining
takes a short reason.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from agyary.api.routes import mobed as mobed_routes
from agyary.models import (
    Agyary,
    AppNotification,
    Booking,
    BookingMobed,
    Customer,
    FuneralRequest,
    Memorial,
    Notification,
    PrayerCallout,
    ReminderOptOut,
    Service,
    User,
)
from agyary.services import funeral_records
from tests.conftest import sign_in
from tests.funeral_helpers import FAMILY, accepted_the_old_way, agyari, auth, form, manager, member

RECORDS = "/api/mobed/manager/records"
REQUESTS = "/api/mobed/requests"
PANTHAKY, MOBED = "+919800000001", "+919800000002"   # the seeded fire temple's


@pytest.fixture
def pushes(monkeypatch):
    sent = []

    async def capture(db, settings, user_ids, **kw):
        sent.append({"to": sorted(user_ids), **kw})
        return 0

    from agyary.services import web_push

    monkeypatch.setattr(web_push, "send_to_users", capture)
    return sent


async def _sent(client, db, agyary_id: int, mgr=None, **changes) -> tuple[dict, dict, int]:
    """A record sent to ``agyary_id``: the manager's headers, the record, the request id."""
    if mgr is None:
        mgr, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(**changes), headers=mgr)).json()["record"]
    r = await client.post(f"{RECORDS}/{rec['id']}/requests", json={"agyary_id": agyary_id, "family_agreed": True},
                          headers=mgr)
    assert r.status_code == 200, r.text
    return mgr, rec, r.json()["record"]["requests"][0]["id"]


async def _as(client, phone: str) -> dict:
    return auth(await sign_in(client, phone))


async def _user(db, phone: str) -> User:
    return (await db.execute(select(User).where(User.phone == phone))).scalar_one()


def _no_family(text: str) -> None:
    assert FAMILY not in text and FAMILY[3:] not in text and "Test Family" not in text, text


async def test_only_those_asked_see_it_and_not_the_family(client, db, seeded, pushes):
    mgr, _, rid = await _sent(client, db, seeded["agyary_id"])
    panthaky = await _as(client, PANTHAKY)
    assert (await client.get(f"{REQUESTS}/count", headers=panthaky)).json() == {"waiting": 1}
    got = await client.get(REQUESTS, headers=panthaky)
    assert got.status_code == 200
    (req,) = got.json()["waiting"]
    assert req["id"] == rid and req["status"] == "waiting" and got.json()["earlier"] == []
    assert req["prayed_name"] == "Behdin Rustom Jamshed" and "bungli" not in req
    assert req["funeral_place"]["name"] == "Doongerwadi (test)" and req["funeral_place"]["kind_label"] == "Doongerwadi"
    assert req["geh_saarnu"]["geh_name"] == "Havan" and req["uthamna"]["time"] == "16:00"
    assert req["mobeds_wanted"] == 5 and req["obsequies_label"] == "Four days"
    assert req["agyari"]["id"] == seeded["agyary_id"]
    assert "family_contact" not in req and "family_message" not in req
    one = await client.get(f"{REQUESTS}/{rid}", headers=panthaky)
    for text in (got.text, one.text):
        _no_family(text)

    # The mobed at the same fire temple is asked too, in the app (Everyone at once, R3.1 step 4),
    # and sees it without the family.
    mobed = await _as(client, MOBED)
    assert (await client.get(f"{REQUESTS}/count", headers=mobed)).json() == {"waiting": 1}
    seen = await client.get(f"{REQUESTS}/{rid}", headers=mobed)
    assert seen.status_code == 200 and "family_contact" not in seen.json()["request"]
    _no_family(seen.text)

    # In Come to me first the mobed is not asked (only the panthaky is): it does not exist for them.
    goti = await db.get(Agyary, seeded["agyary_id"])
    goti.request_mode = "panthaky_first"
    await db.commit()
    _, _, rid2 = await _sent(client, db, seeded["agyary_id"], mgr=mgr)
    assert (await client.get(f"{REQUESTS}/count", headers=mobed)).json() == {"waiting": 1}
    assert [q["id"] for q in (await client.get(REQUESTS, headers=mobed)).json()["waiting"]] == [rid]
    for method, path in (("GET", f"{REQUESTS}/{rid2}"), ("POST", f"{REQUESTS}/{rid2}/answer"),
                         ("POST", f"{REQUESTS}/{rid2}/decline")):
        r = await client.request(method, path, json={}, headers=mobed)
        assert r.status_code == 404, (method, path, r.text)
    assert (await db.get(FuneralRequest, rid2)).status == "waiting"


async def test_the_old_accept_and_call_out_routes_are_gone(client, db, seeded, pushes):
    """R3.1 step 7: the board's actions are the only way to take a request. The
    old Accept, the call-out screen, its hand-picked call-out and "Send the
    details again" are not routes any more: they answer 404 to the confirmed
    panthaky who could use them before, and change nothing."""
    from agyary.api.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert not {p for p in paths if p.endswith("/accept") or "/callout" in p}, paths
    _, _, rid = await _sent(client, db, seeded["agyary_id"])
    panthaky = await _as(client, PANTHAKY)
    callouts = len((await db.execute(select(PrayerCallout))).scalars().all())
    for method, path, body in (("POST", f"{REQUESTS}/{rid}/accept", {"share_contact": True}),
                               ("GET", f"{REQUESTS}/{rid}/callout", None),
                               ("POST", f"{REQUESTS}/{rid}/callout", {"who": ["u2"]}),
                               ("POST", f"{REQUESTS}/{rid}/callout/details-again", None)):
        r = await client.request(method, path, json=body, headers=panthaky)
        assert r.status_code == 404, (method, path, r.text)
    request = await db.get(FuneralRequest, rid, populate_existing=True)
    assert request.status == "waiting" and request.taken_at is None and request.accepted_by_user_id is None
    assert len((await db.execute(select(PrayerCallout))).scalars().all()) == callouts
    assert (await db.execute(select(Notification.id))).first() is None
    assert await _count(db, Customer, Customer.phone == FAMILY) == 0


async def test_one_accepted_the_old_way_reads_as_before_and_its_book_is_the_accepters_only(
    client, db, seeded, pushes,
):
    aid = seeded["agyary_id"]
    # Another mobed at the same fire temple already has the family's number, under their own name for them.
    mobed = await _as(client, MOBED)
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins", json={"name": "Their Own Name", "phone": FAMILY},
                          headers=mobed)
    assert r.status_code == 200, r.text
    theirs = (await db.execute(select(Customer).where(Customer.phone == FAMILY))).scalar_one()
    theirs_before = (theirs.id, theirs.owner_user_id, theirs.name, theirs.reminders_enabled)

    _, rec, rid = await _sent(client, db, aid)
    panthaky_user = await _user(db, PANTHAKY)
    done = await accepted_the_old_way(db, rid, PANTHAKY)
    headers = await _as(client, PANTHAKY)
    req = (await client.get(f"{REQUESTS}/{rid}", headers=headers)).json()["request"]
    assert req["status"] == "accepted" and req["accepted_by_me"] is True
    assert req["family_contact"] == {"name": "Test Family", "phone": FAMILY}
    today = funeral_records.today_ist()
    day = lambda d: f"{d:%a} {d.day} {d:%b}"   # noqa: E731
    assert req["family_message"] == (
        f"Sahebji Test Family, I am Er. Hormuz Dadachanji of {req['agyari']['name']}. Doongerwadi (test) has asked me "
        "to perform the prayers for Behdin Rustom Jamshed. "
        f"The Geh-saarnu is on {day(today)}, Havan geh, and the Uthamna on {day(today + timedelta(days=2))}, 4:00 pm. "
        "Please call or message me here for anything you need. "
        "May the ruvan of Behdin Rustom Jamshed attain Garothman Behesht.")
    assert req["memorial_prefill"] == {
        "name": "Behdin Rustom Jamshed", "calendar": "shenshai", "deathBy": "date",
        "death": rec["death"]["date"], "deathRoj": "", "deathMah": "",
    }
    assert done.created is True and req["customer_id"] == done.customer.id
    assert req["shared_contact"] is True and req["all_set"] is None

    # The accepter's own record: new, under the family contact's name, reminders off.
    mine = await db.get(Customer, done.customer.id)
    assert mine.owner_user_id == panthaky_user.id and mine.phone == FAMILY and mine.name == "Test Family"
    assert mine.reminders_enabled is False and mine.reminders_stopped_at is None
    # The other mobed's record is exactly as it was, and is not the one used.
    await db.refresh(theirs)
    assert (theirs.id, theirs.owner_user_id, theirs.name, theirs.reminders_enabled) == theirs_before
    assert theirs.id != mine.id
    assert await _count(db, Customer, Customer.phone == FAMILY) == 2

    # The Geh-saarnu and the Uthamna on the accepter's calendar, for their own record, at the fire temple.
    events = {e["what"]: e for e in done.events}
    assert set(events) == {"Geh-saarnu", "Uthamna"} and done.skipped == []
    assert events["Geh-saarnu"]["date"] == today.isoformat() and events["Geh-saarnu"]["time"] == "07:00"
    assert events["Uthamna"]["date"] == (today + timedelta(days=2)).isoformat() and events["Uthamna"]["time"] == "16:00"
    assert not events["Uthamna"]["time_guessed"]
    for e in events.values():
        b = await db.get(Booking, e["booking_id"])
        service = await db.get(Service, b.service_id)
        assert service.name == e["what"] and service.agyary_id == aid
        assert b.customer_id == mine.id and b.agyary_id == aid and b.created_by_user_id == panthaky_user.id
        assert b.location == "Doongerwadi (test)" and b.status == "approved"
        assert (await db.execute(select(BookingMobed.user_id).where(BookingMobed.booking_id == b.id))).scalars().all() \
            == [panthaky_user.id]
    # Nothing was put in the other mobed's book.
    assert await _count(db, Booking, Booking.customer_id == theirs.id) == 0
    # The count on the tab is down, and the request is under Earlier.
    assert (await client.get(f"{REQUESTS}/count", headers=headers)).json() == {"waiting": 0}
    lists = (await client.get(REQUESTS, headers=headers)).json()
    assert lists["waiting"] == [] and [q["id"] for q in lists["earlier"]] == [rid]


async def test_an_own_record_is_reused_and_a_stop_is_kept(client, db, seeded, pushes):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins", json={"name": "Known Family", "phone": FAMILY},
                          headers=panthaky)
    known = r.json()["id"]
    _, _, rid = await _sent(client, db, aid)
    done = await accepted_the_old_way(db, rid, PANTHAKY)
    assert done.created is False and done.customer.id == known
    assert (await db.get(Customer, known)).name == "Known Family"   # never renamed by a request
    assert await _count(db, Customer, Customer.phone == FAMILY) == 1

    # A number that replied STOP starts stopped in a new record.
    other = "+919822200044"
    db.add(ReminderOptOut(phone=other, stopped_at=datetime.now(timezone.utc)))
    await db.commit()
    mgr, _ = await manager(client, db, phone="+919911100072", name="Second Manager")
    _, _, rid2 = await _sent(client, db, aid, mgr=mgr, family_contact_phone=other)
    done = await accepted_the_old_way(db, rid2, PANTHAKY, share=False)
    made = await db.get(Customer, done.customer.id)
    assert made.reminders_stopped_at is not None and made.reminders_enabled is False


async def test_the_others_asked_see_who_accepted_it_the_old_way_and_cannot_answer_it(client, db, seeded, pushes):
    temple = await agyari(db, "Two Mobeds Agyari (test)", (18.96, 72.83))
    await member(db, temple, "+919822200011", name="Er. First Mobed")
    await member(db, temple, "+919822200012", name="Er. Second Mobed")
    await db.commit()
    _, _, rid = await _sent(client, db, temple.id)
    await accepted_the_old_way(db, rid, "+919822200011")

    headers = await _as(client, "+919822200012")
    (seen,) = (await client.get(REQUESTS, headers=headers)).json()["earlier"]
    assert seen["status"] == "accepted" and seen["accepted_by"] == "Er. First Mobed" and seen["accepted_by_me"] is False
    assert "family_contact" not in seen and "family_message" not in seen
    page = (await client.get(f"{REQUESTS}/{rid}", headers=headers)).text
    _no_family(page)
    assert "Er. First Mobed" in page
    for path, body in ((f"{REQUESTS}/{rid}/answer", {"answer": "yes"}), (f"{REQUESTS}/{rid}/decline", {})):
        r = await client.post(path, json=body, headers=headers)
        assert r.status_code == 409 and "no longer waiting" in r.json()["detail"], r.text
    row = await db.get(FuneralRequest, rid, populate_existing=True)
    assert row.status == "accepted" and row.accepted_by_user_id == (await _user(db, "+919822200011")).id


async def test_withdrawn_declined_and_accepted_are_refused_in_plain_words(client, db, seeded, pushes):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    mgr, rec, rid = await _sent(client, db, aid)
    assert (await client.post(f"/api/mobed/manager/requests/{rid}/withdraw", headers=mgr)).status_code == 200
    r = await client.post(f"{REQUESTS}/{rid}/decline", json={}, headers=panthaky)
    assert r.status_code == 409
    assert r.json()["detail"] == "Doongerwadi (test) withdrew this request, so nothing more is needed for it."

    # Sent again, and declined with a reason; a reason with a link is refused first.
    r = await client.post(f"{RECORDS}/{rec['id']}/requests", json={"agyary_id": aid, "family_agreed": True},
                          headers=mgr)
    rid2 = r.json()["record"]["requests"][0]["id"]
    r = await client.post(f"{REQUESTS}/{rid2}/decline", json={"reason": "see www.example.com"}, headers=panthaky)
    assert r.status_code == 400 and r.headers["X-Field"] == "reason"
    assert (await db.get(FuneralRequest, rid2)).status == "waiting"
    pushes.clear()
    r = await client.post(f"{REQUESTS}/{rid2}/decline", json={"reason": "  No mobed free that day "}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert r.json()["request"]["status"] == "declined" and r.json()["request"]["decline_reason"] == "No mobed free that day"
    row = await db.get(FuneralRequest, rid2)
    assert row.decline_reason == "No mobed free that day" and row.decided_at is not None
    assert row.accepted_by_user_id is None and row.accepter_shared_contact is None
    r = await client.post(f"{REQUESTS}/{rid2}/decline", json={}, headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == "You have already declined this request."
    # The manager is told, with the reason, and can send it elsewhere.
    (note,) = (await db.execute(select(AppNotification).where(AppNotification.kind == "funeral_request_declined"))
               ).scalars().all()
    assert ": No mobed free that day. You can send it to another fire temple." in note.body
    assert note.link == f"#/manager/record/{rec['id']}"
    (push,) = pushes
    assert push["title"] == "A request was declined" and push["url"] == f"/mobed#/manager/record/{rec['id']}"
    for text in (note.title, note.body, push["title"], push["body"]):
        _no_family(text)
    got = (await client.get(f"{RECORDS}/{rec['id']}", headers=mgr)).json()["record"]
    assert got["may_send"] is True and got["requests"][0]["decline_reason"] == "No mobed free that day"

    # Accepted the old way, then declined: refused.
    _, _, rid3 = await _sent(client, db, aid, mgr=mgr)
    await accepted_the_old_way(db, rid3, PANTHAKY, book=False)
    r = await client.post(f"{REQUESTS}/{rid3}/decline", json={}, headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == "You have already accepted this request."
    assert (await db.get(FuneralRequest, rid3, populate_existing=True)).status == "accepted"


async def test_the_manager_sees_the_accepters_number_only_with_the_tick(client, db, seeded, pushes):
    aid = seeded["agyary_id"]
    mgr, shared, rid = await _sent(client, db, aid)
    _, kept, rid2 = await _sent(client, db, aid, mgr=mgr, departed_name="Dinshaw")
    await accepted_the_old_way(db, rid, PANTHAKY, share=True, book=False)
    await accepted_the_old_way(db, rid2, PANTHAKY, share=False, book=False)

    q = (await client.get(f"{RECORDS}/{shared['id']}", headers=mgr)).json()["record"]["requests"][0]
    assert q["accepted_by"] == "Er. Hormuz Dadachanji" and q["accepter_phone"] == PANTHAKY
    assert q["agyari"]["id"] == aid
    q = (await client.get(f"{RECORDS}/{kept['id']}", headers=mgr)).json()["record"]["requests"][0]
    assert q["accepted_by"] == "Er. Hormuz Dadachanji" and q["accepter_phone"] is None
    assert (await db.get(FuneralRequest, rid2)).accepter_shared_contact is False


async def test_the_memorial_saved_from_it_is_noted_on_it_for_the_accepter_only(client, db, seeded, pushes):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    mgr, rec, rid = await _sent(client, db, aid)
    done = await accepted_the_old_way(db, rid, PANTHAKY)
    baaj = (await db.execute(select(Service.id).where(Service.agyary_id == aid, Service.name == "Baaj"))).scalar_one()
    memorial = {"departed_name": "Behdin Rustom Jamshed", "death_date": rec["death"]["date"], "calendar": "shenshai",
                "day_counts": [30], "service_ids": [baaj], "funeral_request_id": rid}
    # Another mobed's memorial cannot be pinned to it.
    mobed = await _as(client, MOBED)
    other = (await client.post(f"/api/mobed/agyaries/{aid}/behdins", json={"name": "Someone", "phone": "+919822200055"},
                               headers=mobed)).json()
    other_id = other["id"]
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{other_id}/memorials", json=memorial, headers=mobed)
    assert r.status_code == 200, r.text
    assert (await db.get(FuneralRequest, rid)).memorial_id is None
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{done.customer.id}/memorials", json=memorial,
                          headers=panthaky)
    assert r.status_code == 200, r.text
    row = await db.get(FuneralRequest, rid)
    await db.refresh(row)
    assert row.memorial_id == r.json()["id"]
    assert (await db.get(Memorial, row.memorial_id)).created_by_user_id == (await _user(db, PANTHAKY)).id
    seen = (await client.get(f"{REQUESTS}/{rid}", headers=panthaky)).json()["request"]
    assert seen["memorial_id"] == row.memorial_id
    # The manager is never given it.
    assert "memorial" not in (await client.get(f"{RECORDS}/{rec['id']}", headers=mgr)).text


async def test_a_record_by_roj_and_mah_fills_the_memorial_form_so_and_an_uthamna_without_time_is_said(
    client, db, seeded, pushes,
):
    aid = seeded["agyary_id"]
    today = funeral_records.today_ist()
    death = funeral_records.death_day(calendar="shenshai", death_date=today - timedelta(days=1), roj=None, mah=None,
                                      year=None)
    _, _, rid = await _sent(client, db, aid, death_date=None, death_roj=death.roj, death_mah=death.mah,
                            uthamna_time=None, geh_saarnu_date=None, geh_saarnu_geh=None)
    done = await accepted_the_old_way(db, rid, PANTHAKY)
    req = (await client.get(f"{REQUESTS}/{rid}", headers=await _as(client, PANTHAKY))).json()["request"]
    pre = req["memorial_prefill"]
    assert pre["deathBy"] == "parsi" and pre["death"] == ""
    assert (pre["deathRoj"], pre["deathMah"]) == (str(death.roj), str(death.mah))
    assert [e["what"] for e in done.events] == ["Uthamna"]
    assert done.events[0]["time"] == "15:30" and done.events[0]["time_guessed"] is True
    assert [s["what"] for s in done.skipped] == ["Geh-saarnu"]


async def test_a_manager_cannot_reach_the_requests_and_a_mobed_none_of_the_managers_side(client, db, seeded, pushes):
    mgr, rec, rid = await _sent(client, db, seeded["agyary_id"])
    for method, path in (("GET", REQUESTS), ("GET", f"{REQUESTS}/count"), ("GET", f"{REQUESTS}/{rid}"),
                         ("POST", f"{REQUESTS}/{rid}/answer"), ("POST", f"{REQUESTS}/{rid}/decline")):
        r = await client.request(method, path, json={}, headers=mgr)
        assert r.status_code == 403 and r.json()["detail"] == mobed_routes.NOT_FOR_MANAGERS, (method, path)
    from tests.test_funeral_managers import MANAGER_MAY

    panthaky = await _as(client, PANTHAKY)
    manager_side = sorted(c for c in MANAGER_MAY if c[1].startswith("/api/mobed/manager/"))
    assert len(manager_side) >= 10
    for method, path in manager_side:
        url = path.replace("{record_id}", str(rec["id"])).replace("{request_id}", str(rid))
        r = await client.request(method, url, json={}, headers=panthaky)
        assert r.status_code == 403 and r.json()["detail"] == mobed_routes.NOT_FOR_MOBEDS, (method, path)
    # And an account that is not on gets nothing.
    await db.execute(update(User).where(User.phone == PANTHAKY).values(access="off"))
    await db.commit()
    assert (await client.get(REQUESTS, headers=panthaky)).status_code == 403


async def _count(db, model, *where) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


def test_the_family_message_leaves_out_what_is_not_known():
    """Owner, 19 Nov 2026: it ends with the wish of the family's template, and a
    day the record does not have is simply not mentioned."""
    from types import SimpleNamespace as NS

    from agyary.services.funeral_answers import family_message

    record = NS(departed_title="khud", departed_name="Rustom", departed_parent_name=None, family_contact_name="Test Family",
                geh_saarnu_date=None, geh_saarnu_geh=None, uthamna_date=None, uthamna_time=None)
    words = family_message(record, NS(name="Doongerwadi (test)"), NS(name="Goti Adarian"), NS(name="Er. Test"))
    assert words == ("Sahebji Test Family, I am Er. Test of Goti Adarian. Doongerwadi (test) has asked me to perform "
                     "the prayers for Khud Rustom. Please call or message me here for anything you need. "
                     "May the ruvan of Khud Rustom attain Garothman Behesht.")
    assert "Our prayers" not in words and "Geh-saarnu" not in words
