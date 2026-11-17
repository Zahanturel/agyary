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
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.api.routes.mobed import get_current_user
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import LoginOtp, Notification, User
from agyary.models.enums import ACCESS_PENDING
from agyary.services import bot_check, erasure, guardrails, mobed_access, mobed_auth
from agyary.services.phone import Phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobed/admin", tags=["admin"])


def require_admin(user: User = Depends(get_current_user)) -> User:
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
        # For the Mobeds card at the top: how many are waiting for approval (D9).
        "mobeds_waiting": (
            await db.execute(
                select(func.count()).select_from(User).where(
                    User.is_active.is_(True), User.access == ACCESS_PENDING,
                    User.phone.notin_(guardrails.admin_phones(s) or {""}),
                )
            )
        ).scalar_one(),
    }


class SignOutIn(BaseModel):
    phone: Phone


@router.post("/sign-out-everywhere")
async def sign_out_everywhere(
    payload: SignOutIn, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    """End every signed-in device of one mobed (AU-2) - a phone that was lost or
    taken, a sign-in nobody recognises. They can sign in again with WhatsApp."""
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
    return {"mobeds": mobeds, "waiting": sum(1 for m in mobeds if m["access"] == ACCESS_PENDING)}


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
        await mobed_access.set_access(db, get_settings(), user, payload.access)
    except mobed_access.AccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    logger.warning("Admin %s set mobed %s access to %s", admin.id, user.id, payload.access)
    return {"id": user.id, "access": mobed_access.effective(get_settings(), user)}
