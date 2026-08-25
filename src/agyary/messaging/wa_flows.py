"""WhatsApp Flow JSON builders.

Any closed-vocabulary picker that can
exceed the interactive list message's real 10-row-total cap (confirmed
against Meta's docs during planning - not 10-per-section, as the older
`chunk_rows` helper in `flows/base.py` assumed) becomes a WhatsApp Flow with
a predefined Dropdown - tap to select, no free text, no fuzzy matching.

Two genuinely different amounts of work:
  - Roj/Mah/Geh: static. Values never change, baked directly into the Flow
    JSON below. No live endpoint, no encryption.
  - Priest picker / per-agyari Services list: dynamic. Per-tenant, change
    over time, need a real data-exchange endpoint (see `wa_flows_crypto.py`
    and the route in `api/routes/whatsapp.py`) returning the current
    options, encrypted per Meta's Flows Data Exchange spec.

Both read from the same canonical option source the rest of the codebase
already uses (`agyary.calendar` ROJ_NAMES/MAH_NAMES, `models.enums.GEH_NAMES`)
- never a second hardcoded copy, per the same "one shared source" rule
already applied to the machi slot-check and the name-lookup.

Shape verified against Meta's Flow JSON reference
(`developers.facebook.com/docs/whatsapp/flows/reference/flowjson`, fetched
directly while building this module) for the top-level `version`/`screens`
structure, the `Dropdown` component's fields (`name`, `label`,
`data-source`, `required`), and the `Footer` completion action
(`on-click-action: {"name": "complete", "payload": {...}}`). Whether this
exact JSON validates against Meta's Flow Builder cannot be checked from
this environment (no live Meta Business Account) - run it through the
Flow Builder's JSON validator before registering for real.
"""

from __future__ import annotations

import uuid

from agyary.calendar import MAH_NAMES, ROJ_NAMES
from agyary.models.enums import GEH_NAMES

FLOW_JSON_VERSION = "3.1"

# Purpose tags embedded in flow_token (make_flow_token/parse_flow_token),
# used by the data-exchange endpoint to know which dynamic option list to
# resolve and return.
PURPOSE_PRIEST_PICKER = "priest_picker"
PURPOSE_SERVICES_PICKER = "services_picker"


def make_flow_token(purpose: str, agyary_id: int) -> str:
    """Mint an opaque per-request flow_token carrying enough context for the
    data-exchange endpoint (dynamic Flows) or the nfm_reply router (all
    Flows) to know what this completion is for. Not secret - agyary_id
    isn't sensitive - just structured.
    """
    return f"{purpose}:{agyary_id}:{uuid.uuid4().hex}"


def parse_flow_token(token: str) -> tuple[str, int, str]:
    purpose, agyary_id, nonce = token.split(":", 2)
    return purpose, int(agyary_id), nonce


def _single_dropdown_screen(screen_id: str, title: str, field_name: str, options: list[dict]) -> dict:
    """A static, single-screen Flow: one Dropdown, one Footer that submits
    the selection and completes the Flow. Used for Roj/Mah/Geh - the option
    list is baked in directly, no data-exchange round trip.
    """
    return {
        "version": FLOW_JSON_VERSION,
        "screens": [
            {
                "id": screen_id,
                "title": title,
                "terminal": True,
                "layout": {
                    "type": "SingleColumnLayout",
                    "children": [
                        {
                            "type": "Form",
                            "name": "form",
                            "children": [
                                {
                                    "type": "Dropdown",
                                    "name": field_name,
                                    "label": title,
                                    "required": True,
                                    "data-source": options,
                                },
                                {
                                    "type": "Footer",
                                    "label": "Continue",
                                    "on-click-action": {
                                        "name": "complete",
                                        "payload": {field_name: f"${{form.{field_name}}}"},
                                    },
                                },
                            ],
                        }
                    ],
                },
            }
        ],
    }


def roj_options() -> list[dict]:
    """The canonical Roj option list - the one source both the static
    WhatsApp Flow below and the PWA's <select> dropdown (module 6) read
    from. One list, never two independently-hardcoded copies."""
    return [{"id": f"roj_{i + 1}", "title": name} for i, name in enumerate(ROJ_NAMES)]


def mah_options() -> list[dict]:
    return [{"id": f"mah_{i + 1}", "title": name} for i, name in enumerate(MAH_NAMES)]


def geh_options() -> list[dict]:
    return [{"id": f"geh_{geh}", "title": name} for geh, name in GEH_NAMES.items()]


def build_roj_flow_json() -> dict:
    return _single_dropdown_screen("SELECT_ROJ", "Select Roj", "roj", roj_options())


def build_mah_flow_json() -> dict:
    return _single_dropdown_screen("SELECT_MAH", "Select Mah", "mah", mah_options())


def build_geh_flow_json() -> dict:
    return _single_dropdown_screen("SELECT_GEH", "Select Geh", "geh", geh_options())


def build_dynamic_picker_flow_json(screen_id: str, title: str, field_name: str) -> dict:
    """A dynamic, single-screen Flow template: the Dropdown's data-source is
    NOT baked in here - it's resolved per-request by the data-exchange
    endpoint (see `api/routes/whatsapp.py`), keyed off the data bound at
    init time (`${data.options}`). Used for the priest picker and each
    agyari's Services list - both per-tenant, both can exceed 10 options.
    """
    return {
        "version": FLOW_JSON_VERSION,
        "data_api_version": "3.0",
        "screens": [
            {
                "id": screen_id,
                "title": title,
                "terminal": True,
                "data": {
                    "options": {
                        "type": "array",
                        "items": {"type": "object", "properties": {"id": {"type": "string"}, "title": {"type": "string"}}},
                        "__example__": [],
                    }
                },
                "layout": {
                    "type": "SingleColumnLayout",
                    "children": [
                        {
                            "type": "Form",
                            "name": "form",
                            "children": [
                                {
                                    "type": "Dropdown",
                                    "name": field_name,
                                    "label": title,
                                    "required": True,
                                    "data-source": "${data.options}",
                                },
                                {
                                    "type": "Footer",
                                    "label": "Continue",
                                    "on-click-action": {
                                        "name": "complete",
                                        "payload": {field_name: f"${{form.{field_name}}}"},
                                    },
                                },
                            ],
                        }
                    ],
                },
            }
        ],
    }
