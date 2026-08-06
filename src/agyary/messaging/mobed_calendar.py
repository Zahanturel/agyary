"""Shared priest-personal-calendar-conflict check.

One function owns "does this mobed already have something booked around
this time" - the WhatsApp services flow (an informational, non-blocking
note on the chosen priest's notification) and the PWA (My Day / manual add,
same non-blocking flag) both call into this rather than re-deriving the
overlap logic independently. Never a gate: doc 05 is explicit that a
conflict never blocks the request, only flags it for the priest's own
judgment.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.messaging.geh_times import ensure_ist
from agyary.models import Booking, BookingMobed, Service
from agyary.models.enums import SLOT_RELEASING_STATUSES

DEFAULT_DURATION = timedelta(minutes=60)


def _booking_interval(booking: Booking, service: Service | None) -> tuple[datetime, datetime]:
    start = booking.ceremony_datetime
    if booking.end_time is not None:
        end = booking.end_time
    elif service is not None and service.typical_duration_minutes:
        end = start + timedelta(minutes=service.typical_duration_minutes)
    else:
        end = start + DEFAULT_DURATION
    return start, end


async def has_calendar_conflict(
    db: AsyncSession,
    mobed_user_id: int,
    ceremony_datetime: datetime,
    duration: timedelta = DEFAULT_DURATION,
    exclude_booking_id: int | None = None,
) -> bool:
    """True if `mobed_user_id` already has an accepted booking overlapping
    [ceremony_datetime, ceremony_datetime + duration).

    Informational only - callers must never use this result to block
    creation, only to flag it for the priest. ``exclude_booking_id`` skips a
    booking being edited so it doesn't conflict with itself.
    """
    # Anchor the incoming time to IST: stored ceremony_datetimes come back
    # tz-aware from Postgres, so a naive input would raise on comparison
    # (audit finding G1, part b).
    ceremony_datetime = ensure_ist(ceremony_datetime)
    new_start, new_end = ceremony_datetime, ceremony_datetime + duration
    result = await db.execute(
        select(Booking, Service)
        .join(BookingMobed, BookingMobed.booking_id == Booking.id)
        .outerjoin(Service, Service.id == Booking.service_id)
        .where(
            BookingMobed.user_id == mobed_user_id,
            BookingMobed.status == "accepted",
            Booking.status.notin_(SLOT_RELEASING_STATUSES),
        )
    )
    for booking, service in result.all():
        if exclude_booking_id is not None and booking.id == exclude_booking_id:
            continue
        start, end = _booking_interval(booking, service)
        if start < new_end and new_start < end:
            return True
    return False
