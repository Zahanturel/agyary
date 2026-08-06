"""Shared flow plumbing: the per-message context and option matching."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from agyary.messaging import state as state_store
from agyary.messaging.types import Button, FlowPrompt, ListSection, OutgoingMessage
from agyary.models import Agyary, ConversationState, Customer


@dataclass
class FlowContext:
    db: AsyncSession
    agyary: Agyary
    customer: Customer
    phone: str
    text: str
    state: ConversationState | None = None

    @property
    def data(self) -> dict:
        # Deep copy: flows freely mutate nested lists (e.g. pending_names).
        # A shallow copy would mutate SQLAlchemy's committed JSONB value in
        # place, making old == new on flush and silently skipping the UPDATE.
        return copy.deepcopy(dict(self.state.data)) if self.state else {}

    async def set_state(self, flow: str, step: str, data: dict) -> None:
        self.state = await state_store.set_state(
            self.db, self.agyary.id, self.phone, flow, step, data
        )

    async def clear_state(self) -> None:
        await state_store.clear_state(self.db, self.agyary.id, self.phone)
        self.state = None

    def reply(
        self,
        text: str,
        buttons: list[Button] | None = None,
        sections: list[ListSection] | None = None,
        flow: FlowPrompt | None = None,
    ) -> OutgoingMessage:
        return OutgoingMessage(
            to=self.phone, text=text, buttons=buttons or [], sections=sections or [], flow=flow
        )


def matched_option(text: str, options: dict[str, list[str]]) -> str | None:
    """Match inbound text against option ids and their human-typed synonyms.

    ``options`` maps option id -> list of accepted phrasings (the id itself
    always matches, so button taps that send the raw id resolve directly).
    """
    normalized = text.strip().casefold()
    for option_id, synonyms in options.items():
        if normalized == option_id.casefold():
            return option_id
        if any(normalized == s.casefold() for s in synonyms):
            return option_id
    return None


def is_done_line(line: str) -> bool:
    """'done', 'Done.', 'done!' all terminate name accumulation."""
    return line.strip().strip(".!,").casefold() == "done"


def split_done_lines(text: str) -> tuple[list[str], bool]:
    """Split a message into its non-blank, non-'done' lines, plus whether a
    'done' line was present anywhere in it (accumulate-until-'done' steps
    share this: farmayeshne, tandarosti, and pair-name entry)."""
    lines = text.splitlines()
    is_done = any(is_done_line(line) for line in lines)
    content = [line for line in lines if line.strip() and not is_done_line(line)]
    return content, is_done
