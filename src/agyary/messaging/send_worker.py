"""Durable WhatsApp send worker: Postgres-backed outbox, no external broker.

This deploys to a single self-hosted machine with no ops team and no message
broker anywhere in the stack; power/network interruptions are routine, not
an edge case. Postgres (the ``whatsapp_messages`` table, used as an outbox)
is the only stateful service already required to run, so it is also the
durability mechanism here - there is no Redis/RabbitMQ/Celery in this design.

Two paths feed the same claim-and-send step:
  - the webhook route pushes a freshly-created outbox row id onto an
    in-process asyncio.Queue for an immediate wake-up;
  - a periodic sweep independently re-discovers any due ``pending`` row,
    in case the immediate enqueue was missed (process restart) or never
    happened (a row stuck from a previous run).

Both paths converge on ``claim_and_send``, which claims a row with
``SELECT ... FOR UPDATE SKIP LOCKED`` before sending. That single detail is
what makes this correct even when the immediate-enqueue path and the sweep
both notice the same row at once, and what would keep it correct if this
ever ran as more than one process: only one claimer ever gets the row, every
other claimer gets back nothing and does no work.

On startup, the sweep runs once before anything else, so a row left
"pending" from an earlier ungraceful shutdown (this machine reboots
unattended - power blips, OS updates) is picked up with zero manual
intervention.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agyary.core.config import Settings, get_settings
from agyary.models import Agyary, WhatsAppMessage

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v20.0"

MAX_ATTEMPTS = 3
BACKOFF_SECONDS_SCHEDULE = [5, 20, 60]  # index 0 after the 1st failure, etc.

SWEEP_INTERVAL_SECONDS = 2.0
DEFAULT_MAX_CONCURRENT_SENDS = 5
SWEEP_BATCH_LIMIT = 50

# Module-level so the webhook route and the worker task share one queue
# without threading it through FastAPI's dependency system.
SEND_QUEUE: asyncio.Queue[int] = asyncio.Queue()


async def enqueue_send(outbox_id: int) -> None:
    """Wake the worker immediately for a freshly-created outbox row."""
    await SEND_QUEUE.put(outbox_id)


def build_graph_payload(content: dict) -> dict:
    """OutgoingMessage.as_dict() shape (to/text/buttons/sections) -> Cloud
    API send payload (plain text, interactive button, or interactive list)."""
    to = content["to"]
    text = content["text"]
    buttons = content.get("buttons") or []
    sections = content.get("sections") or []

    if buttons:
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                        for b in buttons
                    ]
                },
            },
        }

    if sections:
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": text},
                "action": {
                    "button": "Choose",
                    "sections": [
                        {
                            "title": s["title"],
                            "rows": [
                                {
                                    "id": r["id"],
                                    "title": r["title"],
                                    **({"description": r["description"]} if r.get("description") else {}),
                                }
                                for r in s["rows"]
                            ],
                        }
                        for s in sections
                    ],
                },
            },
        }

    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }


async def _claim_row(db: AsyncSession, outbox_id: int) -> WhatsAppMessage | None:
    """Lock and return the row if it's still pending and due - or None if
    it's already been claimed by someone else, isn't due yet, doesn't exist,
    or was already sent/failed. Non-blocking: SKIP LOCKED means a row held
    by a concurrent claimer is treated as absent, not waited for."""
    result = await db.execute(
        select(WhatsAppMessage)
        .where(
            WhatsAppMessage.id == outbox_id,
            WhatsAppMessage.direction == "outbound",
            WhatsAppMessage.status == "pending",
            WhatsAppMessage.next_attempt_at <= datetime.now(UTC),
        )
        .with_for_update(skip_locked=True)
    )
    return result.scalar_one_or_none()


async def _attempt_send(
    db: AsyncSession, row: WhatsAppMessage, http_client: httpx.AsyncClient, settings: Settings
) -> None:
    """Send one already-claimed row and update its status. Always commits
    (success, failure, or unresolvable) - that commit is also what releases
    the row lock taken by _claim_row's FOR UPDATE."""
    agyary = await db.get(Agyary, row.agyary_id)
    if agyary is None or not agyary.wa_phone_number_id:
        logger.error(
            "Outbox row %s has no resolvable agyary/wa_phone_number_id - marking failed", row.id
        )
        row.status = "failed"
        await db.commit()
        return

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{agyary.wa_phone_number_id}/messages"
    payload = build_graph_payload(row.content)

    try:
        response = await http_client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.whatsapp_api_token}"},
            timeout=20.0,
        )
        response.raise_for_status()
        wa_message_id = response.json()["messages"][0]["id"]
    except Exception:
        row.attempts += 1
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
            logger.error(
                "Outbox row %s: send failed permanently after %s attempts",
                row.id,
                row.attempts,
                exc_info=True,
            )
        else:
            delay = BACKOFF_SECONDS_SCHEDULE[min(row.attempts - 1, len(BACKOFF_SECONDS_SCHEDULE) - 1)]
            row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
            logger.warning(
                "Outbox row %s: send attempt %s failed, retrying in %ss",
                row.id,
                row.attempts,
                delay,
                exc_info=True,
            )
        await db.commit()
        return

    row.wa_message_id = wa_message_id
    row.status = "sent"
    await db.commit()


async def claim_and_send(
    session_factory: async_sessionmaker[AsyncSession],
    outbox_id: int,
    http_client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> bool:
    """Try to claim outbox_id and send it in its own session/transaction.

    Returns True if this call performed the claim+send (whatever the send
    outcome), False if it lost the race - already claimed by someone else,
    not due yet, or gone. Concurrent callers racing the same id are exactly
    the sweep-vs-immediate-enqueue scenario this design has to tolerate.
    """
    async with semaphore:
        async with session_factory() as db:
            row = await _claim_row(db, outbox_id)
            if row is None:
                return False
            await _attempt_send(db, row, http_client, get_settings())
            return True


async def sweep_due(
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    limit: int = SWEEP_BATCH_LIMIT,
) -> int:
    """One discovery pass: find due pending outbound rows and attempt to
    claim+send each concurrently. Returns how many this call actually sent
    (a row discovered here but already claimed elsewhere by the time we try
    is not counted - see claim_and_send's return value)."""
    async with session_factory() as db:
        result = await db.execute(
            select(WhatsAppMessage.id)
            .where(
                WhatsAppMessage.direction == "outbound",
                WhatsAppMessage.status == "pending",
                WhatsAppMessage.next_attempt_at <= datetime.now(UTC),
            )
            .order_by(WhatsAppMessage.next_attempt_at)
            .limit(limit)
        )
        due_ids = [row_id for (row_id,) in result.all()]

    if not due_ids:
        return 0

    outcomes = await asyncio.gather(
        *(claim_and_send(session_factory, outbox_id, http_client, semaphore) for outbox_id in due_ids)
    )
    return sum(1 for sent in outcomes if sent)


async def run_startup_sweep(
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> int:
    """Run once before anything else on process startup, to pick up any row
    left "pending" from an earlier ungraceful shutdown."""
    sent = await sweep_due(session_factory, http_client, semaphore)
    if sent:
        logger.info("Startup sweep: sent %s previously-pending outbox row(s)", sent)
    return sent


async def worker_loop(
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    queue: asyncio.Queue[int] = SEND_QUEUE,
) -> None:
    """Consume immediate-enqueue wake-ups forever. Run as a background task."""
    while True:
        outbox_id = await queue.get()
        try:
            await claim_and_send(session_factory, outbox_id, http_client, semaphore)
        except Exception:
            logger.exception("Unhandled error sending outbox row %s", outbox_id)
        finally:
            queue.task_done()


async def sweep_loop(
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    interval: float = SWEEP_INTERVAL_SECONDS,
) -> None:
    """Periodic safety-net sweep. Run as a background task."""
    while True:
        try:
            await sweep_due(session_factory, http_client, semaphore)
        except Exception:
            logger.exception("Sweep iteration failed")
        await asyncio.sleep(interval)
