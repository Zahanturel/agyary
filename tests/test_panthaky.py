"""Mobed or panthaky (DECISIONS D10): what a person says they are at their
fire temple is a claim, and only the owner's confirmation makes them panthaky.

The panthaky role sees every machi at its temple (D7), and the app never lets
anyone give themselves that. So these tests prove: the answer at each way of
choosing a fire temple is kept and the role stays mobed; a claim grants no
panthaky power anywhere; and a confirmed claim grants exactly the panthaky's.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agyary.core import config
from agyary.models import Agyary, AgyaryUser, AppNotification, User
from tests.conftest import sign_in

NEW = "+919911100088"


@pytest.fixture
def admin_is_panthaky(monkeypatch, seeded):
    """The seeded panthaky is the admin."""
    monkeypatch.setenv("ADMIN_PHONES", seeded["panthaky_phone"])
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def _new(client, phone=NEW, name="Er. Kersi Mistry", *, approve=False) -> tuple[dict, dict]:
    body = await sign_in(client, phone, name, approve=approve)
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


async def _membership(db, user_id: int, agyary_id: int) -> AgyaryUser:
    row = (await db.execute(
        select(AgyaryUser).where(AgyaryUser.user_id == user_id, AgyaryUser.agyary_id == agyary_id)
    )).scalar_one()
    await db.refresh(row)
    return row


async def _notes(db, kind="mobed_request") -> list[AppNotification]:
    return list((await db.execute(select(AppNotification).where(AppNotification.kind == kind))).scalars())


# --- Asked at sign-up, at every way of choosing a fire temple ----------------

async def test_joining_as_the_panthaky_is_a_claim_and_the_role_stays_mobed(client, db, seeded, admin_is_panthaky):
    headers, user = await _new(client)
    aid = seeded["agyary_id"]
    r = await client.post(f"/api/mobed/agyaries/{aid}/join", json={"claimed_role": "panthaky"}, headers=headers)
    assert r.status_code == 200, r.text
    [temple] = r.json()["user"]["agyaries"]
    assert temple["role"] == "mobed"
    assert temple["claimed_role"] == "panthaky" and temple["panthaky_claim_waiting"] is True
    assert temple["may_claim_panthaky"] is False

    m = await _membership(db, user["id"], aid)
    assert (m.role, m.claimed_role, m.claim_decision) == ("mobed", "panthaky", None)
    assert m.claimed_at is not None

    # The admin's notice says so, with the number in the app only.
    [note] = await _notes(db)
    assert "says they are the panthaky" in note.body and NEW in note.body and "Goti Adarian" in note.body
    assert note.title == "A new mobed is waiting"


async def test_joining_as_a_mobed_is_kept_too(client, db, seeded, admin_is_panthaky):
    headers, user = await _new(client)
    aid = seeded["agyary_id"]
    r = await client.post(f"/api/mobed/agyaries/{aid}/join", json={"claimed_role": "mobed"}, headers=headers)
    assert r.status_code == 200, r.text
    [temple] = r.json()["user"]["agyaries"]
    assert (temple["role"], temple["claimed_role"], temple["panthaky_claim_waiting"]) == ("mobed", "mobed", False)
    m = await _membership(db, user["id"], aid)
    assert (m.role, m.claimed_role) == ("mobed", "mobed")
    [note] = await _notes(db)
    assert "panthaky" not in note.body


async def test_an_app_from_before_the_question_still_joins_with_no_claim(client, db, seeded):
    headers, user = await _new(client)
    aid = seeded["agyary_id"]
    r = await client.post(f"/api/mobed/agyaries/{aid}/join", headers=headers)   # no body at all
    assert r.status_code == 200, r.text
    [temple] = r.json()["user"]["agyaries"]
    assert (temple["role"], temple["claimed_role"], temple["may_claim_panthaky"]) == ("mobed", None, True)
    m = await _membership(db, user["id"], aid)
    assert (m.claimed_role, m.claimed_at) == (None, None)


async def test_only_mobed_or_panthaky_can_be_said(client, db, seeded):
    headers, _ = await _new(client)
    for bad in ("caretaker", "admin", "Panthaky", ""):
        r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join",
                              json={"claimed_role": bad}, headers=headers)
        assert r.status_code == 422, bad
    r = await client.post("/api/mobed/agyaries", json={"name": "Some Adarian", "city": "Pune",
                                                       "claimed_role": "caretaker"}, headers=headers)
    assert r.status_code == 422


async def test_setting_up_an_unclaimed_temple_keeps_the_claim_and_the_role_mobed(client, db, seeded):
    """Activating a seeded fire temple gave a plain 'mobed' before the question
    existed, and still does: the person who sets it up is not made its panthaky."""
    seed = Agyary(name="Old Seed Agiary", city="Surat", status="unclaimed")
    db.add(seed)
    await db.commit()
    headers, user = await _new(client)
    r = await client.post(f"/api/mobed/agyaries/{seed.id}/join", json={"claimed_role": "panthaky"}, headers=headers)
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/mobed/agyaries/{seed.id}/activate",
                          json={"name": "Old Seed Agiary", "city": "Surat"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["agyary"]["status"] == "active"
    [temple] = r.json()["user"]["agyaries"]
    assert (temple["role"], temple["claimed_role"]) == ("mobed", "panthaky")
    m = await _membership(db, user["id"], seed.id)
    assert (m.role, m.claimed_role, m.claim_decision) == ("mobed", "panthaky", None)


async def test_adding_a_new_temple_keeps_the_claim_and_the_role_mobed(client, db, seeded, admin_is_panthaky):
    """Creating a fire temple gave a plain 'mobed' before the question existed,
    and still does."""
    headers, user = await _new(client)
    r = await client.post("/api/mobed/agyaries", json={"name": "Banaji Atash Behram", "city": "Mumbai",
                                                       "claimed_role": "panthaky"}, headers=headers)
    assert r.status_code == 200, r.text
    aid = r.json()["agyary"]["id"]
    [temple] = r.json()["user"]["agyaries"]
    assert (temple["role"], temple["claimed_role"], temple["panthaky_claim_waiting"]) == ("mobed", "panthaky", True)
    m = await _membership(db, user["id"], aid)
    assert (m.role, m.claimed_role) == ("mobed", "panthaky")
    [note] = await _notes(db)
    assert "Banaji Atash Behram" in note.body and "says they are the panthaky" in note.body


async def test_adding_a_new_temple_without_an_answer_is_a_plain_mobed(client, db, seeded):
    headers, user = await _new(client)
    r = await client.post("/api/mobed/agyaries", json={"name": "Quiet Dar-e-Mehr", "city": "Pune"}, headers=headers)
    assert r.status_code == 200, r.text
    m = await _membership(db, user["id"], r.json()["agyary"]["id"])
    assert (m.role, m.claimed_role) == ("mobed", None)


async def test_choosing_the_temple_again_does_not_change_the_answer(client, db, seeded):
    headers, user = await _new(client)
    aid = seeded["agyary_id"]
    await client.post(f"/api/mobed/agyaries/{aid}/join", json={"claimed_role": "panthaky"}, headers=headers)
    first = (await _membership(db, user["id"], aid)).claimed_at
    r = await client.post(f"/api/mobed/agyaries/{aid}/join", json={"claimed_role": "mobed"}, headers=headers)
    assert r.status_code == 200, r.text
    m = await _membership(db, user["id"], aid)
    assert (m.role, m.claimed_role, m.claimed_at) == ("mobed", "panthaky", first)


async def test_a_seeded_panthaky_joining_again_is_neither_claimed_nor_demoted(client, db, seeded):
    headers = {"Authorization": f"Bearer {(await sign_in(client, seeded['panthaky_phone']))['access_token']}"}
    aid = seeded["agyary_id"]
    r = await client.post(f"/api/mobed/agyaries/{aid}/join", json={"claimed_role": "mobed"}, headers=headers)
    assert r.status_code == 200, r.text
    panthaky = (await db.execute(select(User).where(User.phone == seeded["panthaky_phone"]))).scalar_one()
    m = await _membership(db, panthaky.id, aid)
    assert (m.role, m.claimed_role) == ("panthaky", None)


async def test_a_mobed_already_in_who_says_panthaky_at_a_second_temple_has_the_admins_told(
    client, db, seeded, admin_is_panthaky,
):
    headers, user = await _new(client, approve=True)
    await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", json={"claimed_role": "mobed"},
                      headers=headers)
    assert await _notes(db) == []          # already on: no "new mobed" notice
    other = Agyary(name="Second Agiary", city="Navsari", status="active")
    db.add(other)
    await db.commit()
    r = await client.post(f"/api/mobed/agyaries/{other.id}/join", json={"claimed_role": "panthaky"}, headers=headers)
    assert r.status_code == 200, r.text
    [note] = await _notes(db, "panthaky_claim")
    assert "Second Agiary" in note.body and note.link == "#/admin/mobeds"
    assert (await _membership(db, user["id"], other.id)).role == "mobed"


# --- A claim grants nothing -------------------------------------------------

WINDOW = "from=2030-08-01&to=2030-08-31"


async def _colleagues_machi(client, seeded) -> int:
    """The seeded mobed's machi at the seeded temple, for another's family."""
    body = await sign_in(client, seeded["mobed_phone"])
    owner = {"Authorization": f"Bearer {body['access_token']}"}
    made = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/manual-add/machi", headers=owner, json={
        "behdin_phone": "+919944400801", "behdin_name": "Colleagues Family", "roj": 1, "mah": 1,
        "year": 1400, "geh": 1, "gregorian": "2030-08-15", "purpose": "patet",
    })
    assert made.status_code == 200, made.text
    return made.json()["machi_id"]


async def _no_panthaky_powers(client, db, seeded, headers, user_id, machi_id) -> None:
    from agyary.messaging import booking_service
    from agyary.services import mobed_dashboard

    aid = seeded["agyary_id"]
    for query in ("", "&mine=false"):
        r = await client.get(f"/api/mobed/agyaries/{aid}/machi-board?{WINDOW}{query}", headers=headers)
        assert r.status_code == 200 and r.json() == [], query
        assert "Colleagues Family" not in r.text
    for what in ("detail", "slip"):
        r = await client.get(f"/api/mobed/agyaries/{aid}/machis/{machi_id}/{what}", headers=headers)
        assert r.status_code == 404, what
        assert "Colleagues Family" not in r.text
    assert await mobed_dashboard.is_admin(db, aid, user_id) is False
    assert user_id not in [u.id for u in await booking_service.get_admins(db, aid)]


async def test_a_waiting_panthaky_claim_grants_no_panthaky_power(client, db, seeded):
    machi_id = await _colleagues_machi(client, seeded)
    headers, user = await _new(client, approve=True)
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", json={"claimed_role": "panthaky"},
                          headers=headers)
    assert r.status_code == 200, r.text
    await _no_panthaky_powers(client, db, seeded, headers, user["id"], machi_id)


# --- Settings: a mobed who never answered can say so, and take it back ---------

async def _settings_mobed(client, seeded):
    """The seeded mobed: joined before the question existed, so no claim."""
    body = await sign_in(client, seeded["mobed_phone"])
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


async def test_a_mobed_with_no_answer_is_asked_in_settings_and_can_claim(client, db, seeded, admin_is_panthaky):
    headers, user = await _settings_mobed(client, seeded)
    aid = seeded["agyary_id"]
    [temple] = (await client.get("/api/mobed/auth/me", headers=headers)).json()["agyaries"]
    assert (temple["role"], temple["claimed_role"], temple["may_claim_panthaky"]) == ("mobed", None, True)

    r = await client.post(f"/api/mobed/agyaries/{aid}/panthaky-claim", headers=headers)
    assert r.status_code == 200, r.text
    [temple] = r.json()["agyaries"]
    assert (temple["role"], temple["panthaky_claim_waiting"], temple["may_claim_panthaky"]) == ("mobed", True, False)
    m = await _membership(db, user["id"], aid)
    assert (m.role, m.claimed_role) == ("mobed", "panthaky")
    [note] = await _notes(db, "panthaky_claim")
    assert "Er. Pervez Kias" in note.body and "Goti Adarian" in note.body and note.link == "#/admin/mobeds"

    # Not twice while it waits.
    again = await client.post(f"/api/mobed/agyaries/{aid}/panthaky-claim", headers=headers)
    assert again.status_code == 409 and again.json()["detail"] == "You have already told us. The admin will check it."
    assert len(await _notes(db, "panthaky_claim")) == 1


async def test_a_waiting_claim_can_be_taken_back_and_made_again(client, db, seeded, admin_is_panthaky):
    headers, user = await _settings_mobed(client, seeded)
    aid = seeded["agyary_id"]
    assert (await client.post(f"/api/mobed/agyaries/{aid}/panthaky-claim", headers=headers)).status_code == 200
    r = await client.delete(f"/api/mobed/agyaries/{aid}/panthaky-claim", headers=headers)
    assert r.status_code == 200, r.text
    [temple] = r.json()["agyaries"]
    assert (temple["claimed_role"], temple["panthaky_claim_waiting"], temple["may_claim_panthaky"]) == (
        None, False, True)
    m = await _membership(db, user["id"], aid)
    assert (m.role, m.claimed_role, m.claimed_at) == ("mobed", None, None)
    # Nothing to take back now.
    again = await client.delete(f"/api/mobed/agyaries/{aid}/panthaky-claim", headers=headers)
    assert again.status_code == 409
    assert (await client.post(f"/api/mobed/agyaries/{aid}/panthaky-claim", headers=headers)).status_code == 200


async def test_settings_cannot_claim_for_someone_who_answered_or_is_panthaky(client, db, seeded):
    aid = seeded["agyary_id"]
    headers, _ = await _new(client, approve=True)
    await client.post(f"/api/mobed/agyaries/{aid}/join", json={"claimed_role": "mobed"}, headers=headers)
    r = await client.post(f"/api/mobed/agyaries/{aid}/panthaky-claim", headers=headers)
    assert r.status_code == 409 and "mobed here" in r.json()["detail"]

    panthaky = {"Authorization": f"Bearer {(await sign_in(client, seeded['panthaky_phone']))['access_token']}"}
    r = await client.post(f"/api/mobed/agyaries/{aid}/panthaky-claim", headers=panthaky)
    assert r.status_code == 409 and r.json()["detail"] == "You are already the panthaky here."
    assert (await client.delete(f"/api/mobed/agyaries/{aid}/panthaky-claim", headers=panthaky)).status_code == 409


async def test_settings_claim_needs_access_and_membership(client, db, seeded):
    aid = seeded["agyary_id"]
    waiting, _ = await _new(client)          # pending: not let in yet (D9)
    await client.post(f"/api/mobed/agyaries/{aid}/join", headers=waiting)
    r = await client.post(f"/api/mobed/agyaries/{aid}/panthaky-claim", headers=waiting)
    assert r.status_code == 403 and r.headers["X-Mobed-Access"] == "pending"

    other = Agyary(name="Not Theirs", city="Pune", status="active")
    db.add(other)
    await db.commit()
    headers, _ = await _settings_mobed(client, seeded)
    assert (await client.post(f"/api/mobed/agyaries/{other.id}/panthaky-claim", headers=headers)).status_code == 403
    assert (await client.post("/api/mobed/agyaries/99999/panthaky-claim", headers=headers)).status_code == 404


# --- The owner's word: confirm, not the panthaky, remove ----------------------

async def _colleagues_work(client, seeded) -> tuple[int, int]:
    """A machi and a booking by the seeded mobed at the seeded temple."""
    machi_id = await _colleagues_machi(client, seeded)
    body = await sign_in(client, seeded["mobed_phone"])
    owner = {"Authorization": f"Bearer {body['access_token']}"}
    made = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/manual-add/booking", headers=owner, json={
        "behdin_phone": "+919944400802", "behdin_name": "Colleagues Booking Family",
        "service_id": 2, "ceremony_datetime": "2030-08-20T10:00:00", "purpose": "khushali_nu",
        "names": [], "location": None, "is_offsite": False,
    })
    assert made.status_code == 200, made.text
    return machi_id, made.json()["booking_id"]


async def _powers(client, db, seeded, headers, user_id, machi_id, booking_id) -> dict:
    """What a person at the seeded temple can see of a colleague's work, and
    whether the app counts them among the temple's admins (ADMIN_ROLES)."""
    from agyary.messaging import booking_service
    from agyary.services import mobed_dashboard

    aid = seeded["agyary_id"]
    board = (await client.get(f"/api/mobed/agyaries/{aid}/machi-board?{WINDOW}&mine=false", headers=headers)).json()

    async def status(path: str) -> int:
        return (await client.get(f"/api/mobed/agyaries/{aid}/{path}", headers=headers)).status_code

    return {
        "board": [m["id"] for m in board],
        "machi_detail": await status(f"machis/{machi_id}/detail"),
        "machi_slip": await status(f"machis/{machi_id}/slip"),
        "booking_detail": await status(f"bookings/{booking_id}/detail"),
        "booking_slip": await status(f"bookings/{booking_id}/slip"),
        "is_admin": await mobed_dashboard.is_admin(db, aid, user_id),
        "in_get_admins": user_id in [u.id for u in await booking_service.get_admins(db, aid)],
    }


NO_POWERS = {"board": [], "machi_detail": 404, "machi_slip": 404, "booking_detail": 404, "booking_slip": 404,
             "is_admin": False, "in_get_admins": False}


async def _claimant(client, seeded):
    headers, user = await _new(client, approve=True)
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", json={"claimed_role": "panthaky"},
                          headers=headers)
    assert r.status_code == 200, r.text
    return headers, user


async def _admin(client, seeded) -> dict:
    return {"Authorization": f"Bearer {(await sign_in(client, seeded['panthaky_phone']))['access_token']}"}


async def _decide(client, admin, user_id, aid, decision):
    return await client.post(f"/api/mobed/admin/mobeds/{user_id}/panthaky",
                             json={"agyary_id": aid, "decision": decision}, headers=admin)


async def test_the_admin_sees_the_claim_and_confirms_it(client, db, seeded, admin_is_panthaky, caplog):
    machi_id, booking_id = await _colleagues_work(client, seeded)
    aid = seeded["agyary_id"]
    headers, user = await _claimant(client, seeded)
    admin = await _admin(client, seeded)

    # Before: nothing of a panthaky's.
    assert await _powers(client, db, seeded, headers, user["id"], machi_id, booking_id) == NO_POWERS

    listed = (await client.get("/api/mobed/admin/mobeds", headers=admin)).json()
    assert listed["panthaky_claims"] == 1
    [row] = [m for m in listed["mobeds"] if m["id"] == user["id"]]
    assert row["panthaky_claim_waiting"] is True
    [t] = row["memberships"]
    assert (t["agyary_id"], t["name"], t["role"], t["claimed_role"], t["panthaky_claim_waiting"]) == (
        aid, "Goti Adarian", "mobed", "panthaky", True)
    assert t["other_panthakys"] == ["Er. Hormuz Dadachanji"]
    assert (await client.get("/api/mobed/admin/overview", headers=admin)).json()["panthaky_claims_waiting"] == 1

    caplog.set_level("INFO")
    r = await _decide(client, admin, user["id"], aid, "confirm")
    assert r.status_code == 200, r.text
    assert (r.json()["role"], r.json()["claim_decision"]) == ("panthaky", "confirmed")
    m = await _membership(db, user["id"], aid)
    panthaky_admin = (await db.execute(select(User).where(User.phone == seeded["panthaky_phone"]))).scalar_one()
    assert (m.role, m.claim_decision, m.claim_decided_by_user_id) == ("panthaky", "confirmed", panthaky_admin.id)
    assert m.claim_decided_at is not None
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert "confirmed user" in logged and "+91" not in logged

    # After: exactly what the temple's existing panthaky has.
    after = await _powers(client, db, seeded, headers, user["id"], machi_id, booking_id)
    existing = await _powers(client, db, seeded, admin, panthaky_admin.id, machi_id, booking_id)
    assert after == existing
    assert after["board"] == [machi_id] and after["is_admin"] and after["in_get_admins"]
    assert after["machi_detail"] == after["booking_detail"] == 200

    # They are told, and Settings says so.
    titles = [n["title"] for n in (await client.get("/api/mobed/notifications", headers=headers)).json()]
    assert "You are the panthaky of Goti Adarian" in titles
    [temple] = (await client.get("/api/mobed/auth/me", headers=headers)).json()["agyaries"]
    assert (temple["role"], temple["panthaky_claim_waiting"], temple["may_claim_panthaky"]) == (
        "panthaky", False, False)
    assert (await client.get("/api/mobed/admin/overview", headers=admin)).json()["panthaky_claims_waiting"] == 0
    # Not twice.
    assert (await _decide(client, admin, user["id"], aid, "confirm")).status_code == 409


async def test_not_the_panthaky_keeps_them_a_mobed_with_nothing_more(client, db, seeded, admin_is_panthaky):
    machi_id, booking_id = await _colleagues_work(client, seeded)
    aid = seeded["agyary_id"]
    headers, user = await _claimant(client, seeded)
    admin = await _admin(client, seeded)
    r = await _decide(client, admin, user["id"], aid, "decline")
    assert r.status_code == 200, r.text
    assert (r.json()["role"], r.json()["claim_decision"]) == ("mobed", "declined")
    m = await _membership(db, user["id"], aid)
    assert (m.role, m.claimed_role, m.claim_decision) == ("mobed", "panthaky", "declined")
    assert await _powers(client, db, seeded, headers, user["id"], machi_id, booking_id) == NO_POWERS
    titles = [n["title"] for n in (await client.get("/api/mobed/notifications", headers=headers)).json()]
    assert "Not confirmed as panthaky" in titles
    # Nothing waits now, and they cannot claim again from Settings.
    assert (await _decide(client, admin, user["id"], aid, "decline")).status_code == 409
    r = await client.post(f"/api/mobed/agyaries/{aid}/panthaky-claim", headers=headers)
    assert r.status_code == 409 and "already decided" in r.json()["detail"]
    # The admin can still change their mind.
    assert (await _decide(client, admin, user["id"], aid, "confirm")).status_code == 200


async def test_a_confirmed_panthaky_can_be_made_a_mobed_again(client, db, seeded, admin_is_panthaky):
    machi_id, booking_id = await _colleagues_work(client, seeded)
    aid = seeded["agyary_id"]
    headers, user = await _claimant(client, seeded)
    admin = await _admin(client, seeded)
    assert (await _decide(client, admin, user["id"], aid, "confirm")).status_code == 200
    r = await _decide(client, admin, user["id"], aid, "remove")
    assert r.status_code == 200, r.text
    assert (r.json()["role"], r.json()["claim_decision"]) == ("mobed", "removed")
    assert await _powers(client, db, seeded, headers, user["id"], machi_id, booking_id) == NO_POWERS
    titles = [n["title"] for n in (await client.get("/api/mobed/notifications", headers=headers)).json()]
    assert "No longer the panthaky of Goti Adarian" in titles
    assert (await _decide(client, admin, user["id"], aid, "remove")).status_code == 409


async def test_confirm_needs_a_claim_and_decisions_need_the_admin(client, db, seeded, admin_is_panthaky):
    aid = seeded["agyary_id"]
    admin = await _admin(client, seeded)
    plain = (await db.execute(select(User).where(User.phone == seeded["mobed_phone"]))).scalar_one()
    # Someone who never said they are the panthaky is not made one.
    assert (await _decide(client, admin, plain.id, aid, "confirm")).status_code == 409
    assert (await _membership(db, plain.id, aid)).role == "mobed"
    assert (await _decide(client, admin, plain.id, aid, "decline")).status_code == 409
    assert (await _decide(client, admin, plain.id, aid, "remove")).status_code == 409
    # Not at that temple, or no such mobed, or no such decision.
    other = Agyary(name="Elsewhere", city="Pune", status="active")
    db.add(other)
    await db.commit()
    assert (await _decide(client, admin, plain.id, other.id, "confirm")).status_code == 404
    assert (await _decide(client, admin, 99999, aid, "confirm")).status_code == 404
    assert (await _decide(client, admin, plain.id, aid, "promote")).status_code == 422

    # A mobed who is not an admin - the claimant themselves included - gets a 404.
    headers, user = await _claimant(client, seeded)
    for decision in ("confirm", "decline", "remove"):
        assert (await _decide(client, headers, user["id"], aid, decision)).status_code == 404
    assert (await client.get("/api/mobed/admin/mobeds", headers=headers)).status_code == 404
    assert (await _membership(db, user["id"], aid)).role == "mobed"


# --- Who a fire temple's requests go to (for Step 4) ---------------------------

async def _person(db, aid, phone, name, role="mobed", *, access="on", active=True, member_active=True,
                  claimed_role=None) -> User:
    from datetime import datetime, timezone

    user = User(name=name, phone=phone, access=access, is_active=active)
    db.add(user)
    await db.flush()
    db.add(AgyaryUser(agyary_id=aid, user_id=user.id, role=role, is_active=member_active,
                      claimed_role=claimed_role,
                      claimed_at=datetime.now(timezone.utc) if claimed_role else None))
    await db.commit()
    return user


async def test_requests_go_to_the_confirmed_panthakys(db, seeded):
    from agyary.services import panthaky

    s = config.get_settings()
    temple = Agyary(name="Recipients Agiary", city="Navsari", status="active")
    db.add(temple)
    await db.commit()
    one = await _person(db, temple.id, "+919955500001", "Er. Panthaky One", "panthaky")
    two = await _person(db, temple.id, "+919955500002", "Er. Panthaky Two", "panthaky")
    await _person(db, temple.id, "+919955500003", "Er. Panthaky Off", "panthaky", access="off")
    await _person(db, temple.id, "+919955500004", "Er. Panthaky Waiting", "panthaky", access="pending")
    await _person(db, temple.id, "+919955500005", "Er. Panthaky Left", "panthaky", member_active=False)
    await _person(db, temple.id, "+919955500006", "Er. Panthaky Gone", "panthaky", active=False)
    await _person(db, temple.id, "+919955500007", "Er. Says Panthaky", claimed_role="panthaky")
    await _person(db, temple.id, "+919955500008", "Er. Plain Mobed")

    assert [u.id for u in await panthaky.panthakys_of(db, s, temple.id)] == [one.id, two.id]
    assert [u.id for u in await panthaky.request_recipients(db, s, temple.id)] == [one.id, two.id]
    # Another temple's panthaky is not this one's.
    assert [u.name for u in await panthaky.panthakys_of(db, s, seeded["agyary_id"])] == ["Er. Hormuz Dadachanji"]


async def test_with_no_panthaky_requests_go_to_its_mobeds_whose_access_is_on(db, seeded):
    from agyary.services import panthaky

    s = config.get_settings()
    temple = Agyary(name="Mobeds Only Agiary", city="Udvada", status="active")
    db.add(temple)
    await db.commit()
    await _person(db, temple.id, "+919955500011", "Er. Panthaky Off", "panthaky", access="off")
    claimant = await _person(db, temple.id, "+919955500012", "Er. Says Panthaky", claimed_role="panthaky")
    plain = await _person(db, temple.id, "+919955500013", "Er. Plain Mobed")
    await _person(db, temple.id, "+919955500014", "Er. Mobed Off", access="off")
    await _person(db, temple.id, "+919955500015", "Er. Mobed Waiting", access="pending")
    await _person(db, temple.id, "+919955500016", "Er. Mobed Left", member_active=False)
    await _person(db, temple.id, "+919955500017", "Er. Caretaker", "caretaker")

    assert await panthaky.panthakys_of(db, s, temple.id) == []
    # The claimant is reached as the mobed they still are, never as a panthaky.
    assert [u.id for u in await panthaky.request_recipients(db, s, temple.id)] == [claimant.id, plain.id]

    empty = Agyary(name="Nobody Agiary", city="Surat", status="active")
    db.add(empty)
    await db.commit()
    assert await panthaky.request_recipients(db, s, empty.id) == []


async def test_a_confirmed_claim_moves_requests_to_the_new_panthaky(client, db, seeded, admin_is_panthaky):
    from agyary.services import panthaky

    s = config.get_settings()
    headers, user = await _new(client, approve=True)
    r = await client.post("/api/mobed/agyaries", json={"name": "New Agiary", "city": "Pune",
                                                       "claimed_role": "panthaky"}, headers=headers)
    aid = r.json()["agyary"]["id"]
    colleague, mate = await _new(client, phone="+919911100089", name="Er. Colleague", approve=True)
    await client.post(f"/api/mobed/agyaries/{aid}/join", json={"claimed_role": "mobed"}, headers=colleague)
    assert [u.id for u in await panthaky.request_recipients(db, s, aid)] == [user["id"], mate["id"]]

    admin = await _admin(client, seeded)
    assert (await _decide(client, admin, user["id"], aid, "confirm")).status_code == 200
    db.expire_all()
    assert [u.id for u in await panthaky.request_recipients(db, s, aid)] == [user["id"]]
