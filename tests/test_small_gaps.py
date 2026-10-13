"""Small gaps closed from the review's list.

PV-3: access logs keep the path but not the query string, which can carry a
behdin search. Retention: in-app notices are deleted a week after they expire.
DM-2: the calendar's "today" is India's date, not the server's UTC one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from agyary.api import main
from agyary.api.routes import calendar as calendar_routes
from agyary.calendar import CalendarSystem, gregorian_to_parsi
from agyary.models import AppNotification, User
from agyary.services import reminders


def test_access_log_lines_drop_the_query_string():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("203.0.113.7:5000", "GET", "/api/mobed/behdins?q=Mehta", "1.1", 200), None)
    assert main._NoQueryStrings().filter(record)
    assert record.getMessage() == '203.0.113.7:5000 - "GET /api/mobed/behdins HTTP/1.1" 200'


async def test_expired_notices_are_deleted_a_week_later(db, seeded):
    user_id = (await db.execute(select(User.id).where(User.phone == seeded["mobed_phone"]))).scalar_one()
    now = datetime(2030, 3, 14, 12, 0, tzinfo=timezone.utc)
    await reminders.notify(db, user_id, "test", "Old", "Long gone", now=now - timedelta(days=9))
    await reminders.notify(db, user_id, "test", "New", "Still useful", now=now)
    assert await reminders.sweep_expired_notices(db, now) == 1
    titles = (await db.execute(select(AppNotification.title))).scalars().all()
    assert titles == ["New"]
    assert (await db.execute(select(func.count()).select_from(AppNotification))).scalar_one() == 1


async def test_today_is_indias_date_even_while_utc_is_still_yesterday(client, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            # 01:00 on 14 Oct in India is 19:30 on 13 Oct in UTC.
            return datetime(2026, 10, 13, 19, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(calendar_routes, "datetime", Clock)
    body = (await client.get("/api/calendar/today?system=shenshai")).json()
    expected = gregorian_to_parsi(datetime(2026, 10, 14).date(), CalendarSystem.SHENSHAI)
    assert (body["roj"], body["mah"], body["year"]) == (expected.roj, expected.mah, expected.year)
