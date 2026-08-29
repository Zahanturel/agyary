"""The calendar's window must reach the past.

/my-day used to ignore from/to and always answer with the 12-hour-horizon
"upcoming" list, so a mobed scrolling back a month saw an empty calendar and
this morning's ceremonies vanished from today by evening. Every other test
books in 2027/2028, which is why nothing caught it.
"""
from datetime import datetime, timedelta

from agyary.messaging.geh_times import IST
from tests.test_mobed_api import _member_headers


def _payload(dt, who):
    return {
        "behdin_phone": "+919922200003", "behdin_name": who,
        "service_id": 2,  # Jashan, per seed_demo order
        "ceremony_datetime": dt.isoformat(),
        "purpose": "khushali_nu",
        "names": [{"section": "farmayeshne", "title": "behdin", "name": "X",
                   "status": "living", "pair_group": None}],
        "location": None, "is_offsite": False,
    }


async def _book(client, aid, headers, dt, label):
    r = await client.post(f"/api/mobed/agyaries/{aid}/manual-add/booking",
                          json=_payload(dt, label), headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["booking_id"]


async def test_window_includes_past_days(db, client, seeded):
    headers = await _member_headers(client, seeded)
    aid, now = seeded["agyary_id"], datetime.now(IST)

    long_ago = await _book(client, aid, headers, now - timedelta(days=3), "long ago")
    this_morning = await _book(client, aid, headers, now - timedelta(hours=14), "this morning")
    upcoming = await _book(client, aid, headers, now + timedelta(days=7), "upcoming")

    lo, hi = (now - timedelta(days=10)).date(), (now + timedelta(days=10)).date()
    windowed = {e["booking_id"] for e in
                (await client.get(f"/api/mobed/my-day?from={lo}&to={hi}", headers=headers)).json()}
    assert windowed == {long_ago, this_morning, upcoming}

    # No window is still the upcoming list - the horizon behaviour is intact.
    bare = {e["booking_id"] for e in
            (await client.get("/api/mobed/my-day", headers=headers)).json()}
    assert bare == {upcoming}


async def test_window_boundaries_are_ist_days_inclusive(db, client, seeded):
    headers = await _member_headers(client, seeded)
    aid, now = seeded["agyary_id"], datetime.now(IST)

    # 00:30 and 23:30 IST on the same past day: both belong to that day, and
    # neither leaks into the neighbouring one. A UTC-anchored boundary would
    # push the 00:30 booking into the previous day (IST is UTC+5:30).
    day = (now - timedelta(days=5)).date()
    early = await _book(client, aid, headers,
                        datetime.combine(day, datetime.min.time(), IST) + timedelta(minutes=30),
                        "early")
    late = await _book(client, aid, headers,
                       datetime.combine(day, datetime.min.time(), IST) + timedelta(hours=23, minutes=30),
                       "late")

    same = {e["booking_id"] for e in
            (await client.get(f"/api/mobed/my-day?from={day}&to={day}", headers=headers)).json()}
    assert same == {early, late}

    after = day + timedelta(days=1)
    before = day - timedelta(days=1)
    for lo, hi in ((after, after), (before, before)):
        assert (await client.get(f"/api/mobed/my-day?from={lo}&to={hi}", headers=headers)).json() == []


async def test_window_rejects_nonsense(db, client, seeded):
    headers = await _member_headers(client, seeded)
    today = datetime.now(IST).date()

    # Half-open: answering with the upcoming list is how this hid for so long.
    assert (await client.get(f"/api/mobed/my-day?from={today}", headers=headers)).status_code == 400
    assert (await client.get(f"/api/mobed/my-day?to={today}", headers=headers)).status_code == 400
    # Reversed.
    assert (await client.get(
        f"/api/mobed/my-day?from={today}&to={today - timedelta(days=1)}",
        headers=headers)).status_code == 400
    # Wider than the cap.
    assert (await client.get(
        f"/api/mobed/my-day?from={today}&to={today + timedelta(days=400)}",
        headers=headers)).status_code == 400
