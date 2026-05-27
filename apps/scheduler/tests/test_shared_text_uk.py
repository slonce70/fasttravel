"""Tests for consolidated shared.text_uk formatters."""

from datetime import date, datetime

from shared.text_uk import (
    format_date_full,
    format_date_short,
    format_location,
    format_stars,
    format_uah,
)


class TestFormatUah:
    def test_thousands_separated(self):
        assert format_uah(35200) == "35 200 ₴"

    def test_small_amount(self):
        assert format_uah(900) == "900 ₴"

    def test_none(self):
        assert format_uah(None) == "—"

    def test_float_truncated(self):
        assert format_uah(12345.67) == "12 345 ₴"

    def test_zero(self):
        assert format_uah(0) == "0 ₴"


class TestFormatDateShort:
    def test_date_object(self):
        assert format_date_short(date(2026, 6, 14)) == "14 черв."

    def test_iso_string(self):
        assert format_date_short("2026-01-05") == "5 січ."

    def test_datetime_string(self):
        assert format_date_short("2026-12-25T10:30:00") == "25 груд."

    def test_datetime_object(self):
        assert format_date_short(datetime(2026, 3, 8, 12, 0)) == "8 бер."

    def test_invalid_string_passthrough(self):
        assert format_date_short("not-a-date") == "not-a-date"

    def test_empty_string_passthrough(self):
        assert format_date_short("") == ""


class TestFormatDateFull:
    def test_june(self):
        assert format_date_full(date(2026, 6, 14)) == "14 червня"

    def test_january(self):
        assert format_date_full(date(2026, 1, 1)) == "1 січня"

    def test_december(self):
        assert format_date_full(date(2026, 12, 31)) == "31 грудня"


class TestFormatStars:
    def test_four_stars(self):
        assert format_stars(4) == "⭐⭐⭐⭐"

    def test_none(self):
        assert format_stars(None) == ""

    def test_zero(self):
        assert format_stars(0) == ""


class TestFormatLocation:
    def test_region_and_country(self):
        assert format_location("Хургада", "Єгипет") == "Хургада, Єгипет"

    def test_region_only(self):
        assert format_location("Анталія", None) == "Анталія"

    def test_country_only(self):
        assert format_location(None, "Туреччина") == "Туреччина"

    def test_neither(self):
        assert format_location(None, None) == "—"
