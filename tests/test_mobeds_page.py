"""The Mobeds page in the panthaky's diary (DECISIONS D10, changed 21 Nov 2026;
R3.1 step 3; "Our mobeds" before).

It lists the fire temple's mobeds in the app, now with their own numbers (owner,
21 Nov 2026), so the panthaky can call them or open a WhatsApp chat from their
own phone, and the mobeds a panthaky added by hand. A mobed switched off,
waiting for approval or who replied STOP is still listed, with the reason and
the number. Only that fire temple's confirmed panthakys and the admin reach the
page: a mobed there, a mobed who only said they are the panthaky, another fire
temple's panthaky and a panthaky whose access is off get nothing, and a
Doongerwadi manager is refused as everywhere in the mobed app. The app mobeds'
numbers are on this page only: the call-out screen, the requests and the
manager's record carry none of them. Mobeds of other fire temples never appear.
Nothing here sends anything.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, update

from agyary.api.routes import mobed as mobed_routes
from agyary.api.routes.callouts import NO_LIST
from agyary.core import config
from agyary.models import Agyary, AgyaryMobedContact, AgyaryUser, Notification, ReminderOptOut
from tests.conftest import sign_in
from tests.funeral_helpers import agyari, auth, form, manager, member

RECORDS = "/api/mobed/manager/records"
PANTHAKY, MOBED, ADMIN = "+919800000001", "+919800000002", "+919800000003"
OFF, WAITING, STOPPED, LISTED, LEFT = (
    "+919822200301", "+919822200302", "+919822200303", "+919822200304", "+919822200305")
CLAIMED, OFF_PANTHAKY = "+919822200311", "+919822200312"
OTHER_PANTHAKY, OTHER_MOBED, OTHER_LISTED = "+919822200321", "+919822200322", "+919822200323"
# The seeded fire temple's app mobeds other than its panthaky, whose number is
# also the fire temple's own contact number (tests/seed_demo.py).
APP_NUMBERS = (MOBED, OFF, WAITING, STOPPED)


def _page(aid) -> str:
    return f"/api/mobed/agyaries/{aid}/our-mobeds"


async def _as(client, phone, name="Er. Test Mobed"):
    return auth(await sign_in(client, phone, name))


@pytest.fixture
def admin_phone(monkeypatch):
    monkeypatch.setenv("ADMIN_PHONES", ADMIN)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def _people(client, db, aid) -> dict:
    """The seeded fire temple with a mobed switched off, one waiting, one who
    replied STOP, one who left, and one added by hand; and another fire temple
    with its own panthaky, mobed and mobed added by hand."""
    temple = await db.get(Agyary, aid)
    await member(db, temple, OFF, access="off", name="Er. Switched Off")
    await member(db, temple, WAITING, access="pending", name="Er. Waiting")
    await member(db, temple, STOPPED, name="Er. Stopped")
    left = await member(db, temple, LEFT, name="Er. Left")
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == left.id).values(is_active=False))
    db.add(ReminderOptOut(phone=STOPPED, stopped_at=datetime.now(timezone.utc)))
    other = await agyari(db, "Other Agyari (test)", None)
    await member(db, other, OTHER_PANTHAKY, "panthaky", name="Er. Other Panthaky")
    await member(db, other, OTHER_MOBED, name="Er. Other Mobed")
    await db.commit()
    r = await client.post(_page(aid), json={"name": "Er. Listed", "phone": LISTED, "agreed": True},
                          headers=await _as(client, PANTHAKY))
    assert r.status_code == 200, r.text
    r = await client.post(_page(other.id), json={"name": "Er. Other Listed", "phone": OTHER_LISTED, "agreed": True},
                          headers=await _as(client, OTHER_PANTHAKY))
    assert r.status_code == 200, r.text
    return {"other": other.id, "contact": next(m["id"] for m in r.json()["mobeds"] if m["kind"] == "contact"),
            "listed": (await db.execute(select(AgyaryMobedContact.id).where(
                AgyaryMobedContact.agyary_id == aid, AgyaryMobedContact.phone == LISTED))).scalar_one()}


async def test_a_confirmed_panthaky_and_the_admin_see_every_app_mobed_with_their_number(
        client, db, seeded, admin_phone):
    aid = seeded["agyary_id"]
    await _people(client, db, aid)
    r = await client.get(_page(aid), headers=await _as(client, PANTHAKY))
    assert r.status_code == 200, r.text
    page = r.json()
    app = {m["name"]: m for m in page["mobeds"] if m["kind"] == "app"}
    # Approved mobeds' numbers only: not one waiting for the admin, nor the panthaky's own.
    assert {name: m["phone"] for name, m in app.items()} == {
        "Er. Hormuz Dadachanji": None, "Er. Pervez Kias": MOBED, "Er. Switched Off": OFF,
        "Er. Waiting": None, "Er. Stopped": STOPPED,
    }
    assert app["Er. Hormuz Dadachanji"]["is_me"] and app["Er. Hormuz Dadachanji"]["why_not"] == "this is you"
    assert app["Er. Pervez Kias"]["can_message"] and app["Er. Pervez Kias"]["why_not"] is None
    # Off, waiting or STOP: listed with the reason (and the number, to call them).
    assert app["Er. Switched Off"]["why_not"] == "their Mobed Diary access is switched off"
    assert app["Er. Waiting"]["why_not"] == "they are waiting for the admin's approval"
    assert app["Er. Stopped"]["stopped"] and not app["Er. Stopped"]["can_message"]
    added = [(m["name"], m["phone"]) for m in page["mobeds"] if m["kind"] == "contact"]
    assert added == [("Er. Listed", LISTED)]

    # The admin sees the same, without being at that fire temple.
    r = await client.get(_page(aid), headers=await _as(client, ADMIN, "Test Admin"))
    assert r.status_code == 200, r.text
    assert {m["name"]: m["phone"] for m in r.json()["mobeds"]} == {
        **{name: m["phone"] for name, m in app.items()}, "Er. Hormuz Dadachanji": PANTHAKY, "Er. Listed": LISTED}
    assert not any(m["is_me"] for m in r.json()["mobeds"])
    # Nothing is sent by any of it.
    assert (await db.execute(select(Notification.id))).first() is None


async def test_nobody_else_reaches_the_page(client, db, seeded):
    aid = seeded["agyary_id"]
    ids = await _people(client, db, aid)
    temple = await db.get(Agyary, aid)
    claimant = await member(db, temple, CLAIMED, name="Er. Says Panthaky")
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == claimant.id)
                     .values(claimed_role="panthaky", claimed_at=datetime.now(timezone.utc)))
    await member(db, temple, OFF_PANTHAKY, "panthaky", access="off", name="Er. Panthaky Switched Off")
    await db.commit()
    tries = (("GET", _page(aid), None),
             ("POST", _page(aid), {"name": "Er. Sneaked In", "phone": OTHER_LISTED, "agreed": True}),
             ("DELETE", f"{_page(aid)}/{ids['listed']}", None))

    # A mobed there, a mobed who only said they are the panthaky, another fire
    # temple's panthaky: as if the page did not exist.
    for phone in (MOBED, CLAIMED, OTHER_PANTHAKY):
        headers = await _as(client, phone)
        for method, path, body in tries:
            r = await client.request(method, path, json=body, headers=headers)
            assert r.status_code == 404 and r.json() == {"detail": NO_LIST}, (phone, method, r.text)
    # A confirmed panthaky whose access is off (D9), and a Doongerwadi manager.
    off = await _as(client, OFF_PANTHAKY)
    mgr, _ = await manager(client, db)
    for method, path, body in tries:
        r = await client.request(method, path, json=body, headers=off)
        assert r.status_code == 403, (method, r.text)
        r = await client.request(method, path, json=body, headers=mgr)
        assert r.status_code == 403 and r.json()["detail"] == mobed_routes.NOT_FOR_MANAGERS, (method, r.text)
        assert not any(n in r.text for n in APP_NUMBERS)

    # Nothing was added or taken off.
    r = await client.get(_page(aid), headers=await _as(client, PANTHAKY))
    assert [(m["name"], m["phone"]) for m in r.json()["mobeds"] if m["kind"] == "contact"] == [("Er. Listed", LISTED)]


async def test_mobeds_of_other_fire_temples_never_appear(client, db, seeded):
    aid = seeded["agyary_id"]
    ids = await _people(client, db, aid)
    page = (await client.get(_page(aid), headers=await _as(client, PANTHAKY))).json()
    for phone in (OTHER_PANTHAKY, OTHER_MOBED, OTHER_LISTED, LEFT):
        assert phone not in json.dumps(page), phone
    assert not {"Er. Other Panthaky", "Er. Other Mobed", "Er. Other Listed", "Er. Left"} \
        & {m["name"] for m in page["mobeds"]}

    # And the other way round: the other fire temple's panthaky sees only theirs.
    page = (await client.get(_page(ids["other"]), headers=await _as(client, OTHER_PANTHAKY))).json()
    assert {m["name"]: m["phone"] for m in page["mobeds"]} == {
        "Er. Other Panthaky": None, "Er. Other Mobed": OTHER_MOBED, "Er. Other Listed": OTHER_LISTED}
    # Nor can one fire temple's panthaky take a mobed off another's list.
    r = await client.delete(f"{_page(aid)}/{ids['contact']}", headers=await _as(client, PANTHAKY))
    assert r.status_code == 404
    page = (await client.get(_page(ids["other"]), headers=await _as(client, OTHER_PANTHAKY))).json()
    assert "Er. Other Listed" in {m["name"] for m in page["mobeds"]}


async def test_no_other_screen_gives_out_the_app_mobeds_numbers(client, db, seeded):
    aid = seeded["agyary_id"]
    await _people(client, db, aid)
    mgr, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(), headers=mgr)).json()["record"]
    r = await client.post(f"{RECORDS}/{rec['id']}/requests", headers=mgr,
                          json={"agyary_id": aid, "family_agreed": True, "family_whatsapp_agreed": True})
    assert r.status_code == 200, r.text
    rid = r.json()["record"]["requests"][0]["id"]

    # The requests do not, for the panthaky or a mobed there, nor the manager's record. (The
    # old call-out screen is gone since R3.1 step 7; the board shows numbers only to the
    # panthakys the request reached and the admin, tests/test_prayer_board.py.)
    panthaky = await _as(client, PANTHAKY)
    seen = [(PANTHAKY, path, await client.get(path, headers=panthaky))
            for path in ("/api/mobed/requests", f"/api/mobed/requests/{rid}")]
    mobed = await _as(client, MOBED)
    seen += [(MOBED, path, await client.get(path, headers=mobed))
             for path in ("/api/mobed/requests", f"/api/mobed/requests/{rid}", f"/api/mobed/requests/{rid}/board")]
    seen += [("manager", path, await client.get(path, headers=mgr))
             for path in (f"{RECORDS}/{rec['id']}", f"{RECORDS}/{rec['id']}/agyaries")]
    for who, path, r in seen:
        assert r.status_code in (200, 404), (who, path, r.text)
        for number in APP_NUMBERS:
            if number != who:
                assert number not in r.text, (who, path, number)
    assert (await db.execute(select(Notification.id))).first() is None


async def test_the_pen_renames_a_mobed_and_a_new_number_needs_the_tick(client, db, seeded):
    """The pen on a mobed added by hand (owner, 24 Nov 2026): the same number only renames;
    a new number is a different person's, so it needs the tick, takes the old entry off the
    list and adds the new one; another fire temple's panthaky cannot touch it."""
    aid = seeded["agyary_id"]
    ids = await _people(client, db, aid)
    panthaky = await _as(client, PANTHAKY)
    path = f"{_page(aid)}/{ids['listed']}"
    NEW = "+919822200331"

    r = await client.put(path, json={"name": "Er. Renamed", "phone": LISTED, "agreed": False}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert [(m["name"], m["phone"]) for m in r.json()["mobeds"] if m["kind"] == "contact"] == [("Er. Renamed", LISTED)]

    r = await client.put(path, json={"name": "", "phone": LISTED, "agreed": False}, headers=panthaky)
    assert r.status_code == 400 and r.headers.get("x-field") == "name"

    # A new number without the tick changes nothing.
    r = await client.put(path, json={"name": "Er. Renamed", "phone": NEW, "agreed": False}, headers=panthaky)
    assert r.status_code == 400 and r.headers.get("x-field") == "agreed"
    row = await db.get(AgyaryMobedContact, ids["listed"])
    await db.refresh(row)
    assert row.is_active and row.phone == LISTED

    # A number already on the list is refused, and the old entry stays.
    r = await client.put(path, json={"name": "Er. Renamed", "phone": MOBED, "agreed": True}, headers=panthaky)
    assert r.status_code == 409 and r.headers.get("x-field") == "phone"
    await db.refresh(row)
    assert row.is_active

    r = await client.put(path, json={"name": "Er. Renamed", "phone": NEW, "agreed": True}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert [(m["name"], m["phone"]) for m in r.json()["mobeds"] if m["kind"] == "contact"] == [("Er. Renamed", NEW)]
    await db.refresh(row)
    assert not row.is_active   # kept, turned off (D8)

    # Another fire temple's panthaky, and a plain mobed, get the same 404 as for a list that is not there.
    other = await _as(client, OTHER_PANTHAKY)
    r = await client.put(path, json={"name": "X", "phone": NEW, "agreed": True}, headers=other)
    assert r.status_code == 404
    r = await client.put(path, json={"name": "X", "phone": NEW, "agreed": True}, headers=await _as(client, MOBED))
    assert r.status_code == 404
    assert (await db.execute(select(Notification.id))).first() is None


async def test_the_panthaky_turns_whatsapp_back_on_for_a_number_that_replied_stop(client, db, seeded):
    """"The behdin can stop, but once the panthaky starts it, it starts again" (owner, 24 Nov 2026):
    the Mobeds page's Turn WhatsApp back on clears the number's STOP; only a confirmed panthaky of
    that fire temple reaches it, and only for someone on its list."""
    aid = seeded["agyary_id"]
    ids = await _people(client, db, aid)
    panthaky = await _as(client, PANTHAKY)
    page = (await client.get(_page(aid), headers=panthaky)).json()
    stopped = next(m for m in page["mobeds"] if m["name"] == "Er. Stopped")
    assert stopped["stopped"] and stopped["key"].startswith("u")
    start = f"{_page(aid)}/{stopped['key']}/start"

    # A plain mobed there, and another fire temple's panthaky, get the 404 of a list that is not there.
    assert (await client.post(start, headers=await _as(client, MOBED))).status_code == 404
    assert (await client.post(start, headers=await _as(client, OTHER_PANTHAKY))).status_code == 404

    r = await client.post(start, headers=panthaky)
    assert r.status_code == 200, r.text
    assert "Er. Stopped" in r.json()["done"]["message"]
    now_stopped = {m["name"]: m["stopped"] for m in r.json()["mobeds"]}
    assert now_stopped["Er. Stopped"] is False
    assert (await db.get(ReminderOptOut, STOPPED)) is None

    # Not stopped any more: nothing to start. A key that is not on this list: 404.
    assert (await client.post(start, headers=panthaky)).status_code == 400
    assert (await client.post(f"{_page(aid)}/c{ids['contact']}/start", headers=panthaky)).status_code == 404
    assert (await client.post(f"{_page(aid)}/zz/start", headers=panthaky)).status_code == 404
    # One added by hand, who replied STOP, can be started again the same way.
    db.add(ReminderOptOut(phone=LISTED, stopped_at=datetime.now(timezone.utc)))
    await db.commit()
    r = await client.post(f"{_page(aid)}/c{ids['listed']}/start", headers=panthaky)
    assert r.status_code == 200, r.text
    assert (await db.get(ReminderOptOut, LISTED)) is None
    assert (await db.execute(select(Notification.id))).first() is None   # nothing is sent by it


async def test_the_panthakys_they_asked_me_to_clears_the_numbers_stop_and_a_plain_mobeds_does_not(
        client, db, seeded):
    from agyary.services import reminders

    aid = seeded["agyary_id"]
    BEHDIN = "+919822200341"
    for who, lifts in ((PANTHAKY, True), (MOBED, False)):
        headers = await _as(client, who)
        made = await client.post(f"/api/mobed/agyaries/{aid}/behdins", json={"name": "Test Behdin", "phone": BEHDIN},
                                 headers=headers)
        assert made.status_code == 200, made.text
        url = f"/api/mobed/agyaries/{aid}/behdins/{made.json()['id']}/reminders"
        await reminders.record_stop(db, BEHDIN)
        await db.commit()
        r = await client.put(url, json={"enabled": True, "confirm_restart": True}, headers=headers)
        assert r.status_code == 200, r.text
        db.expire_all()
        assert ((await db.get(ReminderOptOut, BEHDIN)) is None) is lifts, who
