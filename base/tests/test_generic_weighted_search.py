"""
Tests for Generic Weighted Search Engine across Customers, Suppliers, and Invoices.
"""

from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase

User = get_user_model()

from base.suggestions import (
    category_all_suggestions,
    customer_all_suggestions,
    gst_hsn_all_suggestions,
    invoice_all_suggestions,
    supplier_all_suggestions,
    uom_all_suggestions,
)
from base.weighted_search import (
    CATEGORY_SEARCH_CONFIG,
    CATEGORY_WEIGHTED_CACHE_KEY,
    CUSTOMER_SEARCH_CONFIG,
    CUSTOMER_WEIGHTED_CACHE_KEY,
    GST_HSN_SEARCH_CONFIG,
    GST_HSN_WEIGHTED_CACHE_KEY,
    INVOICE_SEARCH_CONFIG,
    INVOICE_WEIGHTED_CACHE_KEY,
    SUPPLIER_SEARCH_CONFIG,
    SUPPLIER_WEIGHTED_CACHE_KEY,
    UOM_SEARCH_CONFIG,
    UOM_WEIGHTED_CACHE_KEY,
    get_category_suggestions,
    get_customer_suggestions,
    get_generic_records,
    get_generic_suggestions,
    get_gst_hsn_suggestions,
    get_invoice_suggestions,
    get_supplier_suggestions,
    get_uom_suggestions,
    score_generic_record,
    search_generic_weighted,
)
from customer.models import Customer
from inventory.models import Category, GSTHsnCode, UOM
from invoice.models import Invoice
from supplier.models import Supplier


class GenericWeightedSearchScoringTests(TestCase):
    """Unit tests for generic scoring and multi-word alignment."""

    def setUp(self):
        self.sample_customer = {
            "id": 1,
            "name": "John Doe",
            "phone_number": "9876543210",
            "email": "john@example.com",
            "address": "123 Main Street, Surat",
        }
        self.sample_supplier = {
            "id": 1,
            "name": "Acme Textiles",
            "phone": "9988776655",
            "email": "acme@textiles.com",
            "gstin": "24ABCDE1234F1Z5",
            "city": "Surat",
            "state": "Gujarat",
        }
        self.sample_invoice = {
            "id": 1,
            "invoice_number": "INV-2026-001",
            "customer__name": "John Doe",
            "customer__phone_number": "9876543210",
            "notes": "Wedding collection order",
        }

    def test_customer_name_and_phone_scoring(self):
        # Name match
        score = score_generic_record("John", self.sample_customer, CUSTOMER_SEARCH_CONFIG)
        self.assertGreater(score, 70.0)

        # Phone match
        phone_score = score_generic_record("9876543210", self.sample_customer, CUSTOMER_SEARCH_CONFIG)
        self.assertGreater(phone_score, 80.0)

        # Multi-word name + phone
        combo_score = score_generic_record("John 98765", self.sample_customer, CUSTOMER_SEARCH_CONFIG)
        self.assertGreater(combo_score, 80.0)

    def test_customer_typo_tolerance(self):
        # Typo 'Jhon' for 'John'
        typo_score = score_generic_record("Jhon", self.sample_customer, CUSTOMER_SEARCH_CONFIG)
        self.assertGreater(typo_score, 65.0)

    def test_supplier_gstin_and_city_scoring(self):
        # GSTIN match
        gst_score = score_generic_record("24ABCDE1234F1Z5", self.sample_supplier, SUPPLIER_SEARCH_CONFIG)
        self.assertGreater(gst_score, 80.0)

        # City match
        city_score = score_generic_record("Surat", self.sample_supplier, SUPPLIER_SEARCH_CONFIG)
        self.assertGreater(city_score, 50.0)

        # Unordered 'Surat Acme'
        unordered_score = score_generic_record("Surat Acme", self.sample_supplier, SUPPLIER_SEARCH_CONFIG)
        self.assertGreater(unordered_score, 80.0)

    def test_invoice_number_and_customer_scoring(self):
        # Invoice number
        inv_score = score_generic_record("INV-2026-001", self.sample_invoice, INVOICE_SEARCH_CONFIG)
        self.assertGreater(inv_score, 80.0)

        # Customer name
        cust_score = score_generic_record("John Doe", self.sample_invoice, INVOICE_SEARCH_CONFIG)
        self.assertGreater(cust_score, 70.0)


class GenericSuggestionsTests(TestCase):
    """Unit tests for suggestion generation and label formatting across models."""

    def setUp(self):
        self.test_customers = [
            {"id": 1, "name": "Vikas Sharma", "phone_number": "9876543210", "email": "vikas@gmail.com", "address": "Surat"},
            {"id": 2, "name": "Vikram Patel", "phone_number": "9123456789", "email": "vikram@gmail.com", "address": "Ahmedabad"},
            {"id": 3, "name": "Rahul Verma", "phone_number": "9898989898", "email": "rahul@gmail.com", "address": "Mumbai"},
        ]
        self.test_suppliers = [
            {"id": 1, "name": "Royal Fabrics", "phone": "9800112233", "email": "royal@fabrics.com", "gstin": "24AAAAA0000A1Z5", "city": "Surat", "state": "Gujarat"},
            {"id": 2, "name": "Surat Silk Mills", "phone": "9811223344", "email": "info@suratsilk.com", "gstin": "24BBBBB0000B1Z5", "city": "Surat", "state": "Gujarat"},
        ]
        self.test_invoices = [
            {"id": 1, "invoice_number": "INV-001", "customer__name": "Vikas Sharma", "customer__phone_number": "9876543210", "notes": ""},
            {"id": 2, "invoice_number": "INV-002", "customer__name": "Rahul Verma", "customer__phone_number": "9898989898", "notes": ""},
        ]

    def test_customer_suggestions_by_name(self):
        suggestions = get_customer_suggestions("Vikas", records=self.test_customers)
        self.assertTrue(len(suggestions) >= 1)
        self.assertEqual(suggestions[0], "Vikas Sharma")

    def test_customer_suggestions_by_phone(self):
        suggestions = get_customer_suggestions("98765", records=self.test_customers)
        self.assertTrue(len(suggestions) >= 1)
        self.assertIn("Vikas Sharma 9876543210", suggestions)

    def test_customer_suggestions_rich(self):
        rich_sug = get_customer_suggestions("Vikas", records=self.test_customers, rich=True)
        self.assertTrue(len(rich_sug) >= 1)
        self.assertEqual(rich_sug[0]["label"], "Vikas Sharma")
        self.assertEqual(rich_sug[0]["type"], "customer")

    def test_supplier_suggestions(self):
        suggestions = get_supplier_suggestions("Royal", records=self.test_suppliers)
        self.assertTrue(len(suggestions) >= 1)
        self.assertEqual(suggestions[0], "Royal Fabrics")

    def test_invoice_suggestions(self):
        suggestions = get_invoice_suggestions("INV-001", records=self.test_invoices)
        self.assertTrue(len(suggestions) >= 1)
        self.assertIn("INV-001 Vikas Sharma", suggestions)

    def test_invoice_suggestions_by_customer_name(self):
        """Searching invoice by customer name (e.g. 'Vikas') suggests customer name directly without invoice no prefix."""
        suggestions = get_invoice_suggestions("Vikas", records=self.test_invoices)
        self.assertTrue(len(suggestions) >= 1)
        self.assertEqual(suggestions[0], "Vikas Sharma")


class GenericSearchDBAndCacheIntegrationTests(TestCase):
    """Database integration tests for Generic Weighted Search across models."""

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

        # Create Customers
        self.customer1 = Customer.objects.create(
            name="Aarav Mehta",
            phone_number="9876500001",
            email="aarav@mehta.com",
            address="Ring Road, Surat",
        )
        self.customer2 = Customer.objects.create(
            name="Aarohi Shah",
            phone_number="9876500002",
            email="aarohi@shah.com",
            address="Varachha, Surat",
        )

        # Create Supplier
        self.supplier1 = Supplier.objects.create(
            name="Gujarat Texturizers",
            phone="9123400001",
            email="sales@gujarattex.com",
            gstin="24AABCG1234F1Z1",
            city="Surat",
            state="Gujarat",
        )

        # Create User for Invoice
        self.user = User.objects.create_user(
            first_name="Test",
            phone_number="9876543210",
            password="password123",
        )

        # Create Invoice
        self.invoice1 = Invoice.objects.create(
            sequence_no=999,
            invoice_number="INV-2026-999",
            customer=self.customer1,
            amount=Decimal("1500.00"),
            created_by=self.user,
            sold_by=self.user,
        )

    def tearDown(self):
        cache.clear()

    def test_customer_cache_and_suggestions(self):
        # 1. Fetch suggestions from DB
        suggestions = get_customer_suggestions("Aarav")
        self.assertTrue(len(suggestions) >= 1)
        self.assertEqual(suggestions[0], "Aarav Mehta")

        # 2. Check cache populated
        cached = cache.get(CUSTOMER_WEIGHTED_CACHE_KEY)
        self.assertIsNotNone(cached)
        self.assertTrue(any(c["name"] == "Aarav Mehta" for c in cached))

    def test_customer_signal_invalidation(self):
        # Populate cache
        get_customer_suggestions("Aarav")
        self.assertIsNotNone(cache.get(CUSTOMER_WEIGHTED_CACHE_KEY))

        # Update customer -> triggers signal
        self.customer1.name = "Aarav Mehta Updated"
        self.customer1.save()

        # Cache should be cleared
        self.assertIsNone(cache.get(CUSTOMER_WEIGHTED_CACHE_KEY))

    def test_supplier_suggestions_endpoint(self):
        request = self.factory.get("/suggestions/suppliers/?q=Gujarat")
        response = supplier_all_suggestions(request)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data.get("success"))
        labels = [item["label"] for item in data.get("data", [])]
        self.assertIn("Gujarat Texturizers", labels)

    def test_invoice_suggestions_endpoint(self):
        request = self.factory.get("/suggestions/invoices/?q=INV-2026-999")
        response = invoice_all_suggestions(request)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data.get("success"))
        labels = [item["label"] for item in data.get("data", [])]
        self.assertTrue(any("INV-2026-999" in label for label in labels))

    def test_category_suggestions_endpoint(self):
        Category.objects.create(name="Cotton Shirts", description="Pure cotton formal shirts")
        request = self.factory.get("/suggestions/categories/?q=Cotton")
        response = category_all_suggestions(request)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data.get("success"))
        labels = [item["label"] for item in data.get("data", [])]
        self.assertIn("Cotton Shirts", labels)

    def test_uom_suggestions_endpoint(self):
        UOM.objects.create(name="Pieces", short_code="PCS", category="Quantity")
        request = self.factory.get("/suggestions/uom/?q=Piece")
        response = uom_all_suggestions(request)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data.get("success"))
        labels = [item["label"] for item in data.get("data", [])]
        self.assertIn("Pieces", labels)

    def test_gst_hsn_suggestions_endpoint(self):
        GSTHsnCode.objects.create(code="5208", description="Woven fabrics of cotton", is_active=True)
        request = self.factory.get("/suggestions/gst-hsn/?q=5208")
        response = gst_hsn_all_suggestions(request)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertTrue(data.get("success"))
        labels = [item["label"] for item in data.get("data", [])]
        self.assertTrue(any("5208" in label for label in labels))

