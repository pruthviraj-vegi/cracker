"""Tests for supplier suggestions and filtering during variant operations (stock in, out, damage)."""

from decimal import Decimal
from django.test import TestCase

from Billing.tests.helpers import (
    create_test_user,
    create_test_variant,
    create_test_supplier,
    create_test_supplier_invoice,
)
from inventory.forms import (
    StockInForm,
    AdjustmentInForm,
    AdjustmentOutForm,
    DamageForm,
)
from inventory.models import InventoryLog
from inventory.services import InventoryService


class VariantOperationSupplierFilterTests(TestCase):
    """Test suite ensuring variant operations only suggest initial and stock-in suppliers/invoices."""

    def setUp(self):
        self.user = create_test_user()
        self.supplier_a = create_test_supplier(name="Supplier Alpha")
        self.supplier_b = create_test_supplier(name="Supplier Beta")
        self.supplier_unrelated = create_test_supplier(name="Supplier Unrelated")

        self.invoice_a1 = create_test_supplier_invoice(
            supplier=self.supplier_a,
            invoice_number="INV-A-001",
            total_amount=Decimal("1000.00"),
        )
        self.invoice_a2 = create_test_supplier_invoice(
            supplier=self.supplier_a,
            invoice_number="INV-A-002",
            total_amount=Decimal("2000.00"),
        )
        self.invoice_b1 = create_test_supplier_invoice(
            supplier=self.supplier_b,
            invoice_number="INV-B-001",
            total_amount=Decimal("1500.00"),
        )
        self.invoice_unrelated = create_test_supplier_invoice(
            supplier=self.supplier_unrelated,
            invoice_number="INV-UNRELATED-001",
            total_amount=Decimal("5000.00"),
        )

        # Variant initially created with Supplier Alpha via INITIAL log
        self.variant = create_test_variant(
            purchase_price=Decimal("100.00"),
            mrp=Decimal("150.00"),
            quantity=Decimal("50"),
            user=self.user,
        )
        InventoryLog.objects.create(
            variant=self.variant,
            supplier_invoice=self.invoice_a1,
            transaction_type=InventoryLog.TransactionTypes.INITIAL,
            quantity_change=Decimal("50"),
            new_quantity=Decimal("50"),
            created_by=self.user,
        )

    def test_stock_in_form_allows_any_supplier_invoice(self):
        """StockInForm can accept an invoice from any active supplier."""
        form = StockInForm(variant=self.variant)
        qs = form.fields["supplier_invoice"].queryset
        self.assertIn(self.invoice_a1, qs)
        self.assertIn(self.invoice_a2, qs)
        self.assertIn(self.invoice_b1, qs)
        self.assertIn(self.invoice_unrelated, qs)

    def test_stock_in_form_accepts_new_supplier_invoice(self):
        """Submitting a new or unrelated supplier invoice in StockInForm is valid."""
        form = StockInForm(
            data={
                "quantity_change": "10",
                "purchase_price": "100.00",
                "mrp": "150.00",
                "supplier_invoice": self.invoice_unrelated.id,
            },
            variant=self.variant,
        )
        self.assertTrue(form.is_valid())

    def test_adjustment_in_form_only_suggests_invoices_that_supplied_stock(self):
        """AdjustmentInForm should only suggest invoices that supplied stock for this variant."""
        form = AdjustmentInForm(variant=self.variant)
        qs = form.fields["supplier_invoice"].queryset
        self.assertIn(self.invoice_a1, qs)
        # invoice_a2 is from Supplier Alpha but never had stock-in for this variant
        self.assertNotIn(self.invoice_a2, qs)
        self.assertNotIn(self.invoice_unrelated, qs)

    def test_adjustment_out_form_only_suggests_invoices_that_supplied_stock(self):
        """AdjustmentOutForm should only suggest invoices that supplied stock for this variant."""
        form = AdjustmentOutForm(variant=self.variant)
        qs = form.fields["supplier_invoice"].queryset
        self.assertIn(self.invoice_a1, qs)
        self.assertNotIn(self.invoice_a2, qs)
        self.assertNotIn(self.invoice_unrelated, qs)

    def test_damage_form_only_suggests_invoices_that_supplied_stock(self):
        """DamageForm should only suggest invoices that supplied stock for this variant."""
        form = DamageForm(variant=self.variant)
        qs = form.fields["supplier_invoice"].queryset
        self.assertIn(self.invoice_a1, qs)
        self.assertNotIn(self.invoice_a2, qs)
        self.assertNotIn(self.invoice_unrelated, qs)

    def test_adjustment_in_and_out_service_persists_supplier_invoice(self):
        """InventoryService adjust_in_quantity and adjust_out_quantity should record supplier_invoice on the log."""
        InventoryService.adjust_in_quantity(
            variant=self.variant,
            change=Decimal("5"),
            user=self.user,
            notes="Found stock",
            supplier_invoice=self.invoice_a1,
        )
        log_in = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.ADJUSTMENT_IN,
        ).latest("created_at")
        self.assertEqual(log_in.supplier_invoice, self.invoice_a1)

        InventoryService.adjust_out_quantity(
            variant=self.variant,
            change=Decimal("2"),
            user=self.user,
            notes="Shrinkage",
            supplier_invoice=self.invoice_a1,
        )
        log_out = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.ADJUSTMENT_OUT,
        ).latest("created_at")
        self.assertEqual(log_out.supplier_invoice, self.invoice_a1)

    def test_adjustment_and_damage_forms_reject_unrelated_supplier_invoice(self):
        """AdjustmentInForm, AdjustmentOutForm, and DamageForm reject an invoice that did not supply this variant."""
        adj_in = AdjustmentInForm(
            data={"quantity_change": "5", "supplier_invoice": self.invoice_unrelated.id},
            variant=self.variant,
        )
        self.assertFalse(adj_in.is_valid())
        self.assertIn("supplier_invoice", adj_in.errors)

        adj_out = AdjustmentOutForm(
            data={"quantity_change": "2", "supplier_invoice": self.invoice_unrelated.id},
            variant=self.variant,
        )
        self.assertFalse(adj_out.is_valid())
        self.assertIn("supplier_invoice", adj_out.errors)

        damage = DamageForm(
            data={"quantity_change": "2", "supplier_invoice": self.invoice_unrelated.id},
            variant=self.variant,
        )
        self.assertFalse(damage.is_valid())
        self.assertIn("supplier_invoice", damage.errors)

    def test_adjustment_forms_reject_same_supplier_non_stock_invoice(self):
        """Even if from the same supplier, an invoice that did not supply this variant is rejected."""
        adj_in = AdjustmentInForm(
            data={"quantity_change": "5", "supplier_invoice": self.invoice_a2.id},
            variant=self.variant,
        )
        self.assertFalse(adj_in.is_valid())
        self.assertIn("supplier_invoice", adj_in.errors)

    def test_variant_without_invoices_has_empty_adjustment_queryset_and_submits_without_invoice(self):
        """A variant created without supplier invoices has an empty invoice queryset and allows submission without invoice."""
        variant_no_inv = create_test_variant(
            purchase_price=Decimal("50.00"),
            mrp=Decimal("80.00"),
            quantity=Decimal("10"),
            user=self.user,
        )
        adj_in = AdjustmentInForm(variant=variant_no_inv)
        self.assertEqual(adj_in.fields["supplier_invoice"].queryset.count(), 0)

        # Submitting without supplier invoice is valid
        form = AdjustmentInForm(
            data={"quantity_change": "5"},
            variant=variant_no_inv,
        )
        self.assertTrue(form.is_valid())


