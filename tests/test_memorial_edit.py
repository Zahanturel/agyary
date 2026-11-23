"""Editing a memorial after it is saved (17 Nov 2026): one date moved to another
day or taken out, or the whole memorial re-worked from changed choices.

The owner's rules: a re-work counts EVERY date again from the death, past ones
included; what the mobed set on a date (prayers, time, note, paid) carries over
to the same date by its code; dates they took out stay out; a date they moved
by hand stays where they put it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from agyary.calendar import CalendarSystem, gregorian_to_parsi
from agyary.models import Memorial, MemorialObservance, Notification
from agyary.services import memorials
from tests.test_memorial_api import DEATH, OTHER_MOBED, _create, _service_ids, _setup
from tests.test_mobed_api import _member_headers


def _url(aid, mid, tail=""):
    return f"/api/mobed/agyaries/{aid}/memorials/{mid}{tail}"


async def _made(client, db, seeded, **over):
    aid, cid, headers = await _setup(client, db, seeded)
    r = await _create(client, db, aid, cid, headers, **over)
    assert r.status_code == 200, r.text
    return aid, cid, headers, r.json()


async def _form(client, aid, mid, headers):
    r = await client.get(_url(aid, mid, "/edit"), headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _edit_body(form, **over):
    """The edit form's answers sent back as they stand, with ``over`` changed."""
    long_ago = form["long_ago"]
    body = {
        "departed_name": form["departed_name"],
        "long_ago": long_ago,
        "death_date": form["death_date"],
        "death_roj": form["death"]["roj"] if long_ago else None,
        "death_mah": form["death"]["mah"] if long_ago else None,
        "calendar": form["calendar"],
        "opening": form["opening"],
        "day_counts": form["day_counts"],
        "monthly": {"count": form["monthly_months"]} if form["monthly_months"] else None,
        "yearly": {"count": form["yearly_years"]} if form["yearly_years"] else None,
        "fravardin_roj": {"count": form["fravardin_roj_months"]} if form["fravardin_roj_months"] else None,
        "parabs": {"which": form["parabs"], "count": form["parab_count"]} if form["parabs"] else None,
        "birthday": form["birthday"],
        "start_from": form["start_from"],
        "service_ids": form["service_ids"],
    }
    body.update(over)
    return body


async def _edit(client, aid, mid, headers, **over):
    form = await _form(client, aid, mid, headers)
    return await client.put(_url(aid, mid), json=_edit_body(form, **over), headers=headers)


async def _preview(client, aid, mid, headers, **over):
    form = await _form(client, aid, mid, headers)
    return await client.post(_url(aid, mid, "/edit/preview"), json=_edit_body(form, **over), headers=headers)


def _by_label(memorial: dict) -> dict:
    return {o["label"]: o for o in memorial["observances"]}


def _shift(iso: str, days: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


# --- One date taken out -------------------------------------------------------

async def test_one_date_can_be_taken_out_and_stays_out_until_put_back(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    mid = made["id"]
    masiso = _by_label(made)["Masiso"]

    r = await client.delete(_url(aid, mid, f"/observances/{masiso['id']}"), headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 12 and "Masiso" not in _by_label(r.json())
    assert (await db.get(Memorial, mid)).removed_codes == ["day_30"]

    # A longer monthly series does not bring it back: it is listed as left out.
    pv = (await _preview(client, aid, mid, headers, monthly={"count": 4})).json()
    assert [o["code"] for o in pv["left_out"]] == ["day_30"]
    r = await _edit(client, aid, mid, headers, monthly={"count": 4})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 13 and "Masiso" not in _by_label(r.json())

    # Put back from the Edit screen.
    r = await _edit(client, aid, mid, headers, monthly={"count": 4}, restore_codes=["day_30"])
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 14 and "Masiso" in _by_label(r.json())
    assert (await db.get(Memorial, mid)).removed_codes == []


async def test_the_only_date_cannot_be_taken_out(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded, opening="none", day_counts=[10], monthly=None)
    assert made["total"] == 1
    r = await client.delete(_url(aid, made["id"], f"/observances/{made['observances'][0]['id']}"), headers=headers)
    assert r.status_code == 400 and "delete the memorial" in r.json()["detail"]
    assert (await client.get(_url(aid, made["id"]), headers=headers)).json()["total"] == 1


async def test_taking_out_the_last_date_moves_the_closing_notice(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    last, before = made["observances"][-1], made["observances"][-2]
    r = await client.delete(_url(aid, made["id"], f"/observances/{last['id']}"), headers=headers)
    assert r.json()["last_date"] == before["date"]
    feed = (await client.get(f"/api/mobed/agyaries/{aid}/memorial-feed",
                             params={"from": DEATH.isoformat(), "to": _shift(DEATH.isoformat(), 200)},
                             headers=headers)).json()
    closing = [i for i in feed if i["kind"] == "memorial_closing"]
    assert [c["date"] for c in closing] == [before["date"]]


# --- One date moved -------------------------------------------------------------

async def test_a_date_can_be_moved_and_put_back_on_its_usual_day(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    mid = made["id"]
    masiso = _by_label(made)["Masiso"]
    url = _url(aid, mid, f"/observances/{masiso['id']}")

    to = _shift(masiso["date"], 2)
    r = await client.patch(url, json={"move_to": to}, headers=headers)
    assert r.status_code == 200, r.text
    moved = r.json()
    assert moved["date"] == to and moved["moved_by_hand"] is True
    p = gregorian_to_parsi(date.fromisoformat(to), CalendarSystem(made["calendar"]))
    assert (moved["roj"], moved["mah"]) == (p.roj, p.mah)

    # A corrected death moves every other date, but not the one moved by hand.
    r = await _edit(client, aid, mid, headers, death_date=_shift(DEATH.isoformat(), 1))
    assert r.status_code == 200, r.text
    after = _by_label(r.json())
    assert after["Masiso"]["date"] == to and after["Masiso"]["id"] == masiso["id"]
    assert after["Day 1"]["date"] == _shift(DEATH.isoformat(), 1)

    # Back to its usual day: the day the corrected schedule gives it.
    r = await client.patch(url, json={"back_to_usual_day": True}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["date"] == _shift(masiso["date"], 1) and r.json()["moved_by_hand"] is False


async def test_a_date_cannot_be_moved_onto_another_date_of_the_memorial(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    day5, day6 = _by_label(made)["Day 5"], _by_label(made)["Day 6"]
    r = await client.patch(_url(aid, made["id"], f"/observances/{day5['id']}"),
                           json={"move_to": day6["date"]}, headers=headers)
    assert r.status_code == 400 and "Day 6 is already on that day" in r.json()["detail"]


async def test_moving_a_date_forgets_the_reminder_for_its_old_day(client, db, seeded):
    aid, cid, headers, made = await _made(client, db, seeded)
    masiso = _by_label(made)["Masiso"]
    r = await client.put(f"/api/mobed/agyaries/{aid}/memorial-observances/{masiso['id']}/reminded",
                         json={"reminded": True}, headers=headers)
    assert r.status_code == 200
    db.add(Notification(
        agyary_id=aid, recipient_phone="+919944400701", recipient_type="customer", recipient_id=cid,
        notification_type="memorial_reminder", template_name="memorial_reminder_v3",
        memorial_observance_id=masiso["id"], scheduled_at=datetime.now(timezone.utc), status="sent",
    ))
    await db.commit()

    r = await client.patch(_url(aid, made["id"], f"/observances/{masiso['id']}"),
                           json={"move_to": _shift(masiso["date"], 3)}, headers=headers)
    assert r.status_code == 200, r.text
    row = await db.get(MemorialObservance, masiso["id"])
    assert row.reminded_by_hand_at is None
    linked = (await db.execute(select(Notification.memorial_observance_id))).scalars().all()
    assert linked == [None]   # kept on record, but no longer stands for the new day


# --- The whole memorial ------------------------------------------------------------

async def test_the_edit_form_reads_back_what_was_chosen(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    form = await _form(client, aid, made["id"], headers)
    afringan, baaj = await _service_ids(db, aid, "Afringan", "Baaj")
    assert form["departed_name"] == "Dinshaw" and form["death_date"] == DEATH.isoformat()
    assert form["opening"] == "days_1_to_10" and form["day_counts"] == [30] and form["monthly_months"] == 3
    assert form["service_ids"] == sorted([afringan, baaj])
    assert form["start_from"] is None and form["removed_count"] == 0


async def test_a_new_name_changes_no_date(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    mid = made["id"]
    first, masiso = made["observances"][0], _by_label(made)["Masiso"]
    await client.put(_url(aid, mid, f"/observances/{first['id']}/paid"), json={"paid": True}, headers=headers)
    await client.patch(_url(aid, mid, f"/observances/{masiso['id']}"), json={"notes": "Bring flowers"}, headers=headers)

    pv = (await _preview(client, aid, mid, headers, departed_name="Dinshaw Dadachanji")).json()
    assert {o["status"] for o in pv["observances"]} == {"same"} and pv["dropped"] == []

    r = await _edit(client, aid, mid, headers, departed_name="Dinshaw Dadachanji")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["departed_name"] == "Dinshaw Dadachanji"
    assert [(o["id"], o["date"]) for o in out["observances"]] == [(o["id"], o["date"]) for o in made["observances"]]
    assert out["observances"][0]["paid"] is True and _by_label(out)["Masiso"]["notes"] == "Bring flowers"


async def test_a_corrected_death_moves_every_date_and_keeps_what_was_set_on_each(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    mid = made["id"]
    masiso, day5 = _by_label(made)["Masiso"], _by_label(made)["Day 5"]
    (farokshi,) = await _service_ids(db, aid, "Farokshi")
    await client.put(_url(aid, mid, f"/observances/{masiso['id']}/paid"), json={"paid": True}, headers=headers)
    await client.patch(_url(aid, mid, f"/observances/{masiso['id']}"),
                       json={"time": "07:15", "notes": "At home"}, headers=headers)
    await client.patch(_url(aid, mid, f"/observances/{day5['id']}"), json={"service_ids": [farokshi]}, headers=headers)

    corrected = _shift(DEATH.isoformat(), 3)
    pv = (await _preview(client, aid, mid, headers, death_date=corrected)).json()
    assert {o["status"] for o in pv["observances"]} == {"moved"}
    assert all(o["old_date"] == _shift(o["date"], -3) for o in pv["observances"])
    # The preview saved nothing.
    assert (await client.get(_url(aid, mid), headers=headers)).json()["observances"][0]["date"] == DEATH.isoformat()

    r = await _edit(client, aid, mid, headers, death_date=corrected)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["death_date"] == corrected
    assert [(o["id"], o["date"]) for o in out["observances"]] == [
        (o["id"], _shift(o["date"], 3)) for o in made["observances"]]
    after = _by_label(out)
    assert after["Masiso"]["paid"] is True and after["Masiso"]["time"] == "07:15"
    assert after["Masiso"]["notes"] == "At home" and after["Day 5"]["service_ids"] == [farokshi]


async def test_a_death_put_earlier_reworks_past_dates_too(client, db, seeded):
    """Re-work every date, past ones included (the owner's choice)."""
    aid, cid, headers = await _setup(client, db, seeded)
    death = memorials.today_ist() - timedelta(days=40)
    r = await _create(client, db, aid, cid, headers, death=death, opening="none", day_counts=[10, 30], monthly=None)
    assert r.status_code == 200, r.text
    made = r.json()
    r = await _edit(client, aid, made["id"], headers, death_date=(death - timedelta(days=2)).isoformat())
    assert r.status_code == 200, r.text
    assert [(o["id"], o["date"]) for o in r.json()["observances"]] == [
        (o["id"], _shift(o["date"], -2)) for o in made["observances"]]


async def test_shortening_a_series_takes_its_dates_off_and_lengthening_adds_them(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    mid = made["id"]
    month3 = _by_label(made)["Month 3"]
    pv = (await _preview(client, aid, mid, headers, monthly={"count": 2})).json()
    assert [d["code"] for d in pv["dropped"]] == ["month_3"]
    r = await _edit(client, aid, mid, headers, monthly={"count": 2})
    assert r.status_code == 200 and r.json()["total"] == 12
    assert (await db.get(MemorialObservance, month3["id"])) is None

    (farokshi,) = await _service_ids(db, aid, "Farokshi")
    pv = (await _preview(client, aid, mid, headers, monthly={"count": 5})).json()
    assert sorted(o["code"] for o in pv["observances"] if o["status"] == "new") == ["month_3", "month_4", "month_5"]
    r = await _edit(client, aid, mid, headers, monthly={"count": 5}, service_ids=[farokshi])
    assert r.status_code == 200, r.text
    out = _by_label(r.json())
    assert all(out[f"Month {k}"]["service_ids"] == [farokshi] for k in (3, 4, 5))
    assert len(out["Day 1"]["service_ids"]) == 2   # dates already there keep their prayers


async def test_new_dates_follow_the_jashan_rule(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    (jashan,) = await _service_ids(db, aid, "Jashan")
    r = await _edit(client, aid, made["id"], headers, day_counts=[29, 30], service_ids=[jashan])
    assert r.status_code == 400 and "Jashan" in r.json()["detail"]
    r = await _edit(client, aid, made["id"], headers, monthly={"count": 4}, service_ids=[jashan])
    assert r.status_code == 200, r.text   # a monthly day may have Jashan alone


async def test_dates_changed_on_the_review_screen_are_saved(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    mid = made["id"]
    day2 = _by_label(made)["Day 2"]
    (satum,) = await _service_ids(db, aid, "Satum")
    r = await _edit(client, aid, mid, headers, exclude_codes=["day_3"], service_overrides={"day_2": [satum]})
    assert r.status_code == 200, r.text
    out = _by_label(r.json())
    assert "Day 3" not in out and out["Day 2"]["service_ids"] == [satum] and out["Day 2"]["id"] == day2["id"]
    assert (await db.get(Memorial, mid)).removed_codes == ["day_3"]


async def test_taking_every_date_out_in_an_edit_is_refused(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    every = [o["code"] for o in made["observances"]]
    r = await _edit(client, aid, made["id"], headers, exclude_codes=every)
    assert r.status_code == 400
    assert (await client.get(_url(aid, made["id"]), headers=headers)).json()["total"] == made["total"]


async def test_dates_taken_out_when_it_was_made_stay_out(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded, exclude_codes=["day_5"])
    assert "Day 5" not in _by_label(made)
    assert (await _form(client, aid, made["id"], headers))["removed_count"] == 1
    r = await _edit(client, aid, made["id"], headers, departed_name="Dinshaw B.")
    assert "Day 5" not in _by_label(r.json()) and r.json()["total"] == made["total"]


async def test_another_calendar_reads_every_date_again(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded, calendar="shenshai")
    r = await _edit(client, aid, made["id"], headers, calendar="kadmi")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["calendar"] == "kadmi"
    p = gregorian_to_parsi(DEATH, CalendarSystem.KADMI)
    assert (out["observances"][0]["roj"], out["observances"][0]["mah"]) == (p.roj, p.mah)


async def test_parabs_saved_as_years_read_back_as_the_same_dates(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded, monthly=None, parabs={"which": "all", "years": 1})
    form = await _form(client, aid, made["id"], headers)
    assert form["parab_count"] == 12
    pv = (await _preview(client, aid, made["id"], headers)).json()
    assert {o["status"] for o in pv["observances"]} == {"same"} and pv["dropped"] == []


# --- Memorials saved before edits existed --------------------------------------

async def _as_if_saved_before_edits(db, mid):
    m = await db.get(Memorial, mid)
    m.removed_codes, m.start_from = None, None
    await db.commit()


async def test_an_older_memorial_keeps_out_what_its_review_took_out(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded, exclude_codes=["day_5"])
    await _as_if_saved_before_edits(db, made["id"])
    assert (await _form(client, aid, made["id"], headers))["removed_count"] == 1
    r = await _edit(client, aid, made["id"], headers, departed_name="Dinshaw B.")
    assert r.status_code == 200, r.text
    assert "Day 5" not in _by_label(r.json())
    assert (await db.get(Memorial, made["id"])).removed_codes == ["day_5"]


async def test_an_older_memorial_that_started_late_still_starts_late(client, db, seeded):
    aid, cid, headers = await _setup(client, db, seeded)
    today = memorials.today_ist()
    r = await _create(client, db, aid, cid, headers, death=today - timedelta(days=100), opening="none",
                      day_counts=[10, 30], monthly={"count": 3}, start_from=today.isoformat())
    assert r.status_code == 200, r.text
    made = r.json()
    await _as_if_saved_before_edits(db, made["id"])
    assert (await _form(client, aid, made["id"], headers))["start_from"] == today.isoformat()
    r = await _edit(client, aid, made["id"], headers, departed_name="Late start")
    assert r.status_code == 200, r.text
    assert [o["id"] for o in r.json()["observances"]] == [o["id"] for o in made["observances"]]
    assert all(o["date"] >= today.isoformat() for o in r.json()["observances"])


async def test_an_older_memorial_can_have_one_date_taken_out(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded, exclude_codes=["day_5"])
    await _as_if_saved_before_edits(db, made["id"])
    day6 = _by_label(made)["Day 6"]
    r = await client.delete(_url(aid, made["id"], f"/observances/{day6['id']}"), headers=headers)
    assert r.status_code == 200, r.text
    assert (await db.get(Memorial, made["id"])).removed_codes == ["day_5", "day_6"]


# --- A death more than a year ago -------------------------------------------------

def _old(ids, **over):
    body = {"departed_name": "Late Dinshaw", "long_ago": True, "death_roj": 4, "death_mah": 5,
            "monthly": {"count": 24}, "yearly": {"count": 3}, "service_ids": ids}
    body.update(over)
    return body


async def test_a_death_long_ago_keeps_its_dates_when_edited_later(client, db, seeded, monkeypatch):
    aid, cid, headers = await _setup(client, db, seeded)
    ids = await _service_ids(db, aid, "Afringan")
    r = await client.post(f"/api/mobed/agyaries/{aid}/behdins/{cid}/memorials", json=_old(ids), headers=headers)
    assert r.status_code == 200, r.text
    made = r.json()
    mid = made["id"]
    form = await _form(client, aid, mid, headers)
    assert form["death_date"] is None and form["start_from"] == memorials.today_ist().isoformat()

    # Edited a year and more later, a new name changes no date: the stand-in death does not drift.
    later = memorials.today_ist() + timedelta(days=400)
    monkeypatch.setattr(memorials, "today_ist", lambda: later)
    r = await _edit(client, aid, mid, headers, departed_name="Late Dinshaw B.")
    assert r.status_code == 200, r.text
    assert [(o["id"], o["date"]) for o in r.json()["observances"]] == [
        (o["id"], o["date"]) for o in made["observances"]]

    # Nor for one saved before edits existed.
    await _as_if_saved_before_edits(db, mid)
    r = await _edit(client, aid, mid, headers, monthly={"count": 30})
    assert r.status_code == 200, r.text
    ids_after = {o["id"] for o in r.json()["observances"]}
    assert {o["id"] for o in made["observances"]} <= ids_after and r.json()["total"] > made["total"]

    # A corrected Roj moves them all.
    r = await _edit(client, aid, mid, headers, death_roj=6)
    assert r.status_code == 200, r.text
    assert all(o["roj"] == 6 for o in r.json()["observances"])
    assert r.json()["death_date"] is None


# --- Privacy ----------------------------------------------------------------------

async def test_another_mobed_cannot_edit_or_take_out_dates(client, db, seeded):
    aid, _, headers, made = await _made(client, db, seeded)
    mid, oid = made["id"], made["observances"][0]["id"]
    form = await _form(client, aid, mid, headers)
    other = await _member_headers(client, seeded, name="Other", phone=OTHER_MOBED)
    assert (await client.get(_url(aid, mid, "/edit"), headers=other)).status_code == 404
    assert (await client.post(_url(aid, mid, "/edit/preview"), json=_edit_body(form), headers=other)).status_code == 404
    assert (await client.put(_url(aid, mid), json=_edit_body(form, departed_name="X"), headers=other)).status_code == 404
    assert (await client.delete(_url(aid, mid, f"/observances/{oid}"), headers=other)).status_code == 404
    assert (await client.patch(_url(aid, mid, f"/observances/{oid}"), json={"move_to": "2031-01-01"},
                               headers=other)).status_code == 404
    assert (await client.get(_url(aid, mid), headers=headers)).json()["departed_name"] == "Dinshaw"
    r = await client.delete(_url(aid, mid, "/observances/999999"), headers=headers)
    assert r.status_code == 404
