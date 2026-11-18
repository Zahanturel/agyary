"""The admin acts for one Doongerwadi or prayer hall ("Act for this place",
owner, 18 Nov 2026), to show and try the manager's side without a manager's
account of their own.

With ``?act_for=<place id>`` an admin is that one place's manager for the call:
the same routes, checks and limits, recorded in the admin's own name, and seen
by the place's real managers. Nobody else gets in: an admin who names no place,
a place that is unknown or turned off, a mobed who is not an admin, and a
manager naming any place are refused, and acting for one place shows nothing
of another. The answers come back to the admin who sent the request.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from agyary.api.routes import funeral as funeral_routes
from agyary.api.routes import mobed as mobed_routes
from agyary.core import config
from agyary.models import Agyary, AppNotification, FuneralRecord, FuneralRequest, User
from agyary.services import funeral_answers
from tests.conftest import sign_in
from tests.funeral_helpers import MUMBAI, auth, form, manager, place

MANAGER = "/api/mobed/manager"
RECORDS = f"{MANAGER}/records"
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


@pytest.fixture
def admin_phone(monkeypatch):
    """Make one of the seeded fire temple's people the admin."""
    def make(phone: str) -> str:
        monkeypatch.setenv("ADMIN_PHONES", phone)
        config.get_settings.cache_clear()
        return phone

    yield make
    config.get_settings.cache_clear()


async def _id(db, phone: str) -> int:
    return (await db.execute(select(User.id).where(User.phone == phone))).scalar_one()


async def _notices(db, user_id: int, kind: str) -> list[AppNotification]:
    return list((await db.execute(
        select(AppNotification).where(AppNotification.user_id == user_id, AppNotification.kind == kind)
    )).scalars().all())


async def test_the_admin_does_all_a_manager_does_for_that_place_and_its_managers_see_it(
    client, db, seeded, admin_phone, pushes,
):
    admin_phone(PANTHAKY)
    mgr, at = await manager(client, db)
    await db.execute(update(Agyary).where(Agyary.id == seeded["agyary_id"])
                     .values(latitude=MUMBAI[0] + 0.01, longitude=MUMBAI[1], location_source="pin"))
    await db.commit()
    admin = auth(await sign_in(client, PANTHAKY))
    admin_id = await _id(db, PANTHAKY)
    act = f"act_for={at.id}"

    got = (await client.get(f"{MANAGER}/place?{act}", headers=admin)).json()
    assert [p["id"] for p in got["places"]] == [at.id] and got["as_admin"] is True
    day = await client.post(f"{MANAGER}/death-day?{act}", json={"death_date": form()["death_date"]}, headers=admin)
    assert day.status_code == 200 and day.json()["roj"]

    r = await client.post(f"{RECORDS}?{act}", json=form(), headers=admin)
    assert r.status_code == 200, r.text
    rec = r.json()["record"]
    assert rec["funeral_place"]["id"] == at.id and rec["recorded_by_admin"] is True
    assert (await db.get(FuneralRecord, rec["id"])).created_by_user_id == admin_id
    listed = (await client.get(f"{RECORDS}?{act}", headers=admin)).json()["records"]
    assert [x["id"] for x in listed] == [rec["id"]]
    # The place's real manager sees it, and that the admin recorded it.
    theirs = (await client.get(RECORDS, headers=mgr)).json()["records"]
    assert [x["id"] for x in theirs] == [rec["id"]] and theirs[0]["recorded_by_admin"] is True
    assert (await client.get(f"{RECORDS}/{rec['id']}", headers=mgr)).json()["record"]["recorded_by_admin"] is True

    changed = await client.put(f"{RECORDS}/{rec['id']}?{act}", json=form(bungli="Bungli 4"), headers=admin)
    assert changed.status_code == 200 and changed.json()["record"]["bungli"] == "Bungli 4"
    near = (await client.get(f"{RECORDS}/{rec['id']}/agyaries?{act}", headers=admin)).json()["agyaries"]
    assert near[0]["id"] == seeded["agyary_id"] and near[0]["reach"] == "panthaky"
    found = await client.get(f"{MANAGER}/agyaries/search?q=goti&place_id={at.id}&{act}", headers=admin)
    assert found.status_code == 200 and found.json()["agyaries"][0]["id"] == seeded["agyary_id"]

    # Send, withdraw, and send again: in the admin's name, as the manager would.
    send = {"agyary_id": seeded["agyary_id"], "family_agreed": True, "family_whatsapp_agreed": True}
    r = await client.post(f"{RECORDS}/{rec['id']}/requests?{act}", json={**send, "family_agreed": False}, headers=admin)
    assert r.status_code == 400 and r.headers["X-Field"] == "family_agreed"
    r = await client.post(f"{RECORDS}/{rec['id']}/requests?{act}", json=send, headers=admin)
    assert r.status_code == 200, r.text
    first = r.json()["record"]["requests"][0]
    assert first["sent_by_admin"] is True and (await db.get(FuneralRequest, first["id"])).sent_by_user_id == admin_id
    r = await client.post(f"{MANAGER}/requests/{first['id']}/withdraw?{act}", headers=admin)
    assert r.status_code == 200 and r.json()["record"]["requests"][0]["status"] == "withdrawn"
    r = await client.post(f"{RECORDS}/{rec['id']}/requests?{act}", json=send, headers=admin)
    rid = r.json()["record"]["requests"][0]["id"]

    # The admin is also the fire temple's panthaky: they accept it in the same app.
    accepted = await client.post(f"{REQUESTS}/{rid}/accept", json={"share_contact": True}, headers=admin)
    assert accepted.status_code == 200, accepted.text
    for headers in (admin, mgr):
        q = (await client.get(f"{RECORDS}/{rec['id']}?{act}" if headers is admin else f"{RECORDS}/{rec['id']}",
                              headers=headers)).json()["record"]["requests"][0]
        assert q["status"] == "accepted" and q["accepted_by"] == "Er. Hormuz Dadachanji"

    # The answer reaches the manager, and the admin who sent it, each with their own way back.
    mgr_id = (await client.get("/api/mobed/auth/me", headers=mgr)).json()["id"]
    (to_mgr,) = await _notices(db, mgr_id, funeral_answers.KIND_ACCEPTED)
    (to_admin,) = await _notices(db, admin_id, funeral_answers.KIND_ACCEPTED)
    assert to_mgr.link == f"#/manager/record/{rec['id']}"
    assert to_admin.link == f"#/admin/act/{at.id}/record/{rec['id']}"
    answered = [p for p in pushes if p.get("tag") == f"funeral-answer-{rid}"]
    assert sorted(p["to"][0] for p in answered) == sorted([mgr_id, admin_id])
    assert all("Test Family" not in p["body"] for p in answered)


async def test_a_decline_reaches_the_admin_who_sent_it(client, db, seeded, admin_phone, pushes):
    admin_phone(MOBED)
    _, at = await manager(client, db)
    admin = auth(await sign_in(client, MOBED))
    act = f"act_for={at.id}"
    rec = (await client.post(f"{RECORDS}?{act}", json=form(), headers=admin)).json()["record"]
    r = await client.post(f"{RECORDS}/{rec['id']}/requests?{act}",
                          json={"agyary_id": seeded["agyary_id"], "family_agreed": True}, headers=admin)
    rid = r.json()["record"]["requests"][0]["id"]
    panthaky = auth(await sign_in(client, PANTHAKY))
    r = await client.post(f"{REQUESTS}/{rid}/decline", json={"reason": "No mobeds free"}, headers=panthaky)
    assert r.status_code == 200, r.text
    (notice,) = await _notices(db, await _id(db, MOBED), funeral_answers.KIND_DECLINED)
    assert notice.link == f"#/admin/act/{at.id}/record/{rec['id']}" and "No mobeds free" in notice.body
    # The admin is still a mobed: their own side is as it was.
    assert (await client.get("/api/mobed/requests/count", headers=admin)).status_code == 200
    assert (await client.get("/api/mobed/my-day", headers=admin)).status_code == 200


async def test_an_admin_names_one_place_in_use_or_gets_nothing(client, db, seeded, admin_phone):
    admin_phone(PANTHAKY)
    _, at = await manager(client, db)
    off = await place(db, "Prayer Hall (test)", kind="prayer_hall")
    off.is_active = False
    await db.commit()
    admin = auth(await sign_in(client, PANTHAKY))
    for method, path in (("GET", f"{MANAGER}/place"), ("GET", RECORDS), ("POST", RECORDS)):
        r = await client.request(method, path, json=form(), headers=admin)
        assert r.status_code == 403 and r.json()["detail"] == mobed_routes.NOT_FOR_MOBEDS, (method, path)
        for bad in (off.id, at.id + off.id + 1000):
            r = await client.request(method, f"{path}?act_for={bad}", json=form(), headers=admin)
            assert r.status_code == 404 and r.json()["detail"] == funeral_routes.NO_PLACE, (method, path, bad)
    assert (await db.execute(select(FuneralRecord))).first() is None


async def test_only_an_admin_may_name_a_place(client, db, seeded, admin_phone):
    admin_phone(PANTHAKY)
    mgr, at = await manager(client, db)
    other, there = await manager(client, db, phone="+919911100072", at=await place(db, "Aramgah (test)"))
    mobed = auth(await sign_in(client, MOBED))
    for act in (at.id, there.id):
        r = await client.get(f"{RECORDS}?act_for={act}", headers=mobed)
        assert r.status_code == 403 and r.json()["detail"] == mobed_routes.NOT_FOR_MOBEDS
        # A manager names no place, not even their own.
        r = await client.post(f"{RECORDS}?act_for={act}", json=form(), headers=mgr)
        assert r.status_code == 403 and r.json()["detail"] == funeral_routes.ONLY_ADMINS_ACT
    assert (await client.get(f"{RECORDS}?act_for={at.id}")).status_code == 401


async def test_acting_for_one_place_shows_nothing_of_another(client, db, seeded, admin_phone):
    admin_phone(PANTHAKY)
    _, at = await manager(client, db)
    other, there = await manager(client, db, phone="+919911100072", at=await place(db, "Aramgah (test)"))
    theirs = (await client.post(RECORDS, json=form(), headers=other)).json()["record"]
    r = await client.post(f"{RECORDS}/{theirs['id']}/requests",
                          json={"agyary_id": seeded["agyary_id"], "family_agreed": True}, headers=other)
    rid = r.json()["record"]["requests"][0]["id"]
    admin = auth(await sign_in(client, PANTHAKY))
    act = f"act_for={at.id}"
    assert (await client.get(f"{RECORDS}?{act}", headers=admin)).json()["records"] == []
    for method, path in (("GET", f"{RECORDS}/{theirs['id']}"), ("PUT", f"{RECORDS}/{theirs['id']}"),
                         ("GET", f"{RECORDS}/{theirs['id']}/agyaries"),
                         ("POST", f"{RECORDS}/{theirs['id']}/requests"), ("POST", f"{MANAGER}/requests/{rid}/withdraw")):
        body = {"agyary_id": seeded["agyary_id"], "family_agreed": True} if path.endswith("/requests") else form()
        r = await client.request(method, f"{path}?{act}", json=body, headers=admin)
        assert r.status_code == 404, (method, path, r.text)
    # Nor can the other place be named inside the call.
    r = await client.post(f"{RECORDS}?{act}", json=form(funeral_place_id=there.id), headers=admin)
    assert r.status_code == 404
    r = await client.get(f"{MANAGER}/agyaries/search?q=goti&place_id={there.id}&{act}", headers=admin)
    assert r.status_code == 404
    assert (await db.get(FuneralRequest, rid)).status == "waiting"
