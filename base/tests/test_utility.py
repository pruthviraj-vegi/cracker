"""
Tests for base/utility.py: get_financial_year, StringProcessor, build_search_filter,
process_breakdown_data, resolve_user, get_period_label, table_sorting, get_periodic_data.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.db.models import Q
from django.test import TestCase, RequestFactory

from base.utility import (
    _clean_str,
    build_search_filter,
    get_financial_year,
    get_period_label,
    get_periodic_data,
    process_breakdown_data,
    resolve_user,
    StringProcessor,
    table_sorting,
)


class GetFinancialYearTests(TestCase):
    """Tests for get_financial_year()."""

    def test_string_yyyy_mm_dd(self):
        self.assertEqual(get_financial_year("2024-06-15"), "24-25")

    def test_string_dd_mm_yyyy(self):
        self.assertEqual(get_financial_year("15/06/2024"), "24-25")

    def test_string_dd_mm_yyyy_hyphens(self):
        self.assertEqual(get_financial_year("15-06-2024"), "24-25")

    def test_string_month_name_format(self):
        self.assertEqual(get_financial_year("Jun 15, 2024"), "24-25")

    def test_datetime_input(self):
        dt = datetime(2024, 6, 15)
        self.assertEqual(get_financial_year(dt), "24-25")

    def test_date_input(self):
        d = date(2024, 6, 15)
        self.assertEqual(get_financial_year(d), "24-25")

    def test_january_belongs_to_previous_fy(self):
        self.assertEqual(get_financial_year(date(2025, 1, 15)), "24-25")
        self.assertEqual(get_financial_year(date(2025, 3, 31)), "24-25")

    def test_april_starts_new_fy(self):
        self.assertEqual(get_financial_year(date(2025, 4, 1)), "25-26")

    def test_december_end_of_fy(self):
        self.assertEqual(get_financial_year(date(2024, 12, 31)), "24-25")

    def test_year_2000_boundary(self):
        self.assertEqual(get_financial_year(date(2000, 1, 15)), "99-00")
        self.assertEqual(get_financial_year(date(2000, 4, 1)), "00-01")

    def test_unrecognized_string_raises_value_error(self):
        with self.assertRaises(ValueError):
            get_financial_year("not-a-date")

    def test_nonsense_input_raises_value_error(self):
        with self.assertRaises(ValueError):
            get_financial_year(42)


class StringProcessorTests(TestCase):
    """Tests for StringProcessor."""

    def test_none_input_produces_empty(self):
        sp = StringProcessor(None)
        self.assertEqual(sp.input_string, "")
        self.assertEqual(sp.cleaned_string, "")

    def test_empty_string_input(self):
        sp = StringProcessor("")
        self.assertEqual(sp.input_string, "")
        self.assertEqual(sp.cleaned_string, "")

    def test_clean_removes_slashes_question_commas(self):
        sp = StringProcessor("Hello/World? Test, string")
        self.assertEqual(sp.cleaned_string, "HELLOWORLD TEST STRING")

    def test_clean_collapses_multiple_spaces(self):
        sp = StringProcessor("hello    world  test")
        self.assertEqual(sp.cleaned_string, "HELLO WORLD TEST")

    def test_to_uppercase(self):
        sp = StringProcessor("hello world")
        self.assertEqual(sp.toUppercase(), "HELLO WORLD")

    def test_to_lowercase(self):
        sp = StringProcessor("HELLO WORLD")
        self.assertEqual(sp.toLowercase(), "hello world")

    def test_to_title(self):
        sp = StringProcessor("hello world")
        self.assertEqual(sp.toTitle(), "Hello World")

    def test_to_capitalize(self):
        sp = StringProcessor("hello world")
        self.assertEqual(sp.toCapitalize(), "Hello world")

    def test_clean_str_helper(self):
        self.assertEqual(_clean_str(None), "")
        self.assertEqual(_clean_str(""), "")
        self.assertEqual(_clean_str("  hello/world?  foo,bar  "), "HELLOWORLD FOOBAR")


class BuildSearchFilterTests(TestCase):
    """Tests for build_search_filter()."""

    def test_empty_query_returns_empty_q(self):
        result = build_search_filter("", ["name", "email"])
        self.assertEqual(result, Q())

    def test_single_term_single_field(self):
        result = build_search_filter("test", ["name"])
        expected = Q(name__icontains="test")
        self.assertEqual(result, expected)

    def test_single_term_multiple_fields(self):
        result = build_search_filter("test", ["name", "email"])
        expected = Q(name__icontains="test") | Q(email__icontains="test")
        self.assertEqual(result, expected)

    def test_multiple_terms_and_combined(self):
        result = build_search_filter("hello world", ["name", "email"])
        term1 = Q(name__icontains="hello") | Q(email__icontains="hello")
        term2 = Q(name__icontains="world") | Q(email__icontains="world")
        expected = term1 & term2
        self.assertEqual(result, expected)

    def test_whitespace_only_query(self):
        result = build_search_filter("   ", ["name"])
        self.assertEqual(result, Q())


class ProcessBreakdownDataTests(TestCase):
    """Tests for process_breakdown_data()."""

    def test_empty_list(self):
        result = process_breakdown_data([], 100)
        self.assertEqual(result, [])

    def test_single_item(self):
        items = [{"field": "sales", "count": 5, "amount": 50.0}]
        result = process_breakdown_data(items, 100)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["field_name"], "Sales")
        self.assertEqual(result[0]["count"], 5)
        self.assertEqual(result[0]["amount"], 50.0)
        self.assertEqual(result[0]["percentage"], 50.0)

    def test_zero_total_returns_zero_percent(self):
        items = [{"field": "sales", "count": 1, "amount": 50.0}]
        result = process_breakdown_data(items, 0)
        self.assertEqual(result[0]["percentage"], 0)

    def test_rounding(self):
        items = [{"field": "test", "count": 1, "amount": 33.333}]
        result = process_breakdown_data(items, 100)
        self.assertEqual(result[0]["percentage"], 33.3)

    def test_underscore_field_name_replaced(self):
        items = [{"field": "online_sales", "count": 1, "amount": 10.0}]
        result = process_breakdown_data(items, 10)
        self.assertEqual(result[0]["field_name"], "Online Sales")


class ResolveUserTests(TestCase):
    """Tests for resolve_user()."""

    def test_none_request_returns_none(self):
        self.assertIsNone(resolve_user(None))

    def test_unauthenticated_user_returns_none(self):
        request = MagicMock()
        request.user = MagicMock()
        request.user.is_authenticated = False
        self.assertIsNone(resolve_user(request))

    def test_authenticated_user_returned(self):
        request = MagicMock()
        request.user = MagicMock()
        request.user.is_authenticated = True
        self.assertEqual(resolve_user(request), request.user)

    def test_no_user_attr_returns_none(self):
        request = MagicMock()
        del request.user
        request.user = None
        self.assertIsNone(resolve_user(request))


class GetPeriodLabelTests(TestCase):
    """Tests for get_period_label()."""

    def test_daily(self):
        d = date(2024, 6, 15)
        label = get_period_label(d, d, "daily")
        self.assertEqual(label, "June 15, 2024")

    def test_monthly(self):
        start = date(2024, 6, 1)
        end = date(2024, 6, 30)
        label = get_period_label(start, end, "monthly")
        self.assertEqual(label, "June 01 - June 30, 2024")

    def test_quarterly(self):
        start = date(2024, 4, 1)
        end = date(2024, 6, 30)
        label = get_period_label(start, end, "quarterly")
        self.assertEqual(label, "Q2 2024")

    def test_quarterly_q1(self):
        start = date(2024, 1, 1)
        end = date(2024, 3, 31)
        label = get_period_label(start, end, "quarterly")
        self.assertEqual(label, "Q1 2024")

    def test_yearly(self):
        start = date(2024, 4, 1)
        end = date(2025, 3, 31)
        label = get_period_label(start, end, "yearly")
        self.assertEqual(label, "FY 2024-2025")


class TableSortingTests(TestCase):
    """Tests for table_sorting()."""

    def test_no_sort_param_returns_default(self):
        factory = RequestFactory()
        request = factory.get("/")
        result = table_sorting(request, ["name", "date"], default_sort="-id")
        self.assertEqual(result, ["-id"])

    def test_empty_sort_param_returns_default(self):
        factory = RequestFactory()
        request = factory.get("/?sort=")
        result = table_sorting(request, ["name", "date"], default_sort="-id")
        self.assertEqual(result, ["-id"])

    def test_valid_single_sort(self):
        factory = RequestFactory()
        request = factory.get("/?sort=name")
        result = table_sorting(request, ["name", "date"])
        self.assertEqual(result, ["name"])

    def test_valid_desc_sort(self):
        factory = RequestFactory()
        request = factory.get("/?sort=-date")
        result = table_sorting(request, ["name", "date"])
        self.assertEqual(result, ["-date"])

    def test_invalid_field_returns_default(self):
        factory = RequestFactory()
        request = factory.get("/?sort=invalid_field")
        result = table_sorting(request, ["name", "date"], default_sort="-id")
        self.assertEqual(result, ["-id"])

    def test_multiple_sorts(self):
        factory = RequestFactory()
        request = factory.get("/?sort=name,-date")
        result = table_sorting(request, ["name", "date"])
        self.assertEqual(result, ["name", "-date"])

    def test_mixed_valid_invalid_uses_only_valid(self):
        factory = RequestFactory()
        request = factory.get("/?sort=name,bogus")
        result = table_sorting(request, ["name", "date"], default_sort="-id")
        self.assertEqual(result, ["name"])

    def test_sort_mapping_dict(self):
        factory = RequestFactory()
        request = factory.get("/?sort=customer,date")
        mapping = {"customer": "customer__name", "date": "invoice_date"}
        result = table_sorting(request, mapping)
        self.assertEqual(result, ["customer__name", "invoice_date"])

    def test_sort_mapping_with_desc(self):
        factory = RequestFactory()
        request = factory.get("/?sort=-customer")
        mapping = {"customer": "customer__name", "date": "invoice_date"}
        result = table_sorting(request, mapping)
        self.assertEqual(result, ["-customer__name"])


class GetPeriodicDataTests(TestCase):
    """Tests for get_periodic_data()."""

    def test_today(self):
        with patch("base.utility.DatesManipulation") as mock_dates:
            from datetime import date
            mock_instance = MagicMock()
            mock_instance.yesterday_date = (date(2024, 6, 14), date(2024, 6, 14))
            mock_dates.return_value = mock_instance

            current_start = date(2024, 6, 15)
            current_end = date(2024, 6, 15)
            prev_start, prev_end, period_type = get_periodic_data(
                "today", current_start, current_end
            )
            self.assertEqual(period_type, "daily")

    def test_this_month(self):
        with patch("base.utility.DatesManipulation") as mock_dates:
            import datetime
            mock_instance = MagicMock()
            mock_instance.last_month = (
                datetime.datetime(2024, 5, 1, 0, 0, 0),
                datetime.datetime(2024, 5, 31, 23, 59, 59),
            )
            mock_dates.return_value = mock_instance

            current_start = date(2024, 6, 1)
            current_end = date(2024, 6, 30)
            prev_start, prev_end, period_type = get_periodic_data(
                "this_month", current_start, current_end
            )
            self.assertEqual(period_type, "monthly")
            self.assertEqual(prev_start, date(2024, 5, 1))

    def test_last_month(self):
        current_start = date(2024, 6, 1)
        current_end = date(2024, 6, 30)
        prev_start, prev_end, period_type = get_periodic_data(
            "last_month", current_start, current_end
        )
        self.assertEqual(period_type, "monthly")
        self.assertEqual(prev_start, date(2024, 4, 1))

    def test_this_quarter(self):
        with patch("base.utility.DatesManipulation") as mock_dates:
            import datetime
            mock_instance = MagicMock()
            mock_instance.last_quarter = (
                datetime.datetime(2024, 1, 1, 0, 0, 0),
                datetime.datetime(2024, 3, 31, 23, 59, 59),
            )
            mock_dates.return_value = mock_instance

            current_start = date(2024, 4, 1)
            current_end = date(2024, 6, 30)
            prev_start, prev_end, period_type = get_periodic_data(
                "this_quarter", current_start, current_end
            )
            self.assertEqual(period_type, "quarterly")
            self.assertEqual(prev_start, date(2024, 1, 1))

    def test_this_finance(self):
        with patch("base.utility.DatesManipulation") as mock_dates:
            import datetime
            mock_instance = MagicMock()
            mock_instance.last_finance = (
                datetime.datetime(2023, 4, 1, 0, 0, 0),
                datetime.datetime(2024, 3, 31, 23, 59, 59),
            )
            mock_dates.return_value = mock_instance

            current_start = date(2024, 4, 1)
            current_end = date(2025, 3, 31)
            prev_start, prev_end, period_type = get_periodic_data(
                "this_finance", current_start, current_end
            )
            self.assertEqual(period_type, "yearly")
            self.assertEqual(prev_start, date(2023, 4, 1))

    def test_unknown_filter_defaults_to_monthly(self):
        with patch("base.utility.DatesManipulation") as mock_dates:
            import datetime
            mock_instance = MagicMock()
            mock_instance.last_month = (
                datetime.datetime(2024, 5, 1, 0, 0, 0),
                datetime.datetime(2024, 5, 31, 23, 59, 59),
            )
            mock_dates.return_value = mock_instance

            prev_start, prev_end, period_type = get_periodic_data(
                "bogus_filter", date.today(), date.today()
            )
            self.assertEqual(period_type, "monthly")
