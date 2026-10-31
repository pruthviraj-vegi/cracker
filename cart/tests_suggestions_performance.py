"""
Performance and query benchmark tests for Variant Word Suggestions and Cart Barcode Suggestions.

Uses `timed` and `query_debugger` from `base.decorators` to establish baseline
metrics (execution time and SQL query count) to track improvements before and after optimizations.
"""

import json
from decimal import Decimal

from django.conf import settings
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from base.decorators import query_debugger, timed
from base.suggestions import product_variant_all_suggestions
from base.weighted_search import (
    PRODUCT_VARIANT_WEIGHTED_CACHE_KEY,
    get_weighted_variant_suggestions,
    invalidate_cache,
)
from Billing.tests.helpers import (
    create_test_cart,
    create_test_product,
    create_test_user,
    create_test_variant,
)
from inventory.models import Color, ProductVariant, Size
from cart.models import CartItem
from cart.views import barcode_suggestions


class SuggestionsBenchmarkTests(TestCase):
    """
    Measures timing and database query efficiency for:
    1. Word suggestions (Variant Weighted Search)
    2. Cart barcode suggestions (Tiered Matching + Serialization)
    """

    @classmethod
    def setUpTestData(cls):
        cls.factory = RequestFactory()
        cls.user = create_test_user(is_staff=True)
        cls.cart = create_test_cart(user=cls.user)

        # Create sizes and colors
        cls.size_s, _ = Size.objects.get_or_create(name="S")
        cls.size_m, _ = Size.objects.get_or_create(name="M")
        cls.size_l, _ = Size.objects.get_or_create(name="L")
        cls.size_xl, _ = Size.objects.get_or_create(name="XL")

        cls.color_red, _ = Color.objects.get_or_create(name="Red")
        cls.color_blue, _ = Color.objects.get_or_create(name="Blue")
        cls.color_black, _ = Color.objects.get_or_create(name="Black")

        # Create 15 diverse products & variants
        cls.variants = []

        # 1. Adidas Brand (5 variants)
        p_adidas = create_test_product(brand="Adidas", name="Ultraboost Running Shoes")
        for i, (sz, col) in enumerate(
            [
                (cls.size_s, cls.color_black),
                (cls.size_m, cls.color_black),
                (cls.size_l, cls.color_blue),
                (cls.size_xl, cls.color_blue),
                (cls.size_m, cls.color_red),
            ],
            start=1,
        ):
            v = ProductVariant.objects.create(
                product=p_adidas,
                barcode=f"ADI-RUN-0{i}",
                size=sz,
                color=col,
                created_by=cls.user,
                purchase_price=Decimal("2000.00"),
                mrp=Decimal("3999.00"),
                quantity=20,
            )
            cls.variants.append(v)

        # 2. Nike Brand (5 variants)
        p_nike = create_test_product(brand="Nike", name="Air Max Running Shoes")
        for i, (sz, col) in enumerate(
            [
                (cls.size_s, cls.color_black),
                (cls.size_m, cls.color_black),
                (cls.size_l, cls.color_red),
                (cls.size_xl, cls.color_red),
                (cls.size_m, cls.color_blue),
            ],
            start=1,
        ):
            v = ProductVariant.objects.create(
                product=p_nike,
                barcode=f"NIKE-AIR-0{i}",
                size=sz,
                color=col,
                created_by=cls.user,
                purchase_price=Decimal("2500.00"),
                mrp=Decimal("4999.00"),
                quantity=15,
            )
            cls.variants.append(v)

        # 3. Puma Brand (5 variants)
        p_puma = create_test_product(brand="Puma", name="Velocity Sports T-Shirt")
        for i, (sz, col) in enumerate(
            [
                (cls.size_s, cls.color_red),
                (cls.size_m, cls.color_red),
                (cls.size_l, cls.color_black),
                (cls.size_xl, cls.color_black),
                (cls.size_l, cls.color_blue),
            ],
            start=1,
        ):
            v = ProductVariant.objects.create(
                product=p_puma,
                barcode=f"PUMA-TSH-0{i}",
                size=sz,
                color=col,
                created_by=cls.user,
                purchase_price=Decimal("500.00"),
                mrp=Decimal("999.00"),
                quantity=30,
            )
            cls.variants.append(v)

        # Create CartItems for several variants to simulate live cart state
        for v in cls.variants[:6]:
            CartItem.objects.create(
                cart=cls.cart,
                product_variant=v,
                quantity=2,
                price=v.mrp,
            )

    def setUp(self):
        self.client.force_login(self.user)
        # Clear cached search records to ensure clean state
        invalidate_cache(PRODUCT_VARIANT_WEIGHTED_CACHE_KEY)

    # -------------------------------------------------------------------------
    # 1. WORD SUGGESTION BENCHMARK (Uses @timed from base.decorators)
    # -------------------------------------------------------------------------

    def test_variant_word_suggestions_with_timer(self):
        """
        Benchmark word suggestions for product variants using @timed decorator.
        Measures execution time across single-word, multi-word, and fuzzy queries.
        """
        # Wrap suggestion function with timed decorator from base.decorators
        timed_variant_suggestions = timed(get_weighted_variant_suggestions)

        queries = [
            ("Single-word exact", "Adidas"),
            ("Single-word partial", "Adid"),
            ("Multi-word brand + name", "Adidas Running"),
            ("Multi-word brand + size", "Nike Running Shoes"),
            ("Fuzzy typo query", "Adidass Runing"),
        ]

        print(f"\n{'='*70}")
        print("BENCHMARK: Variant Word Suggestions (base.decorators.timed)")
        print(f"{'='*70}")

        for label, q in queries:
            results = timed_variant_suggestions(query=q, rich=True)
            elapsed_sec = timed_variant_suggestions.last_elapsed_time
            elapsed_ms = elapsed_sec * 1000

            print(f"[{label}] Query: '{q}'")
            print(f"  -> Returned: {len(results)} items")
            print(f"  -> Time: {elapsed_ms:.2f} ms ({elapsed_sec:.4f} s)")
            if results:
                print(f"  -> Top result: {results[0]}")

            # Verify function succeeded and timing was recorded
            self.assertIsNotNone(elapsed_sec)
            self.assertGreaterEqual(len(results), 1)

        # Also test the HTTP view layer directly
        timed_view = timed(product_variant_all_suggestions)
        req = self.factory.get("/suggestions/product-variants/", {"q": "Adidas Running"})
        response = timed_view(req)
        view_elapsed_ms = timed_view.last_elapsed_time * 1000

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["success"])
        print(f"[HTTP View Layer] Query: 'Adidas Running' -> {view_elapsed_ms:.2f} ms")
        print(f"{'='*70}\n")

    # -------------------------------------------------------------------------
    # 2. CART BARCODE SUGGESTIONS BENCHMARK (Uses @query_debugger & @timed)
    # -------------------------------------------------------------------------

    @override_settings(DEBUG=True)
    def test_cart_barcode_suggestions_with_query_debugger(self):
        """
        Benchmark cart barcode suggestions using @query_debugger and @timed from base.decorators.
        Exposes query counts, execution time, and reveals N+1 query patterns.
        """
        # Wrap view with query_debugger and timed decorators
        debugged_view = timed(query_debugger(barcode_suggestions))

        scenarios = [
            ("Exact Barcode", "ADI-RUN-01"),
            ("Barcode Prefix", "NIKE-AIR"),
            ("General Search (Multi-match)", "Running"),
            ("Fuzzy Typo Match", "Adidass"),
        ]

        print(f"\n{'='*70}")
        print("BENCHMARK: Cart Barcode Suggestions (query_debugger + timed)")
        print(f"{'='*70}")

        for label, search_term in scenarios:
            req = self.factory.get("/cart/barcode-suggestions/", {"search": search_term})
            req.user = self.user

            with CaptureQueriesContext(connection) as ctx:
                response = debugged_view(req)

            elapsed_ms = debugged_view.last_elapsed_time * 1000
            query_count = len(ctx.captured_queries)
            items = json.loads(response.content)

            print(f"[{label}] Search: '{search_term}'")
            print(f"  -> Results: {len(items)} items")
            print(f"  -> Queries: {query_count}")
            print(f"  -> Time: {elapsed_ms:.2f} ms")

            # Inspect what queries were executed
            if query_count > 0:
                aggregate_queries = [
                    q["sql"] for q in ctx.captured_queries if "SUM(" in q["sql"].upper()
                ]
                print(f"  -> Total Cart Item SUM Queries (N+1 check): {len(aggregate_queries)}")

            self.assertEqual(response.status_code, 200)
            self.assertGreaterEqual(len(items), 1)

        print(f"{'='*70}\n")
