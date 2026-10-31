"""
Models for managing suppliers, their invoices, and payments.
"""

import os
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.text import slugify

from base.manager import SoftDeleteModel, phone_regex
from base.utility import StringProcessor

User = settings.AUTH_USER_MODEL

# Create your models here.


class Supplier(SoftDeleteModel):
    """
    Represents a supplier. This model holds their contact information
    and will be used to track their overall account balance.
    """

    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, unique=True, validators=[phone_regex])
    phone_two = models.CharField(
        max_length=20, unique=True, validators=[phone_regex], blank=True, null=True
    )
    gstin = models.CharField(
        max_length=25, blank=True, help_text="Supplier's GST Identification Number."
    )
    first_line = models.CharField(max_length=255, blank=True, null=True)
    second_line = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    pincode = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="supplier_created_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = [
            ("view_dashboard", "view dashboard"),
            ("download_report", "download report"),
        ]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["is_deleted"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = StringProcessor(self.name).toTitle()
        self.contact_person = StringProcessor(self.contact_person).toTitle()
        self.email = StringProcessor(self.email).toLowercase()
        self.phone = StringProcessor(self.phone).cleaned_string
        self.gstin = StringProcessor(self.gstin).toUppercase()
        self.first_line = StringProcessor(self.first_line).toTitle()
        self.second_line = StringProcessor(self.second_line).toTitle()
        self.city = StringProcessor(self.city).toTitle()
        self.state = StringProcessor(self.state).toTitle()
        self.pincode = StringProcessor(self.pincode).toUppercase()
        self.country = StringProcessor(self.country).toTitle()

        super().save(*args, **kwargs)

    @property
    def balance_due(self):
        """Calculate total balance due for this supplier."""
        if hasattr(self, "annotated_balance_due") and self.annotated_balance_due is not None:
            return self.annotated_balance_due
        total_invoiced = self.invoices.filter(is_deleted=False).aggregate(
            total=Coalesce(
                Sum("total_amount"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            )
        )["total"]
        total_paid_on_invoices = self.payments_made.filter(is_deleted=False).aggregate(
            total=Coalesce(
                Sum("amount"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            )
        )["total"]
        return (total_invoiced - total_paid_on_invoices).quantize(Decimal("0.01"))

    @property
    def last_invoice(self):
        """Get the date of the last unpaid or partially paid invoice."""
        if hasattr(self, "annotated_last_invoice") and self.annotated_last_invoice is not None:
            return self.annotated_last_invoice
        invoice = (
            self.invoices.filter(
                is_deleted=False,
                status__in=[
                    SupplierInvoice.InvoiceStatus.UNPAID,
                    SupplierInvoice.InvoiceStatus.PARTIALLY_PAID,
                ],
            )
            .order_by("invoice_date")
            .first()
        )
        return invoice.invoice_date if invoice else None


class SupplierInvoice(SoftDeleteModel):
    """
    Represents a purchase invoice from a supplier. This is the core model
    for tracking purchases and linking them to your inventory.
    """

    class InvoiceType(models.TextChoices):
        """Types of invoices."""

        GST_APPLICABLE = "GST_APPLICABLE", "GST Applicable"
        LOCAL_PURCHASE = "LOCAL_PURCHASE", "Local Purchase"

    class GstType(models.TextChoices):
        """Types of GST applied."""

        CGST_SGST = "CGST_SGST", "CGST/SGST"
        IGST = "IGST", "IGST"

    class InvoiceStatus(models.TextChoices):
        """Status of the invoice."""

        UNPAID = "UNPAID", "Unpaid"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
        PAID = "PAID", "Paid"

    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="invoices"
    )
    invoice_number = models.CharField(
        max_length=100, help_text="The invoice number from the supplier."
    )
    invoice_date = models.DateTimeField(default=timezone.now)

    invoice_type = models.CharField(
        max_length=20, choices=InvoiceType.choices, default=InvoiceType.GST_APPLICABLE
    )

    gst_type = models.CharField(
        max_length=20,
        choices=GstType.choices,
        null=True,
        blank=True,
        help_text="Specify GST type if applicable.",
        default=GstType.IGST,
    )
    sub_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="The total amount before taxes.",
    )

    # CHANGED: As per your request, only storing cgst_amount. SGST is assumed to be the same.
    cgst_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="For CGST/SGST type, SGST is assumed to be the same as this amount.",
    )
    igst_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0")
    )
    adjustment_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0")
    )

    status = models.CharField(
        max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.UNPAID
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="The grand total amount including all taxes.",
    )
    paid_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0")
    )
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="supplier_invoice_created_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("supplier", "invoice_number", "invoice_date")
        ordering = ["-invoice_date"]
        indexes = [
            # .filter(is_deleted=False) — from SoftDeleteModel, used in every query
            models.Index(fields=["is_deleted"]),
            # default ordering and sort
            models.Index(fields=["invoice_date"]),
            # .filter(is_deleted=False) + ordering combined — most common query pattern
            models.Index(fields=["is_deleted", "invoice_date"]),
            # sorting by total_amount
            models.Index(fields=["total_amount"]),
            # invoice_number search (icontains — partial benefit)
            models.Index(fields=["invoice_number"]),
        ]

    def __str__(self):
        date_str = (
            self.invoice_date.strftime("%Y-%m-%d")  # pylint: disable=no-member
            if self.invoice_date
            else "N/A"
        )
        return (
            f"{self.invoice_number} - {self.supplier.name} ({date_str}) - "
            f"{self.get_invoice_type_display()} - {self.total_amount}"
        )

    def save(self, *args, **kwargs):
        self.invoice_number = StringProcessor(self.invoice_number).toUppercase()
        self.notes = StringProcessor(self.notes).toTitle()

        super().save(*args, **kwargs)


class SupplierPayment(SoftDeleteModel):
    """
    Records a payment made TO a supplier. This payment is linked to the
    supplier's account, not to a single invoice, allowing for bulk payments.
    """

    class PaymentMethod(models.TextChoices):
        """Supported payment methods."""

        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
        UPI = "UPI", "UPI"

    class Meta:
        indexes = [
            models.Index(fields=["is_deleted"]),
            models.Index(fields=["supplier", "is_deleted"]),
            models.Index(fields=["payment_date"]),
        ]

    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="payments_made"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    transaction_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Bank transaction reference number.",
    )
    unallocated_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0")
    )
    payment_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="supplier_payment_created_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.unallocated_amount = self.amount
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.amount} paid to {self.supplier.name} via {self.get_method_display()}"


class SupplierPaymentAllocation(SoftDeleteModel):
    """
    The "bridge" model. This links a specific payment to a specific invoice,
    recording how much of that payment was used to clear that invoice.
    """

    payment = models.ForeignKey(
        SupplierPayment, on_delete=models.CASCADE, related_name="allocations"
    )
    invoice = models.ForeignKey(
        SupplierInvoice, on_delete=models.CASCADE, related_name="allocations"
    )
    amount_allocated = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0")
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="supplier_payment_allocation_created_by",
    )
    allocated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Removed unique_together constraint to allow multiple allocations
        # from the same payment to the same invoice
        pass

    def __str__(self):
        return (
            f"{self.amount_allocated} of Payment {self.payment.id} "
            f"allocated to Invoice {self.invoice.invoice_number}"
        )


# Allowed upload MIME types (PDF and common image formats)
ALLOWED_MEDIA_TYPES = [
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
]

ALLOWED_MEDIA_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"]

# Max upload size: 10 MB
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024


def validate_media_file(file):
    """Validate that the uploaded file is a PDF or image and within size limits."""
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_MEDIA_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '{ext}'. Allowed types: PDF, JPEG, PNG, GIF, WebP."
        )
    if file.size > MAX_UPLOAD_SIZE_BYTES:
        raise ValidationError(
            f"File too large ({file.size // (1024 * 1024)} MB). Maximum allowed size is 10 MB."
        )


def _media_upload_path(instance, filename):
    """Generate a clean upload path with a timestamped slug filename."""
    ext = os.path.splitext(filename)[1].lower()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if instance.supplier_invoice_id:
        slug = slugify(instance.supplier_invoice.invoice_number)
        folder = "supplier_invoices"
    else:
        slug = f"payment-{instance.supplier_payment_id}"
        folder = "supplier_payments"
    return f"{folder}/{slug}-{timestamp}{ext}"


class MediaFile(models.Model):
    """
    Stores an uploaded attachment (PDF or image) linked to either a
    SupplierInvoice or a SupplierPayment.  Exactly one FK must be set.
    """

    supplier_invoice = models.ForeignKey(
        SupplierInvoice,
        on_delete=models.CASCADE,
        related_name="media_files",
        null=True,
        blank=True,
    )
    supplier_payment = models.ForeignKey(
        SupplierPayment,
        on_delete=models.CASCADE,
        related_name="media_files",
        null=True,
        blank=True,
    )
    media_file = models.FileField(
        upload_to=_media_upload_path,
        validators=[validate_media_file],
    )
    original_filename = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_filename or self.media_file.name

    def clean(self):
        """Ensure exactly one parent FK is set."""
        if self.supplier_invoice_id and self.supplier_payment_id:
            raise ValidationError(
                "A MediaFile cannot be linked to both an invoice and a payment."
            )
        if not self.supplier_invoice_id and not self.supplier_payment_id:
            raise ValidationError(
                "A MediaFile must be linked to either an invoice or a payment."
            )

    def save(self, *args, **kwargs):
        """Persist the original filename before Django renames it."""
        if self.media_file and not self.original_filename:
            self.original_filename = os.path.basename(self.media_file.name)
        super().save(*args, **kwargs)

    @property
    def is_image(self):
        """Return True if the file is an image (not a PDF)."""
        ext = os.path.splitext(self.media_file.name)[1].lower()
        return ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]

    @property
    def file_extension(self):
        """Return the lowercase file extension (e.g. '.pdf')."""
        return os.path.splitext(self.media_file.name)[1].lower()
