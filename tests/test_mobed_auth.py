"""Mobed sign-in: WhatsApp OTP, and the membership it creates.

The property under test throughout is that knowing a phone number is not
enough - you have to hold it. And that self-serve sign-in can only ever
make you a plain mobed; anything above that has to be handed to you by
someone who already holds it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from agyary.models import AgyaryUser, AuthOtp, User
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


def test_template_payload_omits_components_when_there_are_none():
    """hello_world and friends have no variables. Sending an empty or absent
    components array matters: WhatsApp rejects components a template doesn't
    define, and this is the payload the smoke test uses to prove credentials
    before our own template exists."""
    from agyary.services import otp_delivery

    payload = otp_delivery.build_template_payload("+919800000003", "hello_world", "en_US")
    assert payload["messaging_product"] == "whatsapp"
    assert payload["type"] == "template"
    # E.164 without the plus - what the Cloud API wants.
    assert payload["to"] == "919800000003"
    assert payload["template"] == {"name": "hello_world", "language": {"code": "en_US"}}
    assert "components" not in payload["template"]


def test_template_payload_carries_the_code_in_body_and_button():
    """An Authentication template with a copy-code button needs the code
    twice - once to render, once for the button to copy."""
    from agyary.services import otp_delivery

    payload = otp_delivery.build_template_payload(
        "+919800000003", "mobed_diary_login_code", "en",
        body_parameters=["123456"], copy_code="123456",
    )
    components = payload["template"]["components"]
    assert [c["type"] for c in components] == ["body", "button"]
    assert components[0]["parameters"] == [{"type": "text", "text": "123456"}]
    assert components[1]["parameters"] == [{"type": "text", "text": "123456"}]
    assert components[1]["index"] == "0"


def test_template_payload_can_omit_the_button():
    """A template without a copy-code button rejects a button component, so
    it has to be possible to leave it out."""
    from agyary.services import otp_delivery

    payload = otp_delivery.build_template_payload(
        "+919800000003", "some_template", "en", body_parameters=["123456"],
    )
    assert [c["type"] for c in payload["template"]["components"]] == ["body"]


async def test_send_uses_the_configured_template(db, client, seeded, monkeypatch):
    """End to end through the endpoint: with WhatsApp configured, a sign-in
    request sends the configured template - not a text message, which
    WhatsApp would reject for a business-initiated conversation."""
    import importlib

    from agyary.core import config
    from agyary.services import otp_delivery

    importlib.reload(otp_delivery)  # conftest stubs the sender; get the real one
    sent = {}

    async def fake_post(payload, client=None):
        sent.update(payload)
        return {"messages": [{"id": "wamid.TEST"}]}

    monkeypatch.setattr(otp_delivery, "post_to_graph", fake_post)
    monkeypatch.setenv("WHATSAPP_API_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_OTP_PHONE_NUMBER_ID", "1234567890")
    monkeypatch.setenv("WHATSAPP_OTP_TEMPLATE_NAME", "mobed_diary_login_code")
    monkeypatch.setenv("WHATSAPP_OTP_TEMPLATE_LANGUAGE", "en")
    config.get_settings.cache_clear()
    try:
        await otp_delivery.send_login_otp("+919800000003", "654321")
        assert sent["type"] == "template"
        assert sent["template"]["name"] == "mobed_diary_login_code"
        assert sent["template"]["language"] == {"code": "en"}
        body = sent["template"]["components"][0]
        assert body["parameters"] == [{"type": "text", "text": "654321"}]
    finally:
        config.get_settings.cache_clear()


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
# Membership: self-serve join, and what it may and may not change
# ---------------------------------------------------------------------------
async def _headers(client, phone=PHONE, name="Er. Test Mobed") -> dict:
    return {"Authorization": f"Bearer {(await _sign_in(client, phone, name))['access_token']}"}


async def _joined_headers(client, seeded, phone=PHONE, name="Er. Test Mobed") -> dict:
    headers = await _headers(client, phone, name)
    r = await client.post(f"/api/mobed/agyaries/{seeded['agyary_id']}/join", headers=headers)
    assert r.status_code == 200, r.text
    return headers


async def test_existing_admin_is_not_demoted_by_a_plain_join(db, client, seeded):
    """ensure_agyary_membership reactivates, but never demotes.

    Nothing in this app grants panthaky any more, so the only privileged
    memberships are the ones seed data and the WhatsApp flows created. A
    plain re-join must leave them alone - silently resetting one to 'mobed'
    would take away the booking-flow rights that role carries.
    """
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
