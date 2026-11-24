"""The behdin app's API (R4.0, docs/behdin-r4-0-design.md).

Every account is a person and a behdin; what it may also be is its
``account_kind``. Everything here is built on ``get_current_person`` (signed in,
any kind) and none of it on the mobed app's dependencies, which in turn refuse a
behdin's account. Signing in reuses the mobed app's WhatsApp and code methods
unchanged, except that a NEW number becomes a 'behdin', on, whatever SIGNUP_MODE
says. The cookies are the app's own (name and path), so the two apps never meet
when served from one host.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Cookie, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.api.routes import mobed as mobed_routes
from agyary.api.routes import otp as otp_routes
from agyary.api.routes.mobed import Cookies, get_current_person, get_signed_in_person
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import User, UserPreferences
from agyary.models.enums import ACCOUNT_BEHDIN, ACCOUNT_FUNERAL_MANAGER, ACCOUNT_MOBED
from agyary.services import account, mobed_access, mobed_auth, template_text, wa_login, web_push

router = APIRouter(prefix="/api/behdin", tags=["behdin"])

# Bumped when the behdin API changes shape; the app shows it on its menu.
APP_VERSION = "r4.0"
COOKIES = Cookies(refresh="behdin_refresh_token", wa_login="behdin_wa_login", path="/api/behdin")


# ---------------------------------------------------------------------------
# Who you are
# ---------------------------------------------------------------------------
def roles_of(user: User) -> list[dict]:
    """Every account is a behdin; a mobed or a manager is that as well, with
    the access (on, pending, off) the mobed app gives them."""
    roles = [{"role": "behdin", "access": "on"}]
    if user.account_kind in (ACCOUNT_MOBED, ACCOUNT_FUNERAL_MANAGER):
        role = "mobed" if user.account_kind == ACCOUNT_MOBED else "funeral_manager"
        roles.append({"role": role, "access": mobed_access.effective(get_settings(), user)})
    return roles


async def _serialize(db: AsyncSession, user: User) -> dict:
    roles = roles_of(user)
    return {
        "id": user.id, "name": user.name, "account_kind": user.account_kind,
        "roles": [r["role"] for r in roles],
        "role_access": {r["role"]: r["access"] for r in roles},
        "app_version": APP_VERSION,
    }


@router.get("/me")
async def me(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    return await _serialize(db, user)


class NameIn(BaseModel):
    name: str


def _clean_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Please enter your name.")
    mobed_routes._check_template_text(name, "name", template_text.MOBED_NAME_MAX)
    return name


@router.patch("/me")
async def update_me(
    payload: NameIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)
) -> dict:
    """The person's own name. The number is the sign-in identity and stays read-only."""
    user.name = _clean_name(payload.name)
    await db.commit()
    return await _serialize(db, user)


class DeleteIn(BaseModel):
    confirm: bool


@router.delete("/account")
async def delete_account(
    payload: DeleteIn, response: Response, db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_person),
) -> dict:
    """Delete this account and everything that is theirs (services/account.py), for
    any kind. Signs out everywhere. Cannot be undone."""
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Nothing was deleted.")
    await account.delete_account(db, user)
    await db.commit()
    response.delete_cookie(
        COOKIES.refresh, path=COOKIES.path, httponly=True, secure=not get_settings().app_debug, samesite="strict"
    )
    return {"deleted": True}


@router.post("/auth/sessions/sign-out-others")
async def sign_out_other_devices(
    payload: mobed_routes.SignOutOthersIn | None = Body(default=None),
    user: User = Depends(get_current_person),
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, session_id = await mobed_routes._current(authorization, db)
    ended = await mobed_auth.end_all_sessions(
        db, user, keep=session_id, keep_endpoint=payload.keep_endpoint if payload is not None else None
    )
    await db.commit()
    return {"signed_out": ended}


# ---------------------------------------------------------------------------
# Signing in: the same methods as the mobed app, a new number becomes a behdin
# ---------------------------------------------------------------------------
async def _session(db, response, secret, phone, name, wa_user_id=None):
    return await mobed_routes._wa_login_session(
        db, response, secret, phone, name, wa_user_id=wa_user_id,
        kind=ACCOUNT_BEHDIN, cookies=COOKIES, serialize=_serialize,
    )


@router.post("/auth/wa/start")
async def wa_login_start(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    """Open a sign-in attempt and hand back the link to send (see the mobed app's)."""
    rate_limit.enforce(request, "wa_login_start", max_requests=10, window_seconds=300)
    try:
        started = await wa_login.start(db)
    except wa_login.WaLoginError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await db.commit()
    settings = get_settings()
    response.set_cookie(
        COOKIES.wa_login, started.poll_secret, httponly=True, secure=not settings.app_debug,
        samesite="lax", max_age=settings.wa_login_ttl_seconds, path=COOKIES.path,
    )
    return {"code": started.code, "wa_link": started.wa_link, "expires_at": started.expires_at.isoformat()}


@router.get("/auth/wa/poll")
async def wa_login_poll(
    request: Request, response: Response,
    wa_login_cookie: str | None = Cookie(default=None, alias=COOKIES.wa_login),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rate_limit.enforce(request, "wa_login_poll", max_requests=200, window_seconds=300)
    if not wa_login_cookie:
        raise HTTPException(status_code=400, detail="No sign-in is in progress.")
    attempt = await wa_login.peek(db, wa_login_cookie)
    if attempt is None or attempt.claimed_at is None:
        return {"status": "pending"}
    if attempt.claimed_phone is None:
        await wa_login.consume(db, wa_login_cookie)
        await db.commit()
        refused = JSONResponse(status_code=403, content={"detail": mobed_routes.NO_NUMBER})
        refused.delete_cookie(COOKIES.wa_login, path=COOKIES.path)
        return refused
    if attempt.confirm_hash is not None:
        return {"status": "confirm"}
    return await _session(db, response, wa_login_cookie, attempt.claimed_phone, "", attempt.claimed_wa_user_id)


@router.post("/auth/wa/confirm")
async def wa_login_confirm(
    payload: mobed_routes.WaLoginConfirmIn, request: Request, response: Response,
    wa_login_cookie: str | None = Cookie(default=None, alias=COOKIES.wa_login),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rate_limit.enforce(request, "wa_login_confirm", max_requests=20, window_seconds=300)
    if not wa_login_cookie:
        raise HTTPException(status_code=400, detail="No sign-in is in progress.")
    attempt = await wa_login.peek(db, wa_login_cookie)
    if attempt is None or attempt.claimed_phone is None or attempt.confirm_hash is None:
        raise HTTPException(status_code=400, detail="That sign-in has expired. Please start again.")
    ok = await wa_login.confirm(db, attempt, payload.number)
    await db.commit()
    if not ok:
        if attempt.confirm_attempts >= wa_login.CONFIRM_MAX_ATTEMPTS:
            raise HTTPException(status_code=400, detail="Too many tries. Please start again.")
        raise HTTPException(status_code=400, detail="That number is not right. Check the WhatsApp message.")
    return await _session(db, response, wa_login_cookie, attempt.claimed_phone, "", attempt.claimed_wa_user_id)


@router.post("/auth/wa/complete")
async def wa_login_complete(
    payload: NameIn, request: Request, response: Response,
    wa_login_cookie: str | None = Cookie(default=None, alias=COOKIES.wa_login),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Finish a first-ever sign-in with the person's own name."""
    rate_limit.enforce(request, "wa_login_complete", max_requests=20, window_seconds=300)
    if not wa_login_cookie:
        raise HTTPException(status_code=400, detail="No sign-in is in progress.")
    name = _clean_name(payload.name)
    attempt = await wa_login.peek(db, wa_login_cookie)
    phone = await wa_login.peek_claimed_phone(db, wa_login_cookie)
    if phone is None:
        raise HTTPException(status_code=400, detail="That sign-in has expired. Please start again.")
    return await _session(db, response, wa_login_cookie, phone, name, attempt.claimed_wa_user_id)


@router.get("/auth/options")
async def auth_options() -> dict:
    return await otp_routes.auth_options()


@router.post("/auth/otp/request")
async def otp_request(
    payload: otp_routes.OtpRequestIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    return await otp_routes.send_code(payload, request, db, open_to_all=True)


@router.post("/auth/otp/verify")
async def otp_verify(
    payload: otp_routes.OtpVerifyIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> dict:
    return await otp_routes.check_code(
        payload, request, response, db, kind=ACCOUNT_BEHDIN, cookies=COOKIES, serialize=_serialize
    )


@router.post("/auth/refresh")
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=COOKIES.refresh),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sliding session, as in the mobed app, on this app's own cookie."""
    if refresh_token is None:
        raise HTTPException(status_code=401, detail="Please sign in again.")
    try:
        claims = mobed_auth.decode_token(refresh_token, "refresh")
        user = await db.get(User, claims["sub"])
        if user is None or not user.is_active:
            raise mobed_auth.TokenError("This account could not be found. Please sign in again.")
        session = await mobed_auth.rotate(db, claims)
    except mobed_auth.TokenError as exc:
        await db.commit()
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    await db.commit()
    mobed_routes._set_refresh_cookie(response, session, COOKIES)
    return {"access_token": mobed_auth.issue_access_token(user.id, session.id)}


@router.post("/auth/logout")
async def logout(
    response: Response,
    payload: mobed_routes.LogoutIn | None = Body(default=None),
    refresh_token: str | None = Cookie(default=None, alias=COOKIES.refresh),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """End the session and clear this app's cookie (the mobed app's is not touched)."""
    if refresh_token:
        try:
            claims = mobed_auth.decode_token(refresh_token, "refresh")
            await mobed_auth.end_token(db, claims)
            if payload is not None and payload.endpoint:
                await web_push.remove(db, claims["sub"], payload.endpoint)
            await db.commit()
        except mobed_auth.TokenError:
            pass
    response.delete_cookie(
        COOKIES.refresh, path=COOKIES.path, httponly=True, secure=not get_settings().app_debug, samesite="strict"
    )
    return {"signed_out": True}


# ---------------------------------------------------------------------------
# Preferences, names and phone notifications: the same, for any kind of person
# ---------------------------------------------------------------------------
@router.get("/me/preferences")
async def get_preferences(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    return mobed_routes._preferences_response(await db.get(UserPreferences, user.id))


@router.put("/me/preferences")
async def put_preferences(
    payload: mobed_routes.PreferencesIn, db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_person),
) -> dict:
    return await mobed_routes.put_preferences(payload, db, user)


@router.get("/me/person-names")
async def my_person_names(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    return await mobed_routes.my_person_names(db, user)


@router.get("/me/push")
async def my_push_status(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    return await mobed_routes.my_push_status(db, user)


@router.post("/me/push/subscribe")
async def my_push_subscribe(
    payload: mobed_routes.PushSubscribeIn, db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_person),
) -> dict:
    return await mobed_routes.my_push_subscribe(payload, db, user)


@router.post("/me/push/unsubscribe")
async def my_push_unsubscribe(
    payload: mobed_routes.PushUnsubscribeIn, db: AsyncSession = Depends(get_db),
    user: User = Depends(get_signed_in_person),
) -> dict:
    """Stopping notifications is never refused, even for an account that is off."""
    return await mobed_routes.my_push_unsubscribe(payload, db, user)


@router.post("/me/push/test")
async def my_push_test(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_person)) -> dict:
    rate_limit.enforce_key(f"push_test:{user.id}", max_requests=5, window_seconds=60)
    s = get_settings()
    if not web_push.configured(s):
        raise HTTPException(status_code=409, detail=mobed_routes.NO_PUSH_KEYS)
    sent = await web_push.send_to_users(
        db, s, [user.id], title="Parsi", body="Notifications are working on this phone.",
        url="/behdin", tag="push-test",
    )
    await db.commit()
    return {"sent": sent, "devices": await web_push.devices(db, user.id)}
