"""Tests for the supplier app."""

from decimal import Decimal
import tempfile
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import Supplier, SupplierInvoice, SupplierPayment, MediaFile

User = get_user_model()


class SupplierMediaTests(TestCase):
    """Test suite for media file attachments during SupplierInvoice and SupplierPayment creation."""

    def setUp(self):
        """Set up test user, permissions, and initial objects."""
        self.user = User.objects.create_user(
            password="testpassword",
            email="testuser@example.com",
            first_name="Test",
            phone_number="9999999999"
        )
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.client.login(username="9999999999", password="testpassword")

        # Create test supplier
        self.supplier = Supplier.objects.create(
            name="Test Supplier",
            contact_person="Contact Person",
            email="supplier@example.com",
            phone="9876543210",
            created_by=self.user
        )

    def test_supplier_invoice_form_and_creation_without_attachments(self):
        """Test creating a supplier invoice without attachments."""
        url = reverse("supplier:create_invoice", kwargs={"supplier_pk": self.supplier.pk})
        data = {
            "invoice_number": "INV-001",
            "invoice_date": "2026-06-29T12:00",
            "invoice_type": "LOCAL_PURCHASE",
            "sub_total": "1000.00",
            "cgst_amount": "0.00",
            "igst_amount": "0.00",
            "adjustment_amount": "0.00",
            "notes": "No attachments",
        }
        response = self.client.post(url, data)
        if response.status_code != 302:
            print("INVOICE CREATE WITHOUT ATTACHMENTS ERRORS:", response.context['form'].errors)
        self.assertEqual(response.status_code, 302)
        
        # Verify invoice created
        invoice = SupplierInvoice.objects.get(invoice_number="INV-001")
        self.assertEqual(invoice.total_amount, Decimal("1000.00"))
        self.assertEqual(invoice.media_files.count(), 0)

    @override_settings(MEDIA_ROOT=tempfile.gettempdir())
    def test_supplier_invoice_creation_with_attachments(self):
        """Test creating a supplier invoice with file attachments."""
        url = reverse("supplier:create_invoice", kwargs={"supplier_pk": self.supplier.pk})
        
        pdf_file = SimpleUploadedFile("invoice.pdf", b"test pdf content", content_type="application/pdf")
        jpg_file = SimpleUploadedFile("receipt.jpg", b"test jpg content", content_type="image/jpeg")

        data = {
            "invoice_number": "INV-002",
            "invoice_date": "2026-06-29T12:00",
            "invoice_type": "LOCAL_PURCHASE",
            "sub_total": "1500.00",
            "cgst_amount": "0.00",
            "igst_amount": "0.00",
            "adjustment_amount": "0.00",
            "notes": "With attachments",
            "attachments": [pdf_file, jpg_file]
        }
        
        response = self.client.post(url, data)
        if response.status_code != 302:
            print("INVOICE CREATE WITH ATTACHMENTS ERRORS:", response.context['form'].errors)
        self.assertEqual(response.status_code, 302)
        
        invoice = SupplierInvoice.objects.get(invoice_number="INV-002")
        self.assertEqual(invoice.media_files.count(), 2)
        
        media_names = [m.original_filename for m in invoice.media_files.all()]
        self.assertIn("invoice.pdf", media_names)
        self.assertIn("receipt.jpg", media_names)

    def test_supplier_payment_creation_without_attachments(self):
        """Test creating a supplier payment without attachments."""
        url = reverse("supplier:create_payment", kwargs={"supplier_pk": self.supplier.pk})
        data = {
            "amount": "500.00",
            "method": "CASH",
            "payment_date": "2026-06-29T12:00",
            "transaction_id": "",
            "notes": "No attachments",
        }
        response = self.client.post(url, data)
        if response.status_code != 302:
            print("PAYMENT CREATE WITHOUT ATTACHMENTS ERRORS:", response.context['form'].errors)
        self.assertEqual(response.status_code, 302)

        payment = SupplierPayment.objects.get(amount=Decimal("500.00"))
        self.assertEqual(payment.media_files.count(), 0)

    @override_settings(MEDIA_ROOT=tempfile.gettempdir())
    def test_supplier_payment_creation_with_attachments(self):
        """Test creating a supplier payment with file attachments."""
        url = reverse("supplier:create_payment", kwargs={"supplier_pk": self.supplier.pk})
        
        pdf_file = SimpleUploadedFile("payment.pdf", b"payment pdf content", content_type="application/pdf")

        data = {
            "amount": "800.00",
            "method": "BANK_TRANSFER",
            "payment_date": "2026-06-29T12:00",
            "transaction_id": "TXN123456",
            "notes": "With payment receipt",
            "attachments": [pdf_file]
        }
        
        response = self.client.post(url, data)
        if response.status_code != 302:
            print("PAYMENT CREATE WITH ATTACHMENTS ERRORS:", response.context['form'].errors)
        self.assertEqual(response.status_code, 302)
        
        payment = SupplierPayment.objects.get(amount=Decimal("800.00"))
        self.assertEqual(payment.media_files.count(), 1)
        self.assertEqual(payment.media_files.first().original_filename, "payment.pdf")
