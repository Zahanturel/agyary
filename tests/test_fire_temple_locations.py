"""The fire temples' town-level starting positions (agyary.scripts.seed_fire_temple_locations).

Matched by name and city exactly as the fire-temple seed stored them, filled
only where there is no position yet, never over a pin a person dropped, and a
dry run unless asked to write.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from agyary.models import Agyary
from agyary.scripts import seed_fire_temple_locations as locations
from agyary.scripts import seed_fire_temples

ROOT = Path(__file__).resolve().parent.parent


async def _all(db) -> dict[tuple[str, str], Agyary]:
    db.expire_all()
    return {(a.name, a.city): a for a in (await db.execute(select(Agyary))).scalars().all()}


def test_the_list_shipped_with_the_app_is_the_one_in_the_docs():
    """The server has no docs/ folder, so the script reads its own copy; the two
    must not drift apart."""
    shipped = locations.DATA.read_bytes()
    assert shipped == (ROOT / "docs" / "phase2-doongerwadi" / "fire-temple-positions.csv").read_bytes()
    report = locations.Report()
    rows = locations.load_rows(locations.DATA, report)
    assert len(rows) == 167 and report.bad_rows == []


async def test_a_dry_run_changes_nothing_and_says_what_it_would_fill(db, seeded):
    await seed_fire_temples.seed(db)
    rows = locations.load_rows()
    report = await locations.fill(db, rows, write=False)
    assert len(report.filled) == 167 and report.not_found == [] and report.ambiguous == []
    assert all(a.latitude is None and a.location_source is None for a in (await _all(db)).values())


async def test_writing_fills_the_seeded_temples_as_town_and_a_second_run_changes_nothing(db, seeded):
    await seed_fire_temples.seed(db)
    rows = locations.load_rows()
    report = await locations.fill(db, rows, write=True)
    assert len(report.filled) == 167

    temples = await _all(db)
    iranshah = temples[("Iranshah", "Udwada")]
    assert (iranshah.latitude, iranshah.longitude, iranshah.location_source) == (20.46214, 72.919, "town")
    assert iranshah.location_set_by_user_id is None and iranshah.location_set_at is not None
    # The demo temple shares its name with a seeded one in another city: not matched, not filled.
    assert temples[("Goti Adarian", "Mumbai")].latitude is None
    assert temples[("Goti Adarian", "Surat")].location_source == "town"

    again = await locations.fill(db, rows, write=True)
    assert again.filled == [] and len(again.already_town) == 167


async def test_a_pin_a_person_dropped_is_never_moved(db, seeded):
    await seed_fire_temples.seed(db)
    temples = await _all(db)
    pinned = temples[("Iranshah", "Udwada")]
    pinned.latitude, pinned.longitude, pinned.location_source = 20.4655, 72.9230, "pin"
    await db.commit()

    report = await locations.fill(db, locations.load_rows(), write=True)
    assert (pinned.id, "Iranshah", "Udwada") in report.already_pin
    assert len(report.filled) == 166
    after = (await _all(db))[("Iranshah", "Udwada")]
    assert (after.latitude, after.longitude, after.location_source) == (20.4655, 72.9230, "pin")


async def test_what_cannot_be_matched_is_listed_not_guessed(db, seeded, tmp_path):
    await seed_fire_temples.seed(db)
    temples = await _all(db)
    # A mobed corrected the name when setting it up.
    temples[("Iranshah", "Udwada")].name = "Iranshah Atash Behram"
    # Two fire temples now share a name and city.
    db.add(Agyary(name="Anjuman Daremeher", city="Surat", status="active"))
    await db.commit()

    csv = tmp_path / "positions.csv"
    csv.write_text(
        "name,city,address,state,latitude,longitude,placed_by\n"
        "Iranshah,Udwada,Udwada Town,Gujerat,20.46214,72.919,town\n"
        "Anjuman Daremeher,Surat,Mandvi,Gujerat,21.20949,72.83171,town\n"
        "Bhagarsath Anjumana,Navsari,Tarota Bazar,Gujerat,95,72.93238,town\n"
        "Seth Pestonji Kalabhai Vakil,Surat,Shahpore,Gujerat,abc,72.83171,town\n"
        "Seth Nosherwanji Dadiseth,Mumbai,Fanaswadi,Maharashtra,0,0,town\n"
        "Seth Hormasji Bomanji Wadia,Mumbai,Dhobi Talao,Maharashtra,18.946,72.829,neighbourhood\n",
        encoding="utf-8", newline="\n",
    )
    report = locations.Report()
    rows = locations.load_rows(csv, report)
    assert [line.split(":")[0] for line in report.bad_rows] == ["line 4", "line 5", "line 6"]
    await locations.fill(db, rows, write=True, report=report)
    assert report.not_found == [("Iranshah", "Udwada")]
    assert report.ambiguous == [("Anjuman Daremeher", "Surat", 2)]
    assert [(n, c) for _, n, c in report.filled] == [("Seth Hormasji Bomanji Wadia", "Mumbai")]
    after = await _all(db)
    assert after[("Iranshah Atash Behram", "Udwada")].latitude is None
    assert all(a.latitude is None for (n, _), a in after.items() if n == "Anjuman Daremeher"
               and a.city == "Surat")
    assert after[("Bhagarsath Anjumana", "Navsari")].latitude is None


def test_the_report_says_plainly_what_happened(capsys):
    report = locations.Report(filled=[(1, "Iranshah", "Udwada")], not_found=[("Iranshah", "Udwada")])
    locations.print_report(report, write=False, total=1)
    out = capsys.readouterr().out
    assert "Would fill 1 of 1" in out and "not found: Iranshah, Udwada" in out and "Dry run" in out
