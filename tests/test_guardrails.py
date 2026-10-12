"""The ceilings on what reminders can cost, the pause switch, and the alerts.

A bug, a bad actor or a Meta billing surprise must not be able to turn the
evening loop into a large bill. These tests pin down each way it is stopped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from agyary.models import AppNotification, Notification
from agyary.services import guardrails, reminder_sender
from tests.test_mobed_api import NEW_MOBED_PHONE
from tests.test_reminder_sender import (
    OTHER_PHONE,
    FakeMeta,
    _owner_notes,
    _planned,
    _rows,
    _scenario,
    _settings,
)

ADMIN = NEW_MOBED_PHONE       # the test mobed doubles as the admin, so alerts land on their bell


async def _two_reminders(client, db, seeded):
    """Two behdins of one mobed, each with a reminder tomorrow."""
    first = await _scenario(client, db, seeded)
    await _scenario(client, db, seeded, phone=OTHER_PHONE)
    return first


async def _statuses(db):
    return sorted((n.status, n.error_message or "") for n in await _rows(db))


# --- Caps -------------------------------------------------------------------

async def test_the_daily_cap_stops_the_reminder_over_it(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    s = _settings(reminders_daily_cap=1, admin_phones=ADMIN)
    assert await reminder_sender.plan_tomorrow(db, now, s) == 1
    await db.commit()

    statuses = await _statuses(db)
    assert [st for st, _ in statuses] == ["failed", "pending"]
    assert "daily limit for all fire temples" in statuses[0][1]


async def test_the_mobed_is_told_a_reminder_was_not_sent_so_they_can_send_it_by_hand(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    await reminder_sender.plan_tomorrow(db, now, _settings(reminders_daily_cap=1))
    await db.commit()
    notes = await _owner_notes(client, headers)
    [skipped] = [n for n in notes if n["kind"] == "reminder_failed"]
    assert "was not sent" in skipped["title"] and "daily limit" in skipped["body"]
    assert "Remind on WhatsApp" in skipped["body"] and skipped["link"] == "#/reminders"


async def test_a_capped_reminder_is_told_and_alerted_once_however_often_the_loop_asks(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    s = _settings(reminders_daily_cap=1, admin_phones=ADMIN)
    for minute in range(5):                                  # every minute of the evening
        await reminder_sender.plan_tomorrow(db, now + timedelta(minutes=minute), s)
        await db.commit()
    kinds = [n["kind"] for n in await _owner_notes(client, headers)]
    assert kinds.count("reminder_failed") == 1 and kinds.count("alert") == 1
    assert len(await _rows(db)) == 2


async def test_a_blocked_reminder_does_not_use_up_the_allowance(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    await reminder_sender.plan_tomorrow(db, now, _settings(reminders_daily_cap=1))
    await db.commit()
    used = await guardrails.usage(db, now)
    assert used.today == 1 and used.month == 1             # the failed row is not counted


async def test_the_monthly_cap(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    await reminder_sender.plan_tomorrow(db, now, _settings(reminders_monthly_cap=1))
    await db.commit()
    statuses = await _statuses(db)
    assert [st for st, _ in statuses] == ["failed", "pending"] and "monthly limit" in statuses[0][1]


async def test_one_mobed_cannot_use_more_than_their_own_daily_cap(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    await reminder_sender.plan_tomorrow(db, now, _settings(reminders_per_mobed_daily_cap=1))
    await db.commit()
    statuses = await _statuses(db)
    assert [st for st, _ in statuses] == ["failed", "pending"] and "your daily limit" in statuses[0][1]


async def test_one_fire_temple_cannot_use_more_than_its_daily_cap(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    await reminder_sender.plan_tomorrow(db, now, _settings(reminders_per_agyary_daily_cap=1))
    await db.commit()
    statuses = await _statuses(db)
    assert [st for st, _ in statuses] == ["failed", "pending"] and "fire temple's daily limit" in statuses[0][1]


async def test_under_every_cap_everything_is_planned(client, db, seeded):
    *_, now = await _two_reminders(client, db, seeded)
    assert await reminder_sender.plan_tomorrow(db, now, _settings()) == 2


async def test_caps_apply_to_a_dry_run_too_but_write_nothing(client, db, seeded, caplog):
    reminder_sender.reset_dry_run_log()
    *_, now = await _two_reminders(client, db, seeded)
    with caplog.at_level("INFO"):
        planned = await reminder_sender.plan_tomorrow(
            db, now, _settings(reminders_send_mode="dry_run", reminders_daily_cap=1))
    assert planned == 1 and caplog.text.count("DRY RUN - would send") == 1
    await db.commit()
    assert await _rows(db) == []


async def test_a_cap_alerts_the_admins_and_names_what_was_stopped(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    await reminder_sender.plan_tomorrow(db, now, _settings(reminders_daily_cap=1, admin_phones=ADMIN))
    await db.commit()
    [alert] = [n for n in await _owner_notes(client, headers) if n["kind"] == "alert"]
    assert alert["title"] == "Reminder limit reached"
    assert "1 reminder not sent" in alert["body"] and "daily limit" in alert["body"]


async def test_no_admins_means_the_alert_goes_to_the_log_not_nowhere(client, db, seeded, caplog):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    with caplog.at_level("ERROR"):
        await reminder_sender.plan_tomorrow(db, now, _settings(reminders_daily_cap=1, admin_phones=""))
    assert "nobody was told" in caplog.text and "Reminder limit reached" in caplog.text


def test_the_day_and_month_run_on_indian_time():
    ist = timezone(timedelta(hours=5, minutes=30))
    late = datetime(2026, 10, 31, 23, 50, tzinfo=ist)       # still the 31st in India
    start, end = guardrails.day_bounds(late)
    assert (start.date().isoformat(), (end - start).days) == ("2026-10-31", 1)
    m_start, m_end = guardrails.month_bounds(late)
    assert (m_start.month, m_end.month, m_end.year) == (10, 11, 2026)
    dec = guardrails.month_bounds(datetime(2026, 12, 15, tzinfo=ist))
    assert (dec[1].year, dec[1].month) == (2027, 1)          # December rolls into January


async def test_yesterdays_reminders_do_not_count_against_today(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    await reminder_sender.plan_tomorrow(db, now, _settings())
    await db.commit()
    for n in await _rows(db):
        n.created_at = now - timedelta(days=1)
    await db.commit()
    used = await guardrails.usage(db, now)
    assert used.today == 0 and used.month == 2


# --- The pause switch -------------------------------------------------------

async def test_a_paused_system_sends_nothing_and_resuming_sends(client, db, seeded):
    aid, cid, headers, later, opening, now = await _planned(client, db, seeded)
    s = _settings(admin_phones=ADMIN)
    await guardrails.pause(db, s, "Testing the switch", now=now)
    await db.commit()

    meta = FakeMeta()
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now, s)
        assert meta.calls == [] and report.sent == 0
        assert [n.status for n in await _rows(db)] == ["pending"]          # kept, not lost

        await guardrails.resume(db)
        await db.commit()
        report = await reminder_sender.send_pending(db, http, now, s)
    assert report.sent == 1 and len(meta.calls) == 1


async def test_pausing_tells_the_admins(client, db, seeded):
    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    await guardrails.pause(db, _settings(admin_phones=ADMIN), "Because I said so", now=now)
    await db.commit()
    [alert] = [n for n in await _owner_notes(client, headers) if n["kind"] == "alert"]
    assert alert["title"] == "Reminder sending is paused" and alert["body"] == "Because I said so"


async def test_the_pause_survives_a_restart(client, db, seeded):
    *_, now = await _scenario(client, db, seeded)
    await guardrails.pause(db, _settings(), "Stay down", now=now)
    await db.commit()
    db.expire_all()                                                         # a fresh read, as after a restart
    assert await guardrails.paused_reason(db) == "Stay down"


async def test_a_reminder_still_unsent_when_the_evening_ends_tells_the_mobed_why(client, db, seeded):
    aid, cid, headers, later, opening, now = await _planned(client, db, seeded)
    s = _settings()
    await guardrails.pause(db, s, "Paused all evening", now=now)
    await db.commit()
    meta = FakeMeta()
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now.replace(hour=21, minute=10), s)
    assert report.missed == 1 and meta.calls == []
    [n] = await _rows(db)
    assert n.status == "failed" and n.error_message == "Not sent: sending was paused"
    [note] = [x for x in await _owner_notes(client, headers) if x["kind"] == "reminder_failed"]
    assert "sending was paused" in note["body"]


# --- The breaker ------------------------------------------------------------

async def test_failures_in_a_row_pause_everything(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    s = _settings(reminders_breaker_failures=2, admin_phones=ADMIN)
    await reminder_sender.plan_tomorrow(db, now, s)
    await db.commit()
    meta = FakeMeta(status=400, code=100)                  # a refusal that is not about one recipient
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now, s)
    assert report.failed == 2 and len(meta.calls) == 2
    assert "in a row failed" in (await guardrails.paused_reason(db))
    assert "Reminder sending is paused" in [n["title"] for n in await _owner_notes(client, headers)]


async def test_the_breaker_stops_before_the_rest_of_the_queue_is_sent(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    s = _settings(reminders_breaker_failures=1)
    await reminder_sender.plan_tomorrow(db, now, s)
    await db.commit()
    meta = FakeMeta(status=400, code=100)
    async with meta.client() as http:
        await reminder_sender.send_pending(db, http, now, s)
    assert len(meta.calls) == 1                            # the second was never tried
    assert sorted(n.status for n in await _rows(db)) == ["failed", "pending"]


async def test_one_bad_number_does_not_pause_everything(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    s = _settings(reminders_breaker_failures=1)
    await reminder_sender.plan_tomorrow(db, now, s)
    await db.commit()
    meta = FakeMeta(status=400, code=131026)               # not on WhatsApp: about the recipient only
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now, s)
    assert report.failed == 2 and await guardrails.paused_reason(db) is None


async def test_a_success_resets_the_count_of_failures_in_a_row(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    s = _settings(reminders_breaker_failures=2)
    await reminder_sender.plan_tomorrow(db, now, s)
    await db.commit()
    answers = iter([(400, 100), (200, None)])
    calls = []

    import httpx

    def handler(request):
        status, code = next(answers)
        calls.append(status)
        if status == 200:
            return httpx.Response(200, json={"messages": [{"id": "wamid.ok"}]})
        return httpx.Response(status, json={"error": {"message": "nope", "code": code}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        report = await reminder_sender.send_pending(db, http, now, s)
    assert (report.failed, report.sent) == (1, 1) and await guardrails.paused_reason(db) is None


async def test_an_account_level_error_pauses_at_once_and_keeps_the_reminder(client, db, seeded):
    aid, cid, headers, later, opening, now = await _two_reminders(client, db, seeded)
    s = _settings(admin_phones=ADMIN)
    await reminder_sender.plan_tomorrow(db, now, s)
    await db.commit()
    meta = FakeMeta(status=401, code=190)                  # the token is invalid or expired
    async with meta.client() as http:
        report = await reminder_sender.send_pending(db, http, now, s)
    assert len(meta.calls) == 1 and report.failed == 0     # stopped on the first
    assert "(190)" in (await guardrails.paused_reason(db))
    assert [n.status for n in await _rows(db)] == ["pending", "pending"]   # neither was at fault
    kinds = [n["kind"] for n in await _owner_notes(client, headers)]
    assert "alert" in kinds and "reminder_failed" not in kinds             # the mobeds are not alarmed


async def test_a_payment_problem_pauses_everything_too(client, db, seeded):
    *_, now = await _planned(client, db, seeded)
    s = _settings()
    meta = FakeMeta(status=400, code=131042)
    async with meta.client() as http:
        await reminder_sender.send_pending(db, http, now, s)
    assert "(131042)" in (await guardrails.paused_reason(db))


# --- Alerts -----------------------------------------------------------------

async def test_the_same_alert_is_not_repeated_within_hours(client, db, seeded):
    *_, now = await _scenario(client, db, seeded)
    s = _settings(admin_phones=ADMIN)
    assert await guardrails.alert_admins(db, s, "Something", "body", now=now) == 1
    assert await guardrails.alert_admins(db, s, "Something", "body", now=now + timedelta(hours=1)) == 0
    assert await guardrails.alert_admins(db, s, "Something", "body", now=now + timedelta(hours=7)) == 1
    assert await guardrails.alert_admins(db, s, "Something else", "body", now=now) == 1


async def test_alerts_go_only_to_admins(client, db, seeded):
    aid, cid, headers, later, opening, now = await _scenario(client, db, seeded)
    await guardrails.alert_admins(db, _settings(admin_phones="+919000000001"), "Not for you", "x", now=now)
    await db.commit()
    assert await _owner_notes(client, headers) == []
    assert (await db.execute(select(AppNotification))).scalars().all() == []


def test_admin_phones_are_read_from_a_comma_separated_list():
    s = _settings(admin_phones=" +919800000001 , +919800000002,, ")
    assert guardrails.admin_phones(s) == {"+919800000001", "+919800000002"}
    assert guardrails.is_admin(s, "+919800000002") and not guardrails.is_admin(s, "+919800000003")
    assert guardrails.admin_phones(_settings(admin_phones="")) == set()


def test_the_shipped_ceilings_are_modest():
    s = _settings()
    # Defaults a first month should never hit by accident, and that cap a
    # runaway at a few hundred rupees at most (see reminders_cost_per_message_inr).
    assert s.reminders_daily_cap <= 200 and s.reminders_monthly_cap <= 3000
    assert s.reminders_per_mobed_daily_cap <= s.reminders_per_agyary_daily_cap <= s.reminders_daily_cap
    worst_month = guardrails.estimated_cost_inr(s, s.reminders_monthly_cap)
    assert worst_month < 500
    assert Notification  # the table the counts come from
