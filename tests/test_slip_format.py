"""What the printed slip's date line says."""

from datetime import date

from agyary.messaging.formatting import date_label, gregorian_label


def test_gregorian_date_carries_its_weekday():
    assert gregorian_label(date(2026, 2, 3)) == "Tue 03 Feb 2026"


def test_slip_date_line_has_roj_mah_and_weekday():
    line = date_label(1, 1, date(2026, 9, 14))
    assert line == "Roj Hormazd, Mah Fravardin (Mon 14 Sep 2026)"
