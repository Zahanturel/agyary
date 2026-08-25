"""Mobed PWA API: onboarding/auth, agyari search, My Day, Machi Board,
manual add, accept/decline. See services/mobed_auth.py and
services/mobed_dashboard.py for the business logic - this module is the
HTTP/JWT/request-response layer on top of it.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.messaging import wa_flows
from agyary.messaging.flows.approval import handle_pwa_booking_action
from agyary.models import (
    Agyary,
    AgyaryUser,
    Booking,
    Customer,
    Service,
    User,
    UserPreferences,
)
from agyary.models.enums import (
    CALENDAR_SYSTEMS,
    DISPLAY_CALENDAR_SYSTEMS,
    DISPLAY_LANGUAGES,
    NAME_SECTIONS,
    NAME_STATUSES,
    NAME_TITLES,
)
from agyary.models.preferences import default_preferences
from agyary.services import behdin_directory, mobed_auth, mobed_dashboard, otp_delivery
from agyary.services.phone import OptionalPhone, Phone

router = APIRouter(prefix="/api/mobed", tags=["mobed"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------
async def get_current_user(
    authorization: str = Header(default=""), db: AsyncSession = Depends(get_db)
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        user_id = mobed_auth.decode_token(token, "access")
    except mobed_auth.TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def _require_membership(db: AsyncSession, agyary_id: int, user: User) -> Agyary:
    agyary = await db.get(Agyary, agyary_id)
    if agyary is None or not agyary.is_active:
        raise HTTPException(status_code=404, detail="Unknown agyary")
    if not await mobed_dashboard.is_active_member(db, agyary_id, user.id):
        raise HTTPException(status_code=403, detail="Not a member of this agyary")
    return agyary


# ---------------------------------------------------------------------------
# Auth: phone + WhatsApp OTP (see services/mobed_auth.py), refresh, me
# ---------------------------------------------------------------------------
def _set_refresh_cookie(response: Response, user_id: int) -> None:
    settings = get_settings()
    response.set_cookie(
        "refresh_token",
        mobed_auth.issue_refresh_token(user_id),
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


class OtpRequestIn(BaseModel):
    phone: Phone


@router.post("/auth/otp/request")
async def request_otp(
    payload: OtpRequestIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    """Step 1 of sign-in: send a code to the phone over WhatsApp.

    Deliberately says nothing about whether the number is already known to
    us. The response is identical for a registered mobed and a stranger, so
    this endpoint can't be used to test whether a given number belongs to
    someone here.

    Two rate limits, because they stop different things: per-IP caps how
    fast one caller can work through a list of numbers, per-phone stops
    anyone using us to bombard a single person's WhatsApp.
    """
    phone = payload.phone.strip()
    rate_limit.enforce(request, "otp_request", max_requests=10, window_seconds=300)
    rate_limit.enforce_key(f"otp_phone:{phone}", max_requests=3, window_seconds=300)

    code = await mobed_auth.issue_otp(db, phone)
    try:
        await otp_delivery.send_login_otp(phone, code)
    except otp_delivery.OtpDeliveryError as exc:
        # Don't leave a live code stranded behind an undelivered message -
        # the next request would otherwise be rejected by the per-phone
        # limiter while the user has nothing to type.
        await db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await db.commit()
    return {"expires_in_seconds": get_settings().otp_ttl_seconds}


class OtpVerifyIn(BaseModel):
    phone: Phone
    code: str
    # Only used the first time a phone signs in; a returning user may send
    # it to correct their display name, or omit it to keep the stored one.
    name: str = ""


@router.post("/auth/otp/verify")
async def verify_otp(
    payload: OtpVerifyIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> dict:
    """Step 2 of sign-in: exchange a valid code for a session.

    Rate-limited on top of the OTP's own attempt cap - the cap protects one
    issued code, this protects against churning through fresh codes.

    """
    rate_limit.enforce(request, "otp_verify", max_requests=20, window_seconds=300)
    phone = payload.phone.strip()

    try:
        await mobed_auth.verify_otp(db, phone, payload.code)
    except mobed_auth.OtpError as exc:
        await db.commit()  # persist the burnt attempt / expiry cleanup
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = await mobed_auth.login_user(db, phone, payload.name.strip())
    if not user.name:
        # A brand-new phone that sent no name has nothing to display; ask
        # the client for one rather than creating a nameless mobed.
        await db.rollback()
        raise HTTPException(status_code=400, detail="Name is required for a first sign-in")
    await db.commit()

    _set_refresh_cookie(response, user.id)
    return {
        "access_token": mobed_auth.issue_access_token(user.id),
        "user": await _serialize_user(db, user),
    }


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
        raise HTTPException(status_code=401, detail="Missing refresh token")
    try:
        user_id = mobed_auth.decode_token(refresh_token, "refresh")
    except mobed_auth.TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    _set_refresh_cookie(response, user.id)
    return {"access_token": mobed_auth.issue_access_token(user.id)}


async def _serialize_user(db: AsyncSession, user: User) -> dict:
    # Ordered by joined_at: the PWA treats agyaries[0] as THE fire temple for
    # this mobed (no switcher in this v1 - one mobed, one temple), so this
    # order must be deterministic, not whatever an unordered join happens to
    # return. Earliest-joined wins if a member ever does end up with more
    # than one active membership.
    result = await db.execute(
        select(Agyary, AgyaryUser.role)
        .join(AgyaryUser, AgyaryUser.agyary_id == Agyary.id)
        .where(AgyaryUser.user_id == user.id, AgyaryUser.is_active.is_(True))
        .order_by(AgyaryUser.joined_at)
    )
    agyaries = [
        {
            "id": a.id, "name": a.name, "role": role, "calendar_system": a.calendar_system,
            "city": a.city, "address": a.address, "contact_phone": a.contact_phone, "status": a.status,
        }
        for a, role in result.all()
    ]
    return {"id": user.id, "name": user.name, "phone": user.phone, "agyaries": agyaries}


@router.post("/auth/logout")
async def logout(response: Response) -> dict:
    """End the session.

    Needed because the refresh cookie is httpOnly: the client can drop its
    in-memory access token, but it cannot clear the cookie, so without this
    "sign out" would silently sign you straight back in on the next load -
    the opposite of what someone handing their phone to a colleague wants.
    Cleared with the same attributes it was set with, or the browser won't
    match it.
    """
    settings = get_settings()
    response.delete_cookie(
        "refresh_token",
        httponly=True,
        secure=not settings.app_debug,
        samesite="strict",
    )
    return {"signed_out": True}


@router.get("/auth/me")
async def me(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return await _serialize_user(db, user)


class UpdateMeIn(BaseModel):
    name: str


@router.patch("/auth/me")
async def update_me(
    payload: UpdateMeIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Let a mobed correct their own display name from the profile screen.
    Phone stays read-only here - it's the sign-in identity (see mobed_auth's
    no-OTP login), so changing it is a bigger decision than a quick edit."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    user.name = name
    await db.commit()
    return await _serialize_user(db, user)


# ---------------------------------------------------------------------------
# Display preferences (per user, not per agyari - see models/preferences.py)
# ---------------------------------------------------------------------------
def _preferences_response(prefs: UserPreferences | None) -> dict:
    if prefs is None:
        return default_preferences()
    return {
        "visible_calendar_systems": list(prefs.visible_calendar_systems),
        "default_secondary_system": prefs.default_secondary_system,
        "display_language": prefs.display_language,
    }


@router.get("/me/preferences")
async def get_preferences(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
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
    unknown = [s for s in systems if s not in DISPLAY_CALENDAR_SYSTEMS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown calendar system(s): {', '.join(unknown)}. "
            f"Choose from: {', '.join(DISPLAY_CALENDAR_SYSTEMS)}",
        )
    if not systems:
        raise HTTPException(status_code=400, detail="At least one calendar system must stay visible")
    if payload.default_secondary_system not in CALENDAR_SYSTEMS:
        raise HTTPException(
            status_code=400,
            detail=f"Secondary system must be one of: {', '.join(CALENDAR_SYSTEMS)}",
        )
    if payload.default_secondary_system not in systems:
        raise HTTPException(
            status_code=400, detail="The secondary system has to be one of the visible ones"
        )
    if payload.display_language not in DISPLAY_LANGUAGES:
        raise HTTPException(
            status_code=400, detail=f"Language must be one of: {', '.join(DISPLAY_LANGUAGES)}"
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
def _agyary_summary(a: Agyary) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "city": a.city,
        "address": a.address,
        "status": a.status,
    }


@router.get("/agyaries/search")
async def search_agyaries(q: str = Query(default=""), db: AsyncSession = Depends(get_db)) -> list[dict]:
    agyaries = await mobed_dashboard.search_agyaries(db, q)
    return [_agyary_summary(a) for a in agyaries]


@router.post("/agyaries/{agyary_id}/join")
async def join_agyari(
    agyary_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    agyary = await db.get(Agyary, agyary_id)
    if agyary is None or not agyary.is_active:
        raise HTTPException(status_code=404, detail="Unknown agyary")
    await mobed_auth.ensure_agyary_membership(db, agyary_id, user)
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
    user: User = Depends(get_current_user),
) -> dict:
    """Claim + set up an unclaimed seed agyari. The mobed must already be a
    member (they join first). Confirms/corrects the stale seed details and
    flips it to active."""
    agyary = await _require_membership(db, agyary_id, user)
    if not payload.name.strip() or not payload.city.strip():
        raise HTTPException(status_code=400, detail="Name and city are required")
    await mobed_dashboard.activate_agyary(
        db, agyary,
        name=payload.name, city=payload.city,
        address=payload.address, contact_phone=payload.contact_phone,
    )
    await db.commit()
    return {"user": await _serialize_user(db, user), "agyary": _agyary_summary(agyary)}


class CreateAgyaryIn(BaseModel):
    name: str
    city: str
    address: str | None = None
    contact_phone: OptionalPhone = None


@router.post("/agyaries")
async def create_agyari(
    payload: CreateAgyaryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Creation fallback: the agyari isn't in the seed list at all. Same
    activation outcome (born active), then the creating mobed joins it."""
    if not payload.name.strip() or not payload.city.strip():
        raise HTTPException(status_code=400, detail="Name and city are required")
    agyary = await mobed_dashboard.create_agyary(
        db,
        name=payload.name, city=payload.city,
        address=payload.address, contact_phone=payload.contact_phone,
    )
    await mobed_auth.ensure_agyary_membership(db, agyary.id, user)
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
    }


@router.get("/my-day")
async def my_day(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    entries = await mobed_dashboard.list_my_day(db, user.id)
    return [_booking_summary(e) for e in entries]


@router.get("/pending-requests")
async def pending_requests(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    entries = await mobed_dashboard.list_pending_requests(db, user.id)
    return [_booking_summary(e) for e in entries]


@router.get("/reference/calendar-options")
async def calendar_options() -> dict:
    """Roj/Mah/Geh option lists for the add-event form's <select> dropdowns
    - closed-vocabulary fields are never free text (07-predefined-input-
    decision.md), and this reads from the exact same canonical source
    (wa_flows.py) the WhatsApp static Flows use, not a second copy."""
    return {
        "roj": wa_flows.roj_options(),
        "mah": wa_flows.mah_options(),
        "geh": wa_flows.geh_options(),
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
    a blank - they are history, not options."""
    await _require_membership(db, agyary_id, user)
    result = await db.execute(
        select(Service)
        .where(Service.agyary_id == agyary_id)
        .order_by(Service.display_order, Service.id)
    )
    return [_service_summary(s) for s in result.scalars() if s.name.strip().lower() != "machi"]


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
        raise HTTPException(status_code=400, detail="Service name is required")
    if name.strip().lower() == "machi":
        raise HTTPException(status_code=400, detail="Machi has its own booking flow, not a service entry")
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

    ``mine=true`` narrows it to the machis the caller entered themselves.
    The mobed app always asks for that - a mobed has no need to see every
    machi at their fire temple, and the unfiltered response carries other
    mobeds' behdin names. The unfiltered form remains for the agyari
    management surface that will come later.
    """
    await _require_membership(db, agyary_id, user)
    try:
        entries = await mobed_dashboard.list_machi_board(
            db, agyary_id, from_, to, created_by_user_id=user.id if mine else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
            "behdin_name": e.behdin_name,
        }
        for e in entries
    ]


@router.get("/agyaries/{agyary_id}/bookable-gehs")
async def bookable_gehs(
    agyary_id: int, on: date = Query(), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Which gehs on `on` can still be booked - via the SAME shared
    availability core the booking path uses, so the Machi Board can show
    empty/taken/already-passed correctly instead of a generic 'tap to book'
    that then fails with 'already booked' for a slot that's simply elapsed."""
    agyary = await _require_membership(db, agyary_id, user)
    return {"bookable": await mobed_dashboard.bookable_gehs(db, agyary, on)}


def _slip_response(slip: mobed_dashboard.SlipData) -> dict:
    return {
        "agyary_name": slip.agyary_name,
        "behdin_name": slip.behdin_name,
        "behdin_phone": slip.behdin_phone,
        "event": slip.event,
        "when": slip.when,
        "names_text": slip.names_text,
    }


@router.get("/agyaries/{agyary_id}/machis/{machi_id}/slip")
async def machi_slip(
    agyary_id: int, machi_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    await _require_membership(db, agyary_id, user)
    slip = await mobed_dashboard.get_machi_slip(db, agyary_id, machi_id, reader_user_id=user.id)
    if slip is None:
        raise HTTPException(status_code=404, detail="Unknown machi")
    return _slip_response(slip)


@router.get("/agyaries/{agyary_id}/bookings/{booking_id}/slip")
async def booking_slip(
    agyary_id: int, booking_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    await _require_membership(db, agyary_id, user)
    slip = await mobed_dashboard.get_booking_slip(db, agyary_id, booking_id, reader_user_id=user.id)
    if slip is None:
        raise HTTPException(status_code=404, detail="Unknown booking")
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
        raise HTTPException(status_code=404, detail="Unknown customer")
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
        raise HTTPException(status_code=404, detail="Unknown behdin")
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
    return behdin_directory.customer_summary(customer)


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
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    for n in payload.names:
        if n.title not in NAME_TITLES:
            raise HTTPException(status_code=400, detail=f"Unknown title: {n.title}")
        if n.status not in NAME_STATUSES:
            raise HTTPException(status_code=400, detail=f"Unknown status: {n.status}")
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
        raise HTTPException(status_code=404, detail="Unknown saved name")
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


class ManualAddMachiIn(BaseModel):
    behdin_phone: Phone
    behdin_name: str
    roj: int
    mah: int
    year: int
    geh: int
    gregorian: date
    purpose: str
    names: list[ManualAddNameIn]
    recurring: bool = False


@router.post("/agyaries/{agyary_id}/manual-add/machi")
async def manual_add_machi(
    agyary_id: int,
    payload: ManualAddMachiIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agyary = await _require_membership(db, agyary_id, user)
    result = await mobed_dashboard.manual_add_machi(
        db, agyary, user.id,
        behdin_phone=payload.behdin_phone, behdin_name=payload.behdin_name,
        roj=payload.roj, mah=payload.mah, year=payload.year, geh=payload.geh,
        gregorian=payload.gregorian, purpose=payload.purpose,
        names=[n.model_dump() for n in payload.names],
        recurring=payload.recurring,
    )
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


class ManualAddBookingIn(BaseModel):
    behdin_phone: Phone
    behdin_name: str
    service_id: int
    ceremony_datetime: datetime
    purpose: str = "gujrela_nu"
    names: list[ManualAddNameIn] | None = None
    location: str | None = None
    is_offsite: bool = False


@router.post("/agyaries/{agyary_id}/manual-add/booking")
async def manual_add_booking(
    agyary_id: int,
    payload: ManualAddBookingIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agyary = await _require_membership(db, agyary_id, user)
    names = [n.model_dump() for n in payload.names] if payload.names is not None else None
    result = await mobed_dashboard.manual_add_booking(
        db, agyary, user.id,
        behdin_phone=payload.behdin_phone, behdin_name=payload.behdin_name,
        service_id=payload.service_id, ceremony_dt_local=payload.ceremony_datetime,
        purpose=payload.purpose, names=names,
        location=payload.location, is_offsite=payload.is_offsite,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown service")
    await db.commit()
    return {
        "booking_id": result.booking.id,
        "calendar_conflict": result.calendar_conflict,
    }


# ---------------------------------------------------------------------------
# Edit (pre-fill detail + save through the shared slot-check / conflict core)
# ---------------------------------------------------------------------------
@router.get("/agyaries/{agyary_id}/machis/{machi_id}/detail")
async def machi_detail(
    agyary_id: int, machi_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    await _require_membership(db, agyary_id, user)
    detail = await mobed_dashboard.get_machi_detail(db, agyary_id, machi_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown machi")
    return detail


@router.get("/agyaries/{agyary_id}/bookings/{booking_id}/detail")
async def booking_detail(
    agyary_id: int, booking_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    await _require_membership(db, agyary_id, user)
    detail = await mobed_dashboard.get_booking_detail(db, agyary_id, booking_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown booking")
    return detail


class EditMachiIn(BaseModel):
    behdin_phone: Phone
    behdin_name: str
    roj: int
    mah: int
    year: int
    geh: int
    gregorian: date
    purpose: str
    names: list[ManualAddNameIn]


@router.put("/agyaries/{agyary_id}/machis/{machi_id}")
async def edit_machi(
    agyary_id: int,
    machi_id: int,
    payload: EditMachiIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agyary = await _require_membership(db, agyary_id, user)
    result = await mobed_dashboard.edit_machi(
        db, agyary, machi_id, user.id,
        behdin_phone=payload.behdin_phone, behdin_name=payload.behdin_name,
        roj=payload.roj, mah=payload.mah, year=payload.year, geh=payload.geh,
        gregorian=payload.gregorian, purpose=payload.purpose,
        names=[n.model_dump() for n in payload.names],
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown machi")
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
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown booking or service")
    await db.commit()
    return {"booking_id": result.booking.id, "calendar_conflict": result.calendar_conflict}


# ---------------------------------------------------------------------------
# Accept / decline (second entry point, same idempotent core as WhatsApp)
# ---------------------------------------------------------------------------
async def _do_booking_action(
    booking_id: int, action: str, db: AsyncSession, user: User
) -> dict:
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Unknown booking")
    agyary = await db.get(Agyary, booking.agyary_id)
    outcome = await handle_pwa_booking_action(db, agyary, user.id, booking_id, action)
    if outcome.status == "unauthorized":
        raise HTTPException(status_code=403, detail="Not the assigned priest for this booking")
    await db.commit()
    if outcome.status == "already_resolved":
        return {"status": outcome.status, "previous_status": outcome.previous_status}
    return {"status": outcome.status, "what": outcome.what, "when": outcome.when}


@router.post("/bookings/{booking_id}/accept")
async def accept_booking(
    booking_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    return await _do_booking_action(booking_id, "approve", db, user)


@router.post("/bookings/{booking_id}/decline")
async def decline_booking(
    booking_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    return await _do_booking_action(booking_id, "decline", db, user)
