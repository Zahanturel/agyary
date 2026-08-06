"""General service booking flow (time-based: jashan, navjote, satum, ...).

Steps: select_service -> select_purpose -> select_date [-> select_mah |
confirm_date] -> select_time [-> select_location -> enter_location]
-> offer_saved_pairs -> enter_pair_names -> offer_saved_farmayeshne
-> enter_farmayeshne -> confirm.

Name sections per v2: 'pair' names adapted by purpose, then 'farmayeshne'
(single living names, always present for non-machi services).
"""

from __future__ import annotations

from datetime import date, datetime, time

from agyary.core.config import get_settings
from agyary.messaging import booking_service, wa_flows
from agyary.messaging.date_parser import parse_time_input
from agyary.messaging.flows import date_steps
from agyary.messaging.flows.base import FlowContext, matched_option, split_done_lines
from agyary.messaging.formatting import (
    PURPOSE_DISPLAY,
    PURPOSE_SHORT,
    date_label,
    name_line,
    names_block,
)
from agyary.messaging.geh_times import IST
from agyary.messaging.mobed_calendar import has_calendar_conflict
from agyary.messaging.name_parser import parse_names, parse_pair_line
from agyary.messaging.types import Button, FlowPrompt, OutgoingMessage
from agyary.models import BookingMobed, User

FLOW = "service_booking"

TITLE_HELP = "Titles: Ervad, Behdin, Osta, Osti, Khud"

PAIR_LINE_HELP = (
    "One pair per line, either:\n"
    "  Er. Zahan, Er. Meherzad\n"
    "  Behdin Roshan Behdin Dinshaw"
)

PAIR_PROMPTS = {
    "gujrela_nu": (
        "Please send the departed names, one pair per line:\n\n"
        + PAIR_LINE_HELP
        + "\n\n"
        + TITLE_HELP
        + "\n\nWhen you're done, send 'done'."
    ),
    "khushali_nu": (
        "Please send the pair names, one pair per line. They may be living "
        "or departed - add (D) for departed:\n\n"
        + PAIR_LINE_HELP
        + "\n\n"
        + TITLE_HELP
        + "\n\nWhen you're done, send 'done'."
    ),
    "hama_anjuman": (
        "You may add pairs (living or departed, add (D) for departed), one "
        "pair per line - or send 'skip' if none:\n\n"
        + PAIR_LINE_HELP
        + "\n\n"
        + TITLE_HELP
        + "\n\nWhen you're done, send 'done'."
    ),
}

FARMAYESHNE_PROMPT = (
    "Now the Farmayeshne - the living names of your family, one per line:\n\n"
    "  Behdin Jaidev\n"
    "  Osti Farzin\n"
    "  Khud Zhian\n\n"
    "When you're done, send 'done'."
)


async def start(ctx: FlowContext, prefill: dict | None = None) -> list[OutgoingMessage]:
    data = dict(prefill or {})
    if data.get("service_id"):
        await ctx.set_state(FLOW, "select_date", data)
        return [_date_prompt(ctx, data)]
    services = await booking_service.list_services(ctx.db, ctx.agyary.id)
    if not services:
        await ctx.clear_state()
        return [ctx.reply("No services are configured yet. Please contact the agyary.")]
    await ctx.set_state(FLOW, "select_service", data)
    settings = get_settings()
    return [
        ctx.reply(
            "Which service would you like to book?",
            flow=FlowPrompt(
                flow_id=settings.whatsapp_flow_id_services_picker,
                flow_token=wa_flows.make_flow_token(wa_flows.PURPOSE_SERVICES_PICKER, ctx.agyary.id),
                flow_cta="Choose",
                screen="PICK_SERVICE",
                data={},
            ),
        )
    ]


def _date_prompt(ctx: FlowContext, data: dict) -> OutgoingMessage:
    return ctx.reply(
        f"When would you like the {data.get('service_name', 'service')}?\n\n"
        + date_steps.DATE_HELP
    )


async def handle(ctx: FlowContext) -> list[OutgoingMessage]:
    handlers = {
        "select_service": _step_select_service,
        "select_purpose": _step_select_purpose,
        "select_date": _step_select_date,
        "select_mah": _step_select_mah,
        "select_roj": _step_select_roj,
        "confirm_date": _step_confirm_date,
        "select_time": _step_select_time,
        "select_location": _step_select_location,
        "enter_location": _step_enter_location,
        "offer_saved_pairs": _step_offer_saved_pairs,
        "enter_pair_names": _step_enter_pair_names,
        "offer_saved_farmayeshne": _step_offer_saved_farmayeshne,
        "enter_farmayeshne": _step_enter_farmayeshne,
        "select_priest": _step_select_priest,
        "confirm": _step_confirm,
    }
    handler = handlers.get(ctx.state.step)
    if handler is None:
        await ctx.clear_state()
        return [ctx.reply("Sorry, something went wrong. Send any message to start over.")]
    return await handler(ctx)


async def _step_select_service(ctx: FlowContext) -> list[OutgoingMessage]:
    services = await booking_service.list_services(ctx.db, ctx.agyary.id)
    options = {f"svc_{s.id}": [s.name] for s in services}
    choice = matched_option(ctx.text, options)
    if choice is None:
        return [ctx.reply("Please select a service from the list above.")]
    service = next(s for s in services if f"svc_{s.id}" == choice)

    data = ctx.data
    data.update(
        service_id=service.id,
        service_name=service.name,
        offsite_capable=service.offsite_capable,
        default_price=str(service.default_price) if service.default_price is not None else None,
    )
    await ctx.set_state(FLOW, "select_purpose", data)
    return [
        ctx.reply(
            f"{service.name} - what is the occasion?",
            buttons=[
                Button(id="purpose_gujrela_nu", title="Gujrela nu"),
                Button(id="purpose_khushali_nu", title="Khushali nu"),
                Button(id="purpose_hama_anjuman", title="Hama Anjuman"),
            ],
        )
    ]


async def _step_select_purpose(ctx: FlowContext) -> list[OutgoingMessage]:
    choice = matched_option(
        ctx.text,
        {
            "purpose_gujrela_nu": ["gujrela nu", "gujrela", "for the departed"],
            "purpose_khushali_nu": ["khushali nu", "khushali", "for happiness"],
            "purpose_hama_anjuman": ["hama anjuman", "hama", "for the community"],
        },
    )
    if choice is None:
        return [
            ctx.reply(
                "Please choose the occasion:",
                buttons=[
                    Button(id="purpose_gujrela_nu", title="Gujrela nu"),
                    Button(id="purpose_khushali_nu", title="Khushali nu"),
                    Button(id="purpose_hama_anjuman", title="Hama Anjuman"),
                ],
            )
        ]
    data = ctx.data
    data["purpose"] = choice.removeprefix("purpose_")
    await ctx.set_state(FLOW, "select_date", data)
    return [_date_prompt(ctx, data)]


def _today(ctx: FlowContext) -> date:
    return datetime.now(IST).date()


async def _step_select_date(ctx: FlowContext) -> list[OutgoingMessage]:
    status, updates, messages = date_steps.resolve_date_text(ctx, _today(ctx))
    data = {**ctx.data, **updates}
    if status == "resolved":
        return await _ask_time(ctx, data)
    next_step = {
        "need_mah": "select_mah",
        "need_roj": "select_roj",
        "confirm_date": "confirm_date",
    }.get(status, "select_date")
    await ctx.set_state(FLOW, next_step, data)
    return messages


async def _step_select_mah(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    status, updates, messages = date_steps.resolve_mah_selection(
        ctx, data.get("pending_roj", 1), _today(ctx)
    )
    if status == "resolved":
        data.update(updates)
        data.pop("pending_roj", None)
        return await _ask_time(ctx, data)
    return messages


async def _step_select_roj(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    status, updates, messages = date_steps.resolve_roj_selection(ctx)
    if status == "need_mah":
        data.update(updates)
        await ctx.set_state(FLOW, "select_mah", data)
    return messages


async def _step_confirm_date(ctx: FlowContext) -> list[OutgoingMessage]:
    choice = matched_option(
        ctx.text,
        {"date_confirm": ["yes", "yes, correct", "correct"], "date_retry": ["no", "no, different date"]},
    )
    data = ctx.data
    if choice == "date_confirm" and data.get("pending_date"):
        data.update(data.pop("pending_date"))
        return await _ask_time(ctx, data)
    if choice == "date_retry":
        data.pop("pending_date", None)
        await ctx.set_state(FLOW, "select_date", data)
        return [_date_prompt(ctx, data)]
    return [
        ctx.reply(
            "Please confirm the date.",
            buttons=[
                Button(id="date_confirm", title="Yes, correct"),
                Button(id="date_retry", title="No, different date"),
            ],
        )
    ]


async def _ask_time(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    await ctx.set_state(FLOW, "select_time", data)
    return [ctx.reply("What time? (e.g. '10:30 am' or '16:00')")]


async def _step_select_time(ctx: FlowContext) -> list[OutgoingMessage]:
    parsed: time | None = parse_time_input(ctx.text)
    if parsed is None:
        return [ctx.reply("Sorry, I didn't understand the time. Try '10:30 am' or '16:00'.")]
    data = ctx.data
    candidate = datetime.combine(date.fromisoformat(data["gregorian"]), parsed, tzinfo=IST)
    if candidate <= datetime.now(IST):
        return [
            ctx.reply(
                f"{parsed.strftime('%I:%M %p').lstrip('0')} has already passed today. "
                "Please send a future time."
            )
        ]
    data["time"] = parsed.strftime("%H:%M")
    if data.get("offsite_capable"):
        await ctx.set_state(FLOW, "select_location", data)
        return [
            ctx.reply(
                "Where will the ceremony take place?",
                buttons=[
                    Button(id="loc_agyary", title="At the agyary"),
                    Button(id="loc_offsite", title="Another location"),
                ],
            )
        ]
    data["is_offsite"] = False
    data["location"] = None
    return await _begin_pair_phase(ctx, data)


async def _step_select_location(ctx: FlowContext) -> list[OutgoingMessage]:
    choice = matched_option(
        ctx.text,
        {
            "loc_agyary": ["at the agyary", "agyary"],
            "loc_offsite": ["another location", "offsite", "home"],
        },
    )
    data = ctx.data
    if choice == "loc_agyary":
        data["is_offsite"] = False
        data["location"] = None
        return await _begin_pair_phase(ctx, data)
    if choice == "loc_offsite":
        await ctx.set_state(FLOW, "enter_location", data)
        return [ctx.reply("Please send the full address.")]
    return [
        ctx.reply(
            "Please choose:",
            buttons=[
                Button(id="loc_agyary", title="At the agyary"),
                Button(id="loc_offsite", title="Another location"),
            ],
        )
    ]


async def _step_enter_location(ctx: FlowContext) -> list[OutgoingMessage]:
    address = ctx.text.strip()
    if not address:
        return [ctx.reply("Please send the full address.")]
    data = ctx.data
    data["is_offsite"] = True
    data["location"] = address[:500]
    return await _begin_pair_phase(ctx, data)


# ---------------------------------------------------------------------------
# Pair-name section
# ---------------------------------------------------------------------------
async def _begin_pair_phase(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    if data.get("names"):  # rebook prefill: both sections already captured
        return await _begin_priest_phase(ctx, data)

    if data["purpose"] in ("gujrela_nu", "khushali_nu"):
        pairs = booking_service.complete_pairs(
            await booking_service.saved_pairs(
                ctx.db, ctx.customer.id, departed_only=data["purpose"] == "gujrela_nu"
            )
        )
        if pairs:
            data["saved_pairs_offer"] = booking_service.saved_rows_to_dicts(pairs, "pair")
            preview_lines = []
            grouped: dict[int | None, list] = {}
            for row in pairs:
                grouped.setdefault(row.pair_group, []).append(row)
            for members in list(grouped.values())[:3]:
                preview_lines.append(", ".join(name_line(m.title, m.name) for m in members))
            await ctx.set_state(FLOW, "offer_saved_pairs", data)
            return [
                ctx.reply(
                    "Use your saved pairs?\n\n" + "\n".join(preview_lines),
                    buttons=[
                        Button(id="names_saved_yes", title="Yes, use these"),
                        Button(id="names_new", title="Enter new names"),
                    ],
                )
            ]
    return await _prompt_pair_entry(ctx, data)


async def _prompt_pair_entry(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    data.pop("saved_pairs_offer", None)
    data["pending_pairs"] = []
    await ctx.set_state(FLOW, "enter_pair_names", data)
    return [ctx.reply(PAIR_PROMPTS[data["purpose"]])]


async def _step_offer_saved_pairs(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    choice = matched_option(
        ctx.text,
        {"names_saved_yes": ["yes", "yes, use these"], "names_new": ["enter new names", "new"]},
    )
    if choice == "names_saved_yes":
        data["pair_names"] = data.pop("saved_pairs_offer", [])
        data["pairs_from_saved"] = True
        return await _begin_farmayeshne_phase(ctx, data)
    if choice == "names_new":
        return await _prompt_pair_entry(ctx, data)
    return [
        ctx.reply(
            "Please choose:",
            buttons=[
                Button(id="names_saved_yes", title="Yes, use these"),
                Button(id="names_new", title="Enter new names"),
            ],
        )
    ]


def _pair_status(pair: list[dict], purpose: str) -> str:
    if purpose == "gujrela_nu":
        return "departed"
    # Keep each pair homogeneous: follow the first name of the pair.
    return "departed" if pair[0]["departed"] else "living"


def _finalize_pair_names(pending_pairs: list[list[dict]], purpose: str) -> list[dict]:
    pair_names = []
    for i, pair in enumerate(pending_pairs):
        status = _pair_status(pair, purpose)
        for n in pair:
            pair_names.append(
                {
                    "section": "pair",
                    "title": n["title"],
                    "name": n["name"],
                    "status": status,
                    "pair_group": i + 1,
                }
            )
    return pair_names


async def _step_enter_pair_names(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    purpose = data["purpose"]

    if purpose == "hama_anjuman" and ctx.text.strip().casefold() in ("skip", "none"):
        data["pair_names"] = []
        data["pairs_from_saved"] = False
        data.pop("pending_pairs", None)
        return await _begin_farmayeshne_phase(ctx, data)

    content_lines, is_done = split_done_lines(ctx.text)
    pending_pairs = data.get("pending_pairs", [])

    if content_lines:
        resolved = []
        for line in content_lines:
            pair = parse_pair_line(line)
            if pair is None:
                return [
                    ctx.reply(
                        f"Couldn't read this line as a pair: '{line.strip()}'. "
                        "Send two names per line, e.g. 'Ervad Zahan, Ervad "
                        "Meherzad' or 'Behdin Roshan Behdin Dinshaw'."
                    )
                ]
            resolved.append(pair)
        pending_pairs = pending_pairs + [
            [{"title": n.title, "name": n.name, "departed": n.departed} for n in pair]
            for pair in resolved
        ]
        data["pending_pairs"] = pending_pairs

    if is_done:
        if not pending_pairs:
            hint = " or 'skip'" if purpose == "hama_anjuman" else ""
            return [
                ctx.reply(f"Please send at least one pair first{hint}.")
            ]
        data["pair_names"] = _finalize_pair_names(pending_pairs, purpose)
        data["pairs_from_saved"] = False
        data.pop("pending_pairs", None)
        return await _begin_farmayeshne_phase(ctx, data)

    await ctx.set_state(FLOW, "enter_pair_names", data)
    if content_lines:
        added = "; ".join(
            f"{name_line(n1.title, n1.name)} & {name_line(n2.title, n2.name)}"
            for n1, n2 in resolved
        )
        count = len(pending_pairs)
        label = "Pair" if len(resolved) == 1 else "Pairs"
        return [
            ctx.reply(
                f"{label} added: {added} "
                f"({count} pair{'s' if count != 1 else ''} so far). "
                "Send more, or 'done'."
            )
        ]
    return [
        ctx.reply(
            "Please send two names per line, like 'Ervad Zahan, Ervad "
            "Meherzad'. Type 'done' when finished."
        )
    ]


# ---------------------------------------------------------------------------
# Farmayeshne section (always present for non-machi services)
# ---------------------------------------------------------------------------
async def _begin_farmayeshne_phase(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    saved = await booking_service.saved_farmayeshne(ctx.db, ctx.customer.id)
    living = [r for r in saved if r.status == "living"]
    if living:
        data["saved_farm_offer"] = booking_service.saved_rows_to_dicts(living, "farmayeshne")
        preview = "\n".join(name_line(r.title, r.name) for r in living[:5])
        if len(living) > 5:
            preview += f"\n... and {len(living) - 5} more"
        await ctx.set_state(FLOW, "offer_saved_farmayeshne", data)
        return [
            ctx.reply(
                f"Use your saved Farmayeshne names?\n\n{preview}",
                buttons=[
                    Button(id="names_saved_yes", title="Yes, use these"),
                    Button(id="names_new", title="Enter new names"),
                ],
            )
        ]
    return await _prompt_farmayeshne_entry(ctx, data)


async def _prompt_farmayeshne_entry(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    data.pop("saved_farm_offer", None)
    data["pending_names"] = []
    await ctx.set_state(FLOW, "enter_farmayeshne", data)
    return [ctx.reply(FARMAYESHNE_PROMPT)]


async def _step_offer_saved_farmayeshne(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    choice = matched_option(
        ctx.text,
        {"names_saved_yes": ["yes", "yes, use these"], "names_new": ["enter new names", "new"]},
    )
    if choice == "names_saved_yes":
        data["farmayeshne_names"] = data.pop("saved_farm_offer", [])
        data["farm_from_saved"] = True
        return await _finalize_names(ctx, data)
    if choice == "names_new":
        return await _prompt_farmayeshne_entry(ctx, data)
    return [
        ctx.reply(
            "Please choose:",
            buttons=[
                Button(id="names_saved_yes", title="Yes, use these"),
                Button(id="names_new", title="Enter new names"),
            ],
        )
    ]


async def _step_enter_farmayeshne(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    content_lines, is_done = split_done_lines(ctx.text)
    parsed = parse_names("\n".join(content_lines))

    pending = data.get("pending_names", [])
    pending.extend(
        {
            "section": "farmayeshne",
            "title": n.title,
            "name": n.name,
            "status": "living",  # farmayeshne names are living by definition
            "pair_group": None,
        }
        for n in parsed
    )
    data["pending_names"] = pending

    if is_done:
        if not pending:
            return [ctx.reply("Farmayeshne needs at least one name. Please send a name first.")]
        data["farmayeshne_names"] = pending
        data.pop("pending_names", None)
        data["farm_from_saved"] = False
        return await _finalize_names(ctx, data)

    await ctx.set_state(FLOW, "enter_farmayeshne", data)
    if parsed:
        count = len(pending)
        return [ctx.reply(f"Got {count} name{'s' if count != 1 else ''}. Send more, or 'done'.")]
    return [
        ctx.reply(
            "Please enter names one per line, like 'Behdin Jaidev'. Type 'done' when finished."
        )
    ]


async def _finalize_names(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    data["names"] = data.get("pair_names", []) + data.get("farmayeshne_names", [])
    return await _begin_priest_phase(ctx, data)


# ---------------------------------------------------------------------------
# Choose who to book with
# ---------------------------------------------------------------------------
async def _begin_priest_phase(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    """"Choose who to book with" - shown by name only, never the word
    "mobed" (a mobed's wife or someone else may be running the account;
    doc 05 - this applies to every customer-facing string, not just this
    screen)."""
    priests = await booking_service.get_active_agyary_users(ctx.db, ctx.agyary.id)
    if not priests:
        # Not-yet-staffed agyari: nobody to route the request to. The
        # booking still goes through - the system never blocks the behdin
        # at input time - but no one will see an accept/decline prompt
        # until someone joins. A genuine bootstrapping edge case, not
        # solved here (out of scope for this redesign).
        data.pop("chosen_priest_id", None)
        return await _show_confirmation(ctx, data)
    if len(priests) == 1:
        # Don't make the single-priest agyari pick from a list of one.
        only = priests[0]
        data["chosen_priest_id"] = only.id
        data["chosen_priest_name"] = only.name
        data["chosen_priest_phone"] = only.phone
        return await _show_confirmation(ctx, data)
    await ctx.set_state(FLOW, "select_priest", data)
    settings = get_settings()
    return [
        ctx.reply(
            "Who would you like to book with?",
            flow=FlowPrompt(
                flow_id=settings.whatsapp_flow_id_priest_picker,
                flow_token=wa_flows.make_flow_token(wa_flows.PURPOSE_PRIEST_PICKER, ctx.agyary.id),
                flow_cta="Choose",
                screen="PICK_PRIEST",
                data={},
            ),
        )
    ]


async def _step_select_priest(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    text = ctx.text.strip().casefold()
    priest_id = None
    if text.startswith("priest_"):
        try:
            priest_id = int(text.removeprefix("priest_"))
        except ValueError:
            priest_id = None
    priest = await ctx.db.get(User, priest_id) if priest_id is not None else None
    if priest is None or not priest.is_active:
        return [ctx.reply("Please choose from the list.")]
    data["chosen_priest_id"] = priest.id
    data["chosen_priest_name"] = priest.name
    data["chosen_priest_phone"] = priest.phone
    return await _show_confirmation(ctx, data)


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------
async def _show_confirmation(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    gregorian = date.fromisoformat(data["gregorian"])
    when = f"{date_label(data['roj'], data['mah'], gregorian)}, {_time_display(data['time'])}"
    lines = [
        "Here's your booking summary:",
        "",
        f"{data['service_name']} - {PURPOSE_DISPLAY[data['purpose']]}",
        f"at {data['location'] if data.get('is_offsite') else ctx.agyary.name}",
        when,
        "",
        "Names:",
        names_block(data["names"]),
    ]
    if data.get("chosen_priest_name"):
        lines += [
            "",
            f"You'll be booking with {data['chosen_priest_name']} "
            f"({data['chosen_priest_phone']}).",
        ]
    await ctx.set_state(FLOW, "confirm", data)
    return [
        ctx.reply(
            "\n".join(lines),
            buttons=[
                Button(id="confirm_booking", title="Confirm"),
                Button(id="edit_booking", title="Edit names"),
                Button(id="cancel_flow", title="Cancel"),
            ],
        )
    ]


def _time_display(hhmm: str) -> str:
    hour, minute = (int(p) for p in hhmm.split(":"))
    return time(hour, minute).strftime("%I:%M %p").lstrip("0")


async def _step_confirm(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    choice = matched_option(
        ctx.text,
        {
            "confirm_booking": ["confirm", "yes"],
            "edit_booking": ["edit", "edit names"],
            "cancel_flow": ["cancel"],
        },
    )
    if choice == "cancel_flow":
        await ctx.clear_state()
        return [ctx.reply("No problem, nothing was booked. Message us anytime.")]
    if choice == "edit_booking":
        data["names"] = []
        data["pair_names"] = []
        data["farmayeshne_names"] = []
        return await _prompt_pair_entry(ctx, data)
    if choice != "confirm_booking":
        return [
            ctx.reply(
                "Please choose:",
                buttons=[
                    Button(id="confirm_booking", title="Confirm"),
                    Button(id="edit_booking", title="Edit names"),
                    Button(id="cancel_flow", title="Cancel"),
                ],
            )
        ]

    service = await booking_service.get_service_by_id(ctx.db, ctx.agyary.id, data["service_id"])
    if service is None:
        await ctx.clear_state()
        return [ctx.reply("That service is no longer available. Send any message to start over.")]

    gregorian = date.fromisoformat(data["gregorian"])
    hour, minute = (int(p) for p in data["time"].split(":"))
    ceremony_dt = datetime.combine(gregorian, time(hour, minute), tzinfo=IST)

    # No money/payment in this pass (doc 05).
    booking = await booking_service.create_booking_request(
        ctx.db,
        ctx.agyary,
        ctx.customer,
        service,
        ceremony_dt_local=ceremony_dt,
        purpose=data["purpose"],
        names=data["names"],
        location=data.get("location"),
        is_offsite=bool(data.get("is_offsite")),
        amount=None,
    )

    if data.get("pair_names") and not data.get("pairs_from_saved"):
        await booking_service.replace_saved_section(
            ctx.db, ctx.customer.id, "pair", data["pair_names"]
        )
    if data.get("farmayeshne_names") and not data.get("farm_from_saved"):
        await booking_service.replace_saved_section(
            ctx.db, ctx.customer.id, "farmayeshne", data["farmayeshne_names"]
        )

    # The chosen priest's own calendar is checked here, once the booking
    # exists (so we have a ceremony_datetime) but before clearing state -
    # never blocks creation, only flags the priest's own notification.
    priest_id = data.get("chosen_priest_id")
    conflict = False
    if priest_id is not None:
        ctx.db.add(BookingMobed(booking_id=booking.id, user_id=priest_id, status="assigned"))
        await ctx.db.flush()
        conflict = await has_calendar_conflict(ctx.db, priest_id, booking.ceremony_datetime)

    await ctx.clear_state()

    # Contact info both directions: the priest's notification below already
    # carries the customer's number; the customer gets the priest's number
    # right here, in the same message that confirms the request was sent.
    customer_lines = [f"Your {service.name} request has been sent to {ctx.agyary.name}."]
    if data.get("chosen_priest_name"):
        customer_lines.append(
            f"You can reach {data['chosen_priest_name']} directly at "
            f"{data['chosen_priest_phone']}."
        )
    messages = [ctx.reply("\n".join(customer_lines))]

    if priest_id is not None:
        priest_lines = [
            f"New {service.name} request at {ctx.agyary.name}:",
            "",
            f"Customer: {ctx.customer.name} ({ctx.customer.phone})",
            f"Purpose: {PURPOSE_SHORT[data['purpose']]}",
            f"{date_label(data['roj'], data['mah'], gregorian)}, {_time_display(data['time'])}",
        ]
        if data.get("is_offsite"):
            priest_lines.append(f"Location: {data['location']}")
        priest_lines += ["", "Names:", names_block(data["names"])]
        if conflict:
            priest_lines += [
                "",
                "Note: you already have something at this time - please check the app.",
            ]
        messages.append(
            OutgoingMessage(
                to=data["chosen_priest_phone"],
                text="\n".join(priest_lines),
                buttons=[
                    Button(id=f"approve_booking_{booking.id}", title="Accept"),
                    Button(id=f"decline_booking_{booking.id}", title="Decline"),
                ],
            )
        )
    return messages
