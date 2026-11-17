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
