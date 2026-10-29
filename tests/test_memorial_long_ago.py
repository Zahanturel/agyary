"""Memorials for someone who died more than a year ago.

Most of the behdins a mobed keeps prayers for are old people whose monthly and
yearly prayers have run for years. Their death is given by Roj and Mah alone -
no date, no year - the opening and named days have long gone, and the prayers
that repeat carry on from today. The date and year stored for them are
stand-ins and must never reach a screen, a message or a PDF.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from agyary.models import Memorial
from agyary.services import memorial_share, memorials
from tests.test_memorial_api import _create, _service_ids, _setup

ROJ, MAH = 4, 5


def _old(**over) -> dict:
    body = {
        "departed_name": "Late Dinshaw", "long_ago": True, "death_roj": ROJ, "death_mah": MAH,
        "monthly": {"count": 24}, "yearly": {"count": 3}, "service_ids": [],
    }
    body.update(over)
    return body


async def _preview(client, aid, headers, **over):
    return await client.post(f"/api/mobed/agyaries/{aid}/memorials/preview", json=_old(**over), headers=headers)


async def test_the_schedule_runs_forward_from_today_with_plain_labels(client, db, seeded):
    aid, _, headers = await _setup(client, db, seeded)
    r = await _preview(client, aid, headers)
    assert r.status_code == 200, r.text
    out = r.json()
    today = memorials.today_ist().isoformat()
    assert out["long_ago"] is True
    assert all(o["date"] >= today for o in out["observances"]), "nothing in the past is booked"
    # Plain names: a count from a stand-in death would be a made-up number.
    assert {o["label"] for o in out["observances"]} <= {"Monthly", "Yearly"}
    # Monthly is the same Roj every Mah, and yearly the same Roj and Mah.
    assert all(o["roj"] == ROJ for o in out["observances"])
    yearly = [o for o in out["observances"] if o["label"] == "Yearly"]
    assert len(yearly) == 3 and all(o["mah"] == MAH for o in yearly)
    # 24 monthly dates ahead, of which every twelfth is the yearly one: 24 + 3 - overlap.
    assert out["count"] == len(out["observances"]) and 24 <= out["count"] <= 27


async def test_no_date_or_year_is_given_back(client, db, seeded):
    aid, _, headers = await _setup(client, db, seeded)
    out = (await _preview(client, aid, headers)).json()
    assert out["death_date"] is None and out["death"]["year"] is None
    assert (out["death"]["roj"], out["death"]["mah"]) == (ROJ, MAH)


async def test_the_opening_and_named_days_are_refused(client, db, seeded):
    aid, _, headers = await _setup(client, db, seeded)
    for bad in ({"opening": "days_5_to_9"}, {"day_counts": [10]}, {"day_counts": [360]}):
        r = await _preview(client, aid, headers, **bad)
        assert r.status_code == 400, (bad, r.text)
        assert "passed" in r.json()["detail"]


async def test_only_roj_and_mah_are_accepted(client, db, seeded):
    aid, _, headers = await _setup(client, db, seeded)
    for bad in ({"death_date": "2001-05-01"}, {"death_year": 1370}):
        r = await _preview(client, aid, headers, **bad)
        assert r.status_code == 400, (bad, r.text)
    r = await _preview(client, aid, headers, death_roj=None, death_mah=None)
    assert r.status_code == 400


async def test_something_must_repeat(client, db, seeded):
    aid, _, headers = await _setup(client, db, seeded)
    r = await _preview(client, aid, headers, monthly=None, yearly=None)
    assert r.status_code == 400


async def test_parabs_roj_fravardin_and_the_birthday_carry_on_too(client, db, seeded):
    aid, _, headers = await _setup(client, db, seeded)
    r = await _preview(client, aid, headers, monthly=None, yearly=None,
                       parabs={"which": "all", "years": 2}, fravardin_roj={"count": 6},
                       birthday={"roj": 9, "mah": 2, "years": 3})
    assert r.status_code == 200, r.text
    labels = {o["label"] for o in r.json()["observances"]}
    assert "Roj Fravardin" in labels and "Birthday" in labels
    assert any(label.endswith("Parab") for label in labels)
    today = memorials.today_ist().isoformat()
    assert all(o["date"] >= today for o in r.json()["observances"])


async def test_series_can_run_for_decades(client, db, seeded):
    aid, _, headers = await _setup(client, db, seeded)
    assert (await _preview(client, aid, headers, monthly={"count": 600}, yearly={"count": 100})).status_code == 200
    assert (await _preview(client, aid, headers, yearly={"count": 101}, monthly=None)).status_code == 400
    assert (await _preview(client, aid, headers, monthly={"count": 1201}, yearly=None)).status_code == 400


async def test_it_is_saved_without_a_date_and_never_shown_with_one(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    ids = await _service_ids(db, aid, "Afringan", "Baaj")
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials",
                          json=_old(service_ids=ids), headers=headers)
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["long_ago"] is True and made["death_date"] is None and made["death"]["year"] is None
    assert {o["label"] for o in made["observances"]} <= {"Monthly", "Yearly"}

    row = (await db.execute(select(Memorial))).scalar_one()
    assert row.died_over_a_year_ago is True        # the stand-in is stored, flagged...
    assert row.death_gregorian <= memorials.today_ist() - timedelta(days=361)   # ...and a year or more back

    text = memorial_share.message_text(made, agyary_name="Goti Adarian", mobed_name="Er. Test")
    assert "Remembered on Roj" in text and "Passed away on" not in text
    stand_in = str(row.death_gregorian.year)
    assert stand_in not in memorial_share.message_text(made, agyary_name="A", mobed_name="B").split("\n")[2]
    assert memorial_share.render_pdf(made, agyary_name="Goti Adarian", mobed_name="Er. Test")[:4] == b"%PDF"


async def test_a_dated_memorial_is_unchanged(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    made = (await _create(client, db, aid, cid, headers, death=date(2030, 3, 10))).json()
    assert made["long_ago"] is False and made["death_date"] == "2030-03-10"
    text = memorial_share.message_text(made, agyary_name="A", mobed_name="B")
    assert "Passed away on" in text and "2030" in text


# --- which days have passed (the greyed-out options) ------------------------------


async def _status(client, aid, headers, **body):
    r = await client.post(f"/api/mobed/agyaries/{aid}/memorials/day-status", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["passed"]


async def test_everything_has_passed_for_a_death_over_a_year_ago(client, db, seeded):
    aid, _, headers = await _setup(client, db, seeded)
    passed = await _status(client, aid, headers, long_ago=True, death_roj=ROJ, death_mah=MAH)
    assert passed and all(passed.values())
    assert {"5_to_9", "10", "30", "360"} <= set(passed)


async def test_days_pass_one_by_one_after_a_recent_death(client, db, seeded):
    aid, _, headers = await _setup(client, db, seeded)
    today = memorials.today_ist()
    passed = await _status(client, aid, headers, death_date=(today - timedelta(days=45)).isoformat())
    assert passed["5_to_9"] and passed["10"] and passed["29"] and passed["30"]
    assert not passed["60"] and not passed["180"] and not passed["360"]


async def test_nothing_has_passed_on_the_day_of_death(client, db, seeded):
    aid, _, headers = await _setup(client, db, seeded)
    passed = await _status(client, aid, headers, death_date=memorials.today_ist().isoformat())
    assert not any(passed.values())


async def test_day_status_is_for_signed_in_mobeds_only(client, db, seeded):
    aid, _, _ = await _setup(client, db, seeded)
    r = await client.post(f"/api/mobed/agyaries/{aid}/memorials/day-status", json={"death_date": "2030-01-01"})
    assert r.status_code in (401, 403)
