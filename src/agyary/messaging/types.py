"""Message shapes exchanged with the messaging layer.

Mirrors WhatsApp Cloud API interactive-message limits so a future WhatsApp
transport can send these verbatim: at most 3 buttons per message, at most
10 rows per list section.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Button:
    id: str
    title: str  # WhatsApp cap: 20 chars


@dataclass(frozen=True)
class ListRow:
    id: str
    title: str  # WhatsApp cap: 24 chars
    description: str | None = None  # WhatsApp cap: 72 chars


@dataclass(frozen=True)
class ListSection:
    title: str
    rows: list[ListRow]


@dataclass(frozen=True)
class FlowPrompt:
    """A WhatsApp Flow launch, for any closed-vocabulary picker that can
    exceed the interactive list message's real 10-row-total cap - and in
    practice for any closed-vocabulary picker at all: tap-to-select,
    never free text/fuzzy matching.

    ``flow_id`` and ``flow_token`` are Meta/registration and per-request
    concerns respectively - callers get flow_id from Settings (module 2's
    Flows are registered out-of-band, see wa_flows.py) and mint flow_token
    themselves (wa_flows.make_flow_token). ``data`` is the initial screen
    data payload (WhatsApp Flows doc: "flow_action_payload.data must be a
    non-empty object").
    """

    flow_id: str
    flow_token: str
    flow_cta: str  # advised <=30 chars, no emoji
    screen: str
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class OutgoingMessage:
    to: str  # recipient phone, E.164
    text: str
    buttons: list[Button] = field(default_factory=list)
    sections: list[ListSection] = field(default_factory=list)
    flow: FlowPrompt | None = None

    def as_dict(self) -> dict:
        return {
            "to": self.to,
            "text": self.text,
            "buttons": [{"id": b.id, "title": b.title} for b in self.buttons],
            "sections": [
                {
                    "title": s.title,
                    "rows": [
                        {"id": r.id, "title": r.title, "description": r.description}
                        for r in s.rows
                    ],
                }
                for s in self.sections
            ],
            "flow": (
                {
                    "flow_id": self.flow.flow_id,
                    "flow_token": self.flow.flow_token,
                    "flow_cta": self.flow.flow_cta,
                    "screen": self.flow.screen,
                    "data": self.flow.data,
                }
                if self.flow
                else None
            ),
        }


@dataclass(frozen=True)
class ParsedName:
    title: str  # ervad | behdin | osta | osti | khud
    name: str
    departed: bool = False
