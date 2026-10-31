"""Unit tests for Billing shared test helpers (Billing/tests/helpers.py)."""

from decimal import Decimal
from django.test import TestCase

from Billing.tests.helpers import (
    create_test_cart,
    create_test_category,
    create_test_customer,
    create_test_hsn_code,
    create_test_invoice,
    create_test_invoice_item,
    create_test_payment,
    create_test_product,
    create_test_supplier,
    create_test_supplier_invoice,
    create_test_user,
    create_test_variant,
)


class TestHelpersTestCase(TestCase):
    """Test all helper factory methods in Billing.tests.helpers."""

    def test_factory_helpers_creation(self):
        """Verify all factory functions create valid, persisted domain objects."""
        user = create_test_user(first_name="FactoryUser", is_staff=True)
        self.assertIsNotNone(user.pk)
        self.assertTrue(user.is_staff)

        customer = create_test_customer(name="Factory Customer", created_by=user)
        self.assertIsNotNone(customer.pk)
        self.assertEqual(customer.name, "Factory Customer")

        cat = create_test_category(name="Factory Category")
        self.assertIsNotNone(cat.pk)

        hsn = create_test_hsn_code(code="55554444", gst_percentage=Decimal("12.00"))
        self.assertEqual(hsn.gst_percentage, Decimal("12.00"))

        product = create_test_product(category=cat, hsn_code=hsn)
        self.assertIsNotNone(product.pk)

        variant = create_test_variant(
            product=product,
            purchase_price=Decimal("150.00"),
            mrp=Decimal("300.00"),
        )
        self.assertEqual(variant.purchase_price, Decimal("150.00"))

        invoice = create_test_invoice(customer=customer, created_by=user, amount=Decimal("1200.00"))
        self.assertIsNotNone(invoice.pk)
        self.assertEqual(invoice.amount, Decimal("1200.00"))

        item = create_test_invoice_item(invoice=invoice, product_variant=variant, quantity=Decimal("2"))
        self.assertIsNotNone(item.pk)
        self.assertEqual(item.quantity, Decimal("2"))

        payment = create_test_payment(customer=customer, amount=Decimal("500.00"))
        self.assertEqual(payment.amount, Decimal("500.00"))

        supplier = create_test_supplier(name="Factory Supplier")
        self.assertIsNotNone(supplier.pk)

        sup_inv = create_test_supplier_invoice(supplier=supplier, total_amount=Decimal("10000.00"))
        self.assertEqual(sup_inv.total_amount, Decimal("10000.00"))

        cart = create_test_cart(name="Factory Cart", user=user)
        self.assertIsNotNone(cart.pk)
