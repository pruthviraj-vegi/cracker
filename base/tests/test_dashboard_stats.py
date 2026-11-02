"""Tests for main dashboard views and statistics endpoint."""

from decimal import Decimal
import json

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from Billing.tests.helpers import (
    create_test_user,
    create_test_customer,
    create_test_product,
    create_test_variant,
    create_test_invoice,
    create_test_invoice_item,
)
from base.views import get_variant_dashboard_data


class DashboardStatsTest(TestCase):
    """Test dashboard stats endpoint and variant breakdowns."""

    def setUp(self):
        self.client = Client()
        self.user = create_test_user(first_name="Admin", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

        self.customer = create_test_customer(name="Rajesh Kumar", created_by=self.user)
        self.product1 = create_test_product(brand="Nike", name="Air Max")
        self.product2 = create_test_product(brand="Adidas", name="Ultraboost")

        self.variant1 = create_test_variant(
            product=self.product1,
            barcode="BAR000001",
            purchase_price=Decimal("1000.00"),
            mrp=Decimal("2000.00"),
            quantity=Decimal("100"),
        )
        self.variant2 = create_test_variant(
            product=self.product2,
            barcode="BAR000002",
            purchase_price=Decimal("1500.00"),
            mrp=Decimal("3000.00"),
            quantity=Decimal("80"),
        )

    def test_get_variant_dashboard_data_empty(self):
        """When no invoices exist, metrics should be 0 and breakdowns empty."""
        today = timezone.now().date()
        data = get_variant_dashboard_data(today, today)

        self.assertEqual(data["total_sales"], 0.0)
        self.assertEqual(data["total_items_count"], 0)
        self.assertEqual(data["total_quantity"], 0.0)
        self.assertEqual(data["total_selling_price"], 0.0)
        self.assertEqual(data["total_mrp"], 0.0)
        self.assertEqual(data["variant_qty_breakdown"], [])
        self.assertEqual(data["variant_selling_price_breakdown"], [])
        self.assertEqual(data["variant_mrp_breakdown"], [])

    def test_get_variant_dashboard_data_with_items(self):
        """When invoices and items exist, metrics and breakdowns must calculate selling price accurately."""
        today = timezone.now().date()
        now = timezone.now()

        invoice = create_test_invoice(
            customer=self.customer,
            created_by=self.user,
            amount=Decimal("14000.00"),
            payment_type="CASH",
            payment_status="PAID",
        )
        invoice.invoice_date = now
        invoice.save()

        # Variant 1: 5 units @ 1800 selling price (unit_price) != 2000 MRP => 9,000 selling price
        create_test_invoice_item(
            invoice=invoice,
            product_variant=self.variant1,
            quantity=Decimal("5"),
            unit_price=Decimal("1800.00"),
            mrp=Decimal("2000.00"),
        )

        # Variant 2: 2 units @ 2500 selling price (unit_price) != 3000 MRP => 5,000 selling price
        create_test_invoice_item(
            invoice=invoice,
            product_variant=self.variant2,
            quantity=Decimal("2"),
            unit_price=Decimal("2500.00"),
            mrp=Decimal("3000.00"),
        )

        data = get_variant_dashboard_data(today, today)

        # Total quantity = 5 + 2 = 7
        self.assertEqual(data["total_quantity"], 7.0)
        # Total Selling Price = (5 * 1800) + (2 * 2500) = 9,000 + 5,000 = 14,000 (NOT 16,000 MRP)
        self.assertEqual(data["total_selling_price"], 14000.0)
        self.assertEqual(data["total_mrp"], 14000.0)
        self.assertEqual(data["total_items_count"], 2)

        # Check Quantity Breakdown (top should be Variant 1 with 5 units)
        qty_bd = data["variant_qty_breakdown"]
        self.assertEqual(len(qty_bd), 2)
        self.assertEqual(qty_bd[0]["quantity"], 5.0)
        self.assertEqual(qty_bd[0]["percentage"], round(5 / 7 * 100, 1))
        self.assertEqual(qty_bd[1]["quantity"], 2.0)
        self.assertEqual(qty_bd[1]["percentage"], round(2 / 7 * 100, 1))

        # Check Selling Price Breakdown (top should be Variant 1 with 9,000 selling price)
        sp_bd = data["variant_selling_price_breakdown"]
        self.assertEqual(len(sp_bd), 2)
        self.assertEqual(sp_bd[0]["selling_price"], 9000.0)
        self.assertEqual(sp_bd[0]["percentage"], round(9000 / 14000 * 100, 1))
        self.assertEqual(sp_bd[1]["selling_price"], 5000.0)
        self.assertEqual(sp_bd[1]["percentage"], round(5000 / 14000 * 100, 1))

    def test_dashboard_stats_endpoint(self):
        """Verify AJAX endpoint returns variant breakdowns and totals using selling price."""
        today = timezone.now().date()
        now = timezone.now()

        invoice = create_test_invoice(
            customer=self.customer,
            created_by=self.user,
            amount=Decimal("3600.00"),
            payment_type="CASH",
            payment_status="PAID",
        )
        invoice.invoice_date = now
        invoice.save()

        create_test_invoice_item(
            invoice=invoice,
            product_variant=self.variant1,
            quantity=Decimal("2"),
            unit_price=Decimal("1800.00"),
            mrp=Decimal("2000.00"),
        )

        response = self.client.get(reverse("base:dashboard_stats"), {"date_filter": "today"})
        self.assertEqual(response.status_code, 200)

        json_data = response.json()
        self.assertTrue(json_data["success"])
        self.assertIn("stats", json_data)
        self.assertEqual(json_data["stats"]["total_quantity"], 2.0)
        self.assertEqual(json_data["stats"]["total_selling_price"], 3600.0)
        self.assertEqual(json_data["stats"]["total_items_count"], 1)

        self.assertIn("variant_qty_breakdown", json_data)
        self.assertIn("variant_selling_price_breakdown", json_data)
        self.assertEqual(len(json_data["variant_qty_breakdown"]), 1)
        self.assertEqual(len(json_data["variant_selling_price_breakdown"]), 1)
        self.assertEqual(json_data["variant_selling_price_breakdown"][0]["selling_price"], 3600.0)

    def test_home_view_renders_successfully(self):
        """Home view should render with status 200 and include the dashboard components."""
        response = self.client.get(reverse("base:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "heroTotalSales")
        self.assertContains(response, "heroTotalItemsQty")
        self.assertContains(response, "heroTotalSellingPrice")
        self.assertContains(response, "charts-three-col-grid")
        self.assertContains(response, "variantQtyChart")
        self.assertContains(response, "variantSellingPriceChart")
        self.assertContains(response, "paymentMethodChart")
        self.assertContains(response, "dashVariantTotalQty")
        self.assertContains(response, "dashVariantTotalSellingPrice")
        self.assertContains(response, "dashPmTotalReceived")
