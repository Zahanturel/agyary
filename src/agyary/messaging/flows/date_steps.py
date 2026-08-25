"""Shared date-entry steps used by both the machi and service booking flows.

Outcomes are returned as (status, data_updates, messages); the calling flow
owns the flow/step naming and state writes.
"""

from __future__ import annotations

from datetime import date

from agyary.calendar import CalendarSystem, ROJ_NAMES, gregorian_to_parsi
from agyary.core.config import get_settings
from agyary.messaging import wa_flows
from agyary.messaging.availability import parsi_slot_fields
from agyary.messaging.date_parser import DateParse, infer_parsi_year, parse_date_input
from agyary.messaging.flows.base import FlowContext
from agyary.messaging.formatting import parsi_label
from agyary.messaging.types import Button, FlowPrompt, OutgoingMessage

DATE_HELP = (
    "You can type:\n"
    "  A Parsi date - 'Roj Bahman' or 'Roj Bahman Mah Fravardin'\n"
    "  A Gregorian date - 'July 23' or '23/7'\n"
    "  Or just 'tomorrow'"
)

MAH_ROWS = [
    ("mah_1", "Fravardin"),
    ("mah_2", "Ardibehesht"),
    ("mah_3", "Khordad"),
    ("mah_4", "Tir"),
    ("mah_5", "Amardad"),
    ("mah_6", "Shahrevar"),
    ("mah_7", "Meher"),
    ("mah_8", "Avan"),
    ("mah_9", "Adar"),
    ("mah_10", "Dae"),
    ("mah_11", "Bahman"),
    ("mah_12", "Aspandard"),
]


def _mah_flow_prompt(ctx: FlowContext, text: str) -> OutgoingMessage:
    """A predefined Dropdown, not a list message - Mah has 12 options,
    already over the interactive list message's real 10-row-total cap
    (confirmed against Meta's docs; the old chunk_rows-based 2-section
    split silently violated it). Closed vocabularies are tap-to-select,
    never free text."""
    settings = get_settings()
    return ctx.reply(
        text,
        flow=FlowPrompt(
            flow_id=settings.whatsapp_flow_id_mah,
            flow_token=wa_flows.make_flow_token("mah", ctx.agyary.id),
            flow_cta="Select Mah",
            screen="SELECT_MAH",
            data={},
        ),
    )


ROJ_ROWS = [(f"roj_{i + 1}", name) for i, name in enumerate(ROJ_NAMES)]


def _roj_flow_prompt(ctx: FlowContext, text: str) -> OutgoingMessage:
    """Roj has 30 options - same reasoning as _mah_flow_prompt."""
    settings = get_settings()
    return ctx.reply(
        text,
        flow=FlowPrompt(
            flow_id=settings.whatsapp_flow_id_roj,
            flow_token=wa_flows.make_flow_token("roj", ctx.agyary.id),
            flow_cta="Select Roj",
            screen="SELECT_ROJ",
            data={},
        ),
    )


def date_fields(roj: int, mah: int, year: int, gregorian: date) -> dict:
    return {"roj": roj, "mah": mah, "year": year, "gregorian": gregorian.isoformat()}


def resolve_date_text(
    ctx: FlowContext, today: date
) -> tuple[str, dict, list[OutgoingMessage]]:
    """Parse a free-text date reply.

    Returns (status, data_updates, messages) with status one of:
    'resolved', 'need_mah', 'need_roj', 'confirm_date', 'invalid'.
    """
    system = CalendarSystem(ctx.agyary.calendar_system)
    parsed: DateParse = parse_date_input(ctx.text, today)

    if parsed.kind == "parsi_full":
        year, gregorian = infer_parsi_year(parsed.roj, parsed.mah, system, today)
        return "resolved", date_fields(parsed.roj, parsed.mah, year, gregorian), []

    if parsed.kind == "parsi_roj_only":
        message = _mah_flow_prompt(
            ctx, f"Roj {ctx.text.strip().split()[-1].capitalize()}. Which Mah?"
        )
        return "need_mah", {"pending_roj": parsed.roj}, [message]

    if parsed.kind == "roj_invalid":
        message = _roj_flow_prompt(
            ctx, "Sorry, I didn't recognize that Roj. Please select one:"
        )
        return "need_roj", {}, [message]

    if parsed.kind == "mah_invalid":
        message = _mah_flow_prompt(
            ctx,
            f"Roj {ROJ_NAMES[parsed.roj - 1]}. Sorry, I didn't recognize that Mah. "
            "Please select one:",
        )
        return "need_mah", {"pending_roj": parsed.roj}, [message]

    if parsed.kind == "gregorian":
        roj, mah, year = parsi_slot_fields(gregorian_to_parsi(parsed.gregorian, system))
        if parsed.gregorian < today:
            return "invalid", {}, [
                ctx.reply("That date has already passed. Please choose a future date.")
            ]
        message = ctx.reply(
            f"{parsed.gregorian.strftime('%d %B %Y')} = {parsi_label(roj, mah)}.\n"
            "Is that correct?",
            buttons=[
                Button(id="date_confirm", title="Yes, correct"),
                Button(id="date_retry", title="No, different date"),
            ],
        )
        return (
            "confirm_date",
            {"pending_date": date_fields(roj, mah, year, parsed.gregorian)},
            [message],
        )

    return "invalid", {}, [
        ctx.reply(f"Sorry, I didn't understand that date.\n\n{DATE_HELP}")
    ]


def resolve_mah_selection(
    ctx: FlowContext, pending_roj: int, today: date
) -> tuple[str, dict, list[OutgoingMessage]]:
    """Handle the reply to the 'Which Mah?' list."""
    from agyary.messaging.date_parser import _MAH_LOOKUP, _match_calendar_name

    mah: int | None = None
    normalized = ctx.text.strip().casefold()
    for row_id, title in MAH_ROWS:
        if normalized in (row_id, title.casefold()):
            mah = int(row_id.split("_")[1])
            break
    if mah is None:
        mah = _match_calendar_name(normalized, _MAH_LOOKUP)
    if mah is None:
        return "invalid", {}, [_mah_flow_prompt(ctx, "Please select a Mah.")]

    system = CalendarSystem(ctx.agyary.calendar_system)
    year, gregorian = infer_parsi_year(pending_roj, mah, system, today)
    return "resolved", date_fields(pending_roj, mah, year, gregorian), []


def resolve_roj_selection(ctx: FlowContext) -> tuple[str, dict, list[OutgoingMessage]]:
    """Handle the reply to the 'Which Roj?' list (shown after a typo)."""
    from agyary.messaging.date_parser import _ROJ_LOOKUP, _match_calendar_name

    roj: int | None = None
    normalized = ctx.text.strip().casefold()
    for row_id, title in ROJ_ROWS:
        if normalized in (row_id, title.casefold()):
            roj = int(row_id.split("_")[1])
            break
    if roj is None:
        roj = _match_calendar_name(normalized, _ROJ_LOOKUP)
    if roj is None:
        return "invalid", {}, [_roj_flow_prompt(ctx, "Please select a Roj.")]

    message = _mah_flow_prompt(ctx, f"Roj {ROJ_NAMES[roj - 1]}. Which Mah?")
    return "need_mah", {"pending_roj": roj}, [message]
