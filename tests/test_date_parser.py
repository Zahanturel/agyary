from datetime import date, time

from agyary.calendar import CalendarSystem
from agyary.messaging.date_parser import infer_parsi_year, parse_date_input, parse_time_input

TODAY = date(2026, 7, 21)  # Shenshai: Roj 11, Mah 12 (Aspandard), year 1395


def test_parsi_full():
    p = parse_date_input("Roj Bahman Mah Fravardin", TODAY)
    assert p.kind == "parsi_full" and (p.roj, p.mah) == (2, 1)


def test_parsi_roj_only():
    p = parse_date_input("Roj Bahman", TODAY)
    assert p.kind == "parsi_roj_only" and p.roj == 2


def test_parsi_prefix_match():
    p = parse_date_input("roj ardi mah shah", TODAY)
    assert p.kind == "parsi_full" and (p.roj, p.mah) == (3, 6)


def test_gregorian_formats():
    for text in ("July 23", "23 July", "23/7", "23-7", "23rd July"):
        p = parse_date_input(text, TODAY)
        assert p.kind == "gregorian", text
        assert p.gregorian == date(2026, 7, 23), text
    p = parse_date_input("2026-07-23", TODAY)
    assert p.gregorian == date(2026, 7, 23)
    p = parse_date_input("23/7/2026", TODAY)
    assert p.gregorian == date(2026, 7, 23)


def test_gregorian_past_rolls_to_next_year():
    p = parse_date_input("1 January", TODAY)
    assert p.gregorian == date(2027, 1, 1)


def test_relative():
    assert parse_date_input("today", TODAY).gregorian == TODAY
    assert parse_date_input("tomorrow", TODAY).gregorian == date(2026, 7, 22)


def test_invalid():
    assert parse_date_input("banana", TODAY).kind == "invalid"
    assert parse_date_input("32/13", TODAY).kind == "invalid"


def test_roj_typo_falls_back_to_roj_invalid():
    p = parse_date_input("Roj Xyz", TODAY)
    assert p.kind == "roj_invalid"


def test_mah_typo_falls_back_to_mah_invalid():
    p = parse_date_input("Roj Bahman Mah Xyz", TODAY)
    assert p.kind == "mah_invalid" and p.roj == 2


def test_year_inference_future_mah():
    # Mah Fravardin is past Navroze (Aug 15 2026): current parsi year 1395
    # is over for Fravardin, so infer 1396 -> Aug 16 2026.
    year, gregorian = infer_parsi_year(2, 1, CalendarSystem.SHENSHAI, TODAY)
    assert gregorian == date(2026, 8, 16)
    assert gregorian >= TODAY


def test_year_inference_current_mah():
    # Roj 15 of Mah 12 is still ahead within the current parsi year.
    year, gregorian = infer_parsi_year(15, 12, CalendarSystem.SHENSHAI, TODAY)
    assert TODAY <= gregorian < date(2026, 8, 15)


def test_time_parsing():
    assert parse_time_input("10:30 am") == time(10, 30)
    assert parse_time_input("10 am") == time(10, 0)
    assert parse_time_input("12 pm") == time(12, 0)
    assert parse_time_input("12 am") == time(0, 0)
    assert parse_time_input("16:00") == time(16, 0)
    assert parse_time_input("4 pm") == time(16, 0)
    assert parse_time_input("6:30") == time(18, 30)  # bare small hour -> PM
    assert parse_time_input("10") == time(10, 0)
    assert parse_time_input("not a time") is None
