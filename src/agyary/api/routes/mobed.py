"""Mobed PWA API: onboarding/auth, agyari search, the mobed's own day and
machi board, and manual event entry. See services/mobed_auth.py and
services/mobed_dashboard.py for the business logic - this module is the
HTTP/JWT/request-response layer on top of it.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Cookie, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.calendar.options import geh_options, mah_options, roj_options
from agyary.models import (
    Agyary,
    AgyaryUser,
    Customer,
    Service,
    User,
    UserPreferences,
)
from agyary.models.enums import (
    ACCESS_OFF,
    ACCESS_ON,
    ACCOUNT_BEHDIN,
    ACCOUNT_FUNERAL_MANAGER,
    ACCOUNT_MOBED,
    DEFAULT_SECONDARY_CALENDAR_SYSTEM,
    DISPLAY_LANGUAGES,
    LOCATION_PIN,
    NAME_SECTIONS,
    NAME_STATUSES,
    NAME_TITLES,
    OFFERED_CALENDARS,
    OFFERED_DISPLAY_SYSTEMS,
)
from agyary.models.preferences import default_preferences
from agyary.services import (
    account,
    behdin_directory,
    funeral_places,
    guardrails,
    join_confirmation,
    mobed_access,
    mobed_auth,
    mobed_dashboard,
    panthaky,
    person_names,
    reminders,
    template_text,
    wa_login,
    web_push,
)
from agyary.services.phone import OptionalPhone, Phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobed", tags=["mobed"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------
async def _current(authorization: str, db: AsyncSession) -> tuple[User, int]:
    """The signed-in user and their session id. The session is checked on every
    request, so ending it (sign out, sign out other devices, an admin's sign out
    everywhere) takes effect at once, not when the access token runs out."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Please sign in again.")
    token = authorization.removeprefix("Bearer ")
    try:
        claims = mobed_auth.decode_token(token, "access")
    except mobed_auth.TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    session = await mobed_auth.live_session(db, claims)
    if session is None:
        raise HTTPException(status_code=401, detail="This sign-in has ended. Please sign in again.")
    user = await db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="That account could not be found.")
    return user, session.id


async def get_signed_in_person(
    authorization: str = Header(default=""), db: AsyncSession = Depends(get_db)
) -> User:
    """Signed in, any kind at all (a behdin's too), on or not. The base of both
    apps; the mobed app's routes use get_signed_in_account and so refuse a
    behdin's account, the behdin app's use get_current_person."""
    user, _ = await _current(authorization, db)
    return user


async def get_signed_in_account(user: User = Depends(get_signed_in_person)) -> User:
    """Signed in, with a mobed's or a Doongerwadi manager's account, on or not.
    Only for what every such account has whatever it is: who they are, their
    name, signing out, deleting the account. A behdin's account (R4.0) is
    refused, with the kind in a header, like a manager's from the mobed routes."""
    if user.account_kind == ACCOUNT_BEHDIN:
        raise HTTPException(status_code=403, detail=NOT_FOR_BEHDINS, headers={ACCOUNT_KIND_HEADER: user.account_kind})
    return user


# A Doongerwadi or prayer hall manager's account (DECISIONS D10) is kept out of
# the whole mobed app: behdins, memorials, calendar, machis, slips, reminders,
# fire temples, the map search. Refused here, in the one dependency every mobed
# route is built on (get_current_user and get_user_not_switched_off ask for
# it), so a new mobed route is closed to managers without anyone remembering
# to; tests/test_funeral_managers.py walks every route to prove it. The header
# tells the app to show the manager's own screen instead.
ACCOUNT_KIND_HEADER = "X-Account-Kind"
NOT_FOR_MANAGERS = "This part of Mobed Diary is for mobeds. Your account is for a Doongerwadi or prayer hall."
NOT_FOR_MOBEDS = "This part of Mobed Diary is for Doongerwadi and prayer hall managers."
# A behdin's account (R4.0) is kept out the same way: it belongs to the behdin app.
NOT_FOR_BEHDINS = "This part of Mobed Diary is for mobeds. Your account is for the behdin app."


def refuse_other_kinds(user: User) -> User:
    """Refuse a manager's or a behdin's account, with the kind in a header so
    the app can show their own screen. A mobed's passes."""
    if user.account_kind == ACCOUNT_FUNERAL_MANAGER:
        raise HTTPException(
            status_code=403, detail=NOT_FOR_MANAGERS, headers={ACCOUNT_KIND_HEADER: user.account_kind},
        )
    if user.account_kind == ACCOUNT_BEHDIN:
        raise HTTPException(
            status_code=403, detail=NOT_FOR_BEHDINS, headers={ACCOUNT_KIND_HEADER: user.account_kind},
        )
    return user


async def get_signed_in_user(user: User = Depends(get_signed_in_account)) -> User:
    """Signed in with a mobed's account, whether or not an admin has let them
    use the app yet - only for what a waiting or switched-off mobed may still
    do: choose a fire temple. A manager's or a behdin's account is refused (see above)."""
    return refuse_other_kinds(user)


# Said to a mobed whose access is not on, with the access in a header the app
# reads to show its waiting screen (D9).
ACCESS_HEADER = "X-Mobed-Access"
NO_ACCESS = {
    "pending": "Your account is waiting for approval.",
    "off": "Your access to Mobed Diary is switched off.",
}


def _require_on(user: User) -> User:
    access = mobed_access.effective(get_settings(), user)
    if access != ACCESS_ON:
        raise HTTPException(
            status_code=403, detail=NO_ACCESS.get(access, NO_ACCESS["off"]), headers={ACCESS_HEADER: access},
        )
    return user


async def get_current_user(user: User = Depends(get_signed_in_user)) -> User:
    """A mobed's account, signed in AND switched on by an admin (D9).
    Everything in the mobed app but the few steps of signing up asks for this."""
    return _require_on(user)


BEHDIN_OFF = "Your access to the behdin app is switched off."


async def get_current_person(user: User = Depends(get_signed_in_person)) -> User:
    """Signed in and active, any kind of account: what every /api/behdin route is
    built on (R4.0). A behdin whose access an admin turned off is refused. A
    mobed or manager who is waiting or switched off is NOT: the D9 switch is the
    mobed side's only, and they still have the behdin app."""
    if user.account_kind == ACCOUNT_BEHDIN and mobed_access.effective(get_settings(), user) != ACCESS_ON:
        raise HTTPException(status_code=403, detail=BEHDIN_OFF, headers={ACCESS_HEADER: ACCESS_OFF})
    return user


async def get_current_account(user: User = Depends(get_signed_in_account)) -> User:
    """Signed in and switched on, any kind of account: only for what every
    account has (its own notices in the app) and for the admin pages, which
    check the number themselves."""
    return _require_on(user)


async def get_current_manager(user: User = Depends(get_signed_in_account)) -> User:
    """A Doongerwadi or prayer hall manager's account, signed in and switched
    on (D9). A mobed's account is refused: none of the manager's side is theirs."""
    if user.account_kind != ACCOUNT_FUNERAL_MANAGER:
        raise HTTPException(status_code=403, detail=NOT_FOR_MOBEDS)
    return _require_on(user)


async def get_user_not_switched_off(user: User = Depends(get_signed_in_user)) -> User:
    """Signed in and not switched off: on, or still signing up. For what adding
    a fire temple while signing up needs (finding it on the map); anything that
    reads or changes the mobed's own book asks for get_current_user."""
    access = mobed_access.effective(get_settings(), user)
    if access == ACCESS_OFF:
        raise HTTPException(status_code=403, detail=NO_ACCESS["off"], headers={ACCESS_HEADER: access})
    return user


async def _require_membership(db: AsyncSession, agyary_id: int, user: User) -> Agyary:
    agyary = await db.get(Agyary, agyary_id)
    if agyary is None or not agyary.is_active:
        raise HTTPException(status_code=404, detail="That fire temple could not be found.")
    if not await mobed_dashboard.is_active_member(db, agyary_id, user.id):
        raise HTTPException(status_code=403, detail="You are not at this fire temple in Mobed Diary.")
    return agyary


# ---------------------------------------------------------------------------
# Auth: session cookies, refresh, me (see services/mobed_auth.py)
# ---------------------------------------------------------------------------
class Cookies(BaseModel):
    """Which cookies an app keeps its sign-in in. The behdin app (R4.0) has its
    own names and its own path, so the two apps never see or clear each
    other's when both are served from one host."""
    model_config = {"frozen": True}
    refresh: str = "refresh_token"
    wa_login: str = "wa_login"
    path: str = "/"


MOBED_COOKIES = Cookies()


def _set_refresh_cookie(response: Response, session, cookies: Cookies = MOBED_COOKIES) -> None:
    settings = get_settings()
    response.set_cookie(
        cookies.refresh,
        mobed_auth.issue_refresh_token(session.user_id, session),
        path=cookies.path,
        httponly=True,
        # Secure cookies are never sent back over plain HTTP - fine in
        # production (this deploys behind a Cloudflare Tunnel terminating
        # TLS), but would silently break local dev/tests, which talk plain
        # HTTP. Match the common framework convention: secure only outside
        # debug mode.
        secure=not settings.app_debug,
        samesite="strict",
        max_age=settings.jwt_refresh_token_days * 86400,
    )


# ---------------------------------------------------------------------------
# Sign-in: the mobed messages us
#
# The only sign-in path. Nothing is sent, so nothing needs an approved
# template and nothing is billable, and the caller never types a phone
# number at all - we learn it from a payload Meta signed, which is why
# there is nothing here to enumerate. See services/wa_login.py.
# ---------------------------------------------------------------------------
async def _wa_login_session(
    db: AsyncSession, response: Response, poll_secret: str, phone: str, name: str,
    *, wa_user_id: str | None = None, kind: str = ACCOUNT_MOBED, cookies: Cookies = MOBED_COOKIES,
    serialize=None,
) -> dict:
    """Turn a claimed attempt into a session, or say a name is still needed.

    The attempt row is only retired once a session actually exists, so a
    first-ever sign-in can come back with a name and finish against the
    same row rather than being handed its own phone number to post back.

    A number that may not sign up (SIGNUP_MODE) is told so plainly, and its
    attempt is spent: polling on would only wait for ever.
    """
    try:
        user = await mobed_auth.login_user(db, phone, name, kind)
    except mobed_auth.SignupRefused as exc:
        await wa_login.consume(db, poll_secret)
        await db.commit()
        refused = JSONResponse(status_code=403, content={"detail": str(exc)})
        refused.delete_cookie(cookies.wa_login, path=cookies.path)
        return refused
    if wa_user_id and not user.wa_user_id:
        # Learnt from a sign-in that carried both, so one that later carries
        # only the username id still finds this mobed (AU-4).
        taken = (await db.execute(select(User.id).where(User.wa_user_id == wa_user_id))).first()
        if taken is None:
            user.wa_user_id = wa_user_id
    if not user.name:
        await db.commit()
        return {"status": "needs_name"}

    await wa_login.consume(db, poll_secret)
    session = await mobed_auth.start_session(db, user)
    await db.commit()
    response.delete_cookie(cookies.wa_login, path=cookies.path)
    _set_refresh_cookie(response, session, cookies)
    return {
        "status": "signed_in",
        "access_token": mobed_auth.issue_access_token(user.id, session.id),
        "user": await (serialize or _serialize_user)(db, user),
    }


@router.post("/auth/wa/start")
async def wa_login_start(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> dict:
    """Open a sign-in attempt and hand back the link to send.

    Takes no phone number - that is the point. There is nothing here to
    enumerate and nothing to confirm or deny, because the caller tells us
    nothing about who they are; we learn that from a payload Meta signed.

    Rate-limited per IP. Sends cost nothing now, but each call still writes
    a row and mints a code, and an endpoint that does either without a
    ceiling is an invitation.
    """
    rate_limit.enforce(request, "wa_login_start", max_requests=10, window_seconds=300)
    try:
        started = await wa_login.start(db)
    except wa_login.WaLoginError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await db.commit()

    settings = get_settings()
    response.set_cookie(
        "wa_login",
        started.poll_secret,
        httponly=True,
        secure=not settings.app_debug,
        samesite="lax",
        max_age=settings.wa_login_ttl_seconds,
    )
    # The code goes back so the screen can show it: the wa.me text is a
    # prefill the user can edit, and someone who mangles it needs to see
    # what they were supposed to send.
    return {
        "code": started.code,
        "wa_link": started.wa_link,
        "expires_at": started.expires_at.isoformat(),
    }


@router.get("/auth/wa/poll")
async def wa_login_poll(
    request: Request,
    response: Response,
    wa_login_cookie: str | None = Cookie(default=None, alias="wa_login"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Has this browser's attempt been claimed yet?

    Matches on the cookie, never on the code. The code is a bearer token
    that travels through the user's own WhatsApp; if polling accepted it,
    anyone who saw the link could collect the session it created.
    """
    rate_limit.enforce(request, "wa_login_poll", max_requests=200, window_seconds=300)
    if not wa_login_cookie:
        raise HTTPException(status_code=400, detail="No sign-in is in progress.")

    attempt = await wa_login.peek(db, wa_login_cookie)
    if attempt is None or attempt.claimed_at is None:
        return {"status": "pending"}
    if attempt.claimed_phone is None:
        # WhatsApp sent a username id we cannot tie to any mobed, and no number.
        await wa_login.consume(db, wa_login_cookie)
        await db.commit()
        refused = JSONResponse(status_code=403, content={"detail": NO_NUMBER})
        refused.delete_cookie("wa_login")
        return refused
    if attempt.confirm_hash is not None:
        # AU-1: waiting for the number we sent to that phone.
        return {"status": "confirm"}
    return await _wa_login_session(
        db, response, wa_login_cookie, attempt.claimed_phone, "", wa_user_id=attempt.claimed_wa_user_id
    )


NO_NUMBER = (
    "WhatsApp did not share your phone number with us - this happens when you use a WhatsApp "
    "username. Ask the person who runs Mobed Diary to help you sign in."
)


class WaLoginConfirmIn(BaseModel):
    number: str


@router.post("/auth/wa/confirm")
async def wa_login_confirm(
    payload: WaLoginConfirmIn,
    request: Request,
    response: Response,
    wa_login_cookie: str | None = Cookie(default=None, alias="wa_login"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Finish a "send us a code" sign-in with the number we sent back to the
    phone the code came from (AU-1). Someone who only started the attempt -
    and tricked a mobed into sending its code - never sees that number."""
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
    return await _wa_login_session(
        db, response, wa_login_cookie, attempt.claimed_phone, "", wa_user_id=attempt.claimed_wa_user_id
    )


class WaLoginCompleteIn(BaseModel):
    name: str


@router.post("/auth/wa/complete")
async def wa_login_complete(
    payload: WaLoginCompleteIn,
    request: Request,
    response: Response,
    wa_login_cookie: str | None = Cookie(default=None, alias="wa_login"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Finish a first-ever sign-in by supplying a display name.

    WhatsApp does send the sender's profile name, and we deliberately do
    not use it: what someone calls themselves on WhatsApp is not what they
    want printed on a ceremony slip.
    """
    rate_limit.enforce(request, "wa_login_complete", max_requests=20, window_seconds=300)
    if not wa_login_cookie:
        raise HTTPException(status_code=400, detail="No sign-in is in progress.")

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Please enter your name.")
    _check_template_text(name, "name", template_text.MOBED_NAME_MAX)

    attempt = await wa_login.peek(db, wa_login_cookie)
    phone = await wa_login.peek_claimed_phone(db, wa_login_cookie)
    if phone is None:
        raise HTTPException(status_code=400, detail="That sign-in has expired. Please start again.")
    return await _wa_login_session(
        db, response, wa_login_cookie, phone, name, wa_user_id=attempt.claimed_wa_user_id
    )


@router.post("/auth/refresh")
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sliding session: every successful refresh re-issues the refresh
    cookie too, not just the access token. Without this, the cookie's
    expiry is pinned to the original login and a daily user still gets
    logged out jwt_refresh_token_days after that - not after they actually
    stopped using the app. This is what makes "log in once, never again"
    (the user's explicit requirement) actually true for someone who opens
    the app at least once within the window."""
    if refresh_token is None:
        raise HTTPException(status_code=401, detail="Please sign in again.")
    try:
        claims = mobed_auth.decode_token(refresh_token, "refresh")
        user = await db.get(User, claims["sub"])
        if user is None or not user.is_active:
            raise mobed_auth.TokenError("This account could not be found. Please sign in again.")
        # Each refresh token is good once: the session moves on a generation,
        # and an older one coming back ends the session (AU-2).
        session = await mobed_auth.rotate(db, claims)
    except mobed_auth.TokenError as exc:
        await db.commit()                      # a session ended for reuse stays ended
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    await db.commit()
    _set_refresh_cookie(response, session)
    return {"access_token": mobed_auth.issue_access_token(user.id, session.id)}


async def _serialize_user(db: AsyncSession, user: User) -> dict:
    # Ordered by joined_at: the PWA treats agyaries[0] as THE fire temple for
    # this mobed (no switcher in this v1 - one mobed, one temple), so this
    # order must be deterministic, not whatever an unordered join happens to
    # return. Earliest-joined wins if a member ever does end up with more
    # than one active membership.
    result = await db.execute(
        select(Agyary, AgyaryUser)
        .join(AgyaryUser, AgyaryUser.agyary_id == Agyary.id)
        .where(AgyaryUser.user_id == user.id, AgyaryUser.is_active.is_(True))
        .order_by(AgyaryUser.joined_at)
    )
    agyaries = [
        {
            "id": a.id, "name": a.name, "role": m.role, "calendar_system": a.calendar_system,
            "city": a.city, "address": a.address, "contact_phone": a.contact_phone, "status": a.status,
            "location": _location(a),
            # What they said they are here, and whether it waits for the admin (D10).
            # Only ``role`` gives anything; Settings shows these.
            "claimed_role": m.claimed_role,
            "panthaky_claim_waiting": panthaky.waiting(m),
            "may_claim_panthaky": panthaky.may_claim(m),
        }
        for a, m in result.all()
    ]
    access = mobed_access.effective(get_settings(), user)
    # A manager's places (D10); always empty for a mobed's account.
    places = (
        [funeral_places.summary(p) for p in await funeral_places.places_of(db, user.id)]
        if user.account_kind == ACCOUNT_FUNERAL_MANAGER else []
    )
    return {
        "id": user.id, "name": user.name, "phone": user.phone, "agyaries": agyaries,
        # "mobed" or "funeral_manager" (D10): the app shows a manager only their own screens.
        "account_kind": user.account_kind,
        "funeral_places": places,
        # A brand-new account first chooses: a mobed (or panthaky), or a
        # Doongerwadi manager. Never asked of an account that has chosen.
        "may_choose_kind": await funeral_places.may_choose_kind(db, get_settings(), user),
        "automatic_reminders": user.automatic_reminders,
        # The mobed's own switch for the evening-before report, and whether it also goes
        # to WhatsApp yet (otherwise it is in the app only) - so Settings can say so.
        "daily_report": user.daily_report,
        "daily_report_whatsapp": get_settings().daily_report_send_mode == "live",
        # Only to show the admin screen's menu entry; the server checks again on every call.
        "is_admin": guardrails.is_admin(get_settings(), user.phone),
        # "on", or "pending"/"off": the app then shows only its waiting screen (D9),
        # with the number to get in touch on, if the server has one. Sent while on
        # too, so a mobed switched off mid-use is shown it without asking again.
        "access": access,
        "support_phone": get_settings().support_phone.strip() or None,
    }


class LogoutIn(BaseModel):
    # This phone's push subscription, if it has notifications on: forgotten too.
    endpoint: str | None = Field(default=None, max_length=2000)


@router.post("/auth/logout")
async def logout(
    response: Response,
    payload: LogoutIn | None = Body(default=None),
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """End the session.

    Needed because the refresh cookie is httpOnly: the client can drop its
    in-memory access token, but it cannot clear the cookie, so without this
    "sign out" would silently sign you straight back in on the next load -
    the opposite of what someone handing their phone to a colleague wants.
    Cleared with the same attributes it was set with, or the browser won't
    match it. This phone's notifications stop too (``endpoint``, its push
    subscription, which the app also unsubscribes in the browser), so a phone
    handed over shows nothing more of this account.
    """
    settings = get_settings()
    # The session ends on the server too, so a copy of the cookie is worthless.
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
        "refresh_token",
        httponly=True,
        secure=not settings.app_debug,
        samesite="strict",
    )
    return {"signed_out": True}


class DeleteAccountIn(BaseModel):
    # The screen asks twice; this is the second answer, so a stray request
    # with no body deletes nothing.
    confirm: bool


@router.post("/auth/account/delete")
async def delete_my_account(
    payload: DeleteAccountIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_signed_in_account),
) -> dict:
    """Delete this account and everything that is the mobed's (PV-2; Google
    Play's account-deletion rule). Signs out everywhere, since the account is
    gone. Cannot be undone."""
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Nothing was deleted.")
    await account.delete_account(db, user)
    await db.commit()
    settings = get_settings()
    response.delete_cookie("refresh_token", httponly=True, secure=not settings.app_debug, samesite="strict")
    return {"deleted": True}


class SignOutOthersIn(BaseModel):
    # This phone's push subscription, if it has notifications on: it stays.
    keep_endpoint: str | None = Field(default=None, max_length=2000)


@router.post("/auth/sessions/sign-out-others")
async def sign_out_other_devices(
    payload: SignOutOthersIn | None = Body(default=None),
    authorization: str = Header(default=""), db: AsyncSession = Depends(get_db)
) -> dict:
    """End every other signed-in device of this mobed - a lost phone, a phone
    lent to someone, a sign-in they do not recognise - and refuse any token
    from before sessions existed. This device stays signed in, and keeps its
    notifications (``keep_endpoint``); the others' stop."""
    user, session_id = await _current(authorization, db)
    if user.account_kind == ACCOUNT_BEHDIN:
        raise HTTPException(status_code=403, detail=NOT_FOR_BEHDINS, headers={ACCOUNT_KIND_HEADER: user.account_kind})
    ended = await mobed_auth.end_all_sessions(db, user, keep=session_id,
                                              keep_endpoint=payload.keep_endpoint if payload is not None else None)
    await db.commit()
    return {"signed_out": ended}


@router.get("/auth/me")
async def me(db: AsyncSession = Depends(get_db), user: User = Depends(get_signed_in_account)) -> dict:
    return await _serialize_user(db, user)


class UpdateMeIn(BaseModel):
    name: str


@router.patch("/auth/me")
async def update_me(
    payload: UpdateMeIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_signed_in_account)
) -> dict:
    """Let a mobed correct their own display name from the profile screen.
    Phone stays read-only here - it is the sign-in identity, and it is the
    one field the mobed never typed: it came off a WhatsApp payload Meta
    signed. Letting the profile screen overwrite that would let someone
    move their proven number to an unproven one."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Please enter a name.")
    _check_template_text(name, "name", template_text.MOBED_NAME_MAX)
    user.name = name
    await db.commit()
    return await _serialize_user(db, user)


# ---------------------------------------------------------------------------
# Display preferences (per user, not per agyari - see models/preferences.py)
# ---------------------------------------------------------------------------
def _preferences_response(prefs: UserPreferences | None) -> dict:
    if prefs is None:
        return default_preferences()
    # Fasli is no longer offered (D5). A preference saved with it reads as the
    # default; the saved row itself is left as it was.
    primary = prefs.default_secondary_system
    if primary not in OFFERED_CALENDARS:
        primary = DEFAULT_SECONDARY_CALENDAR_SYSTEM
    visible = [s for s in prefs.visible_calendar_systems if s in OFFERED_DISPLAY_SYSTEMS]
    if primary not in visible:
        visible.append(primary)
    return {
        "visible_calendar_systems": visible,
        "default_secondary_system": primary,
        "display_language": prefs.display_language,
    }


class DailyReportIn(BaseModel):
    enabled: bool


@router.put("/me/daily-report")
async def put_daily_report(
    payload: DailyReportIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Turn the evening-before report on or off for this mobed."""
    user.daily_report = payload.enabled
    await db.commit()
    return {"daily_report": user.daily_report, "daily_report_whatsapp": get_settings().daily_report_send_mode == "live"}


# ---------------------------------------------------------------------------
# Notifications on this phone (web push, services/web_push.py), for every
# account that is on: a mobed's (a Doongerwadi's request for prayers) and a
# manager's, as well as an admin's. Each phone is turned on by itself.
# ---------------------------------------------------------------------------
class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(max_length=2000)
    keys: PushKeysIn


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=2000)


NO_PUSH_KEYS = "Phone notifications are not set up on the server yet."


@router.get("/me/push")
async def my_push_status(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_account)) -> dict:
    """Whether the server can send to phones, the public key a phone needs to
    sign up, and how many of this account's phones are signed up."""
    s = get_settings()
    return {
        "configured": web_push.configured(s),
        "public_key": s.vapid_public_key.strip() or None,
        "devices": await web_push.devices(db, user.id),
    }


@router.post("/me/push/subscribe")
async def my_push_subscribe(
    payload: PushSubscribeIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_account),
) -> dict:
    rate_limit.enforce_key(f"push_subscribe:{user.id}", max_requests=20, window_seconds=60)
    if not web_push.configured(get_settings()):
        raise HTTPException(status_code=409, detail=NO_PUSH_KEYS)
    # Only the browsers' own push services: this cannot be pointed anywhere else.
    if not web_push.allowed_endpoint(payload.endpoint):
        raise HTTPException(status_code=400, detail="This browser's notification service is not one we know.")
    await web_push.save(db, user.id, payload.endpoint, payload.keys.p256dh, payload.keys.auth)
    await db.commit()
    return {"devices": await web_push.devices(db, user.id)}


@router.post("/me/push/unsubscribe")
async def my_push_unsubscribe(
    payload: PushUnsubscribeIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_signed_in_account),
) -> dict:
    """Stop this phone. Open to an account that is off or waiting too: turning
    notifications off is never refused."""
    await web_push.remove(db, user.id, payload.endpoint)
    await db.commit()
    return {"devices": await web_push.devices(db, user.id)}


@router.post("/me/push/test")
async def my_push_test(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_account)) -> dict:
    """A test notification to every phone this account turned it on for."""
    rate_limit.enforce_key(f"push_test:{user.id}", max_requests=5, window_seconds=60)
    s = get_settings()
    if not web_push.configured(s):
        raise HTTPException(status_code=409, detail=NO_PUSH_KEYS)
    sent = await web_push.send_to_users(
        db, s, [user.id], title="Mobed Diary", body="Notifications are working on this phone.",
        url="/mobed", tag="push-test",
    )
    await db.commit()
    return {"sent": sent, "devices": await web_push.devices(db, user.id)}


@router.get("/me/person-names")
async def my_person_names(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_account)) -> dict:
    """The departed's names kept for this account's own number, newest first
    (D12, 24 Nov 2026). Any kind of account that is on, mobed or manager; only
    by the account's own number. Nothing takes a phone: no one else's pool can
    be asked for, and no other screen reads it."""
    return {"names": [person_names.as_dict(r) for r in await person_names.mine(db, user)]}


@router.get("/me/preferences")
async def get_preferences(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_signed_in_user)
) -> dict:
    """Someone who has never opened Settings has no row; they get the
    defaults rather than a 404, so the client has one shape to render."""
    return _preferences_response(await db.get(UserPreferences, user.id))


class PreferencesIn(BaseModel):
    visible_calendar_systems: list[str]
    default_secondary_system: str
    display_language: str


@router.put("/me/preferences")
async def put_preferences(
    payload: PreferencesIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Replace this user's display preferences. Writes the row on first use.

    Does not touch Agyary.calendar_system, and must not: that field decides
    which Parsi reckoning is stamped onto ceremony records and is part of
    the historical record, not a view setting.
    """
    systems = list(dict.fromkeys(payload.visible_calendar_systems))  # de-dup, keep order
    unknown = [s for s in systems if s not in OFFERED_DISPLAY_SYSTEMS]
    if unknown:
        raise HTTPException(
            status_code=400, detail="Please choose the calendars to show from the list, and try again.",
        )
    if not systems:
        raise HTTPException(status_code=400, detail="Please keep at least one calendar showing.")
    if payload.default_secondary_system not in OFFERED_CALENDARS:
        raise HTTPException(
            status_code=400, detail="Please choose the second calendar from the list, and try again.",
        )
    if payload.default_secondary_system not in systems:
        raise HTTPException(
            status_code=400, detail="Please choose a second calendar from those you show."
        )
    if payload.display_language not in DISPLAY_LANGUAGES:
        raise HTTPException(
            status_code=400, detail="Please choose a language from the list, and try again."
        )

    prefs = await db.get(UserPreferences, user.id)
    if prefs is None:
        prefs = UserPreferences(user_id=user.id)
        db.add(prefs)
    prefs.visible_calendar_systems = systems
    prefs.default_secondary_system = payload.default_secondary_system
    prefs.display_language = payload.display_language
    await db.commit()
    return _preferences_response(prefs)


# ---------------------------------------------------------------------------
# Agyari search / join
# ---------------------------------------------------------------------------
def _check_template_text(text: str, what: str, max_len: int) -> None:
    """A temple or service name is read out in every reminder for it, so it
    may not carry a link, a handle or a number (services/template_text.py)."""
    try:
        template_text.check(text, what, max_len=max_len)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



def _agyary_summary(a: Agyary) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "city": a.city,
        "address": a.address,
        "status": a.status,
    }


async def _has_membership(db: AsyncSession, user: User) -> bool:
    """Whether this mobed has ever joined a fire temple: the first join is the
    end of signing up."""
    return (await db.execute(select(AgyaryUser.agyary_id).where(AgyaryUser.user_id == user.id))).first() is not None


@router.get("/agyaries/search")
async def search_agyaries(q: str = Query(default=""), db: AsyncSession = Depends(get_db)) -> list[dict]:
    agyaries = await mobed_dashboard.search_agyaries(db, q)
    return [_agyary_summary(a) for a in agyaries]


# "Are you a mobed here, or the panthaky?", asked as a fire temple is chosen
# (D10). Optional for the API, so an app from before the question still joins;
# the app itself always asks, and Settings asks anyone who never answered.
ClaimedRole = Literal["mobed", "panthaky"]


class JoinAgyaryIn(BaseModel):
    claimed_role: ClaimedRole | None = None


async def _joined(
    db: AsyncSession, user: User, agyary: Agyary, claimed_role: str | None, *, first: bool,
    created: bool = False,
) -> None:
    """Join ``user`` to ``agyary`` as a plain mobed and keep what they said they
    are there - a claim only, ``role`` stays mobed (D10). A new mobed has then
    finished signing up and the admins are asked to approve them (D9), told
    too if they say they are the panthaky; a mobed already using the app who
    says so has the admins told on its own.

    Joining stays open (D1.4) and grants nobody's behdins (D2); for prayer
    requests the membership waits to be confirmed (D10, 22 Nov 2026): at a
    sign-up, by the admin's approval. ``created``: they have just added this
    fire temple, so there is nobody else there to confirm them, and they are
    confirmed for it now (still nothing reaches them until their own access is
    on, D9)."""
    # Locked, so this and becoming a Doongerwadi manager cannot both happen at
    # once (services/funeral_places.join_as_manager locks the same row).
    await db.refresh(user, with_for_update=True)
    refuse_other_kinds(user)
    before = await mobed_auth.get_membership(db, agyary.id, user.id)
    joined_now = before is None or not before.is_active
    membership = await mobed_auth.ensure_agyary_membership(db, agyary.id, user)
    if created and membership.requests_confirmed_at is None:
        membership.requests_confirmed_at = datetime.now(timezone.utc)
        membership.requests_confirmed_by_user_id = user.id
        await db.flush()
    claimed = bool(claimed_role) and await panthaky.record_claim(db, membership, claimed_role)
    settings = get_settings()
    if first:
        await mobed_access.tell_admins_of_request(
            db, settings, user, agyary, says_panthaky=panthaky.waiting(membership)
        )
    elif claimed and panthaky.waiting(membership) and mobed_access.has_access(settings, user):
        await panthaky.tell_admins_of_claim(db, settings, user, agyary)
    if joined_now:
        # Already using the app and not confirmed here: its panthaky (or, with none,
        # the admin) is told, to confirm them on the Mobeds page (D10, 22 Nov 2026).
        await join_confirmation.tell_of_join(db, settings, user, agyary, membership)


@router.post("/agyaries/{agyary_id}/join")
async def join_agyari(
    agyary_id: int,
    payload: JoinAgyaryIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_signed_in_user),
) -> dict:
    agyary = await db.get(Agyary, agyary_id)
    if agyary is None or not agyary.is_active:
        raise HTTPException(status_code=404, detail="That fire temple could not be found.")
    first = not await _has_membership(db, user)
    await _joined(db, user, agyary, payload.claimed_role if payload else None, first=first)
    await db.commit()
    # Include the agyari (with status) so the client knows whether an
    # activation step is still needed for an unclaimed seed entry.
    return {"user": await _serialize_user(db, user), "agyary": _agyary_summary(agyary)}


class ActivateAgyaryIn(BaseModel):
    name: str
    city: str
    address: str | None = None
    contact_phone: OptionalPhone = None


@router.post("/agyaries/{agyary_id}/activate")
async def activate_agyari(
    agyary_id: int,
    payload: ActivateAgyaryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_signed_in_user),
) -> dict:
    """Claim + set up an unclaimed seed agyari. The mobed must already be a
    member (they join first). Confirms/corrects the stale seed details and
    flips it to active."""
    agyary = await _require_membership(db, agyary_id, user)
    # Only an unclaimed temple is set up this way. An active one's name is
    # read out in every colleague's reminders, and joining is open to anyone
    # (D1), so a new member must not be able to rename it or change its number.
    await db.refresh(agyary, with_for_update=True)
    if agyary.status != "unclaimed":
        raise HTTPException(status_code=409, detail="This fire temple is already set up.")
    if not payload.name.strip() or not payload.city.strip():
        raise HTTPException(status_code=400, detail="Please enter the fire temple's name and city.")
    _check_template_text(payload.name, "fire temple's name", template_text.TEMPLE_MAX)
    await mobed_dashboard.activate_agyary(
        db, agyary,
        name=payload.name, city=payload.city,
        address=payload.address, contact_phone=payload.contact_phone,
    )
    await db.commit()
    return {"user": await _serialize_user(db, user), "agyary": _agyary_summary(agyary)}


# --- "Are you the panthaky?" from Settings (DECISIONS D10) -------------------
async def _own_membership(db: AsyncSession, agyary_id: int, user: User) -> tuple[Agyary, AgyaryUser]:
    agyary = await _require_membership(db, agyary_id, user)
    membership = await mobed_auth.get_membership(db, agyary_id, user.id)
    await db.refresh(membership, with_for_update=True)
    return agyary, membership


@router.post("/agyaries/{agyary_id}/panthaky-claim")
async def claim_panthaky(
    agyary_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """A mobed who joined before the question was asked says they are the
    panthaky of this fire temple. Only a claim: the admins are told, and
    nothing changes for the mobed unless an admin confirms it."""
    rate_limit.enforce_key(f"panthaky_claim:{user.id}", max_requests=10, window_seconds=3600)
    agyary, membership = await _own_membership(db, agyary_id, user)
    try:
        await panthaky.claim_panthaky(db, membership)
    except panthaky.ClaimError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await panthaky.tell_admins_of_claim(db, get_settings(), user, agyary)
    await db.commit()
    return await _serialize_user(db, user)


@router.delete("/agyaries/{agyary_id}/panthaky-claim")
async def withdraw_panthaky_claim(
    agyary_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Take back a panthaky claim the admin has not decided on yet."""
    _, membership = await _own_membership(db, agyary_id, user)
    try:
        await panthaky.withdraw_claim(db, membership)
    except panthaky.ClaimError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return await _serialize_user(db, user)


# --- Where a fire temple is (DECISIONS D10) ---------------------------------
class LocationIn(BaseModel):
    # Checked by hand in _checked_position, not by type: a refusal then comes in
    # plain words, and a NaN or Infinity in the body cannot reach FastAPI's
    # validation reply, which echoes the input and cannot write those as JSON
    # (a 500 instead of a refusal).
    latitude: object = None
    longitude: object = None


def _location(a: Agyary) -> dict | None:
    """The fire temple's position for its own mobeds, or None. ``source`` is
    "town" (only the town, from the seed list) or "pin" (put on the map by a
    person). Who moved it is kept on the record but not shown here."""
    if a.latitude is None or a.longitude is None or not a.location_source:
        return None
    return {
        "latitude": a.latitude,
        "longitude": a.longitude,
        "source": a.location_source,
        "set_at": a.location_set_at.isoformat() if a.location_set_at else None,
    }


def _coordinate(value: object) -> float | None:
    """A JSON number that is a real one: not a string, not true, not NaN."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:          # an integer too long to be a float
        return None
    return value if math.isfinite(value) else None


def _checked_position(payload: LocationIn, what: str = "the fire temple") -> tuple[float, float]:
    """A position on the map, rounded, or a 400 that says to put the pin on
    ``what``. Also used for a funeral place's pin (api/routes/admin.py)."""
    lat, lon = _coordinate(payload.latitude), _coordinate(payload.longitude)
    if (lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180)
            or (lat == 0 and lon == 0)):
        # 0, 0 is in the sea off Africa: what a broken phone or form sends, never a fire temple.
        raise HTTPException(status_code=400, detail=f"That place is not on the map. Please put the pin on {what}.")
    # Six places is about ten centimetres; more is noise.
    return round(lat, 6), round(lon, 6)


def _put_pin(agyary: Agyary, position: tuple[float, float], user: User) -> None:
    agyary.latitude, agyary.longitude = position
    agyary.location_source = LOCATION_PIN
    agyary.location_set_by_user_id = user.id
    agyary.location_set_at = datetime.now(timezone.utc)


async def _may_place_pin(db: AsyncSession, agyary_id: int, user: User) -> Agyary:
    """Its mobeds and panthaky (the caller is already known to be on, D9), or
    an admin, who may place any fire temple."""
    agyary = await db.get(Agyary, agyary_id)
    if agyary is None or not agyary.is_active:
        raise HTTPException(status_code=404, detail="That fire temple could not be found.")
    if guardrails.is_admin(get_settings(), user.phone):
        return agyary
    if not await mobed_dashboard.is_active_member(db, agyary_id, user.id):
        raise HTTPException(status_code=403, detail="Only the mobeds of this fire temple can change where it is.")
    return agyary


def _location_response(agyary: Agyary) -> dict:
    return {
        "agyary_id": agyary.id, "name": agyary.name, "city": agyary.city, "address": agyary.address,
        "location": _location(agyary),
    }


@router.get("/agyaries/{agyary_id}/location")
async def get_agyari_location(
    agyary_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    return _location_response(await _may_place_pin(db, agyary_id, user))


@router.put("/agyaries/{agyary_id}/location")
async def set_agyari_location(
    agyary_id: int,
    payload: LocationIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Put the fire temple's pin on the map, or move it. It becomes a "pin",
    which the town-level seed never overwrites."""
    agyary = await _may_place_pin(db, agyary_id, user)
    rate_limit.enforce_key(f"agyary_location:{user.id}", max_requests=30, window_seconds=3600)
    position = _checked_position(payload)
    await db.refresh(agyary, with_for_update=True)
    _put_pin(agyary, position, user)
    await db.commit()
    logger.info("Fire temple %s placed on the map by user %s", agyary.id, user.id)
    return _location_response(agyary)


class CreateAgyaryIn(BaseModel):
    name: str
    city: str
    address: str | None = None
    contact_phone: OptionalPhone = None
    # Optional: where it is, if the mobed put it on the map while adding it.
    location: LocationIn | None = None
    # What they are there (D10): a claim only, see JoinAgyaryIn.
    claimed_role: ClaimedRole | None = None


@router.post("/agyaries")
async def create_agyari(
    payload: CreateAgyaryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_signed_in_user),
) -> dict:
    """Creation fallback: the agyari isn't in the seed list at all. Same
    activation outcome (born active), then the creating mobed joins it. Every
    temple shows up in everyone's search, so a few a day is plenty (I-10)."""
    rate_limit.enforce_key(f"create_agyary:{user.id}", max_requests=5, window_seconds=86400)
    if not payload.name.strip() or not payload.city.strip():
        raise HTTPException(status_code=400, detail="Please enter the fire temple's name and city.")
    _check_template_text(payload.name, "fire temple's name", template_text.TEMPLE_MAX)
    position = _checked_position(payload.location) if payload.location else None
    agyary = await mobed_dashboard.create_agyary(
        db,
        name=payload.name, city=payload.city,
        address=payload.address, contact_phone=payload.contact_phone,
    )
    if position:
        _put_pin(agyary, position, user)
        await db.flush()
    first = not await _has_membership(db, user)
    # Adding a fire temple makes nobody its panthaky: they join as a mobed like
    # anyone else, and saying "panthaky" is a claim for the admin to confirm.
    # They are confirmed for its prayer requests: nobody else is there to (D10).
    await _joined(db, user, agyary, payload.claimed_role, first=first, created=True)
    await db.commit()
    return {"user": await _serialize_user(db, user), "agyary": _agyary_summary(agyary)}


# ---------------------------------------------------------------------------
# My Day / Machi Board
# ---------------------------------------------------------------------------
def _booking_summary(entry: mobed_dashboard.MyDayEntry) -> dict:
    b = entry.booking
    return {
        "booking_id": b.id,
        "agyary_id": entry.agyary_id,
        "agyary_name": entry.agyary_name,
        "service_id": b.service_id,
        "service_name": entry.service_name,
        "behdin_name": entry.behdin_name,
        "purpose": b.purpose,
        "ceremony_datetime": b.ceremony_datetime.isoformat(),
        "location": b.location,
        "is_offsite": b.is_offsite,
        "status": b.status,
        "paid": b.payment_status == mobed_dashboard.PAID,
    }


class PaidIn(BaseModel):
    paid: bool


@router.put("/agyaries/{agyary_id}/bookings/{booking_id}/paid")
async def set_booking_paid(
    agyary_id: int,
    booking_id: int,
    payload: PaidIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """The mobed's tick: this behdin has paid for this booking, or has not."""
    agyary = await _require_membership(db, agyary_id, user)
    if not await mobed_dashboard.set_booking_paid(db, agyary, booking_id, user.id, payload.paid):
        raise HTTPException(status_code=404, detail="That booking could not be found.")
    await db.commit()
    return {"paid": payload.paid}


@router.put("/agyaries/{agyary_id}/machis/{machi_id}/paid")
async def set_machi_paid(
    agyary_id: int,
    machi_id: int,
    payload: PaidIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agyary = await _require_membership(db, agyary_id, user)
    if not await mobed_dashboard.set_machi_paid(db, agyary, machi_id, user.id, payload.paid):
        raise HTTPException(status_code=404, detail="That machi could not be found.")
    await db.commit()
    return {"paid": payload.paid}


@router.get("/my-day")
async def my_day(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """This mobed's services, across every fire temple they belong to.

    ``from``/``to`` (IST calendar days, inclusive) ask for a window and get
    exactly that window, past days included - which is what the calendar
    needs, since it can be scrolled to any month. Omit both and it is the
    upcoming list from the 12-hour horizon, unchanged.

    Both or neither: a half-open window is a client bug, and quietly
    answering it with the upcoming list is how this went unnoticed the
    first time.
    """
    if (from_ is None) != (to is None):
        raise HTTPException(status_code=400, detail="Please choose both a start and an end date.")
    if from_ is not None and to is not None:
        if to < from_:
            raise HTTPException(status_code=400, detail="The end date is before the start date.")
        if (to - from_).days + 1 > mobed_dashboard.MAX_MY_DAY_RANGE_DAYS:
            raise HTTPException(
                status_code=400,
                detail=f"Please choose a shorter time, up to {mobed_dashboard.MAX_MY_DAY_RANGE_DAYS} days.",
            )
    if to is not None and await mobed_dashboard.ensure_booking_recurrences_generated(db, user.id, through=to):
        # A repeating event is written ahead only a few periods at a time; a
        # window further out tops it up here, so the calendar never stops short.
        await db.commit()
    entries = await mobed_dashboard.list_my_day(db, user.id, from_, to)
    return [_booking_summary(e) for e in entries]


@router.get("/reference/calendar-options")
async def calendar_options() -> dict:
    """Roj/Mah/Geh option lists for the add-event form's <select>
    dropdowns. Closed vocabularies are tap-to-select, never free text, and
    these read from the canonical name lists rather than a second copy."""
    return {
        "roj": roj_options(),
        "mah": mah_options(),
        "geh": geh_options(),
    }


# ---------------------------------------------------------------------------
# Services catalog: list and add. Reachable from the event form's
# "+ Add a new service"; there is no deactivate path and no UI for one.
# ---------------------------------------------------------------------------
def _service_summary(s: Service) -> dict:
    return {"id": s.id, "name": s.name, "is_active": s.is_active, "offsite_capable": s.offsite_capable}


@router.get("/agyaries/{agyary_id}/services")
async def list_all_services(
    agyary_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    """Every service at this agyari, active or not.

    The event form filters to active ones itself. Inactive rows are still
    returned so a past event that used one can render its name rather than
    a blank - they are history, not options. Machi is included: mobeds book
    it as an ordinary service here same as any other, alongside the
    dedicated Machi board's slot-based flow."""
    await _require_membership(db, agyary_id, user)
    result = await db.execute(
        select(Service)
        .where(Service.agyary_id == agyary_id)
        .order_by(Service.display_order, Service.id)
    )
    return [_service_summary(s) for s in result.scalars()]


class CreateServiceIn(BaseModel):
    name: str
    offsite_capable: bool = False


@router.post("/agyaries/{agyary_id}/services")
async def create_service(
    agyary_id: int,
    payload: CreateServiceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await _require_membership(db, agyary_id, user)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Please enter the service's name.")
    _check_template_text(name, "service name", template_text.SERVICE_MAX)
    service = Service(agyary_id=agyary_id, name=name, offsite_capable=payload.offsite_capable, display_order=999)
    db.add(service)
    await db.commit()
    return _service_summary(service)


@router.get("/agyaries/{agyary_id}/machi-board")
async def machi_board(
    agyary_id: int,
    from_: date = Query(alias="from"),
    to: date = Query(),
    mine: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Machis at this agyari within [from, to] inclusive, by Parsi-day
    anchor (gregorian_date).

    The window is required: this previously returned the agyari's entire
    machi history on every call, which a calendar refetching per month-step
    would re-download in full.

    A mobed's machis are private to them (docs/DECISIONS.md D2): whatever is
    asked for, a caller who is not the temple's panthaky or caretaker gets
    only the machis they entered themselves, and never learns that a
    colleague holds a slot. A panthaky or caretaker keeps full authority over
    their temple for now (the roles module comes later) and so sees every
    machi, unless they ask for ``mine=true``, which narrows it to their own.

    Recurring machis are topped up here before reading. There is no
    scheduler in this deployment, so if nothing generated them on the way
    past, a standing monthly arrangement would simply stop at whatever
    horizon it was created with - the mobed steps into a fourth month and
    the machi is not there. Committed only when something was actually
    written, so an ordinary read stays a read.
    """
    await _require_membership(db, agyary_id, user)
    try:
        mobed_dashboard.check_board_range(from_, to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    admin = await mobed_dashboard.is_admin(db, agyary_id, user.id)
    if await mobed_dashboard.ensure_recurrences_generated(
        db, agyary_id, through=to, owner_id=None if admin else user.id
    ):
        await db.commit()
    try:
        entries = await mobed_dashboard.list_machi_board(
            db, agyary_id, from_, to, created_by_user_id=user.id if (mine or not admin) else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _mine(machi) -> bool:
        return admin or user.id in (machi.created_by_user_id, machi.assigned_mobed_id)

    return [
        {
            "id": e.machi.id,
            "purpose": e.machi.purpose,
            "geh": e.machi.geh,
            "parsi_roj": e.machi.parsi_roj,
            "parsi_mah": e.machi.parsi_mah,
            "gregorian_date": e.machi.gregorian_date.isoformat(),
            "ceremony_datetime": e.machi.ceremony_datetime.isoformat(),
            "status": e.machi.status,
            "behdin_name": e.behdin_name if _mine(e.machi) else "",
            "mine": _mine(e.machi),
            # Only on the caller's own machis, like the family's name.
            "paid": (e.machi.payment_status == mobed_dashboard.PAID) if _mine(e.machi) else False,
        }
        for e in entries
    ]


@router.get("/agyaries/{agyary_id}/bookable-gehs")
async def bookable_gehs(
    agyary_id: int, on: date = Query(), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Which gehs on `on` can still be booked by the caller - via the SAME shared
    availability core the booking path uses, so the Machi tab can show
    free/booked/already-passed correctly instead of a generic 'tap to book'
    that then fails with 'already booked' for a slot that's simply elapsed.
    Only the caller's own machis count: a colleague's are not visible here."""
    agyary = await _require_membership(db, agyary_id, user)
    return {"bookable": await mobed_dashboard.bookable_gehs(db, agyary, on, user.id)}


def _slip_response(slip: mobed_dashboard.SlipData) -> dict:
    return {
        "agyary_name": slip.agyary_name,
        "behdin_name": slip.behdin_name,
        "behdin_phone": slip.behdin_phone,
        "event": slip.event,
        "when": slip.when,
        "names_text": slip.names_text,
        "is_recurring": slip.is_recurring,
    }


@router.get("/agyaries/{agyary_id}/machis/{machi_id}/slip")
async def machi_slip(
    agyary_id: int, machi_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    await _require_membership(db, agyary_id, user)
    slip = await mobed_dashboard.get_machi_slip(db, agyary_id, machi_id, reader_user_id=user.id)
    if slip is None:
        raise HTTPException(status_code=404, detail="That machi could not be found.")
    return _slip_response(slip)


@router.get("/agyaries/{agyary_id}/bookings/{booking_id}/slip")
async def booking_slip(
    agyary_id: int, booking_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    await _require_membership(db, agyary_id, user)
    slip = await mobed_dashboard.get_booking_slip(db, agyary_id, booking_id, reader_user_id=user.id)
    if slip is None:
        raise HTTPException(status_code=404, detail="That booking could not be found.")
    return _slip_response(slip)


# ---------------------------------------------------------------------------
# My customers (search + autofill for the add-machi/add-booking form) - a
# mobed's own behdins, not the fire temple's shared customer pool and not
# another mobed's relationship with the same person.
# ---------------------------------------------------------------------------
@router.get("/customers/{customer_id}/history")
async def customer_history(
    customer_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    result = await mobed_dashboard.get_customer_history(db, user.id, customer_id)
    if result is None:
        raise HTTPException(status_code=404, detail="That behdin could not be found.")
    return result


# ---------------------------------------------------------------------------
# Behdin records: explicit create/read/update, plus their saved name pool.
#
# Complements - does not replace - the implicit create-on-save that the
# booking paths still use (mobed_dashboard._resolve_customer): a walk-in
# dictated at the counter shouldn't need a separate setup step first, but
# it can't be the only way to get a record either, or a mistyped number is
# uncorrectable and a family's names can't be prepared in advance.
# ---------------------------------------------------------------------------
async def _require_behdin(db: AsyncSession, agyary_id: int, customer_id: int, user: User) -> Customer:
    await _require_membership(db, agyary_id, user)
    customer = await behdin_directory.get_scoped(db, agyary_id, customer_id, user.id)
    if customer is None:
        # Deliberately 404, not 403, for a behdin who exists but isn't this
        # mobed's: whether a given person is on file elsewhere - or at all -
        # is not this caller's business, and a 403 would confirm it.
        raise HTTPException(status_code=404, detail="That behdin could not be found.")
    return customer


@router.get("/agyaries/{agyary_id}/behdins")
async def list_behdins(
    agyary_id: int,
    q: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """This mobed's own behdins at this fire temple.

    NOT the temple's register. A behdin's name and phone number are their
    own; a mobed has no business reading the people a colleague serves.
    Scoped server-side, because a list filtered in the client is not a
    permission.

    Unlike the old booking-derived customer search, this reads the
    register itself, so it includes someone registered moments ago and
    never booked for - exactly who you are looking for right after
    adding them.
    """
    await _require_membership(db, agyary_id, user)
    rows = await behdin_directory.search_mine(db, agyary_id, user.id, q)
    return [behdin_directory.customer_summary(c) for c in rows]


class CreateBehdinIn(BaseModel):
    name: str
    phone: Phone


@router.post("/agyaries/{agyary_id}/behdins")
async def create_behdin(
    agyary_id: int,
    payload: CreateBehdinIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Register a behdin at this agyari.

    A phone already on file resolves to that existing person and links them
    here (``created: false``) rather than erroring - phone is the identity,
    and that is what lets a behdin who visits more than one temple keep a
    single history. Their stored name is left alone in that case.
    """
    await _require_membership(db, agyary_id, user)
    try:
        customer, created = await behdin_directory.create_or_link(
            db, agyary_id, user.id, name=payload.name, phone=payload.phone
        )
    except behdin_directory.BehdinError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return {**behdin_directory.customer_summary(customer), "created": created}


@router.get("/agyaries/{agyary_id}/behdins/{customer_id}")
async def get_behdin(
    agyary_id: int,
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    customer = await _require_behdin(db, agyary_id, customer_id, user)
    return {
        **behdin_directory.customer_summary(customer),
        "reminders": await reminders.reminder_state(db, user.id, customer),
    }


class UpdateBehdinIn(BaseModel):
    # Both optional so a caller can correct one without restating the other.
    name: str | None = None
    phone: OptionalPhone = None


@router.patch("/agyaries/{agyary_id}/behdins/{customer_id}")
async def update_behdin(
    agyary_id: int,
    customer_id: int,
    payload: UpdateBehdinIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Correct a behdin's name or number. Moving a number onto a person who
    already has their own record is refused - that would merge two
    histories, which is not a typo-shaped decision."""
    customer = await _require_behdin(db, agyary_id, customer_id, user)
    try:
        await behdin_directory.update(db, customer, name=payload.name, phone=payload.phone)
    except behdin_directory.BehdinError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return behdin_directory.customer_summary(customer)


@router.delete("/agyaries/{agyary_id}/behdins/{customer_id}")
async def delete_behdin(
    agyary_id: int,
    customer_id: int,
    scope: str = Query(default="list"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Remove a behdin from this mobed's book. ``scope`` says how much goes with
    them: ``list`` (default) keeps every event - see
    behdin_directory.remove_from_book; ``memorials`` also deletes their
    memorials; ``all`` also deletes their upcoming events (see
    mobed_dashboard.delete_behdin_scoped). ``erased`` says whether the record
    itself went too, or only their place in this mobed's list."""
    if scope not in mobed_dashboard.DELETE_SCOPES:
        raise HTTPException(status_code=400, detail="Please choose how much to delete, and try again.")
    customer = await _require_behdin(db, agyary_id, customer_id, user)
    agyary = await _require_membership(db, agyary_id, user)
    done = await mobed_dashboard.delete_behdin_scoped(db, agyary, customer, user.id, scope)
    await db.commit()
    if scope == "list":
        return {"deleted": True, "erased": done["erased"]}
    return {"deleted": True, **done}


@router.get("/agyaries/{agyary_id}/behdins/{customer_id}/delete-summary")
async def behdin_delete_summary(
    agyary_id: int,
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """What deleting this behdin could take with it - shown before the choice."""
    await _require_behdin(db, agyary_id, customer_id, user)
    return await mobed_dashboard.behdin_delete_summary(db, agyary_id, customer_id)


# --- Saved name pool (the same rows the WhatsApp flows read/write) ---------
@router.get("/agyaries/{agyary_id}/behdins/{customer_id}/saved-names")
async def list_saved_names(
    agyary_id: int,
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    await _require_behdin(db, agyary_id, customer_id, user)
    return await behdin_directory.list_saved_names(db, customer_id)


class SavedNameIn(BaseModel):
    title: str
    name: str
    status: str
    pair_group: int | None = None


class ReplaceSectionIn(BaseModel):
    names: list[SavedNameIn]


@router.put("/agyaries/{agyary_id}/behdins/{customer_id}/saved-names/{section}")
async def replace_saved_name_section(
    agyary_id: int,
    customer_id: int,
    section: str,
    payload: ReplaceSectionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Replace one section ('pair' or 'farmayeshne') of the pool wholesale.

    Section-at-a-time rather than row-at-a-time because the invariant lives
    at that level: a pair is exactly two names of one status, which is a
    property of the set. It's also already how the WhatsApp side thinks
    about this ('New set'), and reuses the same service function.
    """
    await _require_behdin(db, agyary_id, customer_id, user)
    if section not in NAME_SECTIONS:
        raise HTTPException(status_code=404, detail="That list of names could not be found. Please open the behdin again.")
    for n in payload.names:
        if n.title not in NAME_TITLES:
            raise HTTPException(status_code=400, detail="Please choose a title from the list for every name.")
        if n.status not in NAME_STATUSES:
            raise HTTPException(status_code=400, detail="Please choose living or departed for every name.")
    try:
        rows = await behdin_directory.replace_section(
            db, customer_id, section, [n.model_dump() for n in payload.names]
        )
    except behdin_directory.BehdinError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return rows


@router.delete("/agyaries/{agyary_id}/behdins/{customer_id}/saved-names/{row_id}")
async def delete_saved_name(
    agyary_id: int,
    customer_id: int,
    row_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Remove one saved name. A paired name takes its partner with it -
    leaving half a pair behind would create exactly the orphan that
    complete_pairs silently hides, so the name would vanish from the
    behdin's options with no explanation."""
    await _require_behdin(db, agyary_id, customer_id, user)
    if not await behdin_directory.delete_saved_name(db, customer_id, row_id):
        raise HTTPException(status_code=404, detail="That saved name could not be found.")
    await db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Manual add (walk-ins / phone bookings)
# ---------------------------------------------------------------------------
class ManualAddNameIn(BaseModel):
    section: str
    title: str
    name: str
    status: str
    pair_group: int | None = None


# What a machi slot can possibly be. Roj, Mah and year are worked out again on the
# server from the date (see booking_service.slot_keys), but a value that could
# never be real is still refused here - it must never be mistaken for "taken".
RojNo = Annotated[int, Field(ge=1, le=30)]
MahNo = Annotated[int, Field(ge=1, le=13)]       # 13 is the Gatha days
ParsiYear = Annotated[int, Field(ge=1, le=9999)]
GehNo = Annotated[int, Field(ge=1, le=5)]
MachiPurpose = Literal["patet", "tandarosti"]
# How many times a repeat happens in all, counting the first; at most 120 monthly
# or 60 yearly (checked per model below).
RepeatCount = Annotated[int, Field(ge=2, le=120)] | None


def _check_repeat_count(model) -> None:
    if model.recurring_count is not None and model.recurring == "yearly" and model.recurring_count > 60:
        raise ValueError("A yearly repeat can run for at most 60 years.")


class ManualAddMachiIn(BaseModel):
    behdin_phone: Phone
    behdin_name: str
    roj: RojNo
    mah: MahNo
    year: ParsiYear
    geh: GehNo
    gregorian: date
    purpose: MachiPurpose
    # Left out (the PWA never sends it), the behdin's saved names are
    # auto-attached server-side - see manual_add_machi.
    names: list[ManualAddNameIn] | None = None
    # Monthly: same Roj every Mah, for a departed relative. Yearly: same Roj
    # AND Mah every Parsi year, for a birthday or anniversary. None: a
    # one-off, the common case.
    recurring: Literal["monthly", "yearly"] | None = None
    # In all, counting the first: 12 monthly is a year of months. Left out, a
    # repeat has no end.
    recurring_count: RepeatCount = None
    # Add any new names to the behdin's saved names as part of saving. On by
    # default: names typed for an event and then forgotten are names typed
    # again next time.
    remember_names: bool = True

    @model_validator(mode="after")
    def _repeat_count_in_range(self):
        _check_repeat_count(self)
        return self


@router.post("/agyaries/{agyary_id}/manual-add/machi")
async def manual_add_machi(
    agyary_id: int,
    payload: ManualAddMachiIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agyary = await _require_membership(db, agyary_id, user)
    names = [n.model_dump() for n in payload.names] if payload.names is not None else None
    try:
        result = await mobed_dashboard.manual_add_machi(
            db, agyary, user.id,
            behdin_phone=payload.behdin_phone, behdin_name=payload.behdin_name,
            roj=payload.roj, mah=payload.mah, year=payload.year, geh=payload.geh,
            gregorian=payload.gregorian, purpose=payload.purpose,
            names=names,
            recurring=payload.recurring, recurring_count=payload.recurring_count,
            remember_names=payload.remember_names,
        )
    except mobed_dashboard.BookingInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    if result.machi is None:
        return {
            "confirmed": False,
            "alternatives": {
                "same_day_gehs": result.alternatives.same_day_gehs,
                "same_geh_next_days": [
                    {"roj": o.roj, "mah": o.mah, "year": o.year, "geh": o.geh, "gregorian": o.gregorian.isoformat()}
                    for o in result.alternatives.same_geh_next_days
                ],
            },
        }
    return {
        "confirmed": True,
        "machi_id": result.machi.id,
        # Dates of a repeating series that could not be booked: somebody holds that geh.
        "skipped": [{"gregorian": d.isoformat()} for d in result.skipped],
    }


class ManualAddBookingIn(BaseModel):
    behdin_phone: Phone
    behdin_name: str
    service_id: int
    ceremony_datetime: datetime
    purpose: str = "gujrela_nu"
    names: list[ManualAddNameIn] | None = None
    location: str | None = None
    is_offsite: bool = False
    remember_names: bool = True
    # As for a machi: monthly is the same Roj every Mah, yearly the same Roj and
    # Mah every Parsi year (a Salgreh, an anniversary). Only a NEW event repeats.
    recurring: Literal["monthly", "yearly"] | None = None
    recurring_count: RepeatCount = None

    @model_validator(mode="after")
    def _repeat_count_in_range(self):
        _check_repeat_count(self)
        return self


@router.post("/agyaries/{agyary_id}/manual-add/booking")
async def manual_add_booking(
    agyary_id: int,
    payload: ManualAddBookingIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agyary = await _require_membership(db, agyary_id, user)
    names = [n.model_dump() for n in payload.names] if payload.names is not None else None
    try:
        result = await mobed_dashboard.manual_add_booking(
            db, agyary, user.id,
            behdin_phone=payload.behdin_phone, behdin_name=payload.behdin_name,
            service_id=payload.service_id, ceremony_dt_local=payload.ceremony_datetime,
            purpose=payload.purpose, names=names,
            location=payload.location, is_offsite=payload.is_offsite,
            remember_names=payload.remember_names, recurring=payload.recurring,
            recurring_count=payload.recurring_count,
        )
    except mobed_dashboard.BookingInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="That service could not be found.")
    await db.commit()
    return {
        "booking_id": result.booking.id,
        "calendar_conflict": result.calendar_conflict,
    }


# ---------------------------------------------------------------------------
# Review before saving: the slip as it will print, nothing written
# ---------------------------------------------------------------------------
def _preview_response(result: dict) -> dict:
    return {**result, "slip": _slip_response(result["slip"])}


@router.post("/agyaries/{agyary_id}/slip-preview/booking")
async def preview_booking(
    agyary_id: int,
    payload: ManualAddBookingIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """What the slip would say if this were saved now. Writes nothing, so the
    review screen can call it on every change to the names. Same payload as
    saving; ``names`` left out returns the behdin's saved names as the
    starting point."""
    agyary = await _require_membership(db, agyary_id, user)
    names = [n.model_dump() for n in payload.names] if payload.names is not None else None
    try:
        result = await mobed_dashboard.preview_booking_slip(
            db, agyary, user.id,
            behdin_phone=payload.behdin_phone, behdin_name=payload.behdin_name,
            service_id=payload.service_id, ceremony_dt_local=payload.ceremony_datetime, names=names,
            recurring=payload.recurring,
        )
    except mobed_dashboard.BookingInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="That service could not be found.")
    return _preview_response(result)


class PreviewMachiIn(ManualAddMachiIn):
    # Set when reviewing an EDIT, so a machi that already holds its slot is not
    # reported as clashing with itself.
    editing_machi_id: int | None = None


@router.post("/agyaries/{agyary_id}/slip-preview/machi")
async def preview_machi(
    agyary_id: int,
    payload: PreviewMachiIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """As preview_booking, plus ``slot_available``: whether confirming would
    still get the geh."""
    agyary = await _require_membership(db, agyary_id, user)
    names = [n.model_dump() for n in payload.names] if payload.names is not None else None
    try:
        result = await mobed_dashboard.preview_machi_slip(
            db, agyary, user.id,
            behdin_phone=payload.behdin_phone, behdin_name=payload.behdin_name,
            roj=payload.roj, mah=payload.mah, year=payload.year,
            gregorian=payload.gregorian, geh=payload.geh, purpose=payload.purpose,
            names=names, editing_machi_id=payload.editing_machi_id, recurring=payload.recurring,
            recurring_count=payload.recurring_count,
        )
    except mobed_dashboard.BookingInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _preview_response(result)


# ---------------------------------------------------------------------------
# Edit (pre-fill detail + save through the shared slot-check / conflict core)
# ---------------------------------------------------------------------------
@router.get("/agyaries/{agyary_id}/machis/{machi_id}/detail")
async def machi_detail(
    agyary_id: int, machi_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    await _require_membership(db, agyary_id, user)
    detail = await mobed_dashboard.get_machi_detail(db, agyary_id, machi_id, user.id)
    if detail is None:
        raise HTTPException(status_code=404, detail="That machi could not be found.")
    return detail


@router.get("/agyaries/{agyary_id}/bookings/{booking_id}/detail")
async def booking_detail(
    agyary_id: int, booking_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    await _require_membership(db, agyary_id, user)
    detail = await mobed_dashboard.get_booking_detail(db, agyary_id, booking_id, user.id)
    if detail is None:
        raise HTTPException(status_code=404, detail="That booking could not be found.")
    return detail


class EditMachiIn(BaseModel):
    behdin_phone: Phone
    behdin_name: str
    roj: RojNo
    mah: MahNo
    year: ParsiYear
    geh: GehNo
    gregorian: date
    purpose: MachiPurpose
    # Left out, re-pulls the (possibly just-edited) behdin's current saved
    # names - see edit_machi.
    names: list[ManualAddNameIn] | None = None
    remember_names: bool = True


@router.put("/agyaries/{agyary_id}/machis/{machi_id}")
async def edit_machi(
    agyary_id: int,
    machi_id: int,
    payload: EditMachiIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agyary = await _require_membership(db, agyary_id, user)
    names = [n.model_dump() for n in payload.names] if payload.names is not None else None
    result = await mobed_dashboard.edit_machi(
        db, agyary, machi_id, user.id,
        behdin_phone=payload.behdin_phone, behdin_name=payload.behdin_name,
        roj=payload.roj, mah=payload.mah, year=payload.year, geh=payload.geh,
        gregorian=payload.gregorian, purpose=payload.purpose,
        names=names, remember_names=payload.remember_names,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="That machi could not be found.")
    await db.commit()
    if result.machi is None:
        return {
            "confirmed": False,
            "alternatives": {
                "same_day_gehs": result.alternatives.same_day_gehs,
                "same_geh_next_days": [
                    {"roj": o.roj, "mah": o.mah, "year": o.year, "geh": o.geh, "gregorian": o.gregorian.isoformat()}
                    for o in result.alternatives.same_geh_next_days
                ],
            },
        }
    return {"confirmed": True, "machi_id": result.machi.id}


class EditBookingIn(BaseModel):
    behdin_phone: Phone
    behdin_name: str
    service_id: int
    ceremony_datetime: datetime
    purpose: str = "gujrela_nu"
    names: list[ManualAddNameIn] | None = None
    location: str | None = None
    is_offsite: bool = False
    remember_names: bool = True


@router.put("/agyaries/{agyary_id}/bookings/{booking_id}")
async def edit_booking(
    agyary_id: int,
    booking_id: int,
    payload: EditBookingIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agyary = await _require_membership(db, agyary_id, user)
    names = [n.model_dump() for n in payload.names] if payload.names is not None else None
    result = await mobed_dashboard.edit_booking(
        db, agyary, user.id, booking_id,
        behdin_phone=payload.behdin_phone, behdin_name=payload.behdin_name,
        service_id=payload.service_id, ceremony_dt_local=payload.ceremony_datetime,
        purpose=payload.purpose, names=names,
        location=payload.location, is_offsite=payload.is_offsite,
        remember_names=payload.remember_names,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="That booking or service could not be found.")
    await db.commit()
    return {"booking_id": result.booking.id, "calendar_conflict": result.calendar_conflict}


@router.delete("/agyaries/{agyary_id}/machis/{machi_id}")
async def delete_machi(
    agyary_id: int,
    machi_id: int,
    future: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """``future=true`` also removes every later occurrence in this machi's
    recurring series and stops it; the slip only offers that choice when
    ``is_recurring`` said there was a series to begin with."""
    agyary = await _require_membership(db, agyary_id, user)
    try:
        deleted = await mobed_dashboard.delete_machi(
            db, agyary, machi_id, user.id, delete_future=future
        )
    except mobed_dashboard.DeleteBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="That machi could not be found.")
    await db.commit()
    return {"deleted": True}


@router.delete("/agyaries/{agyary_id}/bookings/{booking_id}")
async def delete_booking(
    agyary_id: int,
    booking_id: int,
    future: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """``future=true`` also removes every later occurrence of a repeating event
    and stops the repeat, as for a machi."""
    agyary = await _require_membership(db, agyary_id, user)
    try:
        deleted = await mobed_dashboard.delete_booking(db, agyary, booking_id, user.id, delete_future=future)
    except mobed_dashboard.DeleteBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="That booking could not be found.")
    await db.commit()
    return {"deleted": True}


