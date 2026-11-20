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
    assert {name: m["phone"] for name, m in app.items()} == {
        "Er. Hormuz Dadachanji": PANTHAKY, "Er. Pervez Kias": MOBED, "Er. Switched Off": OFF,
        "Er. Waiting": WAITING, "Er. Stopped": STOPPED,
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
        **{name: m["phone"] for name, m in app.items()}, "Er. Listed": LISTED}
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
        "Er. Other Panthaky": OTHER_PANTHAKY, "Er. Other Mobed": OTHER_MOBED, "Er. Other Listed": OTHER_LISTED}
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

    # The panthaky's call-out screen lists the app mobeds without their numbers.
    panthaky = await _as(client, PANTHAKY)
    view = await client.get(f"/api/mobed/requests/{rid}/callout", headers=panthaky)
    assert view.status_code == 200, view.text
    app = [c for c in view.json()["candidates"] if c["kind"] == "app"]
    assert {c["name"] for c in app} >= {"Er. Pervez Kias", "Er. Switched Off", "Er. Waiting", "Er. Stopped"}
    assert all(c["phone"] is None for c in app)

    # Nor do the requests, for the panthaky or a mobed there, or the manager's record.
    seen = [(PANTHAKY, path, await client.get(path, headers=panthaky))
            for path in ("/api/mobed/requests", f"/api/mobed/requests/{rid}", f"/api/mobed/requests/{rid}/callout")]
    mobed = await _as(client, MOBED)
    seen += [(MOBED, path, await client.get(path, headers=mobed))
             for path in ("/api/mobed/requests", f"/api/mobed/requests/{rid}", f"/api/mobed/requests/{rid}/callout")]
    seen += [("manager", path, await client.get(path, headers=mgr))
             for path in (f"{RECORDS}/{rec['id']}", f"{RECORDS}/{rec['id']}/agyaries")]
    for who, path, r in seen:
        assert r.status_code in (200, 404), (who, path, r.text)
        for number in APP_NUMBERS:
            if number != who:
                assert number not in r.text, (who, path, number)
    assert (await db.execute(select(Notification.id))).first() is None
