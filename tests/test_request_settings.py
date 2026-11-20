"""Settings -> Prayer requests (DECISIONS D10, changed 21 Nov 2026; R3.1 step 1).

A fire temple starts as Everyone at once with no safety net. Only a confirmed
panthaky of that fire temple, or the admin, reads or changes how requests
reach it: a mobed there, a mobed who only said they are the panthaky, and
another fire temple's panthaky get the same 404 as for a fire temple that does
not exist; a Doongerwadi manager is refused like everywhere else in the mobed
app, whichever fire temple is asked about. A wrong way or wrong minutes are
refused in plain words and change nothing; the minutes are kept under either
way. Nothing here sends anything.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select, update

from agyary.api.routes import mobed as mobed_routes
from agyary.api.routes.callouts import NO_AGYARI
from agyary.core import config
from agyary.models import Agyary, AgyaryUser, Notification
from agyary.services import request_settings
from tests.conftest import sign_in
from tests.funeral_helpers import agyari, auth, manager, member

PANTHAKY, MOBED, ADMIN = "+919800000001", "+919800000002", "+919800000003"
CLAIMED, OTHER_PANTHAKY = "+919822200111", "+919822200122"
NOWHERE = 999_999
DEFAULTS = {"mode": "everyone", "escalate_minutes": None}


def _path(aid) -> str:
    return f"/api/mobed/agyaries/{aid}/request-settings"


async def _as(client, phone, name="Er. Test Mobed"):
    return auth(await sign_in(client, phone, name))


async def _stored(db, aid) -> tuple[str, int | None]:
    return tuple((await db.execute(select(Agyary.request_mode, Agyary.request_escalate_minutes)
                                   .where(Agyary.id == aid))).one())


@pytest.fixture
def admin_phone(monkeypatch):
    monkeypatch.setenv("ADMIN_PHONES", ADMIN)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


async def test_a_fire_temple_starts_as_everyone_at_once_with_no_safety_net(client, db, seeded):
    aid = seeded["agyary_id"]
    r = await client.get(_path(aid), headers=await _as(client, PANTHAKY))
    assert r.status_code == 200, r.text
    assert r.json() == DEFAULTS
    assert await _stored(db, aid) == ("everyone", None)
    # One made later starts the same.
    later = await agyari(db, "New Agyari (test)", None)
    await db.commit()
    assert await _stored(db, later.id) == ("everyone", None)


async def test_the_confirmed_panthaky_reads_and_changes_it_and_the_minutes_stay_under_either_way(client, db, seeded):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    r = await client.put(_path(aid), json={"mode": "panthaky_first", "escalate_minutes": 30}, headers=panthaky)
    assert r.status_code == 200, r.text
    assert r.json() == {"mode": "panthaky_first", "escalate_minutes": 30}
    assert (await client.get(_path(aid), headers=panthaky)).json() == {"mode": "panthaky_first", "escalate_minutes": 30}
    assert await _stored(db, aid) == ("panthaky_first", 30)

    # Back to everyone at once: the minutes are kept as given (step 2 reads them only in panthaky_first).
    r = await client.put(_path(aid), json={"mode": "everyone", "escalate_minutes": 15}, headers=panthaky)
    assert r.status_code == 200 and r.json() == {"mode": "everyone", "escalate_minutes": 15}
    assert await _stored(db, aid) == ("everyone", 15)
    for minutes in (60, None):
        r = await client.put(_path(aid), json={"mode": "panthaky_first", "escalate_minutes": minutes}, headers=panthaky)
        assert r.status_code == 200 and r.json() == {"mode": "panthaky_first", "escalate_minutes": minutes}
        assert await _stored(db, aid) == ("panthaky_first", minutes)
    # Leaving the minutes out is Never.
    r = await client.put(_path(aid), json={"mode": "everyone"}, headers=panthaky)
    assert r.status_code == 200 and r.json() == DEFAULTS
    # Nothing is sent by changing it.
    assert (await db.execute(select(Notification.id))).first() is None


async def test_the_admin_may_too_even_without_being_at_that_fire_temple(client, db, seeded, admin_phone):
    aid = seeded["agyary_id"]
    admin = await _as(client, ADMIN, "Test Admin")
    assert (await client.get(_path(aid), headers=admin)).json() == DEFAULTS
    r = await client.put(_path(aid), json={"mode": "panthaky_first", "escalate_minutes": 60}, headers=admin)
    assert r.status_code == 200 and r.json() == {"mode": "panthaky_first", "escalate_minutes": 60}
    assert await _stored(db, aid) == ("panthaky_first", 60)
    # A fire temple that does not exist, or is turned off, is not there for the admin either.
    assert (await client.get(_path(NOWHERE), headers=admin)).status_code == 404
    closed = await agyari(db, "Closed Agyari (test)", None)
    closed.is_active = False
    await db.commit()
    r = await client.put(_path(closed.id), json={"mode": "panthaky_first"}, headers=admin)
    assert r.status_code == 404 and r.json()["detail"] == NO_AGYARI


async def test_nobody_else_learns_it_exists_and_nobody_else_changes_it(client, db, seeded):
    aid = seeded["agyary_id"]
    temple = await db.get(Agyary, aid)
    claimant = await member(db, temple, CLAIMED, "mobed", name="Er. Says Panthaky")
    await db.execute(update(AgyaryUser).where(AgyaryUser.user_id == claimant.id)
                     .values(claimed_role="panthaky", claimed_at=datetime.now(timezone.utc)))
    other = await agyari(db, "Other Agyari (test)", None)
    await member(db, other, OTHER_PANTHAKY, "panthaky", name="Er. Other Panthaky")
    await db.commit()

    # What a fire temple that does not exist answers, to the panthaky themselves.
    missing = await client.get(_path(NOWHERE), headers=await _as(client, PANTHAKY))
    assert missing.status_code == 404 and missing.json() == {"detail": NO_AGYARI}

    for phone in (MOBED, CLAIMED, OTHER_PANTHAKY):
        headers = await _as(client, phone)
        for method, body in (("GET", None), ("PUT", {"mode": "panthaky_first", "escalate_minutes": 15})):
            r = await client.request(method, _path(aid), json=body, headers=headers)
            assert r.status_code == 404 and r.json() == missing.json(), (phone, method, r.text)
    # The other fire temple's panthaky manages their own.
    r = await client.get(_path(other.id), headers=await _as(client, OTHER_PANTHAKY))
    assert r.status_code == 200 and r.json() == DEFAULTS

    # A Doongerwadi manager: the mobed app's one answer to a manager, the same
    # for this fire temple as for one that does not exist.
    mgr, _ = await manager(client, db)
    for path in (_path(aid), _path(NOWHERE)):
        for method, body in (("GET", None), ("PUT", {"mode": "panthaky_first", "escalate_minutes": 15})):
            r = await client.request(method, path, json=body, headers=mgr)
            assert r.status_code == 403 and r.json()["detail"] == mobed_routes.NOT_FOR_MANAGERS, (path, method)
    assert await _stored(db, aid) == ("everyone", None)


async def test_a_wrong_way_or_wrong_minutes_are_refused_in_plain_words_and_change_nothing(client, db, seeded):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    assert (await client.put(_path(aid), json={"mode": "panthaky_first", "escalate_minutes": 30},
                             headers=panthaky)).status_code == 200
    wrong = [
        ({"mode": "whoever", "escalate_minutes": None}, "mode", request_settings.NO_MODE),
        ({"escalate_minutes": 15}, "mode", request_settings.NO_MODE),
        ({"mode": None}, "mode", request_settings.NO_MODE),
        ({"mode": 1}, "mode", request_settings.NO_MODE),
        ({"mode": ["everyone"]}, "mode", request_settings.NO_MODE),
        ({"mode": "panthaky_first", "escalate_minutes": 45}, "escalate_minutes", request_settings.NO_MINUTES),
        ({"mode": "panthaky_first", "escalate_minutes": 0}, "escalate_minutes", request_settings.NO_MINUTES),
        ({"mode": "everyone", "escalate_minutes": "15"}, "escalate_minutes", request_settings.NO_MINUTES),
        ({"mode": "panthaky_first", "escalate_minutes": 15.0}, "escalate_minutes", request_settings.NO_MINUTES),
        ({"mode": "panthaky_first", "escalate_minutes": True}, "escalate_minutes", request_settings.NO_MINUTES),
    ]
    for body, field, words in wrong:
        r = await client.put(_path(aid), json=body, headers=panthaky)
        assert r.status_code == 400, (body, r.text)
        assert r.json()["detail"] == words and r.headers["X-Field"] == field, body
    assert await _stored(db, aid) == ("panthaky_first", 30)
    assert (await client.get(_path(aid), headers=panthaky)).json() == {"mode": "panthaky_first", "escalate_minutes": 30}
