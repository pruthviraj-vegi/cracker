"""Tests for the cart app services."""

from decimal import Decimal

from django.test import TestCase

from cart.services import CartService
from cart.models import Cart, CartItem
from inventory.models import BarcodeMapping
from Billing.tests.helpers import (
    create_test_user,
    create_test_variant,
    create_test_product,
    create_test_cart,
)


class AddVariantToCartTests(TestCase):
    """Tests for CartService.add_variant_to_cart()."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(user=self.user)
        self.cart = create_test_cart(user=self.user)

    def test_new_item_creates(self):
        cart_item, created = CartService.add_variant_to_cart(
            self.cart, self.variant, quantity=2
        )
        self.assertTrue(created)
        self.assertEqual(cart_item.quantity, 2)
        self.assertEqual(cart_item.cart, self.cart)
        self.assertEqual(cart_item.product_variant, self.variant)

    def test_new_item_with_explicit_price(self):
        cart_item, created = CartService.add_variant_to_cart(
            self.cart, self.variant, quantity=1, price=Decimal("150.00")
        )
        self.assertTrue(created)
        self.assertEqual(cart_item.price, Decimal("150.00"))

    def test_new_item_defaults_price_to_final_price(self):
        cart_item, created = CartService.add_variant_to_cart(
            self.cart, self.variant, quantity=1
        )
        self.assertTrue(created)
        self.assertEqual(cart_item.price, self.variant.final_price)

    def test_existing_item_increments_quantity(self):
        CartService.add_variant_to_cart(self.cart, self.variant, quantity=2, price=Decimal("150.00"))
        cart_item, created = CartService.add_variant_to_cart(
            self.cart, self.variant, quantity=3, price=Decimal("150.00")
        )
        self.assertFalse(created)
        self.assertEqual(cart_item.quantity, 5)

    def test_existing_item_different_price_creates_new(self):
        CartService.add_variant_to_cart(self.cart, self.variant, quantity=2, price=Decimal("150.00"))
        cart_item, created = CartService.add_variant_to_cart(
            self.cart, self.variant, quantity=1, price=Decimal("160.00")
        )
        self.assertTrue(created)
        self.assertEqual(cart_item.quantity, 1)
        self.assertEqual(CartItem.objects.filter(cart=self.cart).count(), 2)

    def test_default_quantity_is_one(self):
        cart_item, created = CartService.add_variant_to_cart(
            self.cart, self.variant
        )
        self.assertEqual(cart_item.quantity, 1)


class ResolveVariantByBarcodeTests(TestCase):
    """Tests for CartService.resolve_variant_by_barcode()."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(
            barcode="SCAN001", user=self.user
        )
        self.other_variant = create_test_variant(
            barcode="SCAN002", user=self.user, mrp=Decimal("200.00")
        )

    def test_direct_match(self):
        result = CartService.resolve_variant_by_barcode("SCAN001")
        self.assertEqual(result, self.variant)

    def test_no_match_returns_none(self):
        result = CartService.resolve_variant_by_barcode("NONEXISTENT")
        self.assertIsNone(result)

    def test_barcode_mapping_match(self):
        BarcodeMapping.objects.create(
            barcode="ALT001",
            variant=self.other_variant,
        )
        result = CartService.resolve_variant_by_barcode("ALT001")
        self.assertEqual(result, self.other_variant)

    def test_barcode_mapping_prefers_direct_variant_match(self):
        variant_with_same_barcode_as_mapping = create_test_variant(
            barcode="CONFLICT", user=self.user, mrp=Decimal("300.00")
        )
        BarcodeMapping.objects.create(
            barcode="CONFLICT",
            variant=self.other_variant,
        )
        result = CartService.resolve_variant_by_barcode("CONFLICT")
        self.assertEqual(result, variant_with_same_barcode_as_mapping)

    def test_fuzzy_match_resolves_spelling_mistake(self):
        product = create_test_product(brand="Levi's", name="Cotton Denim Shirt")
        variant = create_test_variant(product=product, barcode="LEV-SHIRT-01", user=self.user)
        from base.weighted_search import invalidate_cache, PRODUCT_VARIANT_WEIGHTED_CACHE_KEY
        invalidate_cache(PRODUCT_VARIANT_WEIGHTED_CACHE_KEY)

        # Misspelled brand/product queries
        result = CartService.resolve_variant_by_barcode("shrit")
        self.assertEqual(result, variant)

        result_brand = CartService.resolve_variant_by_barcode("leevis")
        self.assertEqual(result_brand, variant)


class BarcodeSuggestionsTests(TestCase):
    """Tests for barcode_suggestions view endpoint."""

    def setUp(self):
        self.user = create_test_user(is_staff=True)
        self.client.force_login(self.user)
        self.product = create_test_product(brand="Adidas", name="Sports T-Shirt")
        self.variant = create_test_variant(
            product=self.product, barcode="ADI-TSHIRT-01", user=self.user
        )
        from base.weighted_search import invalidate_cache, PRODUCT_VARIANT_WEIGHTED_CACHE_KEY
        invalidate_cache(PRODUCT_VARIANT_WEIGHTED_CACHE_KEY)

    def test_suggestions_exact_match(self):
        response = self.client.get("/cart/barcode-suggestions/?search=Adidas")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(any(item["barcode"] == "ADI-TSHIRT-01" for item in data))

    def test_suggestions_fuzzy_misspelling_match(self):
        # Misspelled search term "adidass" or "shrit"
        response = self.client.get("/cart/barcode-suggestions/?search=adidass")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data) > 0)
        self.assertEqual(data[0]["barcode"], "ADI-TSHIRT-01")

    def test_suggestions_exact_barcode_priority(self):
        # Create a second variant whose name contains the search string
        prod2 = create_test_product(brand="Brand", name="Item 10001 extra")
        create_test_variant(product=prod2, barcode="999999", user=self.user)

        # Create exact barcode variant
        prod1 = create_test_product(brand="Brand", name="Other Item")
        create_test_variant(product=prod1, barcode="10001", user=self.user)

        response = self.client.get("/cart/barcode-suggestions/?search=10001")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data) > 0)
        # Exact barcode match "10001" must be ranked first
        self.assertEqual(data[0]["barcode"], "10001")

    def test_suggestions_short_query_returns_empty(self):
        response = self.client.get("/cart/barcode-suggestions/?search=a")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

