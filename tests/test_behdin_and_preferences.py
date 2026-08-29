"""Explicit behdin records, their saved name pool, per-user display
preferences, the tandarosti section fix, and the bounded machi board."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from agyary.models import (
    AgyaryCustomer,
    CeremonyName,
    Customer,
    CustomerSavedName,
    Machi,
    UserPreferences,
)
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


async def test_register_lists_behdins_who_have_never_booked(db, client, seeded):
    """The register has to include someone added a minute ago.

    This is why the register exists at all: the old booking-derived
    customer search could only see people who already had a ceremony on
    file, which made it useless at the one moment it was most needed -
    looking up the behdin you just registered in order to book for them."""
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    created = await _behdin(client, aid, headers)

    listed = (await client.get(f"/api/mobed/agyaries/{aid}/behdins", headers=headers)).json()
    assert created["id"] in [b["id"] for b in listed]

    filtered = (
        await client.get(f"/api/mobed/agyaries/{aid}/behdins", params={"q": "Jaidev"}, headers=headers)
    ).json()
    assert [b["id"] for b in filtered] == [created["id"]]
    assert (
        await client.get(f"/api/mobed/agyaries/{aid}/behdins", params={"q": "zzzz"}, headers=headers)
    ).json() == []


async def test_a_mobed_cannot_see_another_mobeds_behdins(db, client, seeded):
    """The behdin list is one mobed's own book, not the fire temple's
    register. A behdin's name and phone number are their own; a colleague
    at the same temple has no business reading them.

    Enforced server-side on every read - listing, fetching by id, and the
    saved-name pool - because a list filtered in the client is not a
    permission.
    """
    aid = seeded["agyary_id"]
    mine = await _member_headers(client, seeded)
    theirs = await _member_headers(client, seeded, name="Colleague", phone="+919944400222")

    created = await _behdin(client, aid, mine, name="Private Behdin", phone="+919944400333")
    cid = created["id"]

    # Not in their list...
    listed = (await client.get(f"/api/mobed/agyaries/{aid}/behdins", headers=theirs)).json()
    assert listed == []
    # ...not findable by searching for the name or the number...
    for q in ("Private", "9944400333"):
        found = (
            await client.get(f"/api/mobed/agyaries/{aid}/behdins", params={"q": q}, headers=theirs)
        ).json()
        assert found == [], q
    # ...and not reachable by guessing the id, on any of the three reads.
    assert (await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}", headers=theirs)).status_code == 404
    assert (
        await client.get(f"/api/mobed/agyaries/{aid}/behdins/{cid}/saved-names", headers=theirs)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/mobed/agyaries/{aid}/behdins/{cid}", json={"name": "Hijacked"}, headers=theirs
        )
    ).status_code == 404

    # The owner still sees them.
    assert [b["id"] for b in (await client.get(f"/api/mobed/agyaries/{aid}/behdins", headers=mine)).json()] == [cid]


async def test_serving_a_behdin_adds_them_to_your_book(db, client, seeded):
    """Most behdins arrive by being served, not registered: a walk-in
    dictated at the counter goes straight into an event. Without this they
    would never appear in the mobed's own list."""
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)

    r = await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/booking",
        json={
            "behdin_phone": "+919944400444", "behdin_name": "Walk-in Family",
            "service_id": 2, "ceremony_datetime": "2028-03-01T10:00:00",
            "purpose": "khushali_nu",
            "names": [{"section": "farmayeshne", "title": "behdin", "name": "X", "status": "living", "pair_group": None}],
            "location": None, "is_offsite": False,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text

    listed = (await client.get(f"/api/mobed/agyaries/{aid}/behdins", headers=headers)).json()
    assert "Walk-in Family" in [b["name"] for b in listed]


async def test_register_is_scoped_to_the_agyari(db, client, seeded):
    from agyary.models import Agyary

    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    mine = await _behdin(client, aid, headers)

    other = Agyary(name="Register Elsewhere", city="Pune", status="active")
    db.add(other)
    await db.commit()
    other_headers = await _member_headers(client, seeded, name="Other Temple Mobed", phone="+919944400088")
    await client.post(f"/api/mobed/agyaries/{other.id}/join", headers=other_headers)

    listed = (await client.get(f"/api/mobed/agyaries/{other.id}/behdins", headers=other_headers)).json()
    assert mine["id"] not in [b["id"] for b in listed]


async def test_register_requires_membership(db, client, seeded):
    from tests.test_mobed_auth import _headers as _bare_headers

    outsider = await _bare_headers(client, phone="+919944400099", name="Outsider")
    r = await client.get(f"/api/mobed/agyaries/{seeded['agyary_id']}/behdins", headers=outsider)
    assert r.status_code == 403


async def test_logout_clears_the_refresh_cookie(db, client, seeded):
    """Sign-out has to be a server round trip: the refresh cookie is
    httpOnly, so without this the next page load signs you straight back
    in - which on a shared phone is the opposite of signing out."""
    await _member_headers(client, seeded)
    assert (await client.post("/api/mobed/auth/refresh")).status_code == 200

    assert (await client.post("/api/mobed/auth/logout")).status_code == 200
    assert (await client.post("/api/mobed/auth/refresh")).status_code == 401


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


async def test_machi_omitted_names_auto_pulls_the_saved_pool(db, client, seeded):
    """The New Machi screen never sends a names key at all - same contract
    as manual_add_booking. Patet pulls the saved pair, tandarosti would
    pull living-only."""
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    phone = "+919944400099"
    behdin = await _behdin(client, aid, headers, name="Auto Pull Behdin", phone=phone)

    await client.put(
        f"/api/mobed/agyaries/{aid}/behdins/{behdin['id']}/saved-names/pair",
        json={"names": [
            {"title": "ervad", "name": "Saved One", "status": "departed", "pair_group": 1},
            {"title": "ervad", "name": "Saved Two", "status": "departed", "pair_group": 1},
        ]},
        headers=headers,
    )

    r = await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/machi",
        json={
            "behdin_phone": phone, "behdin_name": "Auto Pull Behdin",
            "roj": 4, "mah": 6, "year": 1396, "geh": 1, "gregorian": "2027-07-10",
            "purpose": "patet",
        },
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["confirmed"] is True

    rows = (await db.execute(select(CeremonyName))).scalars().all()
    assert sorted(n.name for n in rows) == ["Saved One", "Saved Two"]


async def test_editing_a_machi_without_names_repulls_the_saved_pool(db, client, seeded):
    """Editing is not the place to notice the saved pool has moved on since
    creation and keep serving the stale copy - same contract as
    edit_booking."""
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    phone = "+919944400098"
    await _behdin(client, aid, headers, name="Repull Behdin", phone=phone)

    r = await client.post(
        f"/api/mobed/agyaries/{aid}/manual-add/machi",
        json={
            "behdin_phone": phone, "behdin_name": "Repull Behdin",
            "roj": 5, "mah": 6, "year": 1396, "geh": 2, "gregorian": "2027-07-11",
            "purpose": "patet",
            "names": [
                {"section": "pair", "title": "ervad", "name": "Old A", "status": "departed", "pair_group": 1},
                {"section": "pair", "title": "ervad", "name": "Old B", "status": "departed", "pair_group": 1},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["confirmed"] is True
    mid = r.json()["machi_id"]

    # The saved pool changes after creation - editing should pick up the
    # current pool rather than keeping the original "Old A"/"Old B".
    behdin = (await client.get(f"/api/mobed/agyaries/{aid}/behdins", params={"q": phone}, headers=headers)).json()[0]
    await client.put(
        f"/api/mobed/agyaries/{aid}/behdins/{behdin['id']}/saved-names/pair",
        json={"names": [
            {"title": "ervad", "name": "New A", "status": "departed", "pair_group": 1},
            {"title": "ervad", "name": "New B", "status": "departed", "pair_group": 1},
        ]},
        headers=headers,
    )

    r2 = await client.put(
        f"/api/mobed/agyaries/{aid}/machis/{mid}",
        json={
            "behdin_phone": phone, "behdin_name": "Repull Behdin",
            "roj": 5, "mah": 6, "year": 1396, "geh": 2, "gregorian": "2027-07-11",
            "purpose": "patet",
        },
        headers=headers,
    )
    assert r2.status_code == 200 and r2.json()["confirmed"] is True

    rows = (await db.execute(select(CeremonyName).where(CeremonyName.machi_id == mid))).scalars().all()
    assert sorted(n.name for n in rows) == ["New A", "New B"]


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


async def test_machi_board_mine_scopes_to_the_caller(db, client, seeded):
    """The mobed app must never pull the fire temple's whole board: a mobed
    has no need of every machi there, and the unfiltered rows carry other
    mobeds' behdin names."""
    aid = seeded["agyary_id"]
    mine = await _member_headers(client, seeded)
    theirs = await _member_headers(client, seeded, name="Other Mobed", phone="+919944400123")

    await _add_machi(
        client, aid, mine, "patet",
        [
            {"section": "pair", "title": "ervad", "name": "A", "status": "departed", "pair_group": 1},
            {"section": "pair", "title": "ervad", "name": "B", "status": "departed", "pair_group": 1},
        ],
        geh=1,
    )
    url = f"/api/mobed/agyaries/{aid}/machi-board"
    window = {"from": "2027-06-01", "to": "2027-06-30"}

    # The other mobed sees it on the agyari-wide board...
    everyones = await client.get(url, params=window, headers=theirs)
    assert len(everyones.json()) == 1
    # ...but not among their own.
    only_theirs = await client.get(url, params={**window, "mine": "true"}, headers=theirs)
    assert only_theirs.json() == []
    # The mobed who entered it does.
    only_mine = await client.get(url, params={**window, "mine": "true"}, headers=mine)
    assert len(only_mine.json()) == 1


async def test_slip_reads_in_the_mobeds_primary_calendar(db, client, seeded):
    """A mobed prints and uses these slips themselves, so the slip reads the
    way they read - not in whatever system the record was stamped with."""
    from agyary.calendar import CalendarSystem, gregorian_to_parsi

    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    mid = (
        await _add_machi(
            client, aid, headers, "patet",
            [
                {"section": "pair", "title": "ervad", "name": "A", "status": "departed", "pair_group": 1},
                {"section": "pair", "title": "ervad", "name": "B", "status": "departed", "pair_group": 1},
            ],
            geh=4,
        )
    ).json()["machi_id"]

    day = date(2027, 6, 15)
    readings = {}
    for system in ("shenshai", "kadmi", "fasli"):
        r = await client.put(
            "/api/mobed/me/preferences",
            json={
                "visible_calendar_systems": ["gregorian", system],
                "default_secondary_system": system,
                "display_language": "en",
            },
            headers=headers,
        )
        assert r.status_code == 200, r.text
        slip = (await client.get(f"/api/mobed/agyaries/{aid}/machis/{mid}/slip", headers=headers)).json()
        readings[system] = slip["when"]
        # The slip's Roj name must be that system's reading of the day.
        expected = gregorian_to_parsi(day, CalendarSystem(system)).roj_name
        assert expected in slip["when"], (system, slip["when"], expected)

    # And the three genuinely differ - otherwise the assertions above could
    # pass on a slip that never changed at all.
    assert len(set(readings.values())) == 3, readings

    # The stored record is untouched by any of it.
    machi = await db.get(Machi, mid)
    await db.refresh(machi)
    assert machi.calendar_system == "shenshai"


async def test_machi_board_rejects_a_silly_window(db, client, seeded):
    aid = seeded["agyary_id"]
    headers = await _member_headers(client, seeded)
    url = f"/api/mobed/agyaries/{aid}/machi-board"

    backwards = await client.get(url, params={"from": "2027-06-30", "to": "2027-06-01"}, headers=headers)
    assert backwards.status_code == 400

    huge = await client.get(url, params={"from": "2020-01-01", "to": "2030-01-01"}, headers=headers)
    assert huge.status_code == 400
