"""My Bookings: list upcoming ceremonies, allow cancellation.

Steps: choose_item -> item_actions -> confirm_cancel.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from agyary.messaging import booking_service
from agyary.messaging.flows.base import FlowContext, matched_option
from agyary.messaging.geh_times import to_ist
from agyary.messaging.formatting import (
    PURPOSE_SHORT,
    date_label,
    geh_label,
    rupees,
)
from agyary.messaging.types import Button, OutgoingMessage
from agyary.models import Booking, Machi, Service

FLOW = "my_bookings"

ACTIVE_STATUSES = ("requested", "approved", "assigned", "mobed_declined", "confirmed")

STATUS_DISPLAY = {
    "requested": "Awaiting confirmation",
    "approved": "Confirmed",
    "assigned": "Confirmed",
    "mobed_declined": "Confirmed",
    "confirmed": "Confirmed",  # auto-booked machi (redesign v3) - never "requested"
}


async def _upcoming_items(ctx: FlowContext) -> list[dict]:
    horizon = datetime.now(UTC) - timedelta(hours=12)
    machis = (
        await ctx.db.execute(
            select(Machi).where(
                Machi.agyary_id == ctx.agyary.id,
                Machi.customer_id == ctx.customer.id,
                Machi.status.in_(ACTIVE_STATUSES),
                Machi.ceremony_datetime >= horizon,
            )
        )
    ).scalars()
    bookings = (
        await ctx.db.execute(
            select(Booking).where(
                Booking.agyary_id == ctx.agyary.id,
                Booking.customer_id == ctx.customer.id,
                Booking.status.in_(ACTIVE_STATUSES),
                Booking.ceremony_datetime >= horizon,
            )
        )
    ).scalars()

    items = []
    for machi in machis:
        items.append(
            {
                "type": "machi",
                "id": machi.id,
                "when": machi.ceremony_datetime,
                "label": (
                    f"Machi ({PURPOSE_SHORT[machi.purpose]}) - "
                    f"{date_label(machi.parsi_roj, machi.parsi_mah, machi.gregorian_date)}, "
                    f"{geh_label(machi.geh)}"
                ),
                "status": machi.status,
                "amount": str(machi.amount) if machi.amount is not None else None,
                "payment_status": machi.payment_status,
            }
        )
    for booking in bookings:
        service = await ctx.db.get(Service, booking.service_id)
        service_name = service.name if service else "Service"
        local = to_ist(booking.date_time)
        items.append(
            {
                "type": "booking",
                "id": booking.id,
                "when": booking.ceremony_datetime,
                "label": (
                    f"{service_name} ({PURPOSE_SHORT[booking.purpose]}) - "
                    f"{date_label(booking.parsi_roj, booking.parsi_mah, local.date())}, "
                    f"{local.strftime('%I:%M %p').lstrip('0')}"
                ),
                "status": booking.status,
                "amount": str(booking.amount) if booking.amount is not None else None,
                "payment_status": booking.payment_status,
            }
        )
    items.sort(key=lambda item: item["when"])
    return items


async def start(ctx: FlowContext) -> list[OutgoingMessage]:
    items = await _upcoming_items(ctx)
    if not items:
        await ctx.clear_state()
        return [
            ctx.reply(
                "You have no upcoming bookings.\n"
                "Send any message to see the menu and book one."
            )
        ]
    lines = ["Your upcoming bookings:", ""]
    for i, item in enumerate(items, start=1):
        lines.append(f"{i}. {item['label']}")
        lines.append(f"   Status: {STATUS_DISPLAY.get(item['status'], item['status'])}")
        if item["amount"]:
            paid = "paid" if item["payment_status"] == "received" else "pending"
            lines.append(f"   Amount: {rupees(item['amount'])} ({paid})")
        lines.append("")
    lines.append("To cancel a booking, reply with its number (e.g. '1').")

    stored = [
        {"type": item["type"], "id": item["id"], "label": item["label"]} for item in items
    ]
    await ctx.set_state(FLOW, "choose_item", {"items": stored})
    return [ctx.reply("\n".join(lines))]


async def handle(ctx: FlowContext) -> list[OutgoingMessage]:
    handlers = {
        "choose_item": _step_choose_item,
        "item_actions": _step_item_actions,
        "confirm_cancel": _step_confirm_cancel,
    }
    handler = handlers.get(ctx.state.step)
    if handler is None:
        await ctx.clear_state()
        return [ctx.reply("Sorry, something went wrong. Send any message to start over.")]
    return await handler(ctx)


async def _step_choose_item(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    items = data.get("items", [])
    text = ctx.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= len(items)):
        return [
            ctx.reply(
                f"Please reply with a number between 1 and {len(items)}, "
                "or 'menu' to go back."
            )
        ]
    index = int(text) - 1
    data["selected"] = index
    await ctx.set_state(FLOW, "item_actions", data)
    item = items[index]
    return [
        ctx.reply(
            f"{item['label']}\nWhat would you like to do?",
            buttons=[
                Button(id="cancel_item", title="Cancel booking"),
                Button(id="back_bookings", title="Back"),
            ],
        )
    ]


async def _step_item_actions(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    choice = matched_option(
        ctx.text,
        {"cancel_item": ["cancel booking", "cancel"], "back_bookings": ["back"]},
    )
    if choice == "back_bookings":
        return await start(ctx)
    if choice != "cancel_item":
        return [
            ctx.reply(
                "Please choose:",
                buttons=[
                    Button(id="cancel_item", title="Cancel booking"),
                    Button(id="back_bookings", title="Back"),
                ],
            )
        ]
    item = data["items"][data["selected"]]
    await ctx.set_state(FLOW, "confirm_cancel", data)
    return [
        ctx.reply(
            f"Are you sure you want to cancel?\n\n{item['label']}\n\n"
            "If you've already paid, please collect your refund directly "
            f"from {ctx.agyary.name}.",
            buttons=[
                Button(id="confirm_cancel", title="Yes, cancel"),
                Button(id="keep_item", title="No, keep it"),
            ],
        )
    ]


async def _step_confirm_cancel(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    choice = matched_option(
        ctx.text,
        {"confirm_cancel": ["yes", "yes, cancel"], "keep_item": ["no", "no, keep it", "keep"]},
    )
    if choice == "keep_item":
        await ctx.clear_state()
        return [ctx.reply("No problem, your booking is unchanged.")]
    if choice != "confirm_cancel":
        return [
            ctx.reply(
                "Please choose:",
                buttons=[
                    Button(id="confirm_cancel", title="Yes, cancel"),
                    Button(id="keep_item", title="No, keep it"),
                ],
            )
        ]

    item = data["items"][data["selected"]]
    ceremony = await ctx.db.get(
        Machi if item["type"] == "machi" else Booking, item["id"]
    )
    if ceremony is None or ceremony.status not in ACTIVE_STATUSES:
        await ctx.clear_state()
        return [ctx.reply("That booking can no longer be cancelled - please contact the agyary.")]

    ceremony.status = "cancelled"
    await ctx.db.flush()
    await ctx.clear_state()

    messages = [
        ctx.reply(
            f"Your booking has been cancelled:\n{item['label']}\n\n"
            "If you'd like to rebook, just send us a message anytime."
        )
    ]
    # Every active member, not just ADMIN_ROLES - a peer-mobed agyari has
    # no panthaky/caretaker to notify, and get_admins() would silently
    # return nobody there (the same class of bug this redesign exists to
    # fix, not just for machi's booking path).
    for member in await booking_service.get_active_agyary_users(ctx.db, ctx.agyary.id):
        messages.append(
            OutgoingMessage(
                to=member.phone,
                text=(
                    f"Cancellation at {ctx.agyary.name}:\n\n"
                    f"{ctx.customer.name} ({ctx.customer.phone}) cancelled:\n"
                    f"{item['label']}\n\nThe slot is open again."
                ),
            )
        )
    return messages
