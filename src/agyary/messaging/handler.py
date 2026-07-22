"""The single transport-agnostic entry point of the messaging layer.

handle_message(db, agyary_id, phone_number, text) -> list[OutgoingMessage]

The transport (web chat simulator today, WhatsApp Cloud API adapter later)
resolves the tenant, passes inbound text (or a tapped option's id) here, and
delivers whatever comes back. Everything else - flow state, booking logic,
name parsing, approvals - happens behind this function.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from agyary.messaging import booking_service, state as state_store
from agyary.messaging.flows import approval, machi, my_bookings, service, welcome
from agyary.messaging.flows.base import FlowContext
from agyary.messaging.types import OutgoingMessage
from agyary.models import Agyary, Booking, CeremonyName, Machi, WhatsAppMessage
from sqlalchemy import select

logger = logging.getLogger(__name__)

RESET_KEYWORDS = {"menu", "start over", "restart"}

ERROR_REPLY = (
    "Sorry, something went wrong on our end. Please try again in a few minutes.\n"
    "If the problem continues, please contact the agyary directly."
)


async def handle_message(
    db: AsyncSession, agyary_id: int, phone_number: str, text: str
) -> list[OutgoingMessage]:
    outgoing, _outbox_ids = await _handle_message_impl(db, agyary_id, phone_number, text)
    return outgoing


async def handle_message_with_outbox_ids(
    db: AsyncSession,
    agyary_id: int,
    phone_number: str,
    text: str,
    *,
    inbound_wa_message_id: str | None = None,
) -> list[tuple[OutgoingMessage, int | None]]:
    """WhatsApp-webhook variant of handle_message.

    Same routing/persistence as handle_message, but also returns the outbox
    (WhatsAppMessage) row id alongside each reply, so the webhook route can
    enqueue exactly those rows for the send worker without reconstructing
    them by phone/timestamp heuristics. A reply's id is None only when it
    was never persisted (the in-memory error reply from an unhandled
    exception) - the webhook route should simply skip enqueuing it, same as
    today it is neither persisted nor sent anywhere durable.
    """
    outgoing, outbox_ids = await _handle_message_impl(
        db, agyary_id, phone_number, text, inbound_wa_message_id=inbound_wa_message_id
    )
    return list(zip(outgoing, outbox_ids))


async def _handle_message_impl(
    db: AsyncSession,
    agyary_id: int,
    phone_number: str,
    text: str,
    *,
    inbound_wa_message_id: str | None = None,
) -> tuple[list[OutgoingMessage], list[int | None]]:
    phone = phone_number.strip()
    text = text.strip()
    if not phone or not text:
        return [], []

    agyary = await db.get(Agyary, agyary_id)
    if agyary is None or not agyary.is_active:
        logger.error("Message for unknown/inactive agyary_id=%s", agyary_id)
        return [], []

    inbound_log = WhatsAppMessage(
        agyary_id=agyary.id,
        direction="inbound",
        wa_phone=phone,
        wa_message_id=inbound_wa_message_id,
        wa_timestamp=datetime.now(UTC),
        message_type="text",
        content={"text": text},
    )
    db.add(inbound_log)

    try:
        outgoing = await _route(db, agyary, phone, text, inbound_log)
    except Exception:
        logger.exception("Error handling message from %s at agyary %s", phone, agyary_id)
        await db.rollback()
        return [OutgoingMessage(to=phone, text=ERROR_REPLY)], [None]

    now = datetime.now(UTC)
    outbound_rows = []
    for message in outgoing:
        row = WhatsAppMessage(
            agyary_id=agyary.id,
            direction="outbound",
            wa_phone=message.to,
            wa_timestamp=datetime.now(UTC),
            message_type="interactive" if (message.buttons or message.sections) else "text",
            content=message.as_dict(),
            status="pending",
            attempts=0,
            next_attempt_at=now,
        )
        db.add(row)
        outbound_rows.append(row)
    await db.flush()  # assigns .id to each row without ending the transaction
    await db.commit()
    return outgoing, [row.id for row in outbound_rows]


async def _route(
    db: AsyncSession,
    agyary: Agyary,
    phone: str,
    text: str,
    inbound_log: WhatsAppMessage,
) -> list[OutgoingMessage]:
    # 1. Panthaky approve/decline button replies (stateless).
    admin_match = approval.match_admin_action(text)
    if admin_match:
        return await approval.handle_admin_action(db, agyary, phone, admin_match)

    # 2. Resolve (or create) the customer.
    customer = await booking_service.get_customer_by_phone(db, phone)
    if customer is None:
        customer = await booking_service.create_customer(db, phone)
    inbound_log.customer_id = customer.id

    ctx = FlowContext(db=db, agyary=agyary, customer=customer, phone=phone, text=text)
    ctx.state = await state_store.load_state(db, agyary.id, phone)

    # 3. First-time customers: collect their name before anything else
    #    (WhatsApp profile names are unreliable - v2 audit fix #3).
    if not customer.name:
        if ctx.state and ctx.state.flow == "onboarding":
            return await welcome.handle_name_reply(ctx)
        await ctx.set_state("onboarding", "ask_name", {})
        return [welcome.ask_name_message(ctx)]

    # 4. Global reset keywords.
    if text.casefold() in RESET_KEYWORDS:
        await ctx.clear_state()
        return await welcome.welcome_message(ctx)

    # 5. No active flow: parse intent directly (a stateless "book machi"
    #    starts the flow), otherwise show the welcome menu.
    if ctx.state is None:
        choice = welcome.match_menu_selection(text)
        if choice is not None:
            return await _dispatch_menu_choice(ctx, choice)
        return await welcome.welcome_message(ctx)

    # 6. Dispatch to the active flow.
    flow = ctx.state.flow
    if flow == "onboarding":
        # Name arrived meanwhile (e.g. panthaky filled it in) - just greet.
        await ctx.clear_state()
        return await welcome.welcome_message(ctx)
    if flow == "menu":
        return await _handle_menu(ctx)
    if flow == machi.FLOW:
        return await machi.handle(ctx)
    if flow == service.FLOW:
        return await service.handle(ctx)
    if flow == my_bookings.FLOW:
        return await my_bookings.handle(ctx)

    logger.error("Unknown flow %r for %s - resetting", flow, phone)
    await ctx.clear_state()
    return await welcome.welcome_message(ctx)


async def _handle_menu(ctx: FlowContext) -> list[OutgoingMessage]:
    choice = welcome.match_menu_selection(ctx.text)
    if choice is None:
        unrecognized = ctx.reply("Sorry, I didn't understand that. Please pick an option:")
        return [unrecognized, *await welcome.welcome_message(ctx)]
    return await _dispatch_menu_choice(ctx, choice)


async def _dispatch_menu_choice(ctx: FlowContext, choice: str) -> list[OutgoingMessage]:
    if choice == "book_machi":
        return await machi.start(ctx)
    if choice == "book_service":
        return await service.start(ctx)
    if choice == "my_bookings":
        return await my_bookings.start(ctx)
    if choice == "rebook_last":
        return await _start_rebook(ctx)
    return await welcome.contact_message(ctx)


async def _ceremony_names_as_dicts(ctx: FlowContext, ceremony: Machi | Booking) -> list[dict]:
    column = CeremonyName.machi_id if isinstance(ceremony, Machi) else CeremonyName.booking_id
    rows = (
        await ctx.db.execute(
            select(CeremonyName).where(column == ceremony.id).order_by(CeremonyName.display_order)
        )
    ).scalars()
    return [
        {
            "section": r.section,
            "title": r.title,
            "name": r.name,
            "status": r.status,
            "pair_group": r.pair_group,
        }
        for r in rows
    ]


async def _start_rebook(ctx: FlowContext) -> list[OutgoingMessage]:
    previous = await welcome.last_ceremony(ctx)
    if previous is None:
        return await welcome.welcome_message(ctx)
    names = await _ceremony_names_as_dicts(ctx, previous)
    if isinstance(previous, Machi):
        prefill = {"purpose": previous.purpose, "names": names, "names_from_saved": True}
        return await machi.start(ctx, prefill)
    booking_svc = await booking_service.get_service_by_id(
        ctx.db, ctx.agyary.id, previous.service_id
    )
    if booking_svc is None:
        return await service.start(ctx)
    prefill = {
        "service_id": booking_svc.id,
        "service_name": booking_svc.name,
        "offsite_capable": booking_svc.offsite_capable,
        "default_price": str(booking_svc.default_price)
        if booking_svc.default_price is not None
        else None,
        "purpose": previous.purpose,
        "names": names,
        "names_from_saved": True,
    }
    return await service.start(ctx, prefill)
