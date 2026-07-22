"""Panthaky/caretaker approval actions, stateless (button-id replies).

Button ids: approve_machi_<id>, decline_machi_<id>, approve_booking_<id>,
decline_booking_<id>. The sender must be an active admin at the agyary.
"""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from agyary.messaging import booking_service
from agyary.messaging.formatting import (
    PURPOSE_SHORT,
    date_label,
    geh_label,
    rupees,
)
from agyary.messaging.geh_times import to_ist
from agyary.messaging.types import OutgoingMessage
from agyary.models import Agyary, Booking, Customer, Machi, Service

ACTION_RE = re.compile(r"^(?P<action>approve|decline)_(?P<entity>machi|booking)_(?P<id>\d+)$")


def match_admin_action(text: str) -> re.Match | None:
    return ACTION_RE.match(text.strip().casefold())


async def handle_admin_action(
    db: AsyncSession, agyary: Agyary, sender_phone: str, match: re.Match
) -> list[OutgoingMessage]:
    if not await booking_service.is_admin_phone(db, agyary.id, sender_phone):
        return [
            OutgoingMessage(
                to=sender_phone,
                text="Sorry, only the panthaky or caretaker can approve bookings.",
            )
        ]

    action = match.group("action")
    entity = match.group("entity")
    entity_id = int(match.group("id"))

    ceremony = await db.get(Machi if entity == "machi" else Booking, entity_id)
    if ceremony is None or ceremony.agyary_id != agyary.id:
        return [OutgoingMessage(to=sender_phone, text="That request could not be found.")]

    if ceremony.status != "requested":
        return [
            OutgoingMessage(
                to=sender_phone,
                text=f"This request was already {ceremony.status}.",
            )
        ]

    customer = await db.get(Customer, ceremony.customer_id)

    if isinstance(ceremony, Machi):
        when = (
            f"{date_label(ceremony.parsi_roj, ceremony.parsi_mah, ceremony.gregorian_date)}, "
            f"{geh_label(ceremony.geh)}"
        )
        what = f"Machi ({PURPOSE_SHORT[ceremony.purpose]})"
    else:
        service = await db.get(Service, ceremony.service_id)
        local = to_ist(ceremony.date_time)
        when = (
            f"{date_label(ceremony.parsi_roj, ceremony.parsi_mah, local.date())}, "
            f"{local.strftime('%I:%M %p').lstrip('0')}"
        )
        what = f"{service.name if service else 'Service'} ({PURPOSE_SHORT[ceremony.purpose]})"

    if action == "decline":
        ceremony.status = "declined"
        await db.flush()
        return [
            OutgoingMessage(to=sender_phone, text=f"Declined: {what}, {when}."),
            OutgoingMessage(
                to=customer.phone,
                text=(
                    f"We're sorry, your request for {what} on {when} at "
                    f"{agyary.name} could not be accommodated.\n\n"
                    "You're welcome to try a different date - just send us a message."
                ),
            ),
        ]

    ceremony.status = "approved"
    await db.flush()

    payment_lines = []
    if ceremony.amount is not None:
        upi_link = None
        if agyary.upi_id:
            upi_link = booking_service.generate_upi_link(
                agyary.upi_id, agyary.name, Decimal(ceremony.amount), f"{what} - {when}"
            )
        await booking_service.create_pending_payment(db, ceremony, upi_link)
        payment_lines = ["", f"Amount: {rupees(ceremony.amount)}"]
        if upi_link:
            payment_lines.append(f"Pay via UPI: {upi_link}")
        payment_lines.append("Or pay at the agyary.")

    confirmation = "\n".join(
        [f"Your {what} at {agyary.name} is confirmed for {when}.", *payment_lines]
    )
    return [
        OutgoingMessage(to=sender_phone, text=f"Approved: {what}, {when}."),
        OutgoingMessage(to=customer.phone, text=confirmation),
    ]
