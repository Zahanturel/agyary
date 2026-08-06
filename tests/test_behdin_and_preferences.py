"""Explicit behdin records, their saved name pool, per-user display
preferences, the tandarosti section fix, and the bounded machi board."""

from __future__ import annotations

from sqlalchemy import select

from agyary.models import AgyaryCustomer, CeremonyName, Customer, CustomerSavedName, UserPreferences
from tests.test_mobed_api import _member_headers

BEHDIN_PHONE = "+919944400001"


async def _behdin(client, aid, headers, name="Behdin Jaidev", phone=BEHDIN_PHONE) -> dict:
    r = await client.post(
        f"/api/mobed/agyaries/{aid}/behdins", json={"name": name, "phone": phone}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Display preferences (3b)
# ---------------------------------------------------------------------------
async def test_preferences_default_without_a_row(db, client, seeded):
    headers = await _member_headers(client, seeded)
    body = (await client.get("/api/mobed/me/preferences", headers=headers)).json()
    assert body == {
        "visible_calendar_systems": ["gregorian", "shenshai"],
        "default_secondary_system": "shenshai",
        "display_language": "en",
    }
    # Reading preferences must not create a row.
    assert (await db.execute(select(UserPreferences))).scalars().all() == []


async def test_preferences_round_trip(db, client, seeded):
    headers = await _member_headers(client, seeded)
    payload = {
        "visible_calendar_systems": ["gregorian", "shenshai", "kadmi", "fasli"],
        "default_secondary_system": "kadmi",
        "display_language": "gu",
    }
    r = await client.put("/api/mobed/me/preferences", json=payload, headers=headers)
    assert r.status_code == 200 and r.json() == payload
    assert (await client.get("/api/mobed/me/preferences", headers=headers)).json() == payload

    stored = (await db.execute(select(UserPreferences))).scalar_one()
    assert stored.display_language == "gu"


async def test_preferences_reject_unknown_values(db, client, seeded):
    headers = await _member_headers(client, seeded)
    base = {
        "visible_calendar_systems": ["gregorian", "shenshai"],
        "default_secondary_system": "shenshai",
        "display_language": "en",
    }
    bad = [
        {**base, "visible_calendar_systems": ["gregorian", "julian"]},
        {**base, "visible_calendar_systems": []},
        # Gregorian is the other half of the pair, never the secondary.
        {**base, "default_secondary_system": "gregorian"},
        # A secondary that isn't even shown would be unrenderable.
        {**base, "visible_calendar_systems": ["gregorian", "shenshai"], "default_secondary_system": "fasli"},
        {**base, "display_language": "fr"},
    ]
    for payload in bad:
        r = await client.put("/api/mobed/me/preferences", json=payload, headers=headers)
        assert r.status_code == 400, payload


async def test_preferences_do_not_touch_agyary_calendar_system(db, client, seeded):
    """The per-user view setting and the field that stamps ceremony records
    are separate concerns and must stay that way."""
    from agyary.models import Agyary

    headers = await _member_headers(client, seeded)
    before = (await db.get(Agyary, seeded["agyary_id"])).calendar_system
    await client.put(
        "/api/mobed/me/preferences",
        json={
            "visible_calendar_systems": ["gregorian", "kadmi"],
            "default_secondary_system": "kadmi",
            "display_language": "en",
        },
        headers=headers,
    )
    agyary = await db.get(Agyary, seeded["agyary_id"])
    await db.refresh(agyary)
    assert agyary.calendar_system == before == "shenshai"


async def test_preferences_are_per_user(db, client, seeded):
    mine = await _member_headers(client, seeded)
    theirs = await _member_headers(client, seeded, name="Other Mobed", phone="+919944400099")
    await client.put(
        "/api/mobed/me/preferences",
        json={
            "visible_calendar_systems": ["gregorian", "fasli"],
            "default_secondary_system": "fasli",
            "display_language": "gu",
        },
        headers=mine,
    )
    assert (await client.get("/api/mobed/me/preferences", headers=theirs)).json()[
        "display_language"
    ] == "en"


async def test_preferences_require_auth(client):
    assert (await client.get("/api/mobed/me/preferences")).status_code == 401


# ---------------------------------------------------------------------------
# Behdin records (3c)
# ---------------------------------------------------------------------------
async def test_create_get_and_update_behdin(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)

    created = await _behdin(client, aid, headers)
    assert created["created"] is True and created["name"] == "Behdin Jaidev"

    fetched = (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{created['id']}", headers=headers)).json()
    assert fetched["phone"] == BEHDIN_PHONE

    r = await client.patch(
        f"/api/mobed/agyaries/{aid}/behdins/{created['id']}",
        json={"name": "Behdin Jaidev Mistry", "phone": "+919944400002"},
        headers=headers,
    )
    assert r.status_code == 200
    customer = await db.get(Customer, created["id"])
    await db.refresh(customer)
    assert customer.name == "Behdin Jaidev Mistry" and customer.phone == "+919944400002"


async def test_registering_does_not_claim_they_booked(db, client, seeded):
    """The junction's first_booking_at is a fact about bookings; registering
    someone must leave it alone or 'known to us' and 'has booked here'
    collapse into one."""
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    created = await _behdin(client, aid, headers)

    junction = (
        await db.execute(
            select(AgyaryCustomer).where(
                AgyaryCustomer.agyary_id == aid, AgyaryCustomer.customer_id == created["id"]
            )
        )
    ).scalar_one()
    assert junction.first_booking_at is None


async def test_known_phone_links_instead_of_duplicating(db, client, seeded):
    """Phone is the identity: a behdin who visits a second temple keeps one
    record and one history rather than being duplicated."""
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    first = await _behdin(client, aid, headers)

    again = await _behdin(client, aid, headers, name="Typed Differently")
    assert again["created"] is False and again["id"] == first["id"]
    # An existing person's stored name is not silently rewritten.
    assert again["name"] == "Behdin Jaidev"

    rows = (await db.execute(select(Customer).where(Customer.phone == BEHDIN_PHONE))).scalars().all()
    assert len(rows) == 1


async def test_update_refuses_to_merge_two_behdins(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    a = await _behdin(client, aid, headers, name="A", phone="+919944400011")
    await _behdin(client, aid, headers, name="B", phone="+919944400012")

    r = await client.patch(
        f"/api/mobed/agyaries/{aid}/behdins/{a['id']}",
        json={"phone": "+919944400012"},
        headers=headers,
    )
    assert r.status_code == 400 and "already registered" in r.json()["detail"]


async def test_behdin_endpoints_are_scoped_to_the_agyari(db, client, seeded):
    """A behdin registered at another temple is a 404 here - whether a given
    person is on file elsewhere is not this caller's business."""
    from agyary.models import Agyary

    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    created = await _behdin(client, aid, headers)

    other = Agyary(name="Elsewhere Agiary", city="Surat", status="active")
    db.add(other)
    await db.commit()
    other_headers = await _member_headers(client, seeded, name="Elsewhere Mobed", phone="+919944400055")
    await client.post(f"/api/mobed/agyaries/{other.id}/join", headers=other_headers)

    r = await client.get(f"/api/mobed/agyaries/{other.id}/behdins/{created['id']}", headers=other_headers)
    assert r.status_code == 404


async def test_behdin_endpoints_require_membership(db, client, seeded):
    aid = seeded["agyary_id"]
    member = await _member_headers(client, seeded)
    created = await _behdin(client, aid, member)

    from tests.test_mobed_auth import _headers as _bare_headers

    outsider = await _bare_headers(client, phone="+919944400077", name="Not A Member")
    assert (
        await client.get(f"/api/mobed/agyaries/{aid}/behdins/{created['id']}", headers=outsider)
    ).status_code == 403


# ---------------------------------------------------------------------------
# Saved name pool (3d)
# ---------------------------------------------------------------------------
async def test_saved_names_round_trip_and_delete(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    cid = (await _behdin(client, aid, headers))["id"]
    base = f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names"

    pairs = {
        "names": [
            {"title": "ervad", "name": "Kaikhushru", "status": "departed", "pair_group": 1},
            {"title": "osti", "name": "Banoo", "status": "departed", "pair_group": 1},
        ]
    }
    r = await client.put(f"{base}/pair", json=pairs, headers=headers)
    assert r.status_code == 200 and len(r.json()) == 2

    singles = {"names": [{"title": "behdin", "name": "Jaidev", "status": "living", "pair_group": None}]}
    assert (await client.put(f"{base}/farmayeshne", json=singles, headers=headers)).status_code == 200

    listed = (await client.get(base, headers=headers)).json()
    assert len(listed) == 3
    assert {n["section"] for n in listed} == {"pair", "farmayeshne"}

    # Deleting one half of a pair takes the whole pair - a lone survivor
    # would be filtered out by complete_pairs and vanish unexplained.
    pair_row = next(n for n in listed if n["section"] == "pair")
    assert (await client.delete(f"{base}/{pair_row['id']}", headers=headers)).status_code == 200
    remaining = (await client.get(base, headers=headers)).json()
    assert [n["section"] for n in remaining] == ["farmayeshne"]


async def test_saved_names_reject_a_half_pair(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    cid = (await _behdin(client, aid, headers))["id"]
    base = f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names"

    for bad in [
        {"names": [{"title": "ervad", "name": "Alone", "status": "departed", "pair_group": 1}]},
        {"names": [{"title": "ervad", "name": "Ungrouped", "status": "departed", "pair_group": None}]},
        {
            "names": [
                {"title": "ervad", "name": "A", "status": "departed", "pair_group": 1},
                {"title": "osti", "name": "B", "status": "living", "pair_group": 1},
            ]
        },
    ]:
        r = await client.put(f"{base}/pair", json=bad, headers=headers)
        assert r.status_code == 400, bad


async def test_saved_names_are_the_rows_whatsapp_reads(db, client, seeded):
    """Not a parallel snapshot: what a mobed saves here is exactly what the
    behdin's own WhatsApp flow offers back to them."""
    from agyary.messaging import booking_service

    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    cid = (await _behdin(client, aid, headers))["id"]

    await client.put(
        f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names/pair",
        json={
            "names": [
                {"title": "ervad", "name": "Kaikhushru", "status": "departed", "pair_group": 1},
                {"title": "osti", "name": "Banoo", "status": "departed", "pair_group": 1},
            ]
        },
        headers=headers,
    )

    rows = await booking_service.saved_pairs(db, cid, departed_only=True)
    assert [r.name for r in booking_service.complete_pairs(rows)] == ["Kaikhushru", "Banoo"]


async def test_saved_names_replace_rather_than_append(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    cid = (await _behdin(client, aid, headers))["id"]
    base = f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names/farmayeshne"

    await client.put(
        base, json={"names": [{"title": "behdin", "name": "First", "status": "living"}]}, headers=headers
    )
    await client.put(
        base, json={"names": [{"title": "behdin", "name": "Second", "status": "living"}]}, headers=headers
    )
    rows = (await db.execute(select(CustomerSavedName).where(CustomerSavedName.customer_id == cid))).scalars().all()
    assert [r.name for r in rows] == ["Second"]


# ---------------------------------------------------------------------------
# Tandarosti section (3e)
# ---------------------------------------------------------------------------
async def _add_machi(client, aid, headers, purpose, names, geh=1):
    return await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/machi",
        json={
            "behdin_phone": "+919944400033", "behdin_name": "Tandarosti Family",
            "roj": 4, "mah": 5, "year": 1396, "geh": geh, "gregorian": "2027-06-15",
            "purpose": purpose, "names": names,
        },
        headers=headers,
    )


async def test_tandarosti_names_are_stored_as_farmayeshne(db, client, seeded):
    """Even when the client sends the old shape, the shared slot core
    normalises it - tandarosti names are the living family, which is what
    the farmayeshne section means, and is already how the saved pool stores
    the very same names."""
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    r = await _add_machi(
        client, aid, headers, "tandarosti",
        [{"section": "pair", "title": "khud", "name": "Zahan", "status": "living", "pair_group": None}],
    )
    assert r.status_code == 200 and r.json()["confirmed"] is True

    rows = (await db.execute(select(CeremonyName))).scalars().all()
    assert [(n.section, n.pair_group) for n in rows] == [("farmayeshne", None)]


async def test_patet_pairs_are_left_alone(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    r = await _add_machi(
        client, aid, headers, "patet",
        [
            {"section": "pair", "title": "ervad", "name": "A", "status": "departed", "pair_group": 1},
            {"section": "pair", "title": "ervad", "name": "B", "status": "departed", "pair_group": 1},
        ],
        geh=2,
    )
    assert r.status_code == 200 and r.json()["confirmed"] is True
    rows = (await db.execute(select(CeremonyName))).scalars().all()
    assert {(n.section, n.pair_group) for n in rows} == {("pair", 1)}


async def test_editing_a_machi_normalises_too(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    mid = (
        await _add_machi(
            client, aid, headers, "patet",
            [
                {"section": "pair", "title": "ervad", "name": "A", "status": "departed", "pair_group": 1},
                {"section": "pair", "title": "ervad", "name": "B", "status": "departed", "pair_group": 1},
            ],
            geh=3,
        )
    ).json()["machi_id"]

    r = await client.put(
        f"/api/mobed/agyaries/{aid}/machis/{mid}",
        json={
            "behdin_phone": "+919944400033", "behdin_name": "Tandarosti Family",
            "roj": 4, "mah": 5, "year": 1396, "geh": 3, "gregorian": "2027-06-15",
            "purpose": "tandarosti",
            "names": [{"section": "pair", "title": "khud", "name": "Zahan", "status": "living", "pair_group": None}],
        },
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["confirmed"] is True
    rows = (await db.execute(select(CeremonyName))).scalars().all()
    assert [(n.section, n.pair_group) for n in rows] == [("farmayeshne", None)]


# ---------------------------------------------------------------------------
# Machi board bounds (3f)
# ---------------------------------------------------------------------------
async def test_machi_board_requires_and_honours_a_window(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    await _add_machi(
        client, aid, headers, "patet",
        [
            {"section": "pair", "title": "ervad", "name": "A", "status": "departed", "pair_group": 1},
            {"section": "pair", "title": "ervad", "name": "B", "status": "departed", "pair_group": 1},
        ],
    )
    url = f"/api/mobed/agyaries/{aid}/machi-board"

    assert (await client.get(url, headers=headers)).status_code == 422  # window is required

    inside = await client.get(url, params={"from": "2027-06-01", "to": "2027-06-30"}, headers=headers)
    assert inside.status_code == 200 and len(inside.json()) == 1

    outside = await client.get(url, params={"from": "2027-07-01", "to": "2027-07-31"}, headers=headers)
    assert outside.status_code == 200 and outside.json() == []

    # Boundaries are inclusive on both ends.
    edge = await client.get(url, params={"from": "2027-06-15", "to": "2027-06-15"}, headers=headers)
    assert len(edge.json()) == 1


async def test_machi_board_rejects_a_silly_window(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    url = f"/api/mobed/agyaries/{aid}/machi-board"

    backwards = await client.get(url, params={"from": "2027-06-30", "to": "2027-06-01"}, headers=headers)
    assert backwards.status_code == 400

    huge = await client.get(url, params={"from": "2020-01-01", "to": "2030-01-01"}, headers=headers)
    assert huge.status_code == 400
