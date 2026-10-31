"""
Tests for weighted product and variant search: per-field scoring, sibling expansion,
caching, signal invalidation, and suggestion endpoints.
"""

from decimal import Decimal
import json

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from base.suggestions import (
    product_all_suggestions,
    product_variant_all_suggestions,
)
from base.weighted_search import (
    FIELD_WEIGHTS,
    PRODUCT_VARIANT_WEIGHTED_CACHE_KEY,
    PRODUCT_WEIGHTED_CACHE_KEY,
    VARIANT_FIELD_WEIGHTS,
    get_product_records,
    get_variant_records,
    get_weighted_product_suggestions,
    get_weighted_variant_suggestions,
    score_product,
    score_variant,
    search_products_weighted,
    search_variants_weighted,
)
from inventory.models import Category, Color, GSTHsnCode, Product, ProductVariant, Size


class WeightedSearchScoringTests(TestCase):
    """Unit tests for score_product and score_variant evaluation."""

    def setUp(self):
        self.sample_product = {
            "id": 1,
            "brand": "Vikas",
            "name": "Kamal",
            "category__name": "Shirts",
        }
        self.sample_variant = {
            "id": 10,
            "barcode": "BAR12345",
            "product_id": 1,
            "product__brand": "Vikas",
            "product__name": "Kamal",
            "product__category__name": "Shirts",
            "size__name": "L",
            "color__name": "Red",
        }

    def test_empty_query_or_product(self):
        self.assertEqual(score_product("", self.sample_product), 0.0)
        self.assertEqual(score_product("Vikas", {}), 0.0)
        self.assertEqual(score_product(None, self.sample_product), 0.0)

    def test_exact_brand_match(self):
        score = score_product("Vikas", self.sample_product)
        self.assertGreater(score, 50.0)

    def test_exact_name_match(self):
        score = score_product("Kamal", self.sample_product)
        self.assertGreater(score, 30.0)

    def test_full_brand_and_name_match(self):
        score = score_product("Vikas Kamal", self.sample_product)
        self.assertGreater(score, 80.0)

    def test_custom_weights(self):
        custom_weights = {"brand": 10.0, "name": 1.0}
        score = score_product("Vikas", self.sample_product, weights=custom_weights)
        self.assertGreater(score, 90.0)

    def test_variant_barcode_match(self):
        score = score_variant("BAR12345", self.sample_variant)
        self.assertGreater(score, 90.0)

    def test_variant_brand_name_match(self):
        score = score_variant("Vikas Kamal", self.sample_variant)
        self.assertGreater(score, 80.0)

    def test_variant_empty_query(self):
        self.assertEqual(score_variant("", self.sample_variant), 0.0)
        self.assertEqual(score_variant("BAR12345", {}), 0.0)


class SiblingExpansionSearchTests(TestCase):
    """Tests for anchor detection and sibling expansion algorithm."""

    def setUp(self):
        self.test_records = [
            {"id": 1, "brand": "Vikas", "name": "Kamal", "category__name": "Shirts"},
            {"id": 2, "brand": "Vikas", "name": "Bunny", "category__name": "Pants"},
            {"id": 3, "brand": "Vikas", "name": "Chotu", "category__name": "T-Shirts"},
            {"id": 4, "brand": "Siddhartha", "name": "Black", "category__name": "Jeans"},
            {"id": 5, "brand": "Siddhartha", "name": "Beauty", "category__name": "Sarees"},
        ]
        self.test_variant_records = [
            {
                "id": 101,
                "barcode": "1001",
                "product_id": 1,
                "product__brand": "Vikas",
                "product__name": "Kamal",
                "product__category__name": "Shirts",
                "size__name": "L",
                "color__name": "Red",
            },
            {
                "id": 102,
                "barcode": "1002",
                "product_id": 1,
                "product__brand": "Vikas",
                "product__name": "Kamal",
                "product__category__name": "Shirts",
                "size__name": "XL",
                "color__name": "Blue",
            },
            {
                "id": 103,
                "barcode": "1003",
                "product_id": 2,
                "product__brand": "Vikas",
                "product__name": "Bunny",
                "product__category__name": "Pants",
                "size__name": "M",
                "color__name": "Black",
            },
            {
                "id": 104,
                "barcode": "2001",
                "product_id": 4,
                "product__brand": "Siddhartha",
                "product__name": "Black",
                "product__category__name": "Jeans",
                "size__name": "32",
                "color__name": "Dark",
            },
        ]

    def test_brand_search_dominates(self):
        """Searching 'Vikas' should rank all Vikas products at the top."""
        results = search_products_weighted("Vikas", records=self.test_records, min_score=40.0)
        top_ids = [r["id"] for r in results[:3]]
        self.assertIn(1, top_ids)
        self.assertIn(2, top_ids)
        self.assertIn(3, top_ids)
        for r in results[:3]:
            self.assertEqual(r["brand"], "Vikas")

    def test_anchor_sibling_expansion(self):
        """
        Searching 'Kamal' should find Vikas/Kamal as anchor,
        and pull sibling Vikas products (Bunny, Chotu) into the results.
        """
        results = search_products_weighted(
            "Kamal",
            records=self.test_records,
            min_score=30.0,
            anchor_confidence=70.0,
            sibling_boost_factor=0.85,
        )
        self.assertTrue(len(results) >= 3)
        self.assertEqual(results[0]["name"], "Kamal")
        self.assertEqual(results[0]["brand"], "Vikas")
        self.assertTrue(results[0]["is_anchor"])

        sibling_names = [r["name"] for r in results[1:3]]
        self.assertIn("Bunny", sibling_names)
        self.assertIn("Chotu", sibling_names)

        siddhartha_ranks = [i for i, r in enumerate(results) if r["brand"] == "Siddhartha"]
        for rank in siddhartha_ranks:
            self.assertGreater(rank, 2)

    def test_variant_barcode_search(self):
        results = search_variants_weighted("1001", records=self.test_variant_records)
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0]["barcode"], "1001")
        self.assertEqual(results[0]["id"], 101)

    def test_variant_sibling_expansion(self):
        """
        Searching 'Kamal' should match Vikas Kamal (L/Red) as anchor,
        and boost Vikas Kamal (XL/Blue) [product sibling] and Vikas Bunny [brand sibling].
        """
        results = search_variants_weighted(
            "Kamal",
            records=self.test_variant_records,
            min_score=30.0,
            anchor_confidence=70.0,
        )
        self.assertTrue(len(results) >= 2)
        # Top result is anchor
        self.assertEqual(results[0]["product__name"], "Kamal")
        self.assertTrue(results[0]["is_anchor"])

        # Product sibling (id 102) is boosted
        product_sibling = next((r for r in results if r["id"] == 102), None)
        self.assertIsNotNone(product_sibling)
        self.assertTrue(product_sibling["is_product_sibling"])

    def test_low_confidence_query_does_not_expand_siblings(self):
        results = search_products_weighted(
            "xyzq",
            records=self.test_records,
            min_score=10.0,
            anchor_confidence=95.0,
        )
        for r in results:
            self.assertFalse(r.get("is_sibling", False))

    def test_short_query_returns_empty(self):
        self.assertEqual(search_products_weighted("a", records=self.test_records), [])
        self.assertEqual(search_products_weighted("", records=self.test_records), [])
        self.assertEqual(search_variants_weighted("a", records=self.test_variant_records), [])
        self.assertEqual(search_variants_weighted("", records=self.test_variant_records), [])

    def test_get_weighted_product_suggestions_formatting(self):
        """Querying by product name directly suggests product name without forced brand prefix."""
        suggestions = get_weighted_product_suggestions(
            "Kamal",
            records=self.test_records,
            limit=5,
            min_score=30.0,
            anchor_confidence=70.0,
        )
        self.assertIn("Kamal", suggestions)

    def test_get_weighted_product_suggestions_single_word_hierarchical(self):
        """Single-word query matching brand returns brand first, then products under that brand."""
        suggestions_rich = get_weighted_product_suggestions(
            "Vikas",
            records=self.test_records,
            limit=5,
            rich=True,
        )
        self.assertTrue(len(suggestions_rich) >= 2)
        # Brand should be the first suggestion
        self.assertEqual(suggestions_rich[0]["label"], "Vikas")
        self.assertEqual(suggestions_rich[0]["type"], "brand")

        # Products under Vikas should follow
        labels = [s["label"] for s in suggestions_rich]
        self.assertIn("Vikas Kamal", labels)

    def test_get_weighted_product_suggestions_multi_word(self):
        """Multi-word query should refine directly to matching products."""
        suggestions_rich = get_weighted_product_suggestions(
            "Vikas Kam",
            records=self.test_records,
            limit=5,
            rich=True,
        )
        self.assertTrue(len(suggestions_rich) >= 1)
        self.assertEqual(suggestions_rich[0]["label"], "Vikas Kamal")
        self.assertEqual(suggestions_rich[0]["type"], "product")

    def test_get_weighted_product_suggestions_unordered_words(self):
        """Query with reversed/unordered words (e.g. 'Kamal Vikas' or 'Beauty Siddhartha') matches accurately."""
        score = score_product("Kamal Vikas", self.test_records[0])
        self.assertGreater(score, 85.0)

        suggestions = get_weighted_product_suggestions(
            "Kamal Vikas",
            records=self.test_records,
            limit=5,
        )
        self.assertTrue(len(suggestions) >= 1)
        self.assertIn("Vikas Kamal", suggestions)

    def test_get_weighted_product_suggestions_multi_word_typo(self):
        """Typo in multi-word query (e.g. 'special gald' for 'special gold') ranks the exact product at top."""
        test_records = [
            {"id": 1, "brand": "Saree", "name": "Special Gold", "category__name": "Silk"},
            {"id": 2, "brand": "Saree", "name": "Special White", "category__name": "Silk"},
            {"id": 3, "brand": "Saree", "name": "Special Black", "category__name": "Silk"},
        ]
        suggestions = get_weighted_product_suggestions(
            "special gald",
            records=test_records,
            limit=5,
        )
        self.assertTrue(len(suggestions) >= 1)
        self.assertEqual(suggestions[0], "Special Gold")

    def test_get_weighted_variant_suggestions_multi_word_typo(self):
        """Typo in multi-word variant query ('special gald') ranks Special Gold variant at top."""
        test_variants = [
            {
                "id": 10,
                "barcode": "1001",
                "product_id": 1,
                "product__brand": "Saree",
                "product__name": "Special Gold",
                "product__category__name": "Silk",
                "size__name": "L",
                "color__name": "Red",
            },
            {
                "id": 20,
                "barcode": "1002",
                "product_id": 2,
                "product__brand": "Saree",
                "product__name": "Special White",
                "product__category__name": "Silk",
                "size__name": "M",
                "color__name": "White",
            },
            {
                "id": 30,
                "barcode": "1003",
                "product_id": 3,
                "product__brand": "Saree",
                "product__name": "Special Black",
                "product__category__name": "Silk",
                "size__name": "XL",
                "color__name": "Black",
            },
        ]
        suggestions = get_weighted_variant_suggestions(
            "special gald",
            records=test_variants,
            limit=5,
        )
        self.assertTrue(len(suggestions) >= 1)
        self.assertEqual(suggestions[0], "Special Gold L Red")

    def test_get_weighted_variant_suggestions_formatting(self):
        """Querying variant by name suggests name + size/color."""
        suggestions = get_weighted_variant_suggestions(
            "Kamal",
            records=self.test_variant_records,
            limit=5,
            min_score=30.0,
            anchor_confidence=70.0,
        )
        self.assertTrue(any("Kamal" in s for s in suggestions))

    def test_get_weighted_variant_suggestions_single_word_hierarchical(self):
        """Single-word query for variants returns matching brand first."""
        suggestions_rich = get_weighted_variant_suggestions(
            "Vikas",
            records=self.test_variant_records,
            limit=5,
            rich=True,
        )
        self.assertTrue(len(suggestions_rich) >= 1)
        self.assertEqual(suggestions_rich[0]["label"], "Vikas")
        self.assertEqual(suggestions_rich[0]["type"], "brand")


class WeightedSearchDBAndCacheIntegrationTests(TestCase):
    """Database and caching integration tests for weighted product and variant search."""

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

        self.hsn = GSTHsnCode.objects.create(
            code="6205",
            gst_percentage=Decimal("5.00"),
        )
        self.cat_shirts = Category.objects.create(name="Shirts")
        self.cat_pants = Category.objects.create(name="Pants")
        self.size_l = Size.objects.create(name="L")
        self.size_m = Size.objects.create(name="M")
        self.color_red = Color.objects.create(name="Red")

        self.p1 = Product.objects.create(
            brand="Vikas",
            name="Kamal",
            category=self.cat_shirts,
            hsn_code=self.hsn,
        )
        self.p2 = Product.objects.create(
            brand="Vikas",
            name="Bunny",
            category=self.cat_pants,
            hsn_code=self.hsn,
        )
        self.p3 = Product.objects.create(
            brand="Siddhartha",
            name="Black",
            category=self.cat_shirts,
            hsn_code=self.hsn,
        )

        self.v1 = ProductVariant.objects.create(
            product=self.p1,
            barcode="VK001",
            size=self.size_l,
            color=self.color_red,
            purchase_price=Decimal("500"),
            mrp=Decimal("800"),
        )
        self.v2 = ProductVariant.objects.create(
            product=self.p2,
            barcode="VK002",
            size=self.size_m,
            purchase_price=Decimal("400"),
            mrp=Decimal("700"),
        )

    def tearDown(self):
        cache.clear()

    def test_get_product_records_caching(self):
        records = get_product_records()
        self.assertEqual(len(records), 3)

        cached_records = cache.get(PRODUCT_WEIGHTED_CACHE_KEY)
        self.assertIsNotNone(cached_records)
        self.assertEqual(len(cached_records), 3)

    def test_get_variant_records_caching(self):
        records = get_variant_records()
        self.assertEqual(len(records), 2)

        cached_records = cache.get(PRODUCT_VARIANT_WEIGHTED_CACHE_KEY)
        self.assertIsNotNone(cached_records)
        self.assertEqual(len(cached_records), 2)

    def test_cache_invalidation_on_product_save(self):
        get_product_records()
        get_variant_records()
        self.assertIsNotNone(cache.get(PRODUCT_WEIGHTED_CACHE_KEY))
        self.assertIsNotNone(cache.get(PRODUCT_VARIANT_WEIGHTED_CACHE_KEY))

        Product.objects.create(
            brand="Vikas",
            name="Chotu",
            category=self.cat_shirts,
            hsn_code=self.hsn,
        )

        self.assertIsNone(cache.get(PRODUCT_WEIGHTED_CACHE_KEY))
        self.assertIsNone(cache.get(PRODUCT_VARIANT_WEIGHTED_CACHE_KEY))

    def test_cache_invalidation_on_variant_save(self):
        get_variant_records()
        self.assertIsNotNone(cache.get(PRODUCT_VARIANT_WEIGHTED_CACHE_KEY))

        ProductVariant.objects.create(
            product=self.p3,
            barcode="SID001",
            size=self.size_l,
            purchase_price=Decimal("600"),
            mrp=Decimal("999"),
        )

        self.assertIsNone(cache.get(PRODUCT_VARIANT_WEIGHTED_CACHE_KEY))

    def test_product_suggestions_endpoint(self):
        request = self.factory.get("/suggestions/products/", {"q": "Vikas"})
        response = product_all_suggestions(request)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertTrue(len(data["data"]) >= 1)
        labels = [item["label"] if isinstance(item, dict) else item for item in data["data"]]
        self.assertIn("Vikas", labels)

    def test_variant_suggestions_endpoint(self):
        request = self.factory.get("/suggestions/product-variants/", {"q": "VK001"})
        response = product_variant_all_suggestions(request)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertTrue(len(data["data"]) >= 1)
        labels = [item["label"] if isinstance(item, dict) else item for item in data["data"]]
        self.assertTrue(any("Vikas Kamal" in s for s in labels))

    def test_variant_suggestions_endpoint_empty_query(self):
        request = self.factory.get("/suggestions/product-variants/", {"q": ""})
        response = product_variant_all_suggestions(request)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertEqual(data["data"], [])
