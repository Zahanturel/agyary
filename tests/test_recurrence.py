"""Monthly recurring machis: generation at creation, and top-up on read.

A machi kept for a departed relative is usually kept every month on the
same Roj, indefinitely. There is no scheduler in this deployment, so the
board tops the arrangement up when it is looked at - otherwise it would
stop dead at whatever horizon it happened to be created with.

Instances are real rows rather than something computed on read, because a
machi occupies a real slot: one machi per geh per day per agyary, and a
slot nobody wrote down is a slot somebody else takes.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select

from agyary.calendar import CalendarSystem, parsi_to_gregorian
from agyary.messaging import booking_service
from agyary.models import Agyary, Machi, RecurrenceRule
from agyary.services import mobed_dashboard

ROJ = 4
GEH = 2
YEAR = 1396
START_MAH = 1


async def _agyary(db, seeded) -> Agyary:
    return await db.get(Agyary, seeded["agyary_id"])


def _greg(agyary: Agyary, mah: int, year: int = YEAR, roj: int = ROJ) -> date:
    return parsi_to_gregorian(year, CalendarSystem(agyary.calendar_system), mah=mah, roj=roj)


async def _start_recurring(db, seeded, *, mah: int = START_MAH, roj: int = ROJ, geh: int = GEH):
    agyary = await _agyary(db, seeded)
    result = await mobed_dashboard.manual_add_machi(
        db,
        agyary,
        actor_user_id=1,
        behdin_phone="+919900044444",
        behdin_name="Behdin Recurring",
        roj=roj,
        mah=mah,
        year=YEAR,
        geh=geh,
        gregorian=_greg(agyary, mah, roj=roj),
        purpose="patet",
        names=[
            {"section": "pair", "title": "ervad", "name": "Kaikhushru", "status": "departed", "pair_group": 1},
            {"section": "pair", "title": "ervad", "name": "Hormazd", "status": "departed", "pair_group": 1},
        ],
        recurring=True,
    )
    assert result.machi is not None, "source machi should book cleanly"
    rule = (await db.execute(select(RecurrenceRule))).scalar_one()
    return agyary, result.machi, rule


async def _instances(db, rule) -> list[Machi]:
    rows = (
        await db.execute(
            select(Machi)
            .where(Machi.recurrence_rule_id == rule.id, Machi.is_recurring_instance.is_(True))
            .order_by(Machi.gregorian_date)
        )
    ).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
async def test_creating_a_recurrence_generates_the_first_few_months(db, seeded):
    agyary, source, rule = await _start_recurring(db, seeded)

    instances = await _instances(db, rule)
    assert len(instances) == mobed_dashboard.RECURRENCE_HORIZON_MONTHS

    # Same Roj and Geh every month, which is the whole point of the pattern.
    assert {m.parsi_roj for m in instances} == {ROJ}
    assert {m.geh for m in instances} == {GEH}
    assert [m.parsi_mah for m in instances] == [START_MAH + 1, START_MAH + 2, START_MAH + 3]
    # The source itself is not one of its own instances.
    assert source.id not in {m.id for m in instances}
    assert source.recurrence_rule_id == rule.id


async def test_the_marker_is_the_last_month_attempted(db, seeded):
    """This is the bug the rewrite fixed. The marker used to be assigned
    from a loop variable after the loop, so a month that failed to resolve
    left it stale - or unbound, if the very first one did."""
    agyary, _source, rule = await _start_recurring(db, seeded)

    expected = _greg(agyary, START_MAH + mobed_dashboard.RECURRENCE_HORIZON_MONTHS)
    assert rule.last_generated_until == expected


async def test_names_and_behdin_carry_to_every_instance(db, seeded):
    agyary, source, rule = await _start_recurring(db, seeded)

    for instance in await _instances(db, rule):
        assert instance.customer_id == source.customer_id
        assert instance.purpose == source.purpose
        names = await mobed_dashboard._names_as_dicts(db, machi_id=instance.id)
        assert [n["name"] for n in names] == ["Kaikhushru", "Hormazd"]


# ---------------------------------------------------------------------------
# Top-up on read
# ---------------------------------------------------------------------------
async def test_reading_past_the_horizon_generates_the_missing_months(db, seeded):
    """The reason this exists: without it a standing arrangement stops at
    the horizon and the mobed simply finds nothing in the fourth month."""
    agyary, _source, rule = await _start_recurring(db, seeded)
    before = len(await _instances(db, rule))

    through = _greg(agyary, START_MAH + 8)
    created = await mobed_dashboard.ensure_recurrences_generated(
        db, agyary.id, through=through
    )

    assert created > 0
    assert len(await _instances(db, rule)) == before + created
    assert rule.last_generated_until >= through


async def test_topping_up_twice_creates_nothing_the_second_time(db, seeded):
    agyary, _source, rule = await _start_recurring(db, seeded)
    through = _greg(agyary, START_MAH + 6)

    first = await mobed_dashboard.ensure_recurrences_generated(db, agyary.id, through=through)
    assert first > 0
    second = await mobed_dashboard.ensure_recurrences_generated(db, agyary.id, through=through)
    assert second == 0


async def test_reading_within_the_horizon_generates_nothing(db, seeded):
    agyary, _source, rule = await _start_recurring(db, seeded)
    through = _greg(agyary, START_MAH + 1)
    assert await mobed_dashboard.ensure_recurrences_generated(db, agyary.id, through=through) == 0


async def test_a_taken_slot_is_skipped_without_stalling_the_marker(db, seeded):
    """Somebody else holds that geh. The month is still done with - retrying
    it on every calendar render would be churn that never succeeds."""
    agyary, _source, rule = await _start_recurring(db, seeded)

    # Occupy the month after the horizon, before the recurrence reaches it.
    blocked_mah = START_MAH + mobed_dashboard.RECURRENCE_HORIZON_MONTHS + 1
    other = await booking_service.create_customer(db, "+919900055555", "Behdin Other")
    taken = await booking_service.book_machi_slot(
        db, agyary, other, roj=ROJ, mah=blocked_mah, year=YEAR, geh=GEH,
        gregorian=_greg(agyary, blocked_mah), purpose="patet", names=[],
    )
    assert taken.machi is not None, "the blocking machi should book"

    through = _greg(agyary, blocked_mah + 1)
    await mobed_dashboard.ensure_recurrences_generated(db, agyary.id, through=through)

    # The marker moved past the blocked month rather than sticking on it...
    assert rule.last_generated_until >= _greg(agyary, blocked_mah)
    # ...and the slot still belongs to whoever took it.
    held = (
        await db.execute(
            select(Machi).where(
                Machi.agyary_id == agyary.id, Machi.parsi_mah == blocked_mah,
                Machi.parsi_roj == ROJ, Machi.geh == GEH, Machi.parsi_year == YEAR,
            )
        )
    ).scalars().all()
    assert len(held) == 1 and held[0].customer_id == other.id


async def test_generation_is_capped_per_request(db, seeded):
    """Opening the calendar on a date years out must not materialise
    hundreds of rows inside one page load."""
    agyary, _source, rule = await _start_recurring(db, seeded)

    far = _greg(agyary, START_MAH, year=YEAR + 20)
    created = await mobed_dashboard.ensure_recurrences_generated(db, agyary.id, through=far)

    assert created <= mobed_dashboard.MAX_GENERATE_MONTHS
    assert rule.last_generated_until < far  # more work left for the next read


async def test_the_year_rolls_over_after_mah_twelve(db, seeded):
    agyary, _source, rule = await _start_recurring(db, seeded, mah=11)

    instances = await _instances(db, rule)
    assert [(m.parsi_mah, m.parsi_year) for m in instances] == [
        (12, YEAR),
        (1, YEAR + 1),
        (2, YEAR + 1),
    ]


async def test_an_end_date_stops_generation(db, seeded):
    agyary, _source, rule = await _start_recurring(db, seeded)
    rule.end_date = _greg(agyary, START_MAH + 5)
    await db.flush()

    await mobed_dashboard.ensure_recurrences_generated(
        db, agyary.id, through=_greg(agyary, START_MAH + 10)
    )
    assert rule.last_generated_until <= rule.end_date


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------
async def test_the_board_returns_instances_past_the_horizon(db, client, seeded):
    """End to end: the mobed steps the calendar into a month nothing has
    generated yet, and the machi is there."""
    from tests.test_mobed_api import _member_headers

    agyary, _source, rule = await _start_recurring(db, seeded)
    await db.commit()

    target = _greg(agyary, START_MAH + 7)
    headers = await _member_headers(client, seeded)
    r = await client.get(
        f"/api/mobed/agyaries/{agyary.id}/machi-board",
        params={"from": target.isoformat(), "to": target.isoformat()},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    days = [m["gregorian_date"] for m in r.json()]
    assert target.isoformat() in days, "the recurrence should have been topped up on read"


async def test_a_booking_sourced_rule_is_left_alone(db, seeded):
    """The schema allows a recurrence sourced from a booking rather than a
    machi. Nothing creates one yet, but this generator cannot service it and
    must not treat it as a machi rule with a missing source - which would
    quietly deactivate a perfectly good rule the day someone adds them."""
    agyary, _source, machi_rule = await _start_recurring(db, seeded)

    booked = await mobed_dashboard.manual_add_booking(
        db, agyary, 1,
        behdin_phone="+919900066666", behdin_name="Behdin Booking",
        service_id=2, ceremony_dt_local=datetime(2027, 3, 4, 10, 0),
        purpose="khushali_nu", names=[], location=None, is_offsite=False,
    )
    assert booked is not None
    booking_rule = RecurrenceRule(
        agyary_id=agyary.id,
        source_booking_id=booked.booking.id,
        pattern="same_roj_every_mah",
        end_type="indefinite",
    )
    db.add(booking_rule)
    await db.flush()

    await mobed_dashboard.ensure_recurrences_generated(
        db, agyary.id, through=_greg(agyary, START_MAH + 8)
    )

    assert booking_rule.is_active is True
    assert booking_rule.last_generated_until is None
    # The machi rule beside it still generated normally.
    assert machi_rule.last_generated_until > _greg(agyary, START_MAH + 3)
