"""The security pass of Phase 2 and R3.1 (22 Nov 2026): what each fix makes
true, one section per fix. Outbound HTTP is mocked throughout; nothing is sent.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from agyary.core import config
from agyary.models import AppNotification, FuneralRequest, User
from agyary.services import funeral_whatsapp as fw
from agyary.services import prayer_callout, standbys
from tests.funeral_helpers import FAMILY
from tests.test_prayer_callout import LISTED, LIVE, MOBED, PANTHAKY, SECOND, Meta, _answers, _as, _list, _send, _signed_tap
from tests.test_standbys import REQUESTS, _all_set, _b, _reasks, _to


@pytest.fixture
def meta(monkeypatch):
    fake = Meta()
    monkeypatch.setattr(fw, "make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    from agyary.services import wa_send

    real = wa_send.send_text

    async def send_text(settings, phone, body, client=None):
        return await real(settings, phone, body, client=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))

    monkeypatch.setattr(wa_send, "send_text", send_text)
    return fake


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    from agyary.services import web_push

    async def capture(db, settings, user_ids, **kw):
        sent.append({"to": sorted(user_ids), **kw})
        return 0

    monkeypatch.setattr(web_push, "send_to_users", capture)
    return sent


@pytest.fixture
def live(monkeypatch):
    for key, value in LIVE.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


KIAS = "Er. Pervez Kias"


async def _request(db, rid) -> FuneralRequest:
    return await db.get(FuneralRequest, rid, populate_existing=True)


async def _user(db, phone) -> User:
    return (await db.execute(select(User).where(User.phone == phone))).scalar_one()


async def _notes(db, phone, kind=None) -> list[AppNotification]:
    user = await _user(db, phone)
    where = [AppNotification.user_id == user.id] + ([AppNotification.kind == kind] if kind else [])
    return list((await db.execute(select(AppNotification).where(*where).order_by(AppNotification.id))).scalars())


async def _add(client, aid, headers, name, phone) -> int:
    r = await client.post(_list(aid), json={"name": name, "phone": phone, "agreed": True}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["added"]


async def _remove(client, aid, headers, contact_id) -> None:
    r = await client.delete(f"{_list(aid)}/{contact_id}", headers=headers)
    assert r.status_code == 200, r.text


def _templates(meta, phone, name) -> list[dict]:
    return [m for m in _to(meta, phone) if m.get("type") == "template" and m["template"]["name"] == name]


# --- 1. A mobed taken off the list keeps nothing of what they were sent ---------------

async def test_a_removed_mobeds_old_yes_changes_nothing_and_gets_no_reply(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    contact = await _add(client, aid, panthaky, "Er. Listed", LISTED)
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=1)
    token = (await _answers(db))[LISTED].token
    assert _templates(meta, LISTED, "prayer_request_mobeds_v2")
    await _remove(client, aid, panthaky, contact)
    rows = list((await _answers(db)).values())
    assert await prayer_callout.left_out(db, config.get_settings(), aid, rows) == {
        (await _answers(db))[LISTED].id: prayer_callout.LEFT_THE_LIST}
    sent = len(meta.sent)

    for choice in ("y", "n", "x"):
        await _signed_tap(client, LISTED, f"pca:{token}:{choice}")
    row = (await _answers(db))[LISTED]
    assert row.answer is None and row.picked_at is None and row.backed_out_at is None
    assert len(meta.sent) == sent                # nothing back to them, nothing to anyone
    request = await _request(db, rid)
    assert request.status == "waiting" and request.taken_at is None
    assert await _notes(db, PANTHAKY, "prayer_callout_going") == []
    board = (await client.get(_b(rid), headers=panthaky)).json()
    assert board["places"] == [] and board["standbys"] == []

    # Added again, they are on the list again and their button counts.
    await _add(client, aid, panthaky, "Er. Listed", LISTED)
    await _signed_tap(client, LISTED, f"pca:{token}:y")
    assert (await _answers(db))[LISTED].picked_at is not None


async def test_a_removed_standby_is_never_asked_again(client, db, seeded, meta, pushes, live):
    aid = seeded["agyary_id"]
    rid, _ = await _all_set(client, db, aid)          # Er. Listed and Kias going, Er. Second on standby
    panthaky = await _as(client, PANTHAKY)
    second = (await _answers(db))[SECOND]
    await _remove(client, aid, panthaky, second.contact_id)
    board = (await client.get(_b(rid), headers=panthaky)).json()
    assert board["standbys"] == []
    asked = len(_reasks(meta, SECOND))      # the call-out at Send

    r = await client.post(f"{REQUESTS}/{rid}/back-out", headers=await _as(client, MOBED))
    assert r.status_code == 200, r.text
    assert len(_reasks(meta, SECOND)) == asked
    row = (await _answers(db))[SECOND]
    assert row.reasked_at is None and row.reask_token is None
    # The panthaky is told nobody is on standby, so they find someone.
    (note,) = await _notes(db, PANTHAKY, standbys.KIND_PLACE_OPENED)
    assert "nobody is on standby" in note.title


async def test_a_removed_mobed_holding_a_place_is_not_named_or_sent_the_details(client, db, seeded, meta, pushes,
                                                                                live):
    aid = seeded["agyary_id"]
    panthaky = await _as(client, PANTHAKY)
    contact = await _add(client, aid, panthaky, "Er. Listed", LISTED)
    rid, _, _ = await _send(client, db, aid, mobeds_wanted=2)
    answers = await _answers(db)
    await _signed_tap(client, LISTED, f"pca:{answers[LISTED].token}:y")
    assert (await _answers(db))[LISTED].picked_at is not None
    await _remove(client, aid, panthaky, contact)
    meta.sent.clear()
    await _signed_tap(client, MOBED, f"pca:{answers[MOBED].token}:y")
    assert (await _request(db, rid)).status == "all_set"

    # The details only to the one going who is still on the list; nothing at all to them.
    assert _to(meta, LISTED) == []
    assert len(_templates(meta, MOBED, "prayer_details_mobed_v3")) == 1
    # Not named to the family, the panthaky or the place.
    (family,) = _templates(meta, FAMILY, "prayers_all_set_family")
    words = " ".join(p["text"] for p in family["template"]["components"][0]["parameters"])
    assert KIAS in words and "Er. Listed" not in words and LISTED[3:] not in words
    for m in meta.sent:
        assert "Er. Listed" not in str(m) and LISTED[3:] not in str(m)
    for phone in (PANTHAKY, MOBED):
        for note in await _notes(db, phone, "funeral_request_all_set"):
            assert "Er. Listed" not in note.title + note.body
    board = (await client.get(_b(rid), headers=panthaky)).json()
    assert [g["name"] for g in board["all_set"]["going"]] == [KIAS]
