"""Mobed sign-in: WhatsApp OTP, and the invites that carry a role with them.

The property under test throughout is that knowing a phone number is not
enough - you have to hold it. And that self-serve sign-in can only ever
make you a plain mobed; anything above that has to be handed to you by
someone who already holds it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from agyary.models import AgyaryInvite, AgyaryUser, AuthOtp, User
from agyary.services import mobed_auth
from tests.conftest import SENT_OTPS

PHONE = "+919911100055"
OTHER_PHONE = "+919911100066"


async def _request(client, phone=PHONE):
    r = await client.post("/api/mobed/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, r.text
    return SENT_OTPS[phone]


async def _verify(client, code, phone=PHONE, name="Er. Test Mobed"):
    return await client.post(
        "/api/mobed/auth/otp/verify", json={"phone": phone, "code": code, "name": name}
    )


async def _sign_in(client, phone=PHONE, name="Er. Test Mobed") -> dict:
    r = await _verify(client, await _request(client, phone), phone=phone, name=name)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# OTP issue / verify
# ---------------------------------------------------------------------------
async def test_request_then_verify_creates_user_and_session(db, client, seeded):
    body = await _sign_in(client)
    assert body["user"]["phone"] == PHONE
    assert body["user"]["name"] == "Er. Test Mobed"
    assert body["access_token"]
    assert body["user"]["agyaries"] == []  # signing in joins nothing by itself

    user = (await db.execute(select(User).where(User.phone == PHONE))).scalar_one()
    assert user.name == "Er. Test Mobed"

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert (await client.get("/api/mobed/auth/me", headers=headers)).status_code == 200
    # The refresh cookie was set, so the sliding session still works.
    assert (await client.post("/api/mobed/auth/refresh")).status_code == 200


async def test_code_is_not_stored_in_plaintext(db, client, seeded):
    code = await _request(client)
    row = await db.get(AuthOtp, PHONE)
    assert row is not None
    assert code not in row.code_hash
    assert len(row.code_hash) == 64
    # Salted per phone: the same code for a different number hashes differently.
    assert row.code_hash != mobed_auth._hash_code(OTHER_PHONE, code)


async def test_wrong_code_is_rejected_and_burns_an_attempt(db, client, seeded):
    await _request(client)
    r = await _verify(client, "000000")
    assert r.status_code == 401
    assert (await db.get(AuthOtp, PHONE)).attempts == 1
    assert (await db.execute(select(User).where(User.phone == PHONE))).scalar_one_or_none() is None


async def test_code_dies_after_max_attempts(db, client, seeded):
    real = await _request(client)
    for _ in range(3):
        assert (await _verify(client, "000000")).status_code == 401
    # Even the correct code is now useless - the cap invalidates the code,
    # it doesn't merely refuse one more guess.
    assert (await _verify(client, real)).status_code == 401
    assert await db.get(AuthOtp, PHONE) is None


async def test_correct_code_is_single_use(db, client, seeded):
    code = await _request(client)
    assert (await _verify(client, code)).status_code == 200
    assert await db.get(AuthOtp, PHONE) is None
    assert (await _verify(client, code)).status_code == 401


async def test_expired_code_is_rejected(db, client, seeded):
    code = await _request(client)
    row = await db.get(AuthOtp, PHONE)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()

    r = await _verify(client, code)
    assert r.status_code == 401 and "expired" in r.json()["detail"].lower()
    assert await db.get(AuthOtp, PHONE) is None


async def test_verify_without_requesting_is_rejected(db, client, seeded):
    r = await _verify(client, "123456")
    assert r.status_code == 401
    assert (await db.execute(select(User).where(User.phone == PHONE))).scalar_one_or_none() is None


async def test_new_request_replaces_the_previous_code(db, client, seeded):
    first = await _request(client)
    second = await _request(client)
    assert first != second
    assert (await _verify(client, first)).status_code == 401
    assert (await _verify(client, second)).status_code == 200


async def test_request_does_not_reveal_whether_the_number_is_known(db, client, seeded):
    """An enumeration check: a registered number and a stranger's must be
    indistinguishable from the response alone."""
    await _sign_in(client)  # PHONE is now a known user
    known = await client.post("/api/mobed/auth/otp/request", json={"phone": PHONE})
    unknown = await client.post("/api/mobed/auth/otp/request", json={"phone": OTHER_PHONE})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


async def test_returning_signin_updates_name_without_duplicating_user(db, client, seeded):
    await _sign_in(client, name="Old Name")
    await _sign_in(client, name="New Name")
    users = (await db.execute(select(User).where(User.phone == PHONE))).scalars().all()
    assert len(users) == 1 and users[0].name == "New Name"


async def test_first_signin_requires_a_name(db, client, seeded):
    code = await _request(client)
    r = await _verify(client, code, name="")
    assert r.status_code == 400
    assert (await db.execute(select(User).where(User.phone == PHONE))).scalar_one_or_none() is None


async def test_per_phone_request_limit(db, client, seeded):
    """One person's WhatsApp can't be flooded through this endpoint even
    though each request on its own looks legitimate."""
    for _ in range(3):
        assert (
            await client.post("/api/mobed/auth/otp/request", json={"phone": PHONE})
        ).status_code == 200
    r = await client.post("/api/mobed/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 429


async def test_undeliverable_code_is_not_left_live(db, client, seeded, monkeypatch):
    """If WhatsApp won't take the message, the user must be told - and no
    code should be sitting in the table that they were never sent."""
    from agyary.services import otp_delivery

    async def boom(phone, code, client=None):
        raise otp_delivery.OtpDeliveryError("nope")

    monkeypatch.setattr("agyary.services.otp_delivery.send_login_otp", boom)
    r = await client.post("/api/mobed/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 503
    assert await db.get(AuthOtp, PHONE) is None


def test_delivery_refuses_to_no_op_in_production(monkeypatch):
    """Unconfigured WhatsApp in debug logs the code (the dev path). In
    production the same state has to raise, or every mobed is locked out
    with no indication why."""
    import asyncio
    import importlib

    import pytest

    from agyary.core import config
    from agyary.services import otp_delivery

    # conftest's autouse capture fixture has stubbed out the very function
    # under test; reload to get the real one back for this check.
    importlib.reload(otp_delivery)

    monkeypatch.setenv("APP_DEBUG", "false")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-not-for-production")
    monkeypatch.setenv("WHATSAPP_API_TOKEN", "")
    monkeypatch.setenv("WHATSAPP_OTP_PHONE_NUMBER_ID", "")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(otp_delivery.OtpDeliveryError):
            asyncio.run(otp_delivery.send_login_otp(PHONE, "123456"))
        # ...and in debug it's the dev no-op, not an error.
        monkeypatch.setenv("APP_DEBUG", "true")
        config.get_settings.cache_clear()
        asyncio.run(otp_delivery.send_login_otp(PHONE, "123456"))
    finally:
        config.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Invites: the only route to panthaky / caretaker
# ---------------------------------------------------------------------------
async def _headers(client, phone=PHONE, name="Er. Test Mobed") -> dict:
    return {"Authorization": f"Bearer {(await _sign_in(client, phone, name))['access_token']}"}


async def _joined_headers(client, seeded, phone=PHONE, name="Er. Test Mobed") -> dict:
    headers = await _headers(client, phone, name)
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)
    assert r.status_code == 200, r.text
    return headers


async def _admin_headers(client, seeded) -> dict:
    """The seeded agyari's panthaky - an already-privileged member, which is
    the normal case for issuing invites."""
    return await _headers(client, phone=seeded["panthaky_phone"], name="Er. Hormuz Dadachanji")


async def _invite(client, aid, headers, phone=OTHER_PHONE, role="panthaky"):
    return await client.post(
        f"/api/mobed/agyaries/{aid}/invites", json={"phone": phone, "role": role}, headers=headers
    )


async def test_self_serve_join_is_always_plain_mobed(db, client, seeded):
    await _joined_headers(client, seeded)
    user = (await db.execute(select(User).where(User.phone == PHONE))).scalar_one()
    membership = await mobed_auth.get_membership(db, seeded["agyary_id"], user.id)
    assert membership.role == "mobed"


async def test_invited_role_is_applied_at_signin(db, client, seeded):
    """The full hand-off: an admin invites a phone, that phone signs in, and
    lands already a member at the invited role - no search-and-join step."""
    aid = seeded["agyary_id"]
    r = await _invite(client, aid, await _admin_headers(client, seeded))
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "panthaky" and r.json()["redeemed_at"] is None

    body = await _sign_in(client, phone=OTHER_PHONE, name="Er. Invited Panthaky")
    assert [a["id"] for a in body["user"]["agyaries"]] == [aid]
    assert body["user"]["agyaries"][0]["role"] == "panthaky"

    invited = (await db.execute(select(User).where(User.phone == OTHER_PHONE))).scalar_one()
    assert (await mobed_auth.get_membership(db, aid, invited.id)).role == "panthaky"

    invite = (await db.execute(select(AgyaryInvite))).scalar_one()
    assert invite.redeemed_at is not None and invite.redeemed_by_user_id == invited.id


async def test_invite_also_redeems_on_manual_join(db, client, seeded):
    """Someone already signed in when the invite arrives shouldn't have to
    wait for their session to lapse to pick up the role."""
    aid = seeded["agyary_id"]
    invitee = await _headers(client, phone=OTHER_PHONE, name="Er. Later Joiner")
    await _invite(client, aid, await _admin_headers(client, seeded), role="caretaker")

    r = await client.post(f"/api/mobed/agyaries/{aid}/join", headers=invitee)
    assert r.json()["user"]["agyaries"][0]["role"] == "caretaker"


async def test_reinviting_replaces_rather_than_stacks(db, client, seeded):
    aid = seeded["agyary_id"]
    admin = await _admin_headers(client, seeded)
    for role in ("caretaker", "panthaky"):
        assert (await _invite(client, aid, admin, role=role)).status_code == 200

    invites = (await db.execute(select(AgyaryInvite))).scalars().all()
    assert len(invites) == 1 and invites[0].role == "panthaky"

    body = await _sign_in(client, phone=OTHER_PHONE, name="Er. Reinvited")
    assert body["user"]["agyaries"][0]["role"] == "panthaky"


async def test_revoked_invite_does_not_apply(db, client, seeded):
    aid = seeded["agyary_id"]
    admin = await _admin_headers(client, seeded)
    invite_id = (await _invite(client, aid, admin)).json()["id"]

    assert (
        await client.delete(f"/api/mobed/agyaries/{aid}/invites/{invite_id}", headers=admin)
    ).status_code == 200
    assert (await client.get(f"/api/mobed/agyaries/{aid}/invites", headers=admin)).json() == []

    body = await _sign_in(client, phone=OTHER_PHONE, name="Er. Revoked")
    assert body["user"]["agyaries"] == []  # not carried in at all


async def test_expired_invite_does_not_apply(db, client, seeded):
    aid = seeded["agyary_id"]
    await _invite(client, aid, await _admin_headers(client, seeded))
    invite = (await db.execute(select(AgyaryInvite))).scalar_one()
    invite.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()

    body = await _sign_in(client, phone=OTHER_PHONE, name="Er. Too Late")
    assert body["user"]["agyaries"] == []


async def test_plain_mobed_cannot_invite_when_an_admin_exists(db, client, seeded):
    """The seeded agyari already has a panthaky, so the bootstrap is closed."""
    mobed = await _joined_headers(client, seeded)
    r = await _invite(client, seeded["agyary_id"], mobed)
    assert r.status_code == 403


async def test_bootstrap_lets_the_first_member_appoint_a_panthaky(db, client, seeded):
    """An agyari a mobed just created has no admin at all - without this,
    nobody could ever issue its first invite and the role would be
    unreachable there forever."""
    headers = await _headers(client)
    aid = (
        await client.post(
            "/api/mobed/agyaries",
            json={"name": "Bootstrap Agiary", "city": "Pune", "address": None, "contact_phone": None},
            headers=headers,
        )
    ).json()["agyary"]["id"]

    creator = (await db.execute(select(User).where(User.phone == PHONE))).scalar_one()
    assert (await mobed_auth.get_membership(db, aid, creator.id)).role == "mobed"

    assert (await _invite(client, aid, headers)).status_code == 200
    body = await _sign_in(client, phone=OTHER_PHONE, name="Er. First Panthaky")
    assert body["user"]["agyaries"][0]["role"] == "panthaky"

    # Bootstrap closes now that an admin exists.
    assert (await _invite(client, aid, headers, phone="+919911100088")).status_code == 403


async def test_invites_require_membership(db, client, seeded):
    non_member = await _headers(client)
    assert (await _invite(client, seeded["agyary_id"], non_member)).status_code == 403


async def test_invite_rejects_unknown_role(db, client, seeded):
    admin = await _admin_headers(client, seeded)
    r = await _invite(client, seeded["agyary_id"], admin, role="administrator")
    assert r.status_code == 400


async def test_existing_admin_is_not_demoted_by_a_plain_join(db, client, seeded):
    """ensure_agyary_membership promotes and reactivates, never demotes."""
    aid = seeded["agyary_id"]
    user = (await db.execute(select(User).where(User.phone == seeded["panthaky_phone"]))).scalar_one()
    assert (await mobed_auth.get_membership(db, aid, user.id)).role == "panthaky"

    await mobed_auth.ensure_agyary_membership(db, aid, user)
    await db.commit()
    refreshed = (
        await db.execute(
            select(AgyaryUser).where(AgyaryUser.agyary_id == aid, AgyaryUser.user_id == user.id)
        )
    ).scalar_one()
    assert refreshed.role == "panthaky"
