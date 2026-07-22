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
class OutgoingMessage:
    to: str  # recipient phone, E.164
    text: str
    buttons: list[Button] = field(default_factory=list)
    sections: list[ListSection] = field(default_factory=list)

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
        }


@dataclass(frozen=True)
class ParsedName:
    title: str  # ervad | behdin | osta | osti | khud
    name: str
    departed: bool = False
