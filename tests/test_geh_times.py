from datetime import date

import pytest

from agyary.messaging.geh_times import IST, machi_ceremony_datetime


def test_daytime_gehs_same_civil_date():
    d = date(2026, 7, 23)
    for geh, hour in ((1, 7), (2, 13), (4, 19)):
        dt = machi_ceremony_datetime(d, geh)
        assert dt.date() == d and dt.hour == hour and dt.tzinfo == IST


def test_ushahin_is_next_gregorian_morning():
    # v2 audit fix #1: Roj X / Ushahin physically happens ~4 AM the NEXT day.
    dt = machi_ceremony_datetime(date(2026, 7, 23), 5)
    assert dt.date() == date(2026, 7, 24)
    assert dt.hour == 4


def test_invalid_geh():
    with pytest.raises(ValueError):
        machi_ceremony_datetime(date(2026, 7, 23), 6)
