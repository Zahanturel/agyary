"""Sign-up is by invitation until the open-sign-up safeguards have shipped.

The policy is that any verified number may sign up (docs/DECISIONS.md D1), but
only once the safeguards that make that safe are in. Until then SIGNUP_MODE is
"invite" by default: anyone with an account signs in as before, and a new
account is made only for a number in SIGNUP_ALLOWLIST (how the owner invites a
mobed) or an admin. Both ways in obey it: the "send us a code" webhook flow, and
the code sent over WhatsApp - which sends nothing to a number it would not let
in, while answering exactly as it does for any other number, cool-down
included, so it cannot be used to find out who is a mobed.
"""

from __future__ import annotations

from sqlalchemy import func, select

from agyary.core import config
from agyary.core.config import Settings
from agyary.models import LoginOtp, User, WaLoginAttempt
from tests.conftest import sign_in, signed_inbound

STRANGER = "+919944400901"
INVITED = "+919944400902"
ADMIN = "+919944400903"


def _invite_only(monkeypatch, *, invited: str = "", admins: str = "") -> None:
    monkeypatch.setenv("SIGNUP_MODE", "invite")
    monkeypatch.setenv("SIGNUP_ALLOWLIST", invited)
    monkeypatch.setenv("ADMIN_PHONES", admins)
    config.get_settings.cache_clear()


async def _attempt(client, phone: str):
    client.cookies.clear()
    started = await client.post("/api/mobed/auth/wa/start")
    assert started.status_code == 200, started.text
    raw, headers = signed_inbound(started.json()["code"], phone)
    assert (await client.post("/webhooks/whatsapp", content=raw, headers=headers)).status_code == 200
    return await client.get("/api/mobed/auth/wa/poll")


def test_sign_up_is_by_invitation_unless_opened(monkeypatch):
    monkeypatch.delenv("SIGNUP_MODE", raising=False)
    assert Settings(_env_file=None, jwt_secret_key="x").signup_mode == "invite"


async def test_an_uninvited_number_is_turned_away_and_everyone_else_gets_in(client, db, seeded, monkeypatch):
    _invite_only(monkeypatch, invited=INVITED, admins=ADMIN)

    refused = await _attempt(client, STRANGER)
    assert refused.status_code == 403
    assert "not set up" in refused.json()["detail"]
    users = (await db.execute(select(func.count()).select_from(User).where(User.phone == STRANGER))).scalar_one()
    assert users == 0
    # The attempt is spent, so the page stops waiting rather than polling for ever.
    assert (await db.execute(select(func.count()).select_from(WaLoginAttempt)
                             .where(WaLoginAttempt.claimed_phone == STRANGER))).scalar_one() == 0

    # Someone who already has an account, an invited number, and an admin all get in.
    client.cookies.clear()
    assert (await sign_in(client, seeded["mobed_phone"]))["status"] == "signed_in"
    client.cookies.clear()
    assert (await sign_in(client, INVITED, "Invited Mobed"))["user"]["phone"] == INVITED
    client.cookies.clear()
    assert (await sign_in(client, ADMIN, "The Admin"))["user"]["phone"] == ADMIN


async def test_a_code_is_not_sent_to_a_number_that_could_not_sign_in(client, db, seeded, monkeypatch):
    monkeypatch.setenv("OTP_MODE", "live")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "")
    _invite_only(monkeypatch)

    stranger = await client.post("/api/mobed/auth/otp/request", json={"phone": STRANGER})
    known = await client.post("/api/mobed/auth/otp/request", json={"phone": seeded["mobed_phone"]})
    assert stranger.status_code == known.status_code == 200
    # The same answer either way (the debug-only code aside)...
    assert {k for k in stranger.json() if k != "debug_code"} == {k for k in known.json() if k != "debug_code"}
    # ...and the same cool-down on a second request straight after...
    again = [await client.post("/api/mobed/auth/otp/request", json={"phone": p})
             for p in (STRANGER, seeded["mobed_phone"])]
    assert [r.status_code for r in again] == [429, 429]
    # ...but nothing was sent to the stranger, and no code exists that could let them in.
    assert "debug_code" not in stranger.json()
    sent = (await db.execute(select(func.count()).select_from(LoginOtp).where(
        LoginOtp.phone == STRANGER, LoginOtp.status == "sent"))).scalar_one()
    assert sent == 0
