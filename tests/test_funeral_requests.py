"""A manager chooses a fire temple and sends a funeral record to it (DECISIONS
D10, D2, D9; Phase 2 Step 4).

Suggested: nearest first, by straight-line distance, within 500 km, with the
family's preferred fire temple first; and a search over all of them. Each says
whether a request reaches a confirmed panthaky, only mobeds, or nobody.

Sending needs the tick that the family agreed; it goes to the confirmed
panthakys, else the mobeds whose access is on, and is refused in words when
nobody is there. One waits at a time; it can be withdrawn and sent elsewhere.
The notices and phone notifications never carry the family's name or number.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select, update

from agyary.core import config
from agyary.models import AgyaryUser, AppNotification, FuneralRequest, FuneralRequestRecipient, User
from agyary.services import funeral_requests
from tests.conftest import sign_in
from tests.funeral_helpers import FAMILY, agyari, auth, form, manager, member, place

RECORDS = "/api/mobed/manager/records"
NAVSARI = (20.951, 72.923)
DELHI = (28.61, 77.21)


@pytest.fixture
def admin_is_panthaky(monkeypatch, seeded):
    monkeypatch.setenv("ADMIN_PHONES", seeded["panthaky_phone"])
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_the_distance_is_the_straight_line_over_the_globe():
    assert round(funeral_requests.km(0, 0, 0, 1), 1) == 111.2
    assert funeral_requests.km(18.957, 72.806, 18.957, 72.806) == 0
    assert 215 < funeral_requests.km(18.957, 72.806, *NAVSARI) < 230


async def _temples(db):
    """A fire temple near the Doongerwadi with a confirmed panthaky, one at
    Navsari with only mobeds, one near with nobody whose access is on, one
    turned off, one in Delhi, and one not on the map."""
    near = await agyari(db, "Near Agyari (test)", (18.96, 72.83))
    await member(db, near, "+919822200001", "panthaky")
    await member(db, near, "+919822200002", "mobed")
    navsari = await agyari(db, "Navsari Agyari (test)", NAVSARI, city="Navsari")
    claimed = await member(db, navsari, "+919822200003", "mobed")
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == claimed.id)
                     .values(claimed_role="panthaky", claimed_at=datetime.now(timezone.utc)))
    empty = await agyari(db, "Quiet Agyari (test)", (18.99, 72.84), status="unclaimed")
    await member(db, empty, "+919822200004", "mobed", access="pending")
    await member(db, empty, "+919822200005", "panthaky", access="off")
    off = await agyari(db, "Closed Agyari (test)", (18.958, 72.807))
    off.is_active = False
    delhi = await agyari(db, "Delhi Agyari (test)", DELHI, city="Delhi")
    nowhere = await agyari(db, "Unmapped Agyari (test)", None)
    await db.commit()
    return near, navsari, empty, delhi, nowhere


async def test_suggested_nearest_first_within_500_km_with_who_it_reaches(client, db, seeded):
    near, navsari, empty, delhi, nowhere = await _temples(db)
    headers, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(), headers=headers)).json()["record"]
    got = (await client.get(f"{RECORDS}/{rec['id']}/agyaries", headers=headers)).json()
    assert got["place_has_position"] is True and got["near_km"] == 500
    rows = got["agyaries"]
    # Delhi is too far, the closed one and the ones not on the map are not there.
    assert [r["name"] for r in rows] == ["Near Agyari (test)", "Quiet Agyari (test)", "Navsari Agyari (test)"]
    assert rows[0]["km"] < rows[1]["km"] < rows[2]["km"] and 215 < rows[2]["km"] < 230
    # A confirmed panthaky; only mobeds (a claim is not a panthaky); nobody whose access is on.
    assert [r["reach"] for r in rows] == ["panthaky", "nobody", "mobeds"]
    assert [r["may_send"] for r in rows] == [True, False, True]
    assert not any(r["preferred"] for r in rows)


async def test_the_familys_preferred_fire_temple_is_first_wherever_it_is(client, db, seeded):
    near, navsari, empty, delhi, nowhere = await _temples(db)
    headers, _ = await manager(client, db)
    for preferred, first_km in ((delhi, lambda k: k > 1000), (navsari, lambda k: 215 < k < 230)):
        rec = (await client.post(RECORDS, json=form(preferred_agyary_id=preferred.id), headers=headers)).json()
        rows = (await client.get(f"{RECORDS}/{rec['record']['id']}/agyaries", headers=headers)).json()["agyaries"]
        assert rows[0]["id"] == preferred.id and rows[0]["preferred"] is True and first_km(rows[0]["km"])
        assert [r["id"] for r in rows].count(preferred.id) == 1
        assert rec["record"]["preferred_agyari"]["name"] == preferred.name
    # One not on the map is still first, with no distance.
    rec = (await client.post(RECORDS, json=form(preferred_agyary_id=nowhere.id), headers=headers)).json()
    rows = (await client.get(f"{RECORDS}/{rec['record']['id']}/agyaries", headers=headers)).json()["agyaries"]
    assert rows[0]["id"] == nowhere.id and rows[0]["km"] is None and rows[0]["reach"] == "nobody"


async def test_a_place_with_no_pin_says_so_and_suggests_only_the_preferred(client, db, seeded):
    near, *_ = await _temples(db)
    unpinned = await place(db, "Aramgah (test)", position=None, kind="aramgah")
    headers, _ = await manager(client, db, at=unpinned)
    rec = (await client.post(RECORDS, json=form(), headers=headers)).json()["record"]
    got = (await client.get(f"{RECORDS}/{rec['id']}/agyaries", headers=headers)).json()
    assert got["place_has_position"] is False and got["agyaries"] == []
    rec = (await client.post(RECORDS, json=form(preferred_agyary_id=near.id), headers=headers)).json()["record"]
    got = (await client.get(f"{RECORDS}/{rec['id']}/agyaries", headers=headers)).json()
    assert [r["id"] for r in got["agyaries"]] == [near.id] and got["agyaries"][0]["km"] is None
    # Search still finds them all.
    found = (await client.get("/api/mobed/manager/agyaries/search?q=agyari", headers=headers)).json()["agyaries"]
    assert {"Near Agyari (test)", "Delhi Agyari (test)"} <= {r["name"] for r in found}


async def test_search_all_finds_any_fire_temple_by_name_or_town(client, db, seeded):
    await _temples(db)
    headers, _ = await manager(client, db)
    found = (await client.get("/api/mobed/manager/agyaries/search?q=delhi", headers=headers)).json()["agyaries"]
    assert [r["name"] for r in found] == ["Delhi Agyari (test)"] and found[0]["km"] > 1000
    assert found[0]["reach"] == "nobody" and found[0]["may_send"] is False
    goti = (await client.get("/api/mobed/manager/agyaries/search?q=goti", headers=headers)).json()["agyaries"]
    assert goti[0]["name"] == "Goti Adarian" and goti[0]["reach"] == "panthaky" and goti[0]["km"] is None
    assert (await client.get("/api/mobed/manager/agyaries/search?q=", headers=headers)).json()["agyaries"] == []


async def test_another_places_record_has_no_suggestions_for_them(client, db, seeded):
    headers, _ = await manager(client, db)
    rec = (await client.post(RECORDS, json=form(), headers=headers)).json()["record"]
    other_place = await place(db, "Prayer hall (test)", kind="prayer_hall")
    other, _ = await manager(client, db, phone="+919911100072", name="Other Manager", at=other_place)
    assert (await client.get(f"{RECORDS}/{rec['id']}/agyaries", headers=other)).status_code == 404
    mine = rec["funeral_place"]["id"]
    r = await client.get(f"/api/mobed/manager/agyaries/search?q=goti&place_id={mine}", headers=other)
    assert r.status_code == 404


# --- Sending ----------------------------------------------------------------------

@pytest.fixture
def pushes(monkeypatch):
    sent = []

    async def capture(db, settings, user_ids, **kw):
        sent.append({"to": sorted(user_ids), **kw})
        return 0

    from agyary.services import web_push

    monkeypatch.setattr(web_push, "send_to_users", capture)
    return sent


async def _sent_to(db, request_id: int) -> list[int]:
    rows = await db.execute(select(FuneralRequestRecipient.user_id)
                            .where(FuneralRequestRecipient.funeral_request_id == request_id))
    return sorted(rows.scalars().all())


async def _notices(db, kind: str | None = None) -> list[AppNotification]:
    stmt = select(AppNotification).order_by(AppNotification.id)
    if kind:
        stmt = stmt.where(AppNotification.kind == kind)
    return list((await db.execute(stmt)).scalars().all())


async def _record(client, headers, **changes) -> dict:
    return (await client.post(RECORDS, json=form(**changes), headers=headers)).json()["record"]


def _send(client, headers, record_id, agyary_id, agreed=True):
    return client.post(f"{RECORDS}/{record_id}/requests", json={"agyary_id": agyary_id, "family_agreed": agreed},
                       headers=headers)


async def _user(db, phone: str) -> User:
    return (await db.execute(select(User).where(User.phone == phone))).scalar_one()


async def test_without_the_tick_nothing_is_sent(client, db, seeded, pushes):
    near, *_ = await _temples(db)
    headers, _ = await manager(client, db)
    rec = await _record(client, headers)
    for body in ({"agyary_id": near.id}, {"agyary_id": near.id, "family_agreed": False}):
        r = await client.post(f"{RECORDS}/{rec['id']}/requests", json=body, headers=headers)
        assert r.status_code == 400 and r.headers["X-Field"] == "family_agreed"
        assert "family agreed to share their name and number" in r.json()["detail"]
    assert (await db.execute(select(FuneralRequest))).first() is None
    assert await _notices(db) == [] and pushes == []


async def test_it_goes_to_the_confirmed_panthakys_and_says_nothing_of_the_family(client, db, seeded, pushes):
    near, *_ = await _temples(db)
    panthaky_user = await _user(db, "+919822200001")
    headers, _ = await manager(client, db)
    rec = await _record(client, headers)
    r = await _send(client, headers, rec["id"], near.id)
    assert r.status_code == 200, r.text
    assert r.json()["asked"] == 1
    (req,) = r.json()["record"]["requests"]
    assert req["status"] == "waiting" and req["agyari"]["name"] == "Near Agyari (test)" and req["asked"] == 1
    assert r.json()["record"]["may_send"] is False and r.json()["record"]["may_edit"] is True
    row = await db.get(FuneralRequest, req["id"])
    assert row.family_share_agreed_at is not None and row.sent_by_user_id is not None
    # Only the panthaky: the mobed there is not asked while a panthaky is.
    assert await _sent_to(db, req["id"]) == [panthaky_user.id]

    (note,) = await _notices(db, "funeral_request")
    assert note.user_id == panthaky_user.id and note.link == "#/requests" and note.agyary_id == near.id
    assert note.title == "A Doongerwadi asks for prayers"
    assert note.body.startswith("Behdin Rustom Jamshed. Doongerwadi (test), Bungli 3. Four days. Geh-saarnu: ")
    assert "Havan geh" in note.body and "Uthamna: " in note.body and "4:00 pm" in note.body
    assert "5 mobeds wanted" in note.body and "Asked of Near Agyari (test)" in note.body
    (push,) = pushes
    assert push["to"] == [panthaky_user.id] and push["url"] == "/mobed#/requests"
    assert push["title"] == "A request for prayers"
    assert push["body"] == "Doongerwadi (test) asks Near Agyari (test) for prayers."
    # Never the family's name or number; on the lock screen not even the departed's name.
    for text in (note.title, note.body, push["title"], push["body"]):
        assert FAMILY not in text and FAMILY[3:] not in text and "Test Family" not in text, text
    assert "Rustom" not in push["title"] + push["body"]
    # Nor in what the panthaky's app is given.
    seen = await client.get("/api/mobed/notifications", headers=auth(await sign_in(client, "+919822200001")))
    assert seen.status_code == 200 and "Behdin Rustom" in seen.text
    assert FAMILY[3:] not in seen.text and "Test Family" not in seen.text


async def test_with_no_panthaky_it_goes_to_the_mobeds_whose_access_is_on(client, db, seeded, pushes):
    near, navsari, *_ = await _temples(db)
    on = await _user(db, "+919822200003")
    await member(db, navsari, "+919822200006", "mobed", access="pending")
    await member(db, navsari, "+919822200007", "mobed", access="off")
    second = await member(db, navsari, "+919822200008", "mobed")
    await db.commit()
    headers, _ = await manager(client, db)
    rec = await _record(client, headers)
    r = await _send(client, headers, rec["id"], navsari.id)
    assert r.status_code == 200 and r.json()["asked"] == 2
    assert await _sent_to(db, r.json()["record"]["requests"][0]["id"]) == sorted([on.id, second.id])
    assert sorted(n.user_id for n in await _notices(db, "funeral_request")) == sorted([on.id, second.id])
    assert pushes[0]["to"] == sorted([on.id, second.id])


async def test_a_fire_temple_with_nobody_in_the_app_is_refused_in_words(client, db, seeded, pushes):
    near, navsari, empty, delhi, nowhere = await _temples(db)
    headers, _ = await manager(client, db)
    rec = await _record(client, headers)
    for temple in (empty, delhi):
        r = await _send(client, headers, rec["id"], temple.id)
        assert r.status_code == 409
        assert r.json()["detail"] == funeral_requests.nobody_there(temple)
        assert r.json()["detail"].startswith(f"Nobody at {temple.name} uses Mobed Diary yet")
    assert (await db.execute(select(FuneralRequest))).first() is None and await _notices(db) == []
    assert (await _send(client, headers, rec["id"], 99999)).status_code == 404


async def test_one_waits_at_a_time_and_a_withdrawn_one_can_go_elsewhere(client, db, seeded, pushes):
    near, navsari, *_ = await _temples(db)
    headers, _ = await manager(client, db)
    rec = await _record(client, headers)
    first = (await _send(client, headers, rec["id"], near.id)).json()["record"]["requests"][0]
    r = await _send(client, headers, rec["id"], navsari.id)
    assert r.status_code == 409 and "already waiting at Near Agyari (test)" in r.json()["detail"]
    assert (await _send(client, headers, rec["id"], near.id)).status_code == 409

    r = await client.post(f"/api/mobed/manager/requests/{first['id']}/withdraw", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["record"]["requests"][0]["status"] == "withdrawn" and r.json()["record"]["may_send"] is True
    (gone,) = await _notices(db, "funeral_request_withdrawn")
    assert gone.title == "A request for prayers was withdrawn" and "Behdin Rustom Jamshed" in gone.body
    assert pushes[-1]["body"] == "Doongerwadi (test) withdrew its request to Near Agyari (test)."
    again = await client.post(f"/api/mobed/manager/requests/{first['id']}/withdraw", headers=headers)
    assert again.status_code == 409 and "no longer waiting" in again.json()["detail"]

    r = await _send(client, headers, rec["id"], navsari.id)
    assert r.status_code == 200
    assert [(q["agyari"]["name"], q["status"]) for q in r.json()["record"]["requests"]] == [
        ("Navsari Agyari (test)", "waiting"), ("Near Agyari (test)", "withdrawn")]


async def test_a_change_while_waiting_reaches_those_asked_once(client, db, seeded, pushes):
    near, *_ = await _temples(db)
    headers, _ = await manager(client, db)
    rec = await _record(client, headers)
    await _send(client, headers, rec["id"], near.id)
    r = await client.put(f"{RECORDS}/{rec['id']}", json=form(bungli="Bungli 7"), headers=headers)
    assert r.status_code == 200 and r.json()["told"] == 1
    (changed,) = await _notices(db, "funeral_request_changed")
    assert "Bungli 7" in changed.body and FAMILY[3:] not in changed.body
    assert pushes[-1]["body"] == "Doongerwadi (test) changed its request to Near Agyari (test)."
    # Saved again with nothing different: nobody is told twice.
    r = await client.put(f"{RECORDS}/{rec['id']}", json=form(bungli="Bungli 7"), headers=headers)
    assert r.json()["told"] == 0 and len(await _notices(db, "funeral_request_changed")) == 1


async def test_another_places_manager_cannot_send_or_withdraw(client, db, seeded, pushes):
    near, *_ = await _temples(db)
    headers, _ = await manager(client, db)
    rec = await _record(client, headers)
    req = (await _send(client, headers, rec["id"], near.id)).json()["record"]["requests"][0]
    other_place = await place(db, "Prayer hall (test)", kind="prayer_hall")
    other, _ = await manager(client, db, phone="+919911100072", name="Other Manager", at=other_place)
    assert (await _send(client, other, rec["id"], near.id)).status_code == 404
    r = await client.post(f"/api/mobed/manager/requests/{req['id']}/withdraw", headers=other)
    assert r.status_code == 404
    assert (await db.get(FuneralRequest, req["id"])).status == "waiting"


async def test_sending_is_rate_limited(client, db, seeded, pushes):
    near, *_ = await _temples(db)
    headers, _ = await manager(client, db)
    rec = await _record(client, headers)
    for _ in range(20):
        sent = await _send(client, headers, rec["id"], near.id)
        assert sent.status_code == 200
        await client.post(f"/api/mobed/manager/requests/{sent.json()['record']['requests'][0]['id']}/withdraw",
                          headers=headers)
    assert (await _send(client, headers, rec["id"], near.id)).status_code == 429
