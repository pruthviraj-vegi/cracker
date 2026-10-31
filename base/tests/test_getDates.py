"""
Tests for base/getDates.py: start_of_day, end_of_day, parse_date,
quarter_start_end, DatesManipulation, DatesRange.
"""

from datetime import datetime, timedelta
from unittest.mock import PropertyMock, patch

from django.test import TestCase

from base.getDates import (
    DatesManipulation,
    DatesRange,
    end_of_day,
    parse_date,
    quarter_start_end,
    start_of_day,
)


class StartEndOfDayTests(TestCase):
    """Tests for start_of_day() and end_of_day()."""

    def test_start_of_day(self):
        dt = datetime(2024, 6, 15, 14, 30, 45, 123456)
        result = start_of_day(dt)
        self.assertEqual(result, datetime(2024, 6, 15, 0, 0, 0, 0))

    def test_end_of_day(self):
        dt = datetime(2024, 6, 15, 14, 30, 45, 123456)
        result = end_of_day(dt)
        self.assertEqual(result, datetime(2024, 6, 15, 23, 59, 59, 999999))

    def test_start_of_day_already_midnight(self):
        dt = datetime(2024, 6, 15, 0, 0, 0, 0)
        result = start_of_day(dt)
        self.assertEqual(result, dt)


class ParseDateTests(TestCase):
    """Tests for parse_date()."""

    def test_dd_mm_yyyy(self):
        result = parse_date("15-06-2024")
        self.assertEqual(result, datetime(2024, 6, 15))

    def test_yyyy_mm_dd(self):
        result = parse_date("2024-06-15")
        self.assertEqual(result, datetime(2024, 6, 15))

    def test_none_returns_fallback(self):
        fallback = datetime(2024, 1, 1)
        result = parse_date(None, fallback)
        self.assertEqual(result, fallback)

    def test_empty_string_returns_fallback(self):
        fallback = datetime(2024, 1, 1)
        result = parse_date("", fallback)
        self.assertEqual(result, fallback)

    def test_fallback_none_by_default(self):
        result = parse_date(None)
        self.assertIsNone(result)

    def test_invalid_date_returns_fallback(self):
        fallback = datetime(2024, 1, 1)
        result = parse_date("not-a-date", fallback)
        self.assertEqual(result, fallback)


class QuarterStartEndTests(TestCase):
    """Tests for quarter_start_end()."""

    def test_q1_jan(self):
        start, end = quarter_start_end(2024, 1)
        self.assertEqual(start, datetime(2024, 1, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 3, 31, 23, 59, 59, 999999))

    def test_q2_apr(self):
        start, end = quarter_start_end(2024, 4)
        self.assertEqual(start, datetime(2024, 4, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 6, 30, 23, 59, 59, 999999))

    def test_q3_jul(self):
        start, end = quarter_start_end(2024, 7)
        self.assertEqual(start, datetime(2024, 7, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 9, 30, 23, 59, 59, 999999))

    def test_q4_oct(self):
        start, end = quarter_start_end(2024, 10)
        self.assertEqual(start, datetime(2024, 10, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 12, 31, 23, 59, 59, 999999))

    def test_month_maps_to_correct_q_start(self):
        start, _ = quarter_start_end(2024, 5)
        self.assertEqual(start, datetime(2024, 4, 1, 0, 0, 0))


class DatesManipulationTests(TestCase):
    """Tests for DatesManipulation with controlled "today"."""

    def setUp(self):
        self.patcher = patch(
            "base.getDates.datetime", wraps=datetime
        )
        self.mock_dt = self.patcher.start()
        self.mock_dt.now.return_value = datetime(2024, 6, 15, 12, 0, 0)

    def tearDown(self):
        self.patcher.stop()

    def test_today_date(self):
        dm = DatesManipulation()
        start, end = dm.today_date
        self.assertEqual(start, datetime(2024, 6, 15, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 6, 15, 23, 59, 59, 999999))

    def test_yesterday_date(self):
        dm = DatesManipulation()
        start, end = dm.yesterday_date
        self.assertEqual(start, datetime(2024, 6, 14, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 6, 14, 23, 59, 59, 999999))

    def test_this_month(self):
        dm = DatesManipulation()
        start, end = dm.this_month
        self.assertEqual(start, datetime(2024, 6, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 6, 30, 23, 59, 59, 999999))

    def test_last_month(self):
        dm = DatesManipulation()
        start, end = dm.last_month
        self.assertEqual(start, datetime(2024, 5, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 5, 31, 23, 59, 59, 999999))

    def test_this_finance_after_april(self):
        dm = DatesManipulation()
        start, end = dm.this_finance
        self.assertEqual(start, datetime(2024, 4, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 6, 15, 23, 59, 59, 999999))

    def test_last_finance_after_april(self):
        dm = DatesManipulation()
        start, end = dm.last_finance
        self.assertEqual(start, datetime(2023, 4, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 3, 31, 23, 59, 59, 999999))

    def test_this_quarter(self):
        dm = DatesManipulation()
        start, end = dm.this_quarter
        self.assertEqual(start, datetime(2024, 4, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 6, 30, 23, 59, 59, 999999))

    def test_last_quarter(self):
        dm = DatesManipulation()
        start, end = dm.last_quarter
        self.assertEqual(start, datetime(2024, 1, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 3, 31, 23, 59, 59, 999999))

    def test_january_belongs_to_previous_fy(self):
        self.mock_dt.now.return_value = datetime(2025, 1, 15, 12, 0, 0)
        dm = DatesManipulation()
        start, end = dm.this_finance
        self.assertEqual(start, datetime(2024, 4, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2025, 1, 15, 23, 59, 59, 999999))

    def test_january_last_finance(self):
        self.mock_dt.now.return_value = datetime(2025, 1, 15, 12, 0, 0)
        dm = DatesManipulation()
        start, end = dm.last_finance
        self.assertEqual(start, datetime(2023, 4, 1, 0, 0, 0))
        self.assertEqual(end, datetime(2024, 3, 31, 23, 59, 59, 999999))


class DatesRangeTests(TestCase):
    """Tests for DatesRange wrapper."""

    def setUp(self):
        self.patcher = patch("base.getDates.datetime", wraps=datetime)
        self.mock_dt = self.patcher.start()
        self.mock_dt.now.return_value = datetime(2024, 6, 15, 12, 0, 0)

    def tearDown(self):
        self.patcher.stop()

    def test_today(self):
        dr = DatesRange("today")
        self.assertEqual(dr.from_date, datetime(2024, 6, 15, 0, 0, 0))
        self.assertEqual(dr.to_date, datetime(2024, 6, 15, 23, 59, 59, 999999))

    def test_this_month(self):
        dr = DatesRange("this_month")
        self.assertEqual(dr.from_date, datetime(2024, 6, 1, 0, 0, 0))
        self.assertEqual(dr.to_date, datetime(2024, 6, 30, 23, 59, 59, 999999))

    def test_unknown_value_defaults_to_last_month(self):
        dr = DatesRange("bogus")
        self.assertEqual(dr.from_date, datetime(2024, 5, 1, 0, 0, 0))
        self.assertEqual(dr.to_date, datetime(2024, 5, 31, 23, 59, 59, 999999))

    def test_full_date(self):
        dr = DatesRange("full_date")
        self.assertEqual(dr.from_date, datetime(2023, 1, 1, 0, 0, 0))
        self.assertEqual(dr.to_date, datetime(2024, 6, 15, 23, 59, 59, 999999))

    def test_lazy_evaluation(self):
        with patch.object(
            DatesManipulation, "this_finance", new_callable=PropertyMock
        ) as mock_finance:
            dr = DatesRange("today")
            self.assertEqual(dr.from_date, datetime(2024, 6, 15, 0, 0, 0))
            mock_finance.assert_not_called()
