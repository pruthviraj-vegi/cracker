from decimal import Decimal
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from Billing.tests.helpers import (
    create_test_product,
    create_test_user,
    create_test_variant,
)


class InventoryDashboardTests(TestCase):
    """Tests for inventory dashboard metrics including Total Inventory (MRP)."""

    def setUp(self):
        self.client = Client()
        self.user = create_test_user(is_staff=True)
        # Grant view_dashboard permission
        perm = Permission.objects.get(codename="view_dashboard", content_type__app_label="inventory")
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)

        self.product = create_test_product(brand="Nike", name="Air Zoom")
        # Variant 1: Qty 10, Cost 100, MRP 200 -> Value: Cost=1000, MRP=2000
        self.v1 = create_test_variant(
            product=self.product,
            purchase_price=Decimal("100.00"),
            mrp=Decimal("200.00"),
            quantity=Decimal("10"),
            user=self.user,
        )
        # Variant 2: Qty 5, Cost 150, MRP 300 -> Value: Cost=750, MRP=1500
        self.v2 = create_test_variant(
            product=self.product,
            purchase_price=Decimal("150.00"),
            mrp=Decimal("300.00"),
            quantity=Decimal("5"),
            user=self.user,
        )

    def test_dashboard_renders_total_inventory_mrp_value(self):
        """Dashboard page should calculate and render total inventory MRP value in the 3-box row."""
        response = self.client.get(reverse("inventory:dashboard"))
        self.assertEqual(response.status_code, 200)

        # Total cost = 1000 + 750 = 1750.00
        # Total MRP = 2000 + 1500 = 3500.00
        self.assertEqual(response.context["total_inventory_value"], 1750.0)
        self.assertEqual(response.context["total_inventory_mrp_value"], 3500.0)

        content = response.content.decode("utf-8")
        self.assertIn("Total Inventory (MRP)", content)
        self.assertIn('id="totalInventoryMrp"', content)
        self.assertIn('data-count="3500.0"', content)
        self.assertIn("health-highlights-row three-boxes", content)

    def test_dashboard_fetch_returns_total_inventory_mrp(self):
        """Dashboard AJAX fetch endpoint should return total_inventory_mrp in stats."""
        response = self.client.get(reverse("inventory:dashboard_fetch"), {"date_filter": "this_month"})
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("total_inventory_mrp", data["stats"])
        self.assertEqual(data["stats"]["total_inventory_mrp"], 3500.0)
