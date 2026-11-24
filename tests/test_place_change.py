"""A Doongerwadi manager asks to change their place; the admin approves (owner, 24 Nov 2026).

Nothing changes until the admin approves: a place's family records are private (D2, D10).
Approving moves the manager's link in one transaction, the old place's records stay with it,
and both sides are told in the app and by phone.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agyary.api.routes import mobed as mobed_routes
from agyary.core import config
from agyary.models import AppNotification, FuneralPlaceManager, PlaceChangeRequest, User
from tests.conftest import sign_in
from tests.funeral_helpers import auth, form, manager, place

ASK = "/api/mobed/manager/place-change"
ADMIN = "/api/mobed/admin/place-changes"
ADMIN_PHONE = "+919800000001"   # the seeded fire temple's panthaky, made the admin


@pytest.fixture
def pushes(monkeypatch):
    sent = []

    async def capture(db, settings, user_ids, **kw):
        sent.append({"to": sorted(user_ids), **kw})
        return 0

    from agyary.services import web_push

    monkeypatch.setattr(web_push, "send_to_users", capture)
    return sent


@pytest.fixture
def admin(monkeypatch, seeded):
    monkeypatch.setenv("ADMIN_PHONES", ADMIN_PHONE)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def _admin_headers(client):
    return auth(await sign_in(client, ADMIN_PHONE))


async def _notes(db, user_id, kind):
    return list((await db.execute(
        select(AppNotification).where(AppNotification.user_id == user_id, AppNotification.kind == kind)
    )).scalars().all())


async def _uid(db, phone):
    return (await db.execute(select(User.id).where(User.phone == phone))).scalar_one()


async def _setup(client, db):
    headers, old = await manager(client, db)
    new = await place(db, "Prayer hall (new)", kind="prayer_hall")
    await db.commit()
    return headers, old, new


async def test_only_a_manager_can_ask(client, db, seeded, admin):
    _, _, new = await _setup(client, db)
    mobed = auth(await sign_in(client, seeded["mobed_phone"]))
    for call in (client.post(ASK, json={"to_place_id": new.id}, headers=mobed),
                 client.delete(ASK, headers=mobed), client.get(ASK + "/places", headers=mobed)):
        r = await call
        assert r.status_code == 403 and r.json()["detail"] == mobed_routes.NOT_FOR_MOBEDS
    # An admin is not a manager either.
    r = await client.post(ASK, json={"to_place_id": new.id}, headers=await _admin_headers(client))
    assert r.status_code == 403


async def test_a_manager_asks_for_an_active_other_place_and_is_told_what_waits(client, db, seeded, admin, pushes):
    headers, old, new = await _setup(client, db)
    off = await place(db, "Switched off (test)")
    off.is_active = False
    await db.commit()
    listed = (await client.get(ASK + "/places", headers=headers)).json()["places"]
    assert [p["id"] for p in listed] == [new.id]          # not their own, not a turned-off one
    for bad in (old.id, off.id, 999999):
        assert (await client.post(ASK, json={"to_place_id": bad}, headers=headers)).status_code in (404, 409)
    r = await client.post(ASK, json={"to_place_id": new.id}, headers=headers)
    assert r.status_code == 200 and r.json()["place_change"]["to_place"]["id"] == new.id
    shown = (await client.get("/api/mobed/manager/place", headers=headers)).json()
    assert shown["place_change"]["to_place"]["name"] == "Prayer hall (new)"
    assert [p["id"] for p in shown["places"]] == [old.id]   # nothing changed yet
    # The admin is told in the app and on the phone.
    admin_id = await _uid(db, ADMIN_PHONE)
    [note] = await _notes(db, admin_id, "place_change_request")
    assert "Prayer hall (new)" in note.body and note.link == "#/admin/funeral-places"
    assert [p["to"] for p in pushes] == [[admin_id]] and pushes[0]["tag"] == "place-change-request"


async def test_one_pending_at_a_time_until_taken_back(client, db, seeded, admin):
    headers, old, new = await _setup(client, db)
    other = await place(db, "Aramgah (other)", kind="aramgah")
    await db.commit()
    assert (await client.post(ASK, json={"to_place_id": new.id}, headers=headers)).status_code == 200
    r = await client.post(ASK, json={"to_place_id": other.id}, headers=headers)
    assert r.status_code == 409 and "take that request back" in r.json()["detail"]
    assert (await client.delete(ASK, headers=headers)).status_code == 200
    assert (await client.get("/api/mobed/manager/place", headers=headers)).json()["place_change"] is None
    assert (await client.delete(ASK, headers=headers)).status_code == 409      # nothing left to take back
    assert (await client.post(ASK, json={"to_place_id": other.id}, headers=headers)).status_code == 200
    statuses = (await db.execute(select(PlaceChangeRequest.status).order_by(PlaceChangeRequest.id))).scalars().all()
    assert statuses == ["cancelled", "pending"]


async def test_only_the_admin_decides(client, db, seeded, admin):
    headers, _, new = await _setup(client, db)
    await client.post(ASK, json={"to_place_id": new.id}, headers=headers)
    rid = (await db.execute(select(PlaceChangeRequest.id))).scalar_one()
    mobed = auth(await sign_in(client, seeded["mobed_phone"]))
    for who in (headers, mobed):
        for path in (ADMIN, f"{ADMIN}/{rid}/approve", f"{ADMIN}/{rid}/decline"):
            r = (await client.get(path, headers=who)) if path == ADMIN else await client.post(path, json={}, headers=who)
            assert r.status_code == 404 and r.json()["detail"] == "This page could not be found."
    listed = (await client.get(ADMIN, headers=await _admin_headers(client))).json()["requests"]
    assert [(r["manager"]["name"], r["from_place"]["name"], r["to_place"]["name"]) for r in listed] == [
        ("Test Manager", "Doongerwadi (test)", "Prayer hall (new)")]


async def test_approving_moves_the_link_and_the_records_stay_with_the_old_place(client, db, seeded, admin, pushes):
    headers, old, new = await _setup(client, db)
    made = await client.post("/api/mobed/manager/records", json=form(), headers=headers)
    assert made.status_code == 200, made.text
    record_id = made.json()["record"]["id"]
    await client.post(ASK, json={"to_place_id": new.id}, headers=headers)
    rid = (await db.execute(select(PlaceChangeRequest.id))).scalar_one()
    pushes.clear()
    ahead = await _admin_headers(client)
    r = await client.post(f"{ADMIN}/{rid}/approve", json={}, headers=ahead)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    # Their next screen shows the new place; the old place's records are out of reach, nothing deleted.
    shown = (await client.get("/api/mobed/manager/place", headers=headers)).json()
    assert [p["id"] for p in shown["places"]] == [new.id] and shown["place_change"] is None
    me = (await client.get("/api/mobed/auth/me", headers=headers)).json()
    assert [p["id"] for p in me["funeral_places"]] == [new.id]
    assert (await client.get("/api/mobed/manager/records", headers=headers)).json()["records"] == []
    assert (await client.get(f"/api/mobed/manager/records/{record_id}", headers=headers)).status_code == 404
    # The new place's records are reachable.
    assert (await client.post("/api/mobed/manager/records", json=form(), headers=headers)).status_code == 200
    assert len((await client.get("/api/mobed/manager/records", headers=headers)).json()["records"]) == 1
    links = {(k.funeral_place_id, k.is_active) for k in (await db.execute(select(FuneralPlaceManager))).scalars()}
    assert links == {(old.id, False), (new.id, True)}
    # Told, in the app and by phone.
    manager_id = await _uid(db, "+919911100071")
    [note] = await _notes(db, manager_id, "place_change_decision")
    assert "Prayer hall (new)" in note.title
    assert [p["to"] for p in pushes] == [[manager_id]]
    # A second approve, or a decline after it, is a plain refusal.
    for verb in ("approve", "decline"):
        again = await client.post(f"{ADMIN}/{rid}/{verb}", json={}, headers=ahead)
        assert again.status_code == 409 and "already" in again.json()["detail"]
    assert (await client.post(f"{ADMIN}/999999/approve", json={}, headers=ahead)).status_code == 404


async def test_declining_changes_nothing_and_tells_the_manager(client, db, seeded, admin, pushes):
    headers, old, new = await _setup(client, db)
    await client.post(ASK, json={"to_place_id": new.id}, headers=headers)
    rid = (await db.execute(select(PlaceChangeRequest.id))).scalar_one()
    pushes.clear()
    r = await client.post(f"{ADMIN}/{rid}/decline", json={}, headers=await _admin_headers(client))
    assert r.status_code == 200 and r.json()["status"] == "declined"
    assert [p["id"] for p in (await client.get("/api/mobed/manager/place", headers=headers)).json()["places"]] == [old.id]
    manager_id = await _uid(db, "+919911100071")
    [note] = await _notes(db, manager_id, "place_change_decision")
    assert note.title == "The admin has not moved you to Prayer hall (new)"
    assert [p["to"] for p in pushes] == [[manager_id]]
    # And they may ask again.
    assert (await client.post(ASK, json={"to_place_id": new.id}, headers=headers)).status_code == 200


async def test_a_request_cannot_be_approved_once_the_place_or_manager_is_gone(client, db, seeded, admin):
    headers, _, new = await _setup(client, db)
    await client.post(ASK, json={"to_place_id": new.id}, headers=headers)
    rid = (await db.execute(select(PlaceChangeRequest.id))).scalar_one()
    ahead = await _admin_headers(client)
    new.is_active = False
    await db.commit()
    r = await client.post(f"{ADMIN}/{rid}/approve", json={}, headers=ahead)
    assert r.status_code == 409 and "turned off" in r.json()["detail"]
    new.is_active = True
    boss = (await db.execute(select(User).where(User.phone == "+919911100071"))).scalar_one()
    boss.is_active = False
    await db.commit()
    r = await client.post(f"{ADMIN}/{rid}/approve", json={}, headers=ahead)
    assert r.status_code == 409 and "no longer in use" in r.json()["detail"]
    assert (await db.execute(select(PlaceChangeRequest.status))).scalar_one() == "pending"


async def test_deleting_the_account_removes_its_requests(client, db, seeded, admin):
    headers, _, new = await _setup(client, db)
    await client.post(ASK, json={"to_place_id": new.id}, headers=headers)
    assert (await client.post("/api/mobed/auth/account/delete", json={"confirm": True}, headers=headers)).status_code == 200
    db.expire_all()
    assert (await db.execute(select(PlaceChangeRequest))).scalars().all() == []
