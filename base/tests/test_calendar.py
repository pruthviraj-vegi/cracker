from decimal import Decimal
import datetime
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone

from base.views import CalendarView
from customer.models import Customer
from invoice.models import Invoice

User = get_user_model()


class CalendarViewTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            first_name="Test",
            phone_number="9876543210",
            password="password123"
        )
        perm = Permission.objects.get(codename="view_invoice")
        self.user.user_permissions.add(perm)

        self.customer = Customer.objects.create(
            name="Test Customer",
            phone_number="9876543210"
        )

    def test_calendar_view_context_data(self):
        now = timezone.now()

        Invoice.objects.create(
            sequence_no=1,
            customer=self.customer,
            invoice_number="INV-2026-001",
            amount=Decimal("1000.00"),
            discount_amount=Decimal("100.00"),
            paid_amount=Decimal("500.00"),
            sold_by=self.user,
            created_by=self.user,
            invoice_date=now
        )

        # Naive datetime
        Invoice.objects.create(
            sequence_no=2,
            customer=self.customer,
            invoice_number="INV-2026-002",
            amount=Decimal("500.00"),
            discount_amount=Decimal("50.00"),
            paid_amount=Decimal("450.00"),
            sold_by=self.user,
            created_by=self.user,
            invoice_date=datetime.datetime.now()
        )

        request = self.factory.get(f"/calendar/?year={now.year}&month={now.month}")
        request.user = self.user

        view = CalendarView()
        view.setup(request)
        context = view.get_context_data()

        self.assertIn("month_kpi", context)
        self.assertEqual(context["month_kpi"]["total_billing"], 1350.0)
        self.assertEqual(context["month_kpi"]["total_invoices"], 2)
        self.assertEqual(context["month_kpi"]["paid_amount"], 1350.0)
        self.assertEqual(context["month_kpi"]["pending_amount"], 0.0)

    def test_calendar_details_api_mixed_date_formats(self):
        """Test that calendar_details_api accepts different date formats (e.g. DD-MM-YYYY and YYYY-MM-DD)."""
        from base.views import calendar_details_api

        # Create an invoice in Feb 2026
        feb_date = datetime.datetime(2026, 2, 15, 10, 0, 0)
        Invoice.objects.create(
            sequence_no=10,
            customer=self.customer,
            invoice_number="INV-2026-FEB",
            amount=Decimal("1200.00"),
            discount_amount=Decimal("200.00"),
            paid_amount=Decimal("1000.00"),
            sold_by=self.user,
            created_by=self.user,
            invoice_date=feb_date,
        )

        # Query with start=01-02-2026 (DD-MM-YYYY) and end=2026-08-31 (YYYY-MM-DD)
        request = self.factory.get("/calendar/details-api/?start=01-02-2026&end=2026-08-31")
        request.user = self.user

        response = calendar_details_api(request)
        self.assertEqual(response.status_code, 200)

        import json
        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertEqual(data["date_range"]["start"], "2026-02-01")
        self.assertEqual(data["date_range"]["end"], "2026-08-31")
        self.assertGreaterEqual(data["stats"]["total_invoices"], 1)
        self.assertGreaterEqual(data["stats"]["total_amount"], 1200.0)

    def test_calendar_details_api_swapped_dates(self):
        """Test that passing start > end correctly swaps the date range."""
        from base.views import calendar_details_api

        request = self.factory.get("/calendar/details-api/?start=2026-08-31&end=01-02-2026")
        request.user = self.user

        response = calendar_details_api(request)
        self.assertEqual(response.status_code, 200)

        import json
        data = json.loads(response.content)
        self.assertEqual(data["date_range"]["start"], "2026-02-01")
        self.assertEqual(data["date_range"]["end"], "2026-08-31")

    def test_parse_flexible_date_utility(self):
        """Test parse_flexible_date handles multiple date string formats."""
        from base.utility import parse_flexible_date

        expected = datetime.date(2026, 2, 1)
        self.assertEqual(parse_flexible_date("2026-02-01"), expected)
        self.assertEqual(parse_flexible_date("01-02-2026"), expected)
        self.assertEqual(parse_flexible_date("01/02/2026"), expected)
        self.assertEqual(parse_flexible_date("2026/02/01"), expected)
        self.assertEqual(parse_flexible_date("01.02.2026"), expected)
        self.assertEqual(parse_flexible_date("2026-02-01T14:30:00"), expected)
        self.assertIsNone(parse_flexible_date("invalid-date"))
        self.assertIsNone(parse_flexible_date(""))
        self.assertIsNone(parse_flexible_date(None))
