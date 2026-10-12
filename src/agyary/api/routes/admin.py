"""The admin's view of what sending is costing, and the switch that stops it.

For the people listed in ADMIN_PHONES, nobody else. A non-admin gets a 404 -
the same answer as for a page that does not exist - so the screen's existence
is not something to probe for.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api import rate_limit
from agyary.api.routes.mobed import get_current_user
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import LoginOtp, Notification, User
from agyary.services import guardrails

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
        "otp": {"mode": s.otp_mode, "today": otp_today, "daily_cap": s.otp_daily_cap},
        "recent_failures": [
            {"when": when.isoformat(), "reason": reason or "", "to": _masked(phone)}
            for when, reason, phone in failures
        ],
    }


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
