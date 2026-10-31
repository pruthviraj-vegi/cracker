"""
Settings and configuration models for the application.
"""

import logging

from django.conf import settings
from django.core.cache import cache
from django.db import models

from base.manager import phone_regex
from base.utility import StringProcessor

logger = logging.getLogger(__name__)

User = settings.AUTH_USER_MODEL


class ShopDetails(models.Model):
    """Model to store shop/business information for invoices and reports."""

    shop_name = models.CharField(max_length=255, help_text="Name of the shop/business")
    first_line = models.CharField(
        max_length=255, help_text="First line of address (e.g., Building name, Street)"
    )
    second_line = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Second line of address (e.g., Area, Locality)",
    )
    city = models.CharField(max_length=100, help_text="City name")
    state = models.CharField(max_length=100, help_text="State name")
    pincode = models.CharField(max_length=10, help_text="PIN/ZIP code")
    country = models.CharField(
        max_length=100, default="India", help_text="Country name"
    )
    gst_no = models.CharField(
        max_length=15, blank=True, null=True, help_text="GST Registration Number"
    )
    phone_number = models.CharField(
        max_length=20, validators=[phone_regex], help_text="Primary phone number"
    )
    phone_two = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[phone_regex],
        help_text="Secondary phone number",
    )
    email = models.EmailField(blank=True, null=True, help_text="Business email address")
    website = models.URLField(blank=True, null=True, help_text="Business website URL")
    logo = models.ImageField(
        upload_to="shop_logos/", blank=True, null=True, help_text="Shop logo image"
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether this shop details is currently active"
    )
    is_direct_print_enabled = models.BooleanField(
        default=False, help_text="Enable direct printing to network printer"
    )
    printer_ip = models.CharField(
        max_length=50, blank=True, null=True, help_text="IP Address of the network printer"
    )
    printer_port = models.PositiveIntegerField(
        default=9100, help_text="Port of the network printer (default 9100)"
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shop_details_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Shop Details"
        verbose_name_plural = "Shop Details"
        ordering = ["-created_at"]

    def __str__(self):
        return self.shop_name

    CACHE_KEY = "active_shop_details"

    @classmethod
    def get_active(cls):
        """Return the active shop details, caching the result for 24 hours."""
        return cache.get_or_set(
            cls.CACHE_KEY,
            lambda: cls.objects.filter(is_active=True).first(),
            timeout=86400,
        )

    def save(self, *args, **kwargs):
        """Override save to clean and format data."""
        self.shop_name = StringProcessor(self.shop_name).toTitle()
        self.first_line = StringProcessor(self.first_line).toTitle()
        self.second_line = StringProcessor(self.second_line).toTitle()
        self.city = StringProcessor(self.city).toTitle()
        self.state = StringProcessor(self.state).toTitle()
        self.country = StringProcessor(self.country).toTitle()
        self.phone_number = StringProcessor(self.phone_number).cleaned_string
        self.phone_two = StringProcessor(self.phone_two).cleaned_string
        self.email = StringProcessor(self.email).toLowercase()
        self.gst_no = StringProcessor(self.gst_no).toUppercase()

        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    @property
    def full_address(self):
        """Return complete formatted address."""
        address_parts = [self.first_line]
        if self.second_line:
            address_parts.append(self.second_line)
        address_parts.extend([self.city, self.state, self.pincode])
        if self.country != "India":
            address_parts.append(self.country)
        return ", ".join(address_parts)

    @property
    def address_line_one(self):
        """Return complete formatted address with country."""
        return f"{self.first_line}, {self.second_line}"

    @property
    def address_line_two(self):
        """Return complete formatted address with country."""
        return f"{self.city}, {self.state} - {self.pincode}"

    @property
    def short_address(self):
        """Return shortened address for display."""
        return f"{self.city}, {self.state} - {self.pincode}"

    @property
    def contact_info(self):
        """Return formatted contact information."""
        contacts = [self.phone_number]
        if self.phone_two:
            contacts.append(self.phone_two)
        return ", ".join(contacts)


class ReportConfiguration(models.Model):
    """Model to store report generation preferences and settings."""

    class ReportType(models.TextChoices):
        """Types of reports available."""

        INVOICE = "INVOICE", "Invoice"
        ESTIMATE = "ESTIMATE", "Estimate"
        QUOTATION = "QUOTATION", "Quotation"
        RECEIPT = "RECEIPT", "Receipt"
        STATEMENT = "STATEMENT", "Account Statement"

    class PaperSize(models.TextChoices):
        """Supported paper sizes for reports."""

        A4 = "A4", "A4"
        A5 = "A5", "A5"
        MM58 = "58mm", "58mm Roll (2-inch)"
        MM80 = "80mm", "80mm Roll (3-inch)"
        LETTER = "LETTER", "Letter"
        LEGAL = "LEGAL", "Legal"

    class Currency(models.TextChoices):
        """Supported currencies for reports."""

        INR = "INR", "Indian Rupee (₹)"
        USD = "USD", "US Dollar ($)"
        EUR = "EUR", "Euro (€)"
        GBP = "GBP", "British Pound (£)"

    # Basic Settings
    report_type = models.CharField(
        max_length=20, choices=ReportType.choices, default=ReportType.INVOICE
    )
    paper_size = models.CharField(
        max_length=10, choices=PaperSize.choices, default=PaperSize.MM80
    )
    currency = models.CharField(
        max_length=3, choices=Currency.choices, default=Currency.INR
    )

    # Direct Thermal Printer Hardware Settings
    is_direct_print_enabled = models.BooleanField(
        default=False, help_text="Enable direct network thermal printing via socket"
    )
    printer_ip = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Printer IP Address (e.g. 192.168.1.192)",
    )
    printer_port = models.IntegerField(
        default=9100,
        blank=True,
        null=True,
        help_text="Printer Port (default: 9100)",
    )

    # Header Settings
    show_logo = models.BooleanField(default=True, help_text="Show shop logo in header")
    show_shop_name = models.BooleanField(
        default=True, help_text="Show shop name in header"
    )
    show_address = models.BooleanField(
        default=True, help_text="Show shop address in header"
    )
    show_contact = models.BooleanField(
        default=True, help_text="Show contact information in header"
    )
    show_gst = models.BooleanField(default=True, help_text="Show GST number in header")

    # Invoice/Report Content
    show_invoice_number = models.BooleanField(
        default=True, help_text="Show invoice number"
    )
    show_date = models.BooleanField(default=True, help_text="Show invoice date")
    show_due_date = models.BooleanField(
        default=True, help_text="Show due date (for credit invoices)"
    )
    show_payment_method = models.BooleanField(
        default=True, help_text="Show payment method"
    )
    show_customer_details = models.BooleanField(
        default=True, help_text="Show customer information"
    )

    # Item Details
    show_item_description = models.BooleanField(
        default=True, help_text="Show item descriptions"
    )
    show_quantity = models.BooleanField(default=True, help_text="Show quantities")
    show_unit_price = models.BooleanField(default=True, help_text="Show unit prices")
    show_discount = models.BooleanField(
        default=True, help_text="Show discount information"
    )
    show_tax_breakdown = models.BooleanField(
        default=True, help_text="Show tax breakdown"
    )
    show_total = models.BooleanField(default=True, help_text="Show total amounts")

    # Footer Settings
    show_terms_conditions = models.BooleanField(
        default=True, help_text="Show terms and conditions"
    )
    show_qr_code = models.BooleanField(
        default=True, help_text="Show QR code for payments"
    )
    show_thank_you = models.BooleanField(
        default=True, help_text="Show thank you message"
    )
    show_signature = models.BooleanField(default=False, help_text="Show signature line")

    # Custom Text
    terms_conditions = models.TextField(
        blank=True, null=True, help_text="Custom terms and conditions text"
    )
    thank_you_message = models.TextField(
        blank=True, null=True, help_text="Custom thank you message"
    )
    footer_note = models.TextField(
        blank=True, null=True, help_text="Additional footer note"
    )

    # System Settings
    is_default = models.BooleanField(
        default=False, help_text="Use as default configuration"
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether this configuration is active"
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="report_configs_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Report Configuration"
        verbose_name_plural = "Report Configurations"
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return f"{self.get_report_type_display()} - {self.get_paper_size_display()}"

    def save(self, *args, **kwargs):
        """Override save to ensure only one default config per report type."""
        if self.is_default:
            # Set all other configs of same type to not default
            ReportConfiguration.objects.filter(
                report_type=self.report_type, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)

        super().save(*args, **kwargs)

    @classmethod
    def get_default_config(cls, report_type=ReportType.INVOICE):
        """Get the default configuration for a report type."""
        try:
            return cls.objects.get(
                report_type=report_type, is_default=True, is_active=True
            )
        except cls.DoesNotExist:
            # Create a default config if none exists
            return cls.objects.create(
                report_type=report_type, is_default=True, is_active=True
            )

    @property
    def default_terms_conditions(self):
        """Return default terms and conditions if none set."""
        if self.terms_conditions:
            return self.terms_conditions

        return """1. All Subjects to The Shahapur Juridiction
            2. Goods Once Sold Will Not be taken back
            3. E. & O.E"""

    @property
    def default_thank_you_message(self):
        """Return default thank you message if none set."""
        if self.thank_you_message:
            return self.thank_you_message

        return "Thank You Please Visit Again"


class PaymentDetails(models.Model):
    """Model to store multiple payment methods and QR codes for the shop."""

    class PaymentType(models.TextChoices):
        """Supported payment methods."""

        UPI = "UPI", "UPI"
        BANK_ACCOUNT = "BANK", "Bank Account"
        QR_CODE = "QR", "QR Code"
        CARD = "CARD", "Card Payment"
        WALLET = "WALLET", "Wallet"
        OTHER = "OTHER", "Other"

    # Basic Information
    payment_name = models.CharField(
        max_length=255,
        help_text="Name/Label for this payment method (e.g., 'Main Counter UPI', 'Paytm QR')",
    )
    payment_type = models.CharField(
        max_length=10,
        choices=PaymentType.choices,
        default=PaymentType.UPI,
        help_text="Type of payment method",
    )

    # UPI Details
    upi_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="UPI ID for payments (e.g., shopname@paytm)",
    )

    # Bank Account Details
    account_holder_name = models.CharField(
        max_length=255, blank=True, null=True, help_text="Name of account holder"
    )
    bank_name = models.CharField(
        max_length=255, blank=True, null=True, help_text="Name of the bank"
    )
    account_number = models.CharField(
        max_length=50, blank=True, null=True, help_text="Bank account number"
    )
    ifsc_code = models.CharField(
        max_length=11, blank=True, null=True, help_text="IFSC code"
    )
    branch_name = models.CharField(
        max_length=255, blank=True, null=True, help_text="Bank branch name"
    )

    # QR Code Details
    qr_code_image = models.ImageField(
        upload_to="payment_qr_codes/",
        blank=True,
        null=True,
        help_text="Upload QR code image",
    )
    qr_code_url = models.URLField(
        blank=True, null=True, help_text="URL to generate QR code dynamically"
    )

    # Additional Details
    description = models.TextField(
        blank=True, null=True, help_text="Additional notes about this payment method"
    )

    # Counter/Location Linking (Future use)
    counter_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Counter/Location name (e.g., 'Counter 1', 'Online Store')",
    )

    # Status & Priority
    is_active = models.BooleanField(
        default=True, help_text="Whether this payment method is currently active"
    )
    is_default = models.BooleanField(
        default=False, help_text="Use as default payment method on invoices"
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Order in which to display this payment method (lower number = higher priority)",
    )

    # Link to Shop
    shop = models.ForeignKey(
        "ShopDetails",
        on_delete=models.CASCADE,
        related_name="payment_methods",
        help_text="Shop this payment method belongs to",
    )

    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_details_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payment Detail"
        verbose_name_plural = "Payment Details"
        ordering = ["display_order", "-is_default", "-created_at"]
        # Ensure only one default per shop
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "is_default"],
                condition=models.Q(is_default=True),
                name="unique_default_payment_per_shop",
            )
        ]

    def __str__(self):
        return f"{self.payment_name} ({self.get_payment_type_display()})"

    def clean(self):
        """Validate conditional fields."""
        from django.core.exceptions import ValidationError

        if self.payment_type == self.PaymentType.UPI and not self.upi_id:
            raise ValidationError(
                {"upi_id": "UPI ID is required for UPI payment type."}
            )

        if self.payment_type == self.PaymentType.BANK_ACCOUNT:
            if not self.account_number:
                raise ValidationError(
                    {"account_number": "Account Number is required for Bank Account."}
                )
            if not self.ifsc_code:
                raise ValidationError(
                    {"ifsc_code": "IFSC Code is required for Bank Account."}
                )

    def save(self, *args, **kwargs):
        """Override save to clean and format data."""
        # Format text fields
        if self.payment_name:
            self.payment_name = StringProcessor(self.payment_name).toTitle()
        if self.account_holder_name:
            self.account_holder_name = StringProcessor(
                self.account_holder_name
            ).toTitle()
        if self.bank_name:
            self.bank_name = StringProcessor(self.bank_name).toTitle()
        if self.branch_name:
            self.branch_name = StringProcessor(self.branch_name).toTitle()
        if self.ifsc_code:
            self.ifsc_code = StringProcessor(self.ifsc_code).toUppercase()
        # Handle default payment method
        if self.is_default:
            # Set all other payment methods for this shop to not default
            PaymentDetails.objects.filter(shop=self.shop, is_default=True).exclude(
                pk=self.pk
            ).update(is_default=False)

        super().save(*args, **kwargs)

    @classmethod
    def get_default_payment(cls, shop):
        """Get the default payment method for a shop."""
        try:
            return cls.objects.get(shop=shop, is_default=True, is_active=True)
        except cls.DoesNotExist:
            # Return first active payment method if no default is set
            return cls.objects.filter(shop=shop, is_active=True).first()

    @classmethod
    def get_active_payments(cls, shop):
        """Get all active payment methods for a shop."""
        return cls.objects.filter(shop=shop, is_active=True)

    @property
    def payment_info(self):
        """Return formatted payment information based on type."""
        if self.payment_type == self.PaymentType.UPI and self.upi_id:
            return f"UPI: {self.upi_id}"
        elif self.payment_type == self.PaymentType.BANK_ACCOUNT and self.account_number:
            return f"A/C: {self.account_number} | IFSC: {self.ifsc_code}"
        elif self.payment_type == self.PaymentType.QR_CODE:
            return "Scan QR Code to Pay"
        return self.payment_name

    @property
    def bank_details_formatted(self):
        """Return formatted bank details."""
        if not self.account_number:
            return None

        details = []
        if self.account_holder_name:
            details.append(f"A/C Holder: {self.account_holder_name}")
        if self.bank_name:
            details.append(f"Bank: {self.bank_name}")
        if self.account_number:
            details.append(f"A/C No: {self.account_number}")
        if self.ifsc_code:
            details.append(f"IFSC: {self.ifsc_code}")
        if self.branch_name:
            details.append(f"Branch: {self.branch_name}")

        return " | ".join(details)


class BarcodeConfiguration(models.Model):
    """Simplified model to store barcode/label printing preferences."""

    class BarcodeType(models.TextChoices):
        """Supported barcode formats."""

        CODE128 = "CODE128", "Code 128"
        EAN13 = "EAN13", "EAN-13"
        QR_CODE = "QR", "QR Code"

    class LabelSize(models.TextChoices):
        """Predefined label sizes."""

        SMALL = "25x12", "25mm x 12mm"
        MEDIUM = "38x25", "38mm x 25mm"
        LARGE = "50x25", "50mm x 25mm"
        CUSTOM = "CUSTOM", "Custom Size"

    class PaperSize(models.TextChoices):
        """Supported paper types for barcode printing."""

        A4 = "A4", "A4 (210 x 297 mm)"
        ROLL = "ROLL", "Label Roll"

    # --- Basic Config ---
    config_name = models.CharField(max_length=100, default="Default Barcode")
    barcode_type = models.CharField(
        max_length=10, choices=BarcodeType.choices, default=BarcodeType.CODE128
    )
    label_size = models.CharField(
        max_length=10, choices=LabelSize.choices, default=LabelSize.MEDIUM
    )
    paper_size = models.CharField(
        max_length=10, choices=PaperSize.choices, default=PaperSize.A4
    )

    # --- Heading ---
    show_heading = models.BooleanField(
        default=True, help_text="Show heading on barcode print page"
    )
    heading_text = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Custom heading to display on the barcode print page (e.g., 'SRI SAI GARMENTS' or 'Product Labels')",
    )

    # --- Custom Sizes ---
    custom_label_width = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    custom_label_height = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )

    # --- Layout ---
    labels_per_row = models.PositiveIntegerField(default=2)

    # --- Display Options ---
    show_product_name = models.BooleanField(default=True)
    show_product_code = models.BooleanField(default=True)
    show_mrp = models.BooleanField(default=True)
    show_price = models.BooleanField(default=True)
    show_discount = models.BooleanField(default=True)
    show_shop_logo = models.BooleanField(default=False)

    # --- Link to Shop ---
    shop = models.ForeignKey(
        "ShopDetails", on_delete=models.CASCADE, related_name="barcode_configs"
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Barcode Configuration"
        verbose_name_plural = "Barcode Configurations"
        ordering = ["-is_default", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "is_default"],
                condition=models.Q(is_default=True),
                name="unique_default_barcode_per_shop",
            )
        ]

    def __str__(self):
        return f"{self.config_name} ({self.barcode_type})"

    def save(self, *args, **kwargs):
        """Override save to clean and format data."""
        try:
            self.config_name = StringProcessor(self.config_name).toTitle()
            self.heading_text = StringProcessor(self.heading_text).toTitle()
        except Exception as e:  # pylint: disable=broad-except
            logger.error(str(e))

        return super().save(*args, **kwargs)

    @classmethod
    def get_active_barcodes(cls, shop):
        """Get all active payment methods for a shop."""
        return cls.objects.filter(shop=shop, is_active=True)

    @property
    def actual_label_width(self):
        """Get actual width of the label in mm."""
        if self.label_size == self.LabelSize.CUSTOM and self.custom_label_width:
            return float(self.custom_label_width)

        # self.label_size is a string value of the Choice, not the Enum member itself directly in DB
        label_size_str = str(self.label_size)
        if "x" in label_size_str:
            return float(label_size_str.split("x", maxsplit=1)[0])
        return 38.0

    @property
    def actual_label_height(self):
        """Get actual height of the label in mm."""
        if self.label_size == self.LabelSize.CUSTOM and self.custom_label_height:
            return float(self.custom_label_height)

        label_size_str = str(self.label_size)
        if "x" in label_size_str:
            return float(label_size_str.split("x", maxsplit=1)[1])
        return 25.0

    @property
    def display_heading(self):
        """Return the heading text or fallback to shop name."""
        if self.show_heading:
            return self.heading_text or self.shop.shop_name
        return None
