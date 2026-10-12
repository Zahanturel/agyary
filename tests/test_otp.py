"""Sign-in by a code sent over WhatsApp.

The point of most of these is what an abuser or an honest mistake cannot do:
spend our money, flood a stranger, guess a code, or reuse one. Meta is never
reached; the one function that talks to it is replaced or given a mock.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from agyary.core import config
from agyary.models import AppNotification, LoginOtp, User
from agyary.services import bot_check, guardrails, otp
from tests.test_reminder_sender import _settings

PHONE = "+919944400701"
ADMIN = "+919800000002"        # the seeded mobed


def _s(**over):
    return _settings(otp_mode="live", reminders_send_mode="off", **over)


class Outbox:
    """Stands in for Meta: remembers each code it was asked to send."""

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def __call__(self, client, settings, phone, code):
        self.sent.append((phone, code))
        return f"wamid.{len(self.sent)}"

    @property
    def last(self) -> str:
        return self.sent[-1][1]


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    """Meta is replaced in every test; the few that need a different failure
    replace it again themselves."""
    box = Outbox()
    monkeypatch.setattr(otp, "_send", box)
    return box


@pytest.fixture
def live(monkeypatch):
    """The server configured for sign-in codes, as environment so the routes see
    it - bot check included, with Cloudflare stood in for by a check that passes
    (test_otp_bot_check covers the check itself)."""
    monkeypatch.setenv("OTP_MODE", "live")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "555000111")
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret-key")

    async def passes(settings, token, ip):
        return True

    monkeypatch.setattr(bot_check, "verify", passes)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


NOW = datetime(2030, 3, 14, 12, 0, tzinfo=timezone.utc)

# The real function that talks to Meta, kept before every test replaces it, for
# the few tests that mean to exercise it against a mock transport.
_REAL_SEND = otp._send


async def _ask(db, phone=PHONE, now=NOW, ip="1.2.3.4", **settings):
    return await otp.request_code(db, _s(whatsapp_access_token="tok", **settings), phone, ip, None, now=now)


# --- The happy path, over HTTP ----------------------------------------------

async def test_the_login_screen_is_told_whether_codes_are_offered(client, monkeypatch):
    config.get_settings.cache_clear()
    assert (await client.get("/api/mobed/auth/options")).json()["otp"] is False
    monkeypatch.setenv("OTP_MODE", "live")
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret-key")
    config.get_settings.cache_clear()
    try:
        assert (await client.get("/api/mobed/auth/options")).json()["otp"] is True
    finally:
        config.get_settings.cache_clear()


async def test_it_is_off_unless_switched_on(client, db, seeded):
    r = await client.post("/api/mobed/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 503 and "not available" in r.json()["detail"]


async def test_a_returning_mobed_asks_for_a_code_and_is_signed_in(client, db, seeded, live, outbox):
    r = await client.post("/api/mobed/auth/otp/request", json={"phone": ADMIN})
    assert r.status_code == 200, r.text
    assert r.json() == {"expires_in": 300, "resend_after": 30}          # nothing about the account
    phone, code = outbox.sent[-1]
    assert phone == ADMIN and len(code) == 6 and code.isdigit()

    r = await client.post("/api/mobed/auth/otp/verify", json={"phone": ADMIN, "code": code})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "signed_in", r.text
    assert body["user"]["phone"] == ADMIN and body["access_token"]
    # The same session the other sign-in makes: it can be refreshed.
    assert (await client.post("/api/mobed/auth/refresh")).status_code == 200


async def test_a_first_time_mobed_is_asked_for_their_name_then_signed_in(client, db, seeded, live, outbox):
    new = "+919955500123"
    await client.post("/api/mobed/auth/otp/request", json={"phone": new})
    r = await client.post("/api/mobed/auth/otp/verify", json={"phone": new, "code": outbox.last})
    assert r.json() == {"status": "needs_name"}

    done = await client.post("/api/mobed/auth/wa/complete", json={"name": "Er. Newcomer"})
    assert done.json()["status"] == "signed_in" and done.json()["user"]["phone"] == new
    assert done.json()["user"]["name"] == "Er. Newcomer"


async def test_the_answer_is_the_same_for_a_number_with_an_account_and_one_without(client, db, seeded, live, outbox):
    known = await client.post("/api/mobed/auth/otp/request", json={"phone": ADMIN})
    unknown = await client.post("/api/mobed/auth/otp/request", json={"phone": "+919955500124"})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())


async def test_a_pasted_message_works_as_well_as_the_digits(client, db, seeded, live, outbox):
    await client.post("/api/mobed/auth/otp/request", json={"phone": ADMIN})
    pasted = f"{outbox.last[:3]} {outbox.last[3:]} is your verification code."
    r = await client.post("/api/mobed/auth/otp/verify", json={"phone": ADMIN, "code": pasted})
    assert r.json()["status"] == "signed_in"


# --- Guessing ---------------------------------------------------------------

async def test_the_code_is_never_stored(client, db, seeded, live, outbox):
    await client.post("/api/mobed/auth/otp/request", json={"phone": ADMIN})
    [row] = (await db.execute(select(LoginOtp))).scalars().all()
    assert outbox.last not in json.dumps([row.salt, row.code_hash, row.phone, row.requester, row.wa_message_id])
    assert len(row.code_hash) == 64 and row.status == "sent"


async def test_a_wrong_code_is_refused_and_the_right_one_still_works(client, db, seeded, live, outbox):
    await client.post("/api/mobed/auth/otp/request", json={"phone": ADMIN})
    wrong = "000000" if outbox.last != "000000" else "111111"
    r = await client.post("/api/mobed/auth/otp/verify", json={"phone": ADMIN, "code": wrong})
    assert r.status_code == 400 and "wrong or has expired" in r.json()["detail"]
    r = await client.post("/api/mobed/auth/otp/verify", json={"phone": ADMIN, "code": outbox.last})
    assert r.json()["status"] == "signed_in"


async def test_five_wrong_guesses_kill_the_code_even_for_the_right_digits(db, seeded):
    await _ask(db, ADMIN)
    row = (await db.execute(select(LoginOtp))).scalar_one()
    real = "123456"
    row.code_hash = otp._digest(_s(), row.salt, ADMIN, real)
    await db.commit()
    for _ in range(otp.MAX_ATTEMPTS):
        assert not await otp.verify_code(db, _s(), ADMIN, "654321", now=NOW)
    assert not await otp.verify_code(db, _s(), ADMIN, real, now=NOW)       # too late: it is dead


async def test_a_code_is_spent_once(db, seeded):
    await _ask(db, ADMIN)
    row = (await db.execute(select(LoginOtp))).scalar_one()
    row.code_hash = otp._digest(_s(), row.salt, ADMIN, "123456")
    await db.commit()
    assert await otp.verify_code(db, _s(), ADMIN, "123456", now=NOW)
    assert not await otp.verify_code(db, _s(), ADMIN, "123456", now=NOW)


async def test_a_code_expires(db, seeded):
    await _ask(db, ADMIN)
    row = (await db.execute(select(LoginOtp))).scalar_one()
    row.code_hash = otp._digest(_s(), row.salt, ADMIN, "123456")
    await db.commit()
    assert not await otp.verify_code(db, _s(), ADMIN, "123456", now=NOW + timedelta(seconds=301))
    # An attempt after expiry costs nothing, and the code is still good until then.
    assert await otp.verify_code(db, _s(), ADMIN, "123456", now=NOW + timedelta(seconds=299))


async def test_only_the_newest_code_counts(db, seeded):
    await _ask(db, ADMIN)
    first = (await db.execute(select(LoginOtp))).scalar_one()
    first.code_hash = otp._digest(_s(), first.salt, ADMIN, "111111")
    await db.commit()
    await _ask(db, ADMIN, now=NOW + timedelta(seconds=31))
    # Asking again does not give the old code a second life, and does not add guesses.
    assert not await otp.verify_code(db, _s(), ADMIN, "111111", now=NOW + timedelta(seconds=40))


async def test_a_code_for_one_number_does_not_work_for_another(db, seeded):
    await _ask(db, ADMIN)
    row = (await db.execute(select(LoginOtp))).scalar_one()
    row.code_hash = otp._digest(_s(), row.salt, ADMIN, "123456")
    await db.commit()
    assert not await otp.verify_code(db, _s(), "+919955500999", "123456", now=NOW)


async def test_something_that_is_not_six_digits_is_not_a_guess(db, seeded):
    await _ask(db, ADMIN)
    for junk in ("", "12345", "1234567", "abcdef", "12 3456"):
        assert not await otp.verify_code(db, _s(), ADMIN, junk, now=NOW)
    row = (await db.execute(select(LoginOtp))).scalar_one()
    assert row.attempts == 0                      # none of them used up the real code's tries


def test_extracting_a_code_from_what_was_pasted():
    assert otp.extract_code("123456") == "123456"
    assert otp.extract_code("123 456") == "123456"
    assert otp.extract_code("123-456") == "123456"
    assert otp.extract_code("482913 is your verification code. For your security, do not share it.") == "482913"
    assert otp.extract_code("call 98765 43210 about 482913") == "482913"   # a phone number is not a code
    assert otp.extract_code("codes 482913 and 551234") is None             # two candidates: refuse to guess
    assert otp.extract_code("no digits here") is None and otp.extract_code("") is None


# --- Flooding and money -----------------------------------------------------

async def test_a_second_code_within_thirty_seconds_is_refused_with_how_long_to_wait(db, seeded):
    await _ask(db, ADMIN)
    with pytest.raises(otp.OtpError) as err:
        await _ask(db, ADMIN, now=NOW + timedelta(seconds=10))
    assert err.value.status == 429 and err.value.retry_after == 20
    await _ask(db, ADMIN, now=NOW + timedelta(seconds=31))                 # then it is fine


async def test_one_number_gets_at_most_three_codes_an_hour(db, seeded):
    for i in range(otp.PER_PHONE_HOURLY):
        await _ask(db, ADMIN, now=NOW + timedelta(minutes=i * 2))
    with pytest.raises(otp.OtpError) as err:
        await _ask(db, ADMIN, now=NOW + timedelta(minutes=8))
    assert err.value.status == 429 and "hour" in str(err.value)
    await _ask(db, ADMIN, now=NOW + timedelta(minutes=61))                 # the hour passes


async def test_one_number_gets_at_most_eight_codes_a_day(db, seeded):
    for i in range(otp.PER_PHONE_DAILY):
        await _ask(db, ADMIN, now=NOW + timedelta(minutes=i * 70))        # inside the hourly limit each time
    with pytest.raises(otp.OtpError) as err:
        await _ask(db, ADMIN, now=NOW + timedelta(minutes=8 * 70 + 1))
    assert err.value.status == 429 and "today" in str(err.value)


async def test_the_daily_cap_stops_all_codes_and_alerts_the_admins(db, seeded):
    phones = [f"+9199555001{i:02d}" for i in range(3)]
    for p in phones:
        await _ask(db, p, otp_daily_cap=3, admin_phones=ADMIN, otp_new_number_hourly_cap=50)
    with pytest.raises(otp.OtpError) as err:
        await _ask(db, "+919955500199", otp_daily_cap=3, admin_phones=ADMIN, otp_new_number_hourly_cap=50)
    assert err.value.status == 429 and "WhatsApp sign-in" in str(err.value)
    await db.commit()
    alerts = (await db.execute(select(AppNotification).where(AppNotification.kind == "alert"))).scalars().all()
    assert [a.title for a in alerts] == ["Sign-in code limit reached"]


async def test_codes_to_strangers_have_a_harder_cap_than_codes_to_known_numbers(db, seeded):
    kw = dict(otp_new_number_hourly_cap=2, otp_daily_cap=100)
    await _ask(db, "+919955500201", **kw)
    await _ask(db, "+919955500202", **kw)
    with pytest.raises(otp.OtpError):
        await _ask(db, "+919955500203", **kw)                              # a third stranger this hour
    await _ask(db, ADMIN, **kw)                                            # a known number is unaffected
    await _ask(db, "+919955500203", now=NOW + timedelta(hours=1, minutes=1), **kw)


async def test_a_failed_send_does_not_use_up_the_allowance(db, seeded, monkeypatch):
    async def refuse(client, settings, phone, code):
        raise otp._SendFailed("recipient unreachable", 131026)

    monkeypatch.setattr(otp, "_send", refuse)
    for i in range(5):                                                     # more than PER_PHONE_HOURLY
        with pytest.raises(otp.OtpError):
            await _ask(db, ADMIN, now=NOW + timedelta(seconds=40 * i))
    monkeypatch.setattr(otp, "_send", Outbox())
    await _ask(db, ADMIN, now=NOW + timedelta(seconds=300))


async def test_nothing_is_sent_while_sending_is_paused(db, seeded, outbox):
    await guardrails.pause(db, _s(), "Cost check", now=NOW)
    await db.commit()
    with pytest.raises(otp.OtpError) as err:
        await _ask(db, ADMIN)
    assert err.value.status == 503 and outbox.sent == []


async def test_an_account_level_error_from_meta_pauses_everything_and_tells_the_admins(db, seeded, monkeypatch):
    async def boom(client, settings, phone, code):
        raise otp._AccountProblem("Invalid OAuth access token", 190)

    monkeypatch.setattr(otp, "_send", boom)
    with pytest.raises(otp.OtpError) as err:
        await _ask(db, ADMIN, admin_phones=ADMIN)
    assert err.value.status == 503 and "WhatsApp sign-in" in str(err.value)
    assert "(190)" in (await guardrails.paused_reason(db))
    # And the caller was told nothing about why.
    assert "OAuth" not in str(err.value) and "190" not in str(err.value)


async def test_an_ordinary_send_failure_does_not_pause_anything(db, seeded, monkeypatch):
    async def boom(client, settings, phone, code):
        raise otp._SendFailed("network error: ConnectError")

    monkeypatch.setattr(otp, "_send", boom)
    with pytest.raises(otp.OtpError):
        await _ask(db, ADMIN)
    assert await guardrails.paused_reason(db) is None


# --- Where there is no way to send ------------------------------------------

async def test_with_no_token_a_laptop_gets_the_code_back_so_the_flow_can_be_tried(db, seeded):
    s = _s(whatsapp_access_token="", app_debug=True)
    out = await otp.request_code(db, s, ADMIN, "1.2.3.4", None, now=NOW)
    assert len(out["debug_code"]) == 6
    assert await otp.verify_code(db, s, ADMIN, out["debug_code"], now=NOW)


async def test_with_no_token_a_real_server_refuses_and_never_returns_a_code(db, seeded):
    s = _s(whatsapp_access_token="", app_debug=False)
    with pytest.raises(otp.OtpError) as err:
        await otp.request_code(db, s, ADMIN, "1.2.3.4", None, now=NOW)
    assert err.value.status == 503


# --- What goes to Meta ------------------------------------------------------

def test_the_message_is_an_authentication_template_with_the_code_in_the_body_and_the_copy_button():
    body = otp._payload(_s(whatsapp_template_language="en"), PHONE, "482913")
    assert body["to"] == "919944400701" and body["type"] == "template"
    assert body["template"]["name"] == "login_code" and body["template"]["language"] == {"code": "en"}
    body_part, button = body["template"]["components"]
    assert body_part == {"type": "body", "parameters": [{"type": "text", "text": "482913"}]}
    assert button["type"] == "button" and button["sub_type"] == "url" and button["index"] == "0"
    assert button["parameters"] == [{"type": "text", "text": "482913"}]


async def _post_with(status: int, json_body: dict):
    def handler(request):
        return httpx.Response(status, json=json_body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await _REAL_SEND(client, _s(whatsapp_access_token="tok", whatsapp_phone_number_id="555"), PHONE, "482913")


async def test_meta_accepting_the_message_gives_back_its_id():
    assert await _post_with(200, {"messages": [{"id": "wamid.1"}]}) == "wamid.1"


async def test_meta_errors_are_sorted_into_account_problems_and_ordinary_failures():
    with pytest.raises(otp._AccountProblem) as e:
        await _post_with(401, {"error": {"message": "bad token", "code": 190}})
    assert e.value.code == 190
    with pytest.raises(otp._AccountProblem):
        await _post_with(400, {"error": {"message": "payment", "code": 131042}})
    with pytest.raises(otp._SendFailed) as e2:
        await _post_with(400, {"error": {"message": "not on whatsapp", "code": 131026}})
    assert not isinstance(e2.value, otp._AccountProblem)


# --- Over HTTP: limits that do not need a clock -----------------------------

async def test_the_endpoint_limits_how_often_one_address_can_ask(client, db, seeded, live, outbox):
    seen = []
    for i in range(12):
        r = await client.post("/api/mobed/auth/otp/request", json={"phone": f"+9199555003{i:02d}"})
        seen.append(r.status_code)
    assert 429 in seen and seen.index(429) <= 10          # the eleventh from one address at the latest


async def test_a_bad_phone_is_refused_before_anything_is_sent(client, db, seeded, live, outbox):
    r = await client.post("/api/mobed/auth/otp/request", json={"phone": "not a number"})
    assert r.status_code == 422 and outbox.sent == []


async def test_verifying_for_a_number_that_never_asked_is_just_wrong(client, db, seeded, live):
    r = await client.post("/api/mobed/auth/otp/verify", json={"phone": "+919955500777", "code": "123456"})
    assert r.status_code == 400 and r.json()["detail"] == "That code is wrong or has expired."


async def test_a_signed_in_session_exists_only_after_the_right_code(client, db, seeded, live, outbox):
    await client.post("/api/mobed/auth/otp/request", json={"phone": ADMIN})
    wrong = "000000" if outbox.last != "000000" else "111111"
    r = await client.post("/api/mobed/auth/otp/verify", json={"phone": ADMIN, "code": wrong})
    assert r.status_code == 400 and "access_token" not in r.text
    assert (await db.execute(select(User).where(User.phone == ADMIN))).scalar_one()
