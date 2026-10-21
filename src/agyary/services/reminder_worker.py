"""The loop that runs the evening jobs.

Every minute it asks one question - is it time, and is there anything to do? -
and does it. It holds no state of its own: what has been planned and sent is
in the database, so a restart or a redeploy in the middle of the evening picks
up exactly where it was, and two of these running at once cannot double-send
(see reminder_sender).

From ``reminders_send_hour`` IST until ``reminders_cutoff_hour`` it:
  - tells each mobed whose memorial has its last prayer tomorrow (always: it
    only leaves a notice in the app, so it does not depend on sending), and
  - when sending is on, plans tomorrow's WhatsApp reminders and sends them.
Past the cutoff it plans nothing and anything still unsent is given up on,
because "tomorrow" is no longer true.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from agyary.core.config import get_settings
from agyary.core.database import async_session_factory
from agyary.services import daily_report, reminder_sender, reminders

logger = logging.getLogger(__name__)

TICK_SECONDS = 60

# When a pass last finished cleanly, for /health?deep=1 (OP-2). Per process.
last_pass_at: datetime | None = None


async def ping_heartbeat(*, ok: bool, client: httpx.AsyncClient | None = None) -> None:
    """Tell the outside heartbeat check (HEARTBEAT_URL, e.g. Healthchecks.io)
    that a pass ran - or, with "/fail", that it went wrong. Its silence is the
    alarm: the app down, the loop dead. Never raises; a ping that cannot be
    made is the check's to notice."""
    url = get_settings().heartbeat_url.strip()
    if not url:
        return
    own = client is None
    client = client or httpx.AsyncClient(timeout=5)
    try:
        await client.get(url if ok else url.rstrip("/") + "/fail")
    except httpx.HTTPError as exc:
        logger.warning("Heartbeat ping failed: %s", exc.__class__.__name__)
    finally:
        if own:
            await client.aclose()


async def tick(
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
    session_factory=async_session_factory,
) -> reminder_sender.Report:
    """One pass. ``now``, ``client`` and ``session_factory`` can be given so
    it can be tested without the clock, Meta or the real database."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    report = reminder_sender.Report()

    hour = now.astimezone(reminder_sender.IST).hour
    in_window = settings.reminders_send_hour <= hour < settings.reminders_cutoff_hour
    sending = settings.reminders_send_mode != "off"
    report_window = settings.daily_report_hour <= hour < settings.daily_report_cutoff_hour
    if not in_window and not sending and not report_window:
        return report            # nothing to do, and nothing worth opening a connection for

    own_client = client is None and sending
    if sending and client is None:
        client = httpx.AsyncClient(timeout=20)
    try:
        async with session_factory() as db:
            if in_window:
                report.closing = await reminders.notify_closing_tomorrow(db, now)
                await reminders.sweep_expired_notices(db, now)
                await db.commit()
            if report_window:
                # Its own step: a failure here must never stop the reminders below.
                try:
                    await daily_report.run(db, now, settings, client)
                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.exception("Daily report pass failed")
            if sending:
                if in_window:
                    report.planned = await reminder_sender.plan_tomorrow(db, now, settings)
                    await db.commit()
                sent = await reminder_sender.send_pending(db, client, now, settings)
                report.sent, report.failed, report.missed = sent.sent, sent.failed, sent.missed
    finally:
        if own_client:
            await client.aclose()
    if report.closing or report.planned or report.sent or report.failed or report.missed:
        logger.info(
            "Evening run: closing notices %d, reminders planned %d, sent %d, failed %d, missed %d",
            report.closing, report.planned, report.sent, report.failed, report.missed,
        )
    return report


async def run_forever() -> None:
    """Run until cancelled. An error in one pass is logged and the next pass
    tries again - a loop that dies on its first exception stays dead until
    someone notices, and nobody would."""
    global last_pass_at
    logger.info("Evening worker started (reminders: %s)", get_settings().reminders_send_mode)
    while True:
        try:
            await tick()
            last_pass_at = datetime.now(timezone.utc)
            await ping_heartbeat(ok=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Evening run failed")
            await ping_heartbeat(ok=False)
        await asyncio.sleep(TICK_SECONDS)
