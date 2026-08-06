"""Tests for the Postgres-backed durable send worker: claim-under-lock,
backoff/failure bookkeeping, the sweep-vs-immediate-enqueue race, and the
startup-recovery sweep."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from agyary.messaging import send_worker
from agyary.models import Agyary, WhatsAppMessage
from tests.conftest import TEST_DATABASE_URL

WA_PHONE_NUMBER_ID = "PNID_WORKER_TEST"


@pytest.fixture
async def session_factory():
    """A session factory independent of the `db` fixture's session, bound to
    the same test database - needed for real cross-session row locking
    (FOR UPDATE SKIP LOCKED only means something across separate sessions)."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def agyary_with_phone_id(db, seeded):
    agyary = await db.get(Agyary, seeded["agyary_id"])
    agyary.wa_phone_number_id = WA_PHONE_NUMBER_ID
    await db.commit()
    return agyary


async def _make_outbox_row(
    db, agyary_id: int, *, status: str = "pending", attempts: int = 0, next_attempt_at=None
) -> int:
    row = WhatsAppMessage(
        agyary_id=agyary_id,
        direction="outbound",
        wa_phone="+919900011111",
        message_type="text",
        content={"to": "+919900011111", "text": "hello", "buttons": [], "sections": []},
        status=status,
        attempts=attempts,
        next_attempt_at=next_attempt_at or datetime.now(UTC),
    )
    db.add(row)
    await db.flush()
    await db.commit()
    return row.id


def _success_transport(calls: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.SENT_" + str(len(calls))}]})

    return httpx.MockTransport(handler)


def _failing_transport(calls: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, json={"error": "boom"})

    return httpx.MockTransport(handler)


async def test_pending_row_is_picked_up_and_sent(db, session_factory, agyary_with_phone_id):
    outbox_id = await _make_outbox_row(db, agyary_with_phone_id.id)
    calls: list = []

    async with httpx.AsyncClient(transport=_success_transport(calls)) as http_client:
        semaphore = asyncio.Semaphore(5)
        sent = await send_worker.claim_and_send(session_factory, outbox_id, http_client, semaphore)

    assert sent is True
    assert len(calls) == 1

    await db.refresh(await db.get(WhatsAppMessage, outbox_id))
    row = await db.get(WhatsAppMessage, outbox_id)
    assert row.status == "sent"
    assert row.wa_message_id == "wamid.SENT_1"


async def test_failing_send_increments_attempts_and_sets_backoff(
    db, session_factory, agyary_with_phone_id
):
    outbox_id = await _make_outbox_row(db, agyary_with_phone_id.id)
    calls: list = []

    async with httpx.AsyncClient(transport=_failing_transport(calls)) as http_client:
        semaphore = asyncio.Semaphore(5)
        before = datetime.now(UTC)
        sent = await send_worker.claim_and_send(session_factory, outbox_id, http_client, semaphore)

    assert sent is True  # claimed and attempted, even though the send failed
    row = await db.get(WhatsAppMessage, outbox_id)
    await db.refresh(row)
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.next_attempt_at > before + timedelta(seconds=4)
    assert row.next_attempt_at <= before + timedelta(seconds=6)


async def test_after_max_attempts_status_is_failed_and_no_further_attempts(
    db, session_factory, agyary_with_phone_id
):
    outbox_id = await _make_outbox_row(db, agyary_with_phone_id.id)
    calls: list = []

    async with httpx.AsyncClient(transport=_failing_transport(calls)) as http_client:
        semaphore = asyncio.Semaphore(5)
        for _ in range(send_worker.MAX_ATTEMPTS):
            # Force each retry to be immediately due, as if the backoff had
            # already elapsed.
            row = await db.get(WhatsAppMessage, outbox_id)
            row.next_attempt_at = datetime.now(UTC)
            await db.commit()
            await send_worker.claim_and_send(session_factory, outbox_id, http_client, semaphore)

        row = await db.get(WhatsAppMessage, outbox_id)
        await db.refresh(row)
        assert row.status == "failed"
        assert row.attempts == send_worker.MAX_ATTEMPTS
        assert len(calls) == send_worker.MAX_ATTEMPTS

        # A further attempt (even if forced due) must not send again - the
        # row is no longer "pending" so _claim_row can't match it.
        row.next_attempt_at = datetime.now(UTC)
        await db.commit()
        sent_again = await send_worker.claim_and_send(session_factory, outbox_id, http_client, semaphore)
        assert sent_again is False
        assert len(calls) == send_worker.MAX_ATTEMPTS


async def test_concurrent_claims_on_same_row_send_exactly_once(
    db, session_factory, agyary_with_phone_id
):
    outbox_id = await _make_outbox_row(db, agyary_with_phone_id.id)
    calls: list = []

    async with httpx.AsyncClient(transport=_success_transport(calls)) as http_client:
        semaphore = asyncio.Semaphore(5)
        results = await asyncio.gather(
            send_worker.claim_and_send(session_factory, outbox_id, http_client, semaphore),
            send_worker.claim_and_send(session_factory, outbox_id, http_client, semaphore),
        )

    assert sorted(results) == [False, True]
    assert len(calls) == 1

    row = await db.get(WhatsAppMessage, outbox_id)
    await db.refresh(row)
    assert row.status == "sent"


async def test_startup_sweep_picks_up_row_left_pending_from_before_process_start(
    db, session_factory, agyary_with_phone_id
):
    past = datetime.now(UTC) - timedelta(minutes=5)
    outbox_id = await _make_outbox_row(db, agyary_with_phone_id.id, next_attempt_at=past)
    calls: list = []

    async with httpx.AsyncClient(transport=_success_transport(calls)) as http_client:
        semaphore = asyncio.Semaphore(5)
        sent_count = await send_worker.run_startup_sweep(session_factory, http_client, semaphore)

    assert sent_count == 1
    assert len(calls) == 1
    row = await db.get(WhatsAppMessage, outbox_id)
    await db.refresh(row)
    assert row.status == "sent"


async def test_not_yet_due_row_is_not_sent_by_sweep(db, session_factory, agyary_with_phone_id):
    future = datetime.now(UTC) + timedelta(minutes=5)
    outbox_id = await _make_outbox_row(db, agyary_with_phone_id.id, next_attempt_at=future)
    calls: list = []

    async with httpx.AsyncClient(transport=_success_transport(calls)) as http_client:
        semaphore = asyncio.Semaphore(5)
        sent_count = await send_worker.sweep_due(session_factory, http_client, semaphore)

    assert sent_count == 0
    assert calls == []
    row = await db.get(WhatsAppMessage, outbox_id)
    await db.refresh(row)
    assert row.status == "pending"


def test_build_graph_payload_text():
    payload = send_worker.build_graph_payload(
        {"to": "+919900011111", "text": "hi", "buttons": [], "sections": []}
    )
    assert payload["type"] == "text"
    assert payload["text"]["body"] == "hi"


def test_build_graph_payload_buttons():
    payload = send_worker.build_graph_payload(
        {
            "to": "+919900011111",
            "text": "choose",
            "buttons": [{"id": "yes", "title": "Yes"}],
            "sections": [],
        }
    )
    assert payload["interactive"]["type"] == "button"
    assert payload["interactive"]["action"]["buttons"][0]["reply"]["id"] == "yes"


def test_build_graph_payload_sections():
    payload = send_worker.build_graph_payload(
        {
            "to": "+919900011111",
            "text": "pick one",
            "buttons": [],
            "sections": [{"title": "Options", "rows": [{"id": "a", "title": "A", "description": None}]}],
        }
    )
    assert payload["interactive"]["type"] == "list"
    assert payload["interactive"]["action"]["sections"][0]["rows"][0]["id"] == "a"


def test_build_graph_payload_flow():
    payload = send_worker.build_graph_payload(
        {
            "to": "+919900011111",
            "text": "Pick a Roj",
            "buttons": [],
            "sections": [],
            "flow": {
                "flow_id": "999",
                "flow_token": "roj:1:abc123",
                "flow_cta": "Continue",
                "screen": "SELECT_ROJ",
                "data": {},
            },
        }
    )
    interactive = payload["interactive"]
    assert interactive["type"] == "flow"
    params = interactive["action"]["parameters"]
    assert params["flow_message_version"] == "3"
    assert params["flow_id"] == "999"
    assert params["flow_token"] == "roj:1:abc123"
    assert params["flow_action"] == "navigate"
    assert params["flow_action_payload"]["screen"] == "SELECT_ROJ"
    assert params["flow_action_payload"]["data"]  # non-empty, per Meta's requirement


def test_build_graph_payload_flow_takes_precedence_over_buttons_and_sections():
    """A message shouldn't carry both a flow and buttons/sections in
    practice, but if it did, the flow branch must win - Cloud API rejects
    an interactive payload with more than one action shape."""
    payload = send_worker.build_graph_payload(
        {
            "to": "+919900011111",
            "text": "pick",
            "buttons": [{"id": "x", "title": "X"}],
            "sections": [],
            "flow": {
                "flow_id": "1",
                "flow_token": "t",
                "flow_cta": "Go",
                "screen": "S",
                "data": {"k": "v"},
            },
        }
    )
    assert payload["interactive"]["type"] == "flow"
