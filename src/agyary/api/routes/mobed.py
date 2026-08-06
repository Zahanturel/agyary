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
from agyary.messaging import booking_service, wa_flows
from agyary.messaging.flows.approval import handle_pwa_booking_action
from agyary.models import Agyary, AgyaryUser, Booking, Service, User
from agyary.services import mobed_auth, mobed_dashboard
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
# Auth: name + phone login (no OTP - see services/mobed_auth.py), refresh, me
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


class LoginIn(BaseModel):
    name: str
    phone: Phone


@router.post("/auth/login")
async def login(
    payload: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> dict:
    """Name + phone, no verification. First visit creates the mobed's User;
    a returning visit that re-enters name + phone logs them straight back in
    (the existing session cookie carries them in without this call). Joining
    an agyari is a separate, authenticated step (search -> join/activate).

    Rate-limited per IP (see api/rate_limit.py): with no OTP, phone is the
    only gate, so this slows scripted phone-number guessing without
    changing the trust model itself."""
    rate_limit.enforce(request, "login", max_requests=10, window_seconds=300)
    name = payload.name.strip()
    phone = payload.phone.strip()
    if not name or not phone:
        raise HTTPException(status_code=400, detail="Name and phone are both required")

    user = await mobed_auth.login_user(db, phone, name)
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
    await mobed_auth.ensure_agyary_membership(db, agyary_id, user.id)
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
    await mobed_auth.ensure_agyary_membership(db, agyary.id, user.id)
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


@router.get("/agyaries/{agyary_id}/form-options")
async def form_options(
    agyary_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Services and priests at this agyari, for the add-event form's
    dropdowns - same rule, same reasoning. Machi is excluded from the
    services list: it has its own dedicated "Type: Machi" path through
    book_machi_slot, not the generic booking flow."""
    await _require_membership(db, agyary_id, user)
    services = await booking_service.list_services(db, agyary_id, exclude_machi=True)
    priests = await booking_service.get_active_agyary_users(db, agyary_id)
    return {
        "services": [{"id": s.id, "name": s.name} for s in services],
        "priests": [{"id": p.id, "name": p.name} for p in priests],
    }


# ---------------------------------------------------------------------------
# Services catalog management (add / activate / deactivate) - reachable from
# the event form's "+ Add a new service" and from the Profile screen.
# ---------------------------------------------------------------------------
def _service_summary(s: Service) -> dict:
    return {"id": s.id, "name": s.name, "is_active": s.is_active, "offsite_capable": s.offsite_capable}


@router.get("/agyaries/{agyary_id}/services")
async def list_all_services(
    agyary_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    """Every service including inactive ones, for the Profile management
    view - unlike form-options (which only offers active ones to book
    against), a mobed needs to see what's deactivated to reactivate it."""
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


class SetServiceActiveIn(BaseModel):
    is_active: bool


@router.patch("/agyaries/{agyary_id}/services/{service_id}")
async def set_service_active(
    agyary_id: int,
    service_id: int,
    payload: SetServiceActiveIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Activate/deactivate a service - the mobed's own catalog management.
    Deactivating doesn't delete it or touch past bookings that used it, it
    just stops offering it for new ones (list_services already filters to
    active-only)."""
    await _require_membership(db, agyary_id, user)
    service = await db.get(Service, service_id)
    if service is None or service.agyary_id != agyary_id:
        raise HTTPException(status_code=404, detail="Unknown service")
    service.is_active = payload.is_active
    await db.commit()
    return _service_summary(service)


@router.get("/agyaries/{agyary_id}/machi-board")
async def machi_board(
    agyary_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    await _require_membership(db, agyary_id, user)
    entries = await mobed_dashboard.list_machi_board(db, agyary_id)
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
    slip = await mobed_dashboard.get_machi_slip(db, agyary_id, machi_id)
    if slip is None:
        raise HTTPException(status_code=404, detail="Unknown machi")
    return _slip_response(slip)


@router.get("/agyaries/{agyary_id}/bookings/{booking_id}/slip")
async def booking_slip(
    agyary_id: int, booking_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    await _require_membership(db, agyary_id, user)
    slip = await mobed_dashboard.get_booking_slip(db, agyary_id, booking_id)
    if slip is None:
        raise HTTPException(status_code=404, detail="Unknown booking")
    return _slip_response(slip)


# ---------------------------------------------------------------------------
# My customers (search + autofill for the add-machi/add-booking form) - a
# mobed's own behdins, not the fire temple's shared customer pool and not
# another mobed's relationship with the same person.
# ---------------------------------------------------------------------------
@router.get("/customers/search")
async def search_customers(
    q: str = Query(default=""), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    return await mobed_dashboard.search_my_customers(db, user.id, q)


@router.get("/customers/{customer_id}/history")
async def customer_history(
    customer_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    result = await mobed_dashboard.get_customer_history(db, user.id, customer_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown customer")
    return result


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
    purpose: str
    names: list[ManualAddNameIn]
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
    result = await mobed_dashboard.manual_add_booking(
        db, agyary, user.id,
        behdin_phone=payload.behdin_phone, behdin_name=payload.behdin_name,
        service_id=payload.service_id, ceremony_dt_local=payload.ceremony_datetime,
        purpose=payload.purpose, names=[n.model_dump() for n in payload.names],
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
        db, agyary, machi_id,
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
    purpose: str
    names: list[ManualAddNameIn]
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
    result = await mobed_dashboard.edit_booking(
        db, agyary, user.id, booking_id,
        behdin_phone=payload.behdin_phone, behdin_name=payload.behdin_name,
        service_id=payload.service_id, ceremony_dt_local=payload.ceremony_datetime,
        purpose=payload.purpose, names=[n.model_dump() for n in payload.names],
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
