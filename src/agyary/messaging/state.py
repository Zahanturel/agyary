"""Conversation state persistence (Postgres-backed, 30-minute TTL).

One active flow per (agyary, phone) enforced by the unique constraint.
No "session expired" messages: an expired state is silently dropped and the
customer's next message gets a fresh welcome menu.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.models import ConversationState

STATE_TTL = timedelta(minutes=30)


async def load_state(db: AsyncSession, agyary_id: int, phone: str) -> ConversationState | None:
    result = await db.execute(
        select(ConversationState).where(
            ConversationState.agyary_id == agyary_id,
            ConversationState.phone == phone,
        )
    )
    state = result.scalar_one_or_none()
    if state and state.expires_at < datetime.now(UTC):
        await db.delete(state)
        await db.flush()
        return None
    return state


async def set_state(
    db: AsyncSession, agyary_id: int, phone: str, flow: str, step: str, data: dict
) -> ConversationState:
    """UPSERT the single conversation slot for this customer at this agyary."""
    state = await load_state(db, agyary_id, phone)
    if state is None:
        state = ConversationState(
            agyary_id=agyary_id,
            phone=phone,
            flow=flow,
            step=step,
            data=data,
            expires_at=datetime.now(UTC) + STATE_TTL,
        )
        db.add(state)
    else:
        state.flow = flow
        state.step = step
        state.data = dict(data)  # new dict so the JSONB change is detected
        state.expires_at = datetime.now(UTC) + STATE_TTL
    await db.flush()
    return state


async def clear_state(db: AsyncSession, agyary_id: int, phone: str) -> None:
    result = await db.execute(
        select(ConversationState).where(
            ConversationState.agyary_id == agyary_id,
            ConversationState.phone == phone,
        )
    )
    state = result.scalar_one_or_none()
    if state:
        await db.delete(state)
        await db.flush()
