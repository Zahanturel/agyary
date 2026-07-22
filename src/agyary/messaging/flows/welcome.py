"""Welcome menu, first-time name collection, and menu routing."""

from __future__ import annotations

from sqlalchemy import select

from agyary.messaging.flows.base import FlowContext, matched_option
from agyary.messaging.formatting import PURPOSE_SHORT, date_label, geh_label, gregorian_label
from agyary.messaging.geh_times import to_ist
from agyary.messaging.types import ListRow, ListSection, OutgoingMessage
from agyary.models import Booking, Machi, Service

MENU_OPTIONS = {
    "rebook_last": ["same as last booking", "same as last time", "rebook"],
    "book_machi": ["book a machi", "machi", "book machi"],
    "book_service": ["book a service", "service", "book service"],
    "my_bookings": ["my bookings", "bookings"],
    "contact": ["contact", "contact us", "help"],
}


async def last_ceremony(ctx: FlowContext) -> Machi | Booking | None:
    """The customer's most recent ceremony at this agyary (machi or booking)."""
    machi = (
        await ctx.db.execute(
            select(Machi)
            .where(Machi.agyary_id == ctx.agyary.id, Machi.customer_id == ctx.customer.id)
            .order_by(Machi.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    booking = (
        await ctx.db.execute(
            select(Booking)
            .where(Booking.agyary_id == ctx.agyary.id, Booking.customer_id == ctx.customer.id)
            .order_by(Booking.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if machi and booking:
        return machi if machi.created_at >= booking.created_at else booking
    return machi or booking


async def _rebook_description(ctx: FlowContext, ceremony: Machi | Booking) -> str:
    if isinstance(ceremony, Machi):
        return (
            f"Machi ({PURPOSE_SHORT[ceremony.purpose]}), "
            f"{date_label(ceremony.parsi_roj, ceremony.parsi_mah, ceremony.gregorian_date)}, "
            f"{geh_label(ceremony.geh)}"
        )[:72]
    service = await ctx.db.get(Service, ceremony.service_id)
    service_name = service.name if service else "Service"
    return (
        f"{service_name} ({PURPOSE_SHORT[ceremony.purpose]}), "
        f"{gregorian_label(to_ist(ceremony.date_time).date())}"
    )[:72]


async def welcome_message(
    ctx: FlowContext, greeting: str | None = None
) -> list[OutgoingMessage]:
    """Greet and show the main menu; sets the menu state."""
    previous = await last_ceremony(ctx)
    sections: list[ListSection] = []
    if previous is not None:
        sections.append(
            ListSection(
                title="Quick Rebook",
                rows=[
                    ListRow(
                        id="rebook_last",
                        title="Same as last booking",
                        description=await _rebook_description(ctx, previous),
                    )
                ],
            )
        )
    sections.append(
        ListSection(
            title="Book",
            rows=[
                ListRow(id="book_machi", title="Book a Machi"),
                ListRow(id="book_service", title="Book a Service"),
            ],
        )
    )
    sections.append(
        ListSection(
            title="Other",
            rows=[
                ListRow(id="my_bookings", title="My Bookings"),
                ListRow(id="contact", title="Contact us"),
            ],
        )
    )

    if greeting is None:
        greeting = (
            f"Hi {ctx.customer.name}! What would you like to do?"
            if ctx.customer.name
            else f"Welcome to {ctx.agyary.name}. What would you like to do?"
        )
    await ctx.set_state("menu", "main", {})
    return [ctx.reply(greeting, sections=sections)]


def ask_name_message(ctx: FlowContext) -> OutgoingMessage:
    return ctx.reply(f"Welcome to {ctx.agyary.name} - may we have your name?")


async def handle_name_reply(ctx: FlowContext) -> list[OutgoingMessage]:
    name = ctx.text.strip()[:200]
    if not name:
        return [ctx.reply("Sorry, we didn't catch that. Please send us your name.")]
    ctx.customer.name = name
    await ctx.db.flush()
    return await welcome_message(ctx, greeting=f"Thanks, {name}! What would you like to do?")


async def contact_message(ctx: FlowContext) -> list[OutgoingMessage]:
    from agyary.messaging.booking_service import get_admins

    admins = await get_admins(ctx.db, ctx.agyary.id)
    contact_phone = ctx.agyary.contact_phone or (admins[0].phone if admins else None)
    contact_name = admins[0].name if admins else ctx.agyary.name
    if contact_phone:
        text = f"You can reach {contact_name} directly at {contact_phone}."
    else:
        text = f"Please visit {ctx.agyary.name} and the team will be happy to help."
    await ctx.clear_state()
    return [ctx.reply(text)]


def match_menu_selection(text: str) -> str | None:
    return matched_option(text, MENU_OPTIONS)
