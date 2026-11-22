"""The admin's view of what sending is costing, and the switch that stops it.

For the people listed in ADMIN_PHONES, nobody else. A non-admin gets a 404 -
the same answer as for a page that does not exist - so the screen's existence
is not something to probe for.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.api.routes.mobed import (
    LocationIn,
    PushSubscribeIn,
    PushUnsubscribeIn,
    _checked_position,
    get_current_account,
)
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import Agyary, AgyaryUser, FuneralPlace, LoginOtp, Notification, User
from agyary.models.enums import (
    ACCESS_PENDING,
    ACCOUNT_FUNERAL_MANAGER,
    ACCOUNT_MOBED,
    ROLE_MOBED,
    ROLE_PANTHAKY,
)
from agyary.services import (
    bot_check,
    erasure,
    funeral_places,
    guardrails,
    join_confirmation,
    mobed_access,
    mobed_auth,
    panthaky,
    web_push,
)
from agyary.services.phone import Phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobed/admin", tags=["admin"])


def require_admin(user: User = Depends(get_current_account)) -> User:
    # Any kind of account that is on: the number is what makes an admin, and a
    # manager's or a mobed's account that is not an admin gets the same 404.
    if not guardrails.is_admin(get_settings(), user.phone):
        raise HTTPException(status_code=404, detail="Not found")
    return user


def _masked(phone: str) -> str:
    """Enough to recognise a number, not enough to read it off a screenshot."""
    return f"{phone[:3]}…{phone[-3:]}" if len(phone) > 8 else "…"


def _allowlist_text(raw: str) -> str:
    raw = raw.strip()
    if raw == "*":
        return "everyone"
    n = len([p for p in raw.split(",") if p.strip()])
    return "nobody" if n == 0 else f"{n} number{'s' if n != 1 else ''}"


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    s = get_settings()
    now = datetime.now(timezone.utc)
    used = await guardrails.usage(db, now)

    day_start, day_end = guardrails.day_bounds(now)
    otp_today = (
        await db.execute(
            select(func.count()).select_from(LoginOtp).where(
                LoginOtp.status.notin_(("failed", "suppressed")),
                LoginOtp.created_at >= day_start, LoginOtp.created_at < day_end,
            )
        )
    ).scalar_one()

    failures = (
        await db.execute(
            select(Notification.created_at, Notification.error_message, Notification.recipient_phone)
            .where(Notification.notification_type == "memorial_reminder", Notification.status == "failed")
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(10)
        )
    ).all()

    return {
        "reminders": {
            "mode": s.reminders_send_mode,
            "paused": await guardrails.paused_reason(db),
            "sending_to": _allowlist_text(s.reminders_allowlist) if s.reminders_send_mode == "live" else None,
            "today": used.today,
            "month": used.month,
            "caps": {
                "daily": s.reminders_daily_cap,
                "monthly": s.reminders_monthly_cap,
                "per_mobed": s.reminders_per_mobed_daily_cap,
                "per_agyary": s.reminders_per_agyary_daily_cap,
            },
            "estimated_month_cost_inr": guardrails.estimated_cost_inr(s, used.month),
        },
        "otp": {
            "mode": s.otp_mode, "today": otp_today, "daily_cap": s.otp_daily_cap,
            "bot_check": bot_check.configured(s),
        },
        "recent_failures": [
            {"when": when.isoformat(), "reason": reason or "", "to": _masked(phone)}
            for when, reason, phone in failures
        ],
        # And how many say they are a panthaky, waiting for the admin's word (D10).
        "panthaky_claims_waiting": (
            await db.execute(
                select(func.count()).select_from(AgyaryUser).join(User, User.id == AgyaryUser.user_id).where(
                    User.is_active.is_(True), AgyaryUser.is_active.is_(True),
                    AgyaryUser.role == ROLE_MOBED, AgyaryUser.claimed_role == ROLE_PANTHAKY,
                    AgyaryUser.claim_decision.is_(None),
                )
            )
        ).scalar_one(),
        # For the Mobeds card at the top: how many are waiting for approval (D9),
        # mobeds and Doongerwadi managers apart (D10).
        "mobeds_waiting": await _waiting(db, s, ACCOUNT_MOBED),
        "managers_waiting": await _waiting(db, s, ACCOUNT_FUNERAL_MANAGER),
        # What is in the app (D10).
        "in_the_app": await _in_the_app(db, s),
    }


async def _waiting(db: AsyncSession, s, kind: str) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(User).where(
                User.is_active.is_(True), User.access == ACCESS_PENDING, User.account_kind == kind,
                User.phone.notin_(guardrails.admin_phones(s) or {""}),
            )
        )
    ).scalar_one()


async def _in_the_app(db: AsyncSession, s) -> dict:
    """Mobeds and managers by their access (an admin counts as on), confirmed
    panthakys, fire temples with at least one member, and funeral places."""
    people = {ACCOUNT_MOBED: {"on": 0, "pending": 0, "off": 0}, ACCOUNT_FUNERAL_MANAGER: {"on": 0, "pending": 0, "off": 0}}
    for user in (await db.execute(select(User).where(User.is_active.is_(True)))).scalars():
        people.setdefault(user.account_kind, {"on": 0, "pending": 0, "off": 0})[mobed_access.effective(s, user)] += 1
    member = (
        select(AgyaryUser)
        .join(User, User.id == AgyaryUser.user_id)
        .join(Agyary, Agyary.id == AgyaryUser.agyary_id)
        .where(AgyaryUser.is_active.is_(True), User.is_active.is_(True), Agyary.is_active.is_(True))
        .subquery()
    )
    panthakys = (await db.execute(
        select(func.count(func.distinct(member.c.user_id))).where(member.c.role == ROLE_PANTHAKY)
    )).scalar_one()
    temples = (await db.execute(select(func.count(func.distinct(member.c.agyary_id))))).scalar_one()
    places = dict((await db.execute(
        select(FuneralPlace.is_active, func.count()).group_by(FuneralPlace.is_active)
    )).all())
    return {
        "mobeds": people[ACCOUNT_MOBED],
        "panthakys": panthakys,
        "fire_temples_in_use": temples,
        "funeral_places": {"in_use": places.get(True, 0), "off": places.get(False, 0)},
        "managers": people[ACCOUNT_FUNERAL_MANAGER],
    }


class SignOutIn(BaseModel):
    phone: Phone


@router.post("/sign-out-everywhere")
async def sign_out_everywhere(
    payload: SignOutIn, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    """End every signed-in device of one mobed (AU-2) - a phone that was lost or
    taken, a sign-in nobody recognises - and stop the phone notifications of
    every one of them. They can sign in again with WhatsApp."""
    user = (await db.execute(select(User).where(User.phone == payload.phone))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="No mobed has that number")
    ended = await mobed_auth.end_all_sessions(db, user)
    await db.commit()
    return {"signed_out": ended}


class EraseIn(BaseModel):
    phone: Phone
    confirm: bool = False


@router.post("/erase-number")
async def erase_number(
    payload: EraseIn, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    """A family asked to be removed (docs/DATA-REQUESTS.md). Without ``confirm``
    this only says how much we hold. With it, the number is erased from every
    mobed's book, for good. Answers and logs counts, never names or the number."""
    rate_limit.enforce_key(f"admin_erase:{admin.id}", max_requests=10, window_seconds=60)
    if not payload.confirm:
        return {"found": await erasure.what_we_hold(db, payload.phone)}
    erased = await erasure.erase_number(db, payload.phone)
    await db.commit()
    logger.warning("A number was erased on request by admin %s: %s", admin.id, erased)
    return {"erased": erased}


class PauseIn(BaseModel):
    paused: bool
    reason: str = ""


@router.post("/reminders/pause")
async def set_paused(
    payload: PauseIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """The kill switch: stop all outbound WhatsApp sending (reminders and sign-in
    codes) at once, or start it again. It takes effect on the next pass of the
    loop, within a minute, and survives a restart."""
    rate_limit.enforce_key(f"admin_pause:{admin.id}", max_requests=10, window_seconds=60)
    if payload.paused:
        reason = payload.reason.strip() or f"Paused by {admin.name}"
        await guardrails.pause(db, get_settings(), reason, user_id=admin.id)
    else:
        await guardrails.resume(db, user_id=admin.id)
    await db.commit()
    return {"paused": await guardrails.paused_reason(db)}


# ---------------------------------------------------------------------------
# Mobeds: who is waiting, and the one switch per mobed (DECISIONS D9)
# ---------------------------------------------------------------------------
@router.get("/mobeds")
async def list_mobeds(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    """Every mobed, those waiting for approval first. The admin sees the whole
    number: they are the ones who call a mobed about their account."""
    mobeds = await mobed_access.list_mobeds(db, get_settings())
    return {
        "mobeds": mobeds,
        "waiting": sum(1 for m in mobeds if m["access"] == ACCESS_PENDING),
        # Of those, Doongerwadi managers (D10): approved with the same switch.
        "managers_waiting": sum(
            1 for m in mobeds if m["access"] == ACCESS_PENDING and m["account_kind"] == ACCOUNT_FUNERAL_MANAGER
        ),
        # Mobeds who say they are a panthaky and wait for the admin's word (D10).
        "panthaky_claims": sum(1 for m in mobeds for t in m["memberships"] if t["panthaky_claim_waiting"]),
    }


class AccessIn(BaseModel):
    access: Literal["on", "off"]


@router.post("/mobeds/{user_id}/access")
async def set_mobed_access(
    user_id: int, payload: AccessIn, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin),
) -> dict:
    """Approve a waiting mobed or turn one on, or turn one off. Off keeps
    everything they saved; they see one screen saying so, and nothing is sent
    under their account until they are on again."""
    rate_limit.enforce_key(f"admin_access:{admin.id}", max_requests=60, window_seconds=60)
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="That mobed could not be found.")
    try:
        await mobed_access.set_access(db, get_settings(), user, payload.access, by=admin)
    except mobed_access.AccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    logger.warning("Admin %s set mobed %s access to %s", admin.id, user.id, payload.access)
    return {"id": user.id, "access": mobed_access.effective(get_settings(), user)}


class PanthakyDecisionIn(BaseModel):
    agyary_id: int
    decision: Literal["confirm", "decline", "remove"]


@router.post("/mobeds/{user_id}/panthaky")
async def decide_panthaky(
    user_id: int, payload: PanthakyDecisionIn, db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """The owner's word on a mobed's panthaky role at one fire temple (D10):
    "confirm" makes them its panthaky (role = panthaky, with what that role
    sees, D7), "decline" keeps them a mobed, "remove" makes a panthaky a mobed
    again. Each is kept on the membership with when and by whom, and the
    mobed is told in the app."""
    rate_limit.enforce_key(f"admin_panthaky:{admin.id}", max_requests=60, window_seconds=60)
    user = await db.get(User, user_id)
    agyary = await db.get(Agyary, payload.agyary_id)
    membership = await mobed_auth.get_membership(db, payload.agyary_id, user_id)
    if user is None or not user.is_active or agyary is None or membership is None or not membership.is_active:
        raise HTTPException(status_code=404, detail="That mobed is not at that fire temple.")
    await db.refresh(membership, with_for_update=True)
    act = {"confirm": panthaky.confirm, "decline": panthaky.decline, "remove": panthaky.remove}[payload.decision]
    try:
        await act(db, membership, agyary, admin)
    except panthaky.ClaimError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return {"id": user.id, "agyary_id": agyary.id, "role": membership.role,
            "claim_decision": membership.claim_decision}


class RequestsDecisionIn(BaseModel):
    agyary_id: int
    # "confirm" (one who joined), "off" (Not one of ours / Take off the list), "on" (Put back).
    action: Literal["confirm", "off", "on"]


@router.post("/mobeds/{user_id}/requests")
async def decide_requests(
    user_id: int, payload: RequestsDecisionIn, db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """The admin's word on whether a mobed gets one fire temple's prayer
    requests (D10, 22 Nov 2026): the same actions as a confirmed panthaky's on
    the Mobeds page, for the fire temples that have none in the app. ``done``
    says what happened; the mobed is told in the app when confirmed."""
    rate_limit.enforce_key(f"admin_requests:{admin.id}", max_requests=60, window_seconds=60)
    agyary = await db.get(Agyary, payload.agyary_id)
    if agyary is None or not agyary.is_active:
        raise HTTPException(status_code=404, detail="That mobed is not at that fire temple.")
    act = {"confirm": join_confirmation.confirm, "off": join_confirmation.take_off,
           "on": join_confirmation.put_back}[payload.action]
    try:
        done = await act(db, get_settings(), admin, agyary, user_id)
    except join_confirmation.JoinError as exc:   # refused before anything changed
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    await db.commit()
    membership = await mobed_auth.get_membership(db, agyary.id, user_id)
    user = await db.get(User, user_id)
    return {"id": user_id, "agyary_id": agyary.id,
            "requests": panthaky.request_state(get_settings(), membership, user), "done": done}


# ---------------------------------------------------------------------------
# Notifications on the admin's phone (web push, services/web_push.py)
# ---------------------------------------------------------------------------
@router.get("/push")
async def push_status(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    """Whether the server can send to phones, the public key a phone needs to
    subscribe, and how many of this admin's devices are signed up."""
    s = get_settings()
    return {
        "configured": web_push.configured(s),
        "public_key": s.vapid_public_key.strip() or None,
        "devices": await web_push.devices(db, admin.id),
    }


@router.post("/push/subscribe")
async def push_subscribe(
    payload: PushSubscribeIn, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin),
) -> dict:
    rate_limit.enforce_key(f"admin_push:{admin.id}", max_requests=20, window_seconds=60)
    if not web_push.configured(get_settings()):
        raise HTTPException(status_code=409, detail="Phone notifications are not set up on the server yet.")
    if not web_push.allowed_endpoint(payload.endpoint):
        raise HTTPException(status_code=400, detail="This browser's notification service is not one we know.")
    await web_push.save(db, admin.id, payload.endpoint, payload.keys.p256dh, payload.keys.auth)
    await db.commit()
    return {"devices": await web_push.devices(db, admin.id)}


@router.post("/push/unsubscribe")
async def push_unsubscribe(
    payload: PushUnsubscribeIn, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin),
) -> dict:
    await web_push.remove(db, admin.id, payload.endpoint)
    await db.commit()
    return {"devices": await web_push.devices(db, admin.id)}


@router.post("/push/test")
async def push_test(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    """Send a test notification to every phone this admin turned it on for."""
    rate_limit.enforce_key(f"admin_push_test:{admin.id}", max_requests=5, window_seconds=60)
    s = get_settings()
    if not web_push.configured(s):
        raise HTTPException(status_code=409, detail="Phone notifications are not set up on the server yet.")
    sent = await web_push.send_to_users(
        db, s, [admin.id], title="Mobed Diary",
        body="Notifications are working on this phone. New mobeds waiting for approval will show here.",
        url="/mobed#/admin/mobeds", tag="push-test",
    )
    await db.commit()
    return {"sent": sent, "devices": await web_push.devices(db, admin.id)}


# ---------------------------------------------------------------------------
# Doongerwadis, prayer halls and aramgahs (DECISIONS D10). Only an admin adds
# or changes one; a place is turned off, never deleted (D8).
# ---------------------------------------------------------------------------
class FuneralPlaceIn(BaseModel):
    name: str = Field(max_length=500)
    kind: Literal["doongerwadi", "prayer_hall", "aramgah"]
    city: str = Field(max_length=500)
    address: str | None = Field(default=None, max_length=2000)
    run_by: str | None = Field(default=None, max_length=500)
    # Where it is, if the admin put it on the map; null for no pin.
    location: LocationIn | None = None


def _place_details(payload: FuneralPlaceIn) -> tuple[dict, tuple[float, float] | None]:
    try:
        details = funeral_places.checked_details(
            name=payload.name, kind=payload.kind, city=payload.city, address=payload.address, run_by=payload.run_by,
        )
    except funeral_places.PlaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    position = _checked_position(payload.location, "the place") if payload.location else None
    return details, position


async def _place(db: AsyncSession, place_id: int, *, lock: bool = False) -> FuneralPlace:
    place = await db.get(FuneralPlace, place_id, with_for_update=True if lock else None)
    if place is None:
        raise HTTPException(status_code=404, detail="That place could not be found.")
    return place


@router.get("/funeral-places")
async def list_funeral_places(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    """Every funeral place, those in use first, with how many managers each has."""
    return {"places": await funeral_places.admin_list(db)}


@router.get("/funeral-places/{place_id}")
async def get_funeral_place(
    place_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    return funeral_places.summary(await _place(db, place_id))


@router.post("/funeral-places")
async def create_funeral_place(
    payload: FuneralPlaceIn, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    rate_limit.enforce_key(f"admin_funeral_place:{admin.id}", max_requests=30, window_seconds=60)
    details, position = _place_details(payload)
    place = await funeral_places.create(db, admin, details, position)
    await db.commit()
    return funeral_places.summary(place)


@router.put("/funeral-places/{place_id}")
async def update_funeral_place(
    place_id: int, payload: FuneralPlaceIn, db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """Change a place's details or its pin. ``location`` null takes the pin off."""
    rate_limit.enforce_key(f"admin_funeral_place:{admin.id}", max_requests=30, window_seconds=60)
    details, position = _place_details(payload)
    place = await funeral_places.update(db, await _place(db, place_id, lock=True), admin, details, position)
    await db.commit()
    return funeral_places.summary(place)


class PlaceActiveIn(BaseModel):
    active: bool


@router.post("/funeral-places/{place_id}/active")
async def set_funeral_place_active(
    place_id: int, payload: PlaceActiveIn, db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """Turn a place off (managers signing up no longer see it) or on again.
    Nothing is deleted, and its managers keep their accounts."""
    rate_limit.enforce_key(f"admin_funeral_place:{admin.id}", max_requests=30, window_seconds=60)
    place = await funeral_places.set_active(db, await _place(db, place_id, lock=True), admin, payload.active)
    await db.commit()
    return funeral_places.summary(place)
