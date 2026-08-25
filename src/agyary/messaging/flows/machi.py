"""Machi booking flow (slot-based, purpose patet/tandarosti).

Steps: select_purpose -> select_date [-> select_mah | confirm_date]
-> select_geh [-> select_alternative] -> offer_saved_names -> enter_names
-> confirm.
"""

from __future__ import annotations

from datetime import date, datetime

from agyary.calendar import CalendarSystem, gregorian_to_parsi
from agyary.core.config import get_settings
from agyary.messaging import booking_service, wa_flows
from agyary.messaging.availability import (
    available_gehs,
    drop_elapsed_gehs,
    next_days_with_any_geh,
    parsi_slot_fields,
)
from agyary.messaging.flows import date_steps
from agyary.messaging.flows.base import FlowContext, matched_option, split_done_lines
from agyary.messaging.formatting import (
    PURPOSE_DISPLAY,
    PURPOSE_SHORT,
    date_label,
    geh_label,
    gregorian_label,
    name_line,
    names_block,
    parsi_label,
)
from agyary.messaging.geh_times import IST
from agyary.messaging.types import Button, FlowPrompt, ListRow, ListSection, OutgoingMessage
from agyary.models.enums import GEH_NAMES

FLOW = "machi_booking"
MAX_TANDAROSTI_NAMES = 15  # v2: soft limit, silently enforced

TITLE_HELP = "Titles: Ervad, Behdin, Osta, Osti, Khud"

PATET_PROMPT = (
    "Please send the departed pair for the Patet Machi - both names on one "
    "line:\n\n"
    "  Ervad Kaikhushru, Ervad Hormazd\n\n" + TITLE_HELP
)
TANDAROSTI_PROMPT = (
    "Please send the living names for the Tandarosti Machi, one per line:\n\n"
    "  Er. Zahan\n"
    "  Osti Farzin\n"
    "  Khud Zhian\n\n" + TITLE_HELP + "\n\nWhen you're done, send 'done'."
)


def _today(ctx: FlowContext) -> date:
    return datetime.now(IST).date()


async def start(ctx: FlowContext, prefill: dict | None = None) -> list[OutgoingMessage]:
    data = dict(prefill or {})
    if data.get("purpose"):
        await ctx.set_state(FLOW, "select_date", data)
        return [_date_prompt(ctx)]
    await ctx.set_state(FLOW, "select_purpose", data)
    return [
        ctx.reply(
            "Is this Machi for the departed or for the living?",
            buttons=[
                Button(id="purpose_patet", title="Patet (departed)"),
                Button(id="purpose_tandarosti", title="Tandarosti (living)"),
            ],
        )
    ]


def _date_prompt(ctx: FlowContext) -> OutgoingMessage:
    return ctx.reply("When would you like the Machi?\n\n" + date_steps.DATE_HELP)


async def handle(ctx: FlowContext) -> list[OutgoingMessage]:
    step = ctx.state.step
    handlers = {
        "select_purpose": _step_select_purpose,
        "select_date": _step_select_date,
        "select_mah": _step_select_mah,
        "select_roj": _step_select_roj,
        "confirm_date": _step_confirm_date,
        "select_geh": _step_select_geh,
        "select_alternative": _step_select_alternative,
        "offer_saved_names": _step_offer_saved_names,
        "enter_names": _step_enter_names,
        "confirm": _step_confirm,
    }
    handler = handlers.get(step)
    if handler is None:  # unknown step - restart cleanly
        await ctx.clear_state()
        return [ctx.reply("Sorry, something went wrong. Send any message to start over.")]
    return await handler(ctx)


async def _step_select_purpose(ctx: FlowContext) -> list[OutgoingMessage]:
    choice = matched_option(
        ctx.text,
        {
            "purpose_patet": ["patet", "patet (departed)", "departed", "for the departed"],
            "purpose_tandarosti": [
                "tandarosti",
                "tandarosti (living)",
                "living",
                "for the living",
            ],
        },
    )
    if choice is None:
        return [
            ctx.reply(
                "Please choose Patet or Tandarosti.",
                buttons=[
                    Button(id="purpose_patet", title="Patet (departed)"),
                    Button(id="purpose_tandarosti", title="Tandarosti (living)"),
                ],
            )
        ]
    data = ctx.data
    data["purpose"] = choice.removeprefix("purpose_")
    await ctx.set_state(FLOW, "select_date", data)
    return [_date_prompt(ctx)]


async def _step_select_date(ctx: FlowContext) -> list[OutgoingMessage]:
    status, updates, messages = date_steps.resolve_date_text(ctx, _today(ctx))
    data = {**ctx.data, **updates}
    if status == "resolved":
        return await _proceed_to_geh(ctx, data)
    if status == "need_mah":
        await ctx.set_state(FLOW, "select_mah", data)
        return messages
    if status == "need_roj":
        await ctx.set_state(FLOW, "select_roj", data)
        return messages
    if status == "confirm_date":
        await ctx.set_state(FLOW, "confirm_date", data)
        return messages
    await ctx.set_state(FLOW, "select_date", data)
    return messages


async def _step_select_mah(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    status, updates, messages = date_steps.resolve_mah_selection(
        ctx, data.get("pending_roj", 1), _today(ctx)
    )
    if status == "resolved":
        data.update(updates)
        data.pop("pending_roj", None)
        return await _proceed_to_geh(ctx, data)
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
        return await _proceed_to_geh(ctx, data)
    if choice == "date_retry":
        data.pop("pending_date", None)
        await ctx.set_state(FLOW, "select_date", data)
        return [_date_prompt(ctx)]
    return [
        ctx.reply(
            "Please confirm the date.",
            buttons=[
                Button(id="date_confirm", title="Yes, correct"),
                Button(id="date_retry", title="No, different date"),
            ],
        )
    ]


async def _proceed_to_geh(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    free = await available_gehs(
        ctx.db, ctx.agyary.id, data["roj"], data["mah"], data["year"]
    )
    gregorian = date.fromisoformat(data["gregorian"])
    free = drop_elapsed_gehs(free, gregorian)
    label = date_label(data["roj"], data["mah"], gregorian)

    if not free:
        await ctx.set_state(FLOW, "select_alternative", data)
        return [
            ctx.reply(
                f"No Gehs are available for {label}.",
                buttons=[
                    Button(id="alt_try_date", title="Try another date"),
                    Button(id="alt_next_any", title="Next available day"),
                    Button(id="alt_contact", title="Contact us"),
                ],
            )
        ]

    # Geh is a static Flow (all 5 options, values never change) - same
    # treatment as Roj/Mah: a closed vocabulary is tap-to-select. It isn't
    # filtered to just the currently-free gehs (unlike the old list
    # message): availability is re-checked after selection, the same way
    # a Roj/Mah combo can already resolve to zero free gehs today.
    await ctx.set_state(FLOW, "select_geh", data)
    settings = get_settings()
    return [
        ctx.reply(
            f"{label}\n\nWhich Geh would you like?",
            flow=FlowPrompt(
                flow_id=settings.whatsapp_flow_id_geh,
                flow_token=wa_flows.make_flow_token("geh", ctx.agyary.id),
                flow_cta="Select Geh",
                screen="SELECT_GEH",
                data={},
            ),
        )
    ]


async def _step_select_geh(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    geh_options = {f"geh_{g}": [name, f"{name} geh"] for g, name in GEH_NAMES.items()}
    choice = matched_option(ctx.text, geh_options)
    if choice is None:
        return [ctx.reply("Please select a Geh from the list above.")]
    geh = int(choice.split("_")[1])

    free = drop_elapsed_gehs(
        await available_gehs(ctx.db, ctx.agyary.id, data["roj"], data["mah"], data["year"]),
        date.fromisoformat(data["gregorian"]),
    )
    if geh not in free:
        return await _alternatives_for_taken_slot(ctx, data, geh)

    data["geh"] = geh
    return await _begin_names_phase(ctx, data)


def _alternatives_sections(
    data: dict, geh: int, same_day_gehs: list[int], same_geh_next_days: list
) -> list[ListSection]:
    gregorian = date.fromisoformat(data["gregorian"])
    same_day = [
        ListRow(
            id=f"altslot_{data['gregorian']}_{g}",
            title=f"{GEH_NAMES[g]} Geh",
            description=f"{parsi_label(data['roj'], data['mah'])} ({gregorian_label(gregorian)})"[:72],
        )
        for g in same_day_gehs
    ]
    same_geh = [
        ListRow(
            id=f"altslot_{option.gregorian.isoformat()}_{option.geh}",
            title=parsi_label(option.roj, option.mah)[:24],
            description=f"{geh_label(option.geh)} ({gregorian_label(option.gregorian)})"[:72],
        )
        for option in same_geh_next_days
    ]
    sections = []
    if same_day:
        sections.append(ListSection(title="Same day, different Geh", rows=same_day))
    if same_geh:
        sections.append(
            ListSection(title=f"Same Geh ({GEH_NAMES[geh]}), different day", rows=same_geh)
        )
    sections.append(
        ListSection(
            title="Other",
            rows=[
                ListRow(id="alt_cancel", title="Cancel"),
                ListRow(id="alt_contact", title="Contact us"),
            ],
        )
    )
    return sections


async def _render_taken_slot_alternatives(
    ctx: FlowContext,
    data: dict,
    geh: int,
    alternatives: booking_service.MachiSlotAlternatives,
) -> list[OutgoingMessage]:
    sections = _alternatives_sections(
        data, geh, alternatives.same_day_gehs, alternatives.same_geh_next_days
    )
    await ctx.set_state(FLOW, "select_alternative", data)
    return [
        ctx.reply(
            f"{geh_label(geh)} is booked on {parsi_label(data['roj'], data['mah'])}.\n\n"
            "Here are some alternatives:",
            sections=sections,
        )
    ]


async def _alternatives_for_taken_slot(
    ctx: FlowContext, data: dict, geh: int
) -> list[OutgoingMessage]:
    """Mid-flow re-check (geh selection / altslot navigation): not yet
    attempting to claim a slot, just showing what's free, so this computes
    fresh via the shared availability query rather than through
    book_machi_slot (that function claims a slot; this is only browsing)."""
    gregorian = date.fromisoformat(data["gregorian"])
    alternatives = await booking_service.compute_machi_alternatives(
        ctx.db, ctx.agyary, data["roj"], data["mah"], data["year"], geh, gregorian
    )
    return await _render_taken_slot_alternatives(ctx, data, geh, alternatives)


async def _step_select_alternative(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    text = ctx.text.strip().casefold()

    if text in ("alt_cancel", "cancel"):
        await ctx.clear_state()
        return [ctx.reply("No problem, your booking was cancelled. Message us anytime.")]
    if text in ("alt_contact", "contact us", "contact"):
        from agyary.messaging.flows.welcome import contact_message

        return await contact_message(ctx)
    if text in ("alt_try_date", "try another date"):
        await ctx.set_state(FLOW, "select_date", data)
        return [_date_prompt(ctx)]
    if text in ("alt_next_any", "next available day"):
        gregorian = date.fromisoformat(data["gregorian"])
        options = await next_days_with_any_geh(
            ctx.db, ctx.agyary.id, CalendarSystem(ctx.agyary.calendar_system), gregorian
        )
        if not options:
            return [ctx.reply("Sorry, no free days found in the next 3 months.")]
        rows = [
            ListRow(
                id=f"altday_{option.gregorian.isoformat()}",
                title=parsi_label(option.roj, option.mah)[:24],
                description=gregorian_label(option.gregorian),
            )
            for option in options
        ]
        return [
            ctx.reply(
                "The next days with an open Geh:",
                sections=[ListSection(title="Available days", rows=rows)],
            )
        ]

    if text.startswith("altday_"):
        try:
            gregorian = date.fromisoformat(text.removeprefix("altday_"))
        except ValueError:
            return [ctx.reply("Please choose one of the options above.")]
        system = CalendarSystem(ctx.agyary.calendar_system)
        roj, mah, year = parsi_slot_fields(gregorian_to_parsi(gregorian, system))
        data.update(date_steps.date_fields(roj, mah, year, gregorian))
        return await _proceed_to_geh(ctx, data)

    if text.startswith("altslot_"):
        try:
            _, iso, geh_raw = text.split("_")
            gregorian = date.fromisoformat(iso)
            geh = int(geh_raw)
        except ValueError:
            return [ctx.reply("Please choose one of the options above.")]
        if geh not in GEH_NAMES:
            return [ctx.reply("Please choose one of the options above.")]
        system = CalendarSystem(ctx.agyary.calendar_system)
        roj, mah, year = parsi_slot_fields(gregorian_to_parsi(gregorian, system))
        data.update(date_steps.date_fields(roj, mah, year, gregorian))
        free = drop_elapsed_gehs(
            await available_gehs(ctx.db, ctx.agyary.id, roj, mah, year), gregorian
        )
        if geh not in free:
            return await _alternatives_for_taken_slot(ctx, data, geh)
        data["geh"] = geh
        return await _begin_names_phase(ctx, data)

    return [ctx.reply("Please choose one of the options above.")]


# ---------------------------------------------------------------------------
# Names phase
# ---------------------------------------------------------------------------
async def _begin_names_phase(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    if data.get("names"):  # prefilled via rebook or edit-preserving path
        return await _show_confirmation(ctx, data)

    if data["purpose"] == "patet":
        pairs = booking_service.complete_pairs(
            await booking_service.saved_pairs(ctx.db, ctx.customer.id, departed_only=True)
        )
        first_pair = pairs[:2]
        if len(first_pair) == 2:
            data["saved_offer"] = booking_service.saved_rows_to_dicts(first_pair, "pair")
            preview = ", ".join(name_line(r.title, r.name) for r in first_pair)
            await ctx.set_state(FLOW, "offer_saved_names", data)
            return [
                ctx.reply(
                    f"Use your saved departed pair?\n\n{preview}",
                    buttons=[
                        Button(id="names_saved_yes", title="Yes, use these"),
                        Button(id="names_new", title="Enter new names"),
                    ],
                )
            ]
    else:
        saved = await booking_service.saved_farmayeshne(ctx.db, ctx.customer.id)
        living = [r for r in saved if r.status == "living"]
        if living:
            data["saved_offer"] = booking_service.saved_rows_to_dicts(living, "farmayeshne")
            preview = "\n".join(name_line(r.title, r.name) for r in living[:5])
            if len(living) > 5:
                preview += f"\n... and {len(living) - 5} more"
            await ctx.set_state(FLOW, "offer_saved_names", data)
            return [
                ctx.reply(
                    f"Use your saved names?\n\n{preview}",
                    buttons=[
                        Button(id="names_saved_yes", title="Yes, use these"),
                        Button(id="names_new", title="Enter new names"),
                    ],
                )
            ]

    return await _prompt_name_entry(ctx, data)


async def _prompt_name_entry(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    data.pop("saved_offer", None)
    data["pending_names"] = []
    await ctx.set_state(FLOW, "enter_names", data)
    prompt = PATET_PROMPT if data["purpose"] == "patet" else TANDAROSTI_PROMPT
    return [ctx.reply(prompt)]


async def _step_offer_saved_names(ctx: FlowContext) -> list[OutgoingMessage]:
    data = ctx.data
    choice = matched_option(
        ctx.text,
        {"names_saved_yes": ["yes", "yes, use these"], "names_new": ["enter new names", "new"]},
    )
    if choice == "names_saved_yes":
        saved = data.pop("saved_offer", [])
        if data["purpose"] == "patet":
            names = [
                {**n, "section": "pair", "status": "departed", "pair_group": 1} for n in saved[:2]
            ]
        else:
            # Tandarosti names are the living family the machi is for, which
            # is what 'farmayeshne' means - and is already the section they
            # were saved under in the pool these are being read back from.
            names = [
                {**n, "section": "farmayeshne", "status": "living", "pair_group": None}
                for n in saved[:MAX_TANDAROSTI_NAMES]
            ]
        data["names"] = names
        data["names_from_saved"] = True
        return await _show_confirmation(ctx, data)
    if choice == "names_new":
        return await _prompt_name_entry(ctx, data)
    return [
        ctx.reply(
            "Please choose:",
            buttons=[
                Button(id="names_saved_yes", title="Yes, use these"),
                Button(id="names_new", title="Enter new names"),
            ],
        )
    ]


async def _step_enter_names(ctx: FlowContext) -> list[OutgoingMessage]:
    from agyary.messaging.name_parser import parse_names, parse_pair_line

    data = ctx.data

    if data["purpose"] == "patet":
        content_lines, _ = split_done_lines(ctx.text)
        if len(content_lines) != 1:
            return [
                ctx.reply(
                    "A Patet Machi takes exactly one departed pair - send "
                    "both names on one line, e.g. 'Ervad Kaikhushru, Ervad "
                    "Hormazd'."
                )
            ]
        pair = parse_pair_line(content_lines[0])
        if pair is None:
            return [
                ctx.reply(
                    f"Couldn't read this line as a pair: '{content_lines[0].strip()}'. "
                    "Send two names on one line, e.g. 'Ervad Zahan, Ervad "
                    "Meherzad' or 'Behdin Roshan Behdin Dinshaw'."
                )
            ]
        data["names"] = [
            {
                "section": "pair",
                "title": n.title,
                "name": n.name,
                "status": "departed",  # patet names are departed by definition
                "pair_group": 1,
            }
            for n in pair
        ]
        data["names_from_saved"] = False
        return await _show_confirmation(ctx, data)

    # Tandarosti: accumulate until 'done'
    content_lines, is_done = split_done_lines(ctx.text)
    parsed = parse_names("\n".join(content_lines))
    pending = data.get("pending_names", [])
    pending.extend(
        {
            "section": "farmayeshne",  # living names of the family, not a pair
            "title": n.title,
            "name": n.name,
            "status": "living",
            "pair_group": None,
        }
        for n in parsed
    )
    pending = pending[:MAX_TANDAROSTI_NAMES]  # soft limit, silently enforced
    data["pending_names"] = pending

    if is_done:
        if not pending:
            return [ctx.reply("Please send at least one name before 'done'.")]
        data["names"] = pending
        data.pop("pending_names", None)
        data["names_from_saved"] = False
        return await _show_confirmation(ctx, data)

    await ctx.set_state(FLOW, "enter_names", data)
    if parsed:
        count = len(pending)
        return [ctx.reply(f"Got {count} name{'s' if count != 1 else ''}. Send more, or 'done'.")]
    return [
        ctx.reply(
            "Please enter names one per line, like 'Ervad Meherzad'. "
            "Type 'done' when finished."
        )
    ]


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------
async def _show_confirmation(ctx: FlowContext, data: dict) -> list[OutgoingMessage]:
    # No money/payment in this pass - machi confirmation never showed a
    # price, and the eventual booking never records an amount either.
    gregorian = date.fromisoformat(data["gregorian"])
    lines = [
        "Here's your booking summary:",
        "",
        f"Machi - {PURPOSE_DISPLAY[data['purpose']]}",
        f"at {ctx.agyary.name}",
        date_label(data["roj"], data["mah"], gregorian),
        geh_label(data["geh"]),
        "",
        "Names:",
        names_block(data["names"]),
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
        return await _prompt_name_entry(ctx, data)
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

    gregorian = date.fromisoformat(data["gregorian"])

    # Machi is fully automatic: no approval gate, no human in the loop.
    # book_machi_slot (module 1's shared core) owns the entire "is this
    # slot valid, is it free, claim it, what are the alternatives if not"
    # decision - re-checked fresh here (including the elapsed-geh past
    # check), not just relying on the unique-index race exception, so a
    # slot that quietly elapsed while the customer was typing names can't
    # silently get booked in the past.
    result = await booking_service.book_machi_slot(
        ctx.db,
        ctx.agyary,
        ctx.customer,
        roj=data["roj"],
        mah=data["mah"],
        year=data["year"],
        geh=data["geh"],
        gregorian=gregorian,
        purpose=data["purpose"],
        names=data["names"],
    )
    if result.machi is None:
        return await _render_taken_slot_alternatives(ctx, data, data["geh"], result.alternatives)

    # Update the saved pool only with freshly typed names ('New set' replaces).
    if not data.get("names_from_saved"):
        if data["purpose"] == "patet":
            await booking_service.replace_saved_section(
                ctx.db, ctx.customer.id, "pair", data["names"]
            )
        else:
            pool_names = [
                {**n, "section": "farmayeshne", "status": "living", "pair_group": None}
                for n in data["names"]
            ]
            await booking_service.replace_saved_section(
                ctx.db, ctx.customer.id, "farmayeshne", pool_names
            )

    await ctx.clear_state()

    messages = [
        ctx.reply(
            f"Your Machi ({PURPOSE_SHORT[data['purpose']]}) at {ctx.agyary.name} is "
            f"confirmed for {date_label(data['roj'], data['mah'], gregorian)}, "
            f"{geh_label(data['geh'])}."
        )
    ]
    fyi_text = "\n".join(
        [
            f"New Machi booked at {ctx.agyary.name}:",
            "",
            f"{ctx.customer.name} ({ctx.customer.phone})",
            f"Purpose: {PURPOSE_SHORT[data['purpose']]}",
            date_label(data["roj"], data["mah"], gregorian),
            geh_label(data["geh"]),
            "",
            "Names:",
            names_block(data["names"]),
        ]
    )
    # Every active member at the agyary, not just ADMIN_ROLES - a
    # peer-mobed agyari has no panthaky/caretaker to notify, and this is
    # informational only (no button, no gate) so there's no reason to
    # narrow the recipient list the way an approval request would.
    for member in await booking_service.get_active_agyary_users(ctx.db, ctx.agyary.id):
        messages.append(OutgoingMessage(to=member.phone, text=fyi_text))
    return messages
