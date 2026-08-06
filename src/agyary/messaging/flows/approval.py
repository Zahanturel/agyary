"""Accept/decline actions on service (booking) requests: idempotent,
actionable from more than one entry point (WhatsApp button today, the PWA -
module 5 - as well). The state transition + idempotency guard is one
shared function (``apply_booking_action``); each transport does its own
authorization check (phone match for WhatsApp, authenticated user id for
the PWA) before calling it, then renders its own output shape from the
same ``BookingActionOutcome``.

Button ids: approve_machi_<id>, decline_machi_<id>, approve_booking_<id>,
decline_booking_<id> (kept as the internal action-id scheme; the visible
button title is "Accept"/"Decline", not "Approve").

Machi (redesign v3): no longer sent - machi.py's confirm step stopped
sending approve_machi_/decline_machi_ buttons entirely, since machi is now
fully automatic (booking_service.book_machi_slot decides on the spot, no
human gate). That "machi" branch below is left functional, not deleted -
per doc 04's own recommendation - purely so any machi still sitting at
status="requested" from before this cutover can still be resolved by an
admin who taps an already-delivered button; no new message will ever
trigger it going forward. Its authorization check is unchanged
(ADMIN_ROLES) since that's a legacy-only path.

Bookings (services, redesign v3): the gate holder changed from "any admin"
to "the specific priest the behdin chose" (service.py's new "choose who to
book with" step creates a BookingMobed row at request time). Authorization
here checks that row, not ADMIN_ROLES - this *is* the new gate, replacing
the old generic admin approve/decline, not stacked on top of it. No
money/payment in the confirmation text (doc 05: none in this pass).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.messaging import booking_service
from agyary.messaging.formatting import PURPOSE_SHORT, date_label, geh_label
from agyary.messaging.geh_times import to_ist
from agyary.messaging.types import OutgoingMessage
from agyary.models import Agyary, Booking, BookingMobed, Customer, Machi, Service, User

ACTION_RE = re.compile(r"^(?P<action>approve|decline)_(?P<entity>machi|booking)_(?P<id>\d+)$")


def match_admin_action(text: str) -> re.Match | None:
    return ACTION_RE.match(text.strip().casefold())


async def get_booking_mobed_row(db: AsyncSession, booking_id: int) -> BookingMobed | None:
    result = await db.execute(select(BookingMobed).where(BookingMobed.booking_id == booking_id))
    return result.scalar_one_or_none()


def _describe(ceremony: Machi | Booking, service: Service | None) -> tuple[str, str]:
    if isinstance(ceremony, Machi):
        when = (
            f"{date_label(ceremony.parsi_roj, ceremony.parsi_mah, ceremony.gregorian_date)}, "
            f"{geh_label(ceremony.geh)}"
        )
        what = f"Machi ({PURPOSE_SHORT[ceremony.purpose]})"
    else:
        local = to_ist(ceremony.date_time)
        when = (
            f"{date_label(ceremony.parsi_roj, ceremony.parsi_mah, local.date())}, "
            f"{local.strftime('%I:%M %p').lstrip('0')}"
        )
        what = f"{service.name if service else 'Service'} ({PURPOSE_SHORT[ceremony.purpose]})"
    return what, when


@dataclass
class BookingActionOutcome:
    """Transport-agnostic result of an accept/decline attempt.

    ``status`` is one of: "not_found", "already_resolved", "declined",
    "approved". The caller (WhatsApp handler or the PWA route) renders its
    own message/response shape from this - neither transport re-derives
    the state transition itself.
    """

    status: str
    ceremony: Machi | Booking | None = None
    customer: Customer | None = None
    what: str | None = None
    when: str | None = None
    previous_status: str | None = None


async def apply_booking_action(
    db: AsyncSession, ceremony: Machi | Booking, mobed_row: BookingMobed | None, action: str
) -> BookingActionOutcome:
    """The one idempotent state transition, shared by every entry point.

    Callers MUST authorize before calling this - it only guards resolution
    idempotency (has this already been decided), not who's allowed to
    decide, since that check differs by transport.
    """
    if ceremony.status != "requested":
        return BookingActionOutcome(status="already_resolved", previous_status=ceremony.status)

    customer = await db.get(Customer, ceremony.customer_id)
    service = (
        await db.get(Service, ceremony.service_id) if isinstance(ceremony, Booking) else None
    )
    what, when = _describe(ceremony, service)

    if action == "decline":
        ceremony.status = "declined"
        if mobed_row is not None:
            mobed_row.status = "declined"
        await db.flush()
        return BookingActionOutcome(
            status="declined", ceremony=ceremony, customer=customer, what=what, when=when
        )

    ceremony.status = "approved"
    if mobed_row is not None:
        mobed_row.status = "accepted"
    await db.flush()
    return BookingActionOutcome(
        status="approved", ceremony=ceremony, customer=customer, what=what, when=when
    )


async def handle_admin_action(
    db: AsyncSession, agyary: Agyary, sender_phone: str, match: re.Match
) -> list[OutgoingMessage]:
    action = match.group("action")
    entity = match.group("entity")
    entity_id = int(match.group("id"))

    ceremony = await db.get(Machi if entity == "machi" else Booking, entity_id)
    if ceremony is None or ceremony.agyary_id != agyary.id:
        return [OutgoingMessage(to=sender_phone, text="That request could not be found.")]

    mobed_row: BookingMobed | None = None
    if entity == "machi":
        # Legacy path only - see module docstring. Unchanged authorization.
        authorized = await booking_service.is_admin_phone(db, agyary.id, sender_phone)
    else:
        mobed_row = await get_booking_mobed_row(db, entity_id)
        mobed = await db.get(User, mobed_row.user_id) if mobed_row else None
        authorized = mobed is not None and mobed.phone == sender_phone

    if not authorized:
        return [OutgoingMessage(to=sender_phone, text="Sorry, you're not able to take that action.")]

    outcome = await apply_booking_action(db, ceremony, mobed_row, action)

    if outcome.status == "already_resolved":
        return [
            OutgoingMessage(to=sender_phone, text=f"This request was already {outcome.previous_status}.")
        ]

    if outcome.status == "declined":
        return [
            OutgoingMessage(to=sender_phone, text=f"Declined: {outcome.what}, {outcome.when}."),
            OutgoingMessage(
                to=outcome.customer.phone,
                text=(
                    f"We're sorry, your request for {outcome.what} on {outcome.when} at "
                    f"{agyary.name} could not be accommodated.\n\n"
                    "You're welcome to try a different date - just send us a message."
                ),
            ),
        ]

    return [
        OutgoingMessage(to=sender_phone, text=f"Accepted: {outcome.what}, {outcome.when}."),
        OutgoingMessage(
            to=outcome.customer.phone,
            text=f"Your {outcome.what} at {agyary.name} is confirmed for {outcome.when}.",
        ),
    ]


async def handle_pwa_booking_action(
    db: AsyncSession, agyary: Agyary, actor_user_id: int, booking_id: int, action: str
) -> BookingActionOutcome:
    """The PWA's accept/decline entry point (module 5's API route calls
    this) - same idempotent core as the WhatsApp path, authorized against
    the already-authenticated user's id instead of a phone number."""
    booking = await db.get(Booking, booking_id)
    if booking is None or booking.agyary_id != agyary.id:
        return BookingActionOutcome(status="not_found")

    mobed_row = await get_booking_mobed_row(db, booking_id)
    if mobed_row is None or mobed_row.user_id != actor_user_id:
        return BookingActionOutcome(status="unauthorized")

    return await apply_booking_action(db, booking, mobed_row, action)
