"""Inventory models: products, variants, stock tracking, and related masters."""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.urls import reverse

from base.manager import SoftDeleteModel
from base.utility import StringProcessor
from supplier.models import SupplierInvoice

from .manager import InventoryLogManager, ProductVariantManager
from .mixins import (
    ProductVariantNamingMixin,
    ProductVariantPricingMixin,
    ProductVariantStockMixin,
)

User = settings.AUTH_USER_MODEL


class Category(models.Model):
    """Product category for grouping products (e.g. Shirts, Trousers)."""

    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} → {self.name}"
        return self.name

    def get_descendants(self):
        """Return all descendant categories (children, grandchildren, etc.)."""
        descendants = set()
        children = self.children.all()
        for child in children:
            descendants.add(child)
            descendants.update(child.get_descendants())
        return descendants

    def save(self, *args, **kwargs):
        self.name = StringProcessor(self.name).toTitle()
        self.description = StringProcessor(self.description).toTitle()
        super().save(*args, **kwargs)


class ClothType(models.Model):
    """Fabric / cloth type master (e.g. Cotton, Silk)."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = StringProcessor(self.name).toTitle()
        self.description = StringProcessor(self.description).toTitle()
        super().save(*args, **kwargs)


class Color(models.Model):
    """
    Defines a specific color. e.g., Red, Blue, Pink.
    """

    name = models.CharField(max_length=50, unique=True)
    hex_code = models.CharField(
        max_length=7,
        blank=True,
        null=True,
        help_text="Optional: Hex color code, e.g., #FF0000",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = StringProcessor(self.name).toTitle()
        self.hex_code = StringProcessor(self.hex_code).toUppercase()
        super().save(*args, **kwargs)


class Size(models.Model):
    """Size master for product variants (e.g. S, M, L, XL)."""

    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = StringProcessor(self.name).toUppercase()
        self.description = StringProcessor(self.description).toTitle()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        """Return the URL for the size listing page."""
        return reverse("inventory:size_home")


class UOM(models.Model):
    """
    Unit of Measurement Master Table
    """

    name = models.CharField(
        max_length=50, help_text="Full name of the UOM, e.g., Piece, Dozen, Meter"
    )
    short_code = models.CharField(
        max_length=10,
        unique=True,
        help_text="Abbreviation for the UOM, e.g., pcs, doz, m",
    )
    category = models.CharField(
        max_length=50, help_text="Type of UOM, e.g., Quantity, Weight, Length, Volume"
    )
    base_unit = models.BooleanField(
        default=False, help_text="Marks if this is the base unit for conversions"
    )
    conversion_factor = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=1.0,
        help_text="Factor to convert to base unit (e.g., 1 dozen = 12 pcs)",
    )
    description = models.TextField(
        blank=True, null=True, help_text="Optional notes about this UOM"
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether this UOM is active or not"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Unit of Measurement"
        verbose_name_plural = "Units of Measurement"

    def __str__(self):
        return f"{self.name} ({self.short_code})"

    def save(self, *args, **kwargs):
        self.name = StringProcessor(self.name).toTitle()
        self.description = StringProcessor(self.description).toTitle()
        self.short_code = StringProcessor(self.short_code).toUppercase()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        """Return the URL for the UOM listing page."""
        return reverse("inventory:uom_home")


class GSTHsnCode(models.Model):
    """GST HSN code with tax rates for product classification."""

    code = models.CharField(max_length=8, unique=True, db_index=True)
    gst_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("40.00")),
        ],
    )

    cess_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("25.00")),
        ],
    )
    effective_from = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.code} ({self.gst_percentage}% GST + {self.cess_rate}% Cess)"

    def save(self, *args, **kwargs):
        self.code = StringProcessor(self.code).toUppercase()
        self.description = StringProcessor(self.description).toTitle()
        super().save(*args, **kwargs)

    def get_applicable_rate(self, transaction_type="intrastate"):
        """Return CGST/SGST/IGST/cess breakdown for the given transaction type."""
        if transaction_type == "interstate":
            return {
                "cgst": Decimal("0.00"),
                "sgst": Decimal("0.00"),
                "igst": self.gst_percentage,
                "cess": self.cess_rate,
                "total": self.gst_percentage + self.cess_rate,
            }
        else:
            half = self.gst_percentage / 2
            return {
                "cgst": half,
                "sgst": half,
                "igst": Decimal("0.00"),
                "cess": self.cess_rate,
                "total": self.gst_percentage + self.cess_rate,
            }


class Product(SoftDeleteModel):
    """Master product record (brand + name + HSN + category)."""

    class ProductStatus(models.TextChoices):
        """Lifecycle statuses for a product."""

        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        DISCONTINUED = "DISCONTINUED", "Discontinued"

    brand = models.CharField(max_length=255, help_text="The brand of the product")
    name = models.CharField(max_length=255, help_text="The name of the product")
    description = models.TextField(
        blank=True, null=True, help_text="The description of the product"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    cloth_type = models.ForeignKey(
        ClothType,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    uom = models.ForeignKey(
        UOM, on_delete=models.PROTECT, related_name="products", null=True, blank=True
    )
    hsn_code = models.ForeignKey(
        GSTHsnCode,
        on_delete=models.PROTECT,
        related_name="products",
    )
    status = models.CharField(
        max_length=20, choices=ProductStatus.choices, default=ProductStatus.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name

    class Meta:
        indexes = [
            models.Index(fields=["brand"]),
            models.Index(fields=["name"]),
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]
        permissions = [
            ("view_dashboard", "View Dashboard"),
            ("export_reports", "Export Reports"),
            ("view_supplier_details", "View Supplier Details"),
            ("view_low_stock_details", "View Low Stock Details"),
            ("view_supplier_invoice", "View Supplier Invoice"),
            ("view_supplier_invoice_details", "View Supplier Invoice Details"),
        ]

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.name = StringProcessor(self.name).toTitle()
        self.brand = StringProcessor(self.brand).toTitle()
        self.description = StringProcessor(self.description).toTitle()
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        """Return 'Brand - Name' or just Brand if name is blank."""
        if self.name:
            return f"{self.brand} - {self.name}"
        return self.brand


class ProductVariant(
    ProductVariantNamingMixin,
    ProductVariantStockMixin,
    ProductVariantPricingMixin,
    SoftDeleteModel,
):
    """Specific SKU of a product with size, colour, pricing, and stock."""

    class VariantStatus(models.TextChoices):
        """Active / discontinued status for a variant."""

        ACTIVE = "ACTIVE", "Active"
        DISCONTINUED = "DISCONTINUED", "Discontinued"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "size", "color"],
                name="unique_product_size_color",
                condition=models.Q(size__isnull=False, color__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["product", "size"],
                name="unique_product_size_null_color",
                condition=models.Q(size__isnull=False, color__isnull=True),
            ),
            models.UniqueConstraint(
                fields=["product", "color"],
                name="unique_product_color_null_size",
                condition=models.Q(size__isnull=True, color__isnull=False),
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["barcode"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["product", "status"]),
            models.Index(fields=["quantity", "minimum_quantity"]),
            models.Index(fields=["is_deleted", "status"]),
        ]

    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="product_variants"
    )
    barcode = models.CharField(max_length=100, unique=True)
    size = models.ForeignKey(
        Size,
        on_delete=models.PROTECT,
        related_name="product_variants",
        null=True,
        blank=True,
    )
    color = models.ForeignKey(
        Color,
        on_delete=models.PROTECT,
        related_name="product_variants",
        null=True,
        blank=True,
    )
    extra_attributes = models.JSONField(default=dict, blank=True)
    # Price fields
    purchase_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        validators=[
            MinValueValidator(Decimal("0"), "Purchase price must be greater than 0")
        ],
        help_text="Cost price of the product",
    )
    mrp = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        validators=[
            MinValueValidator(Decimal("0"), "Selling price must be greater than 0")
        ],
        help_text="Selling price of the product",
    )
    # Quantity fields
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        validators=[
            MinValueValidator(Decimal("0"), "Quantity cannot be negative"),
        ],
    )
    damaged_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        help_text="The quantity of the product that is damaged",
        validators=[
            MinValueValidator(Decimal("0"), "Damaged quantity cannot be negative"),
        ],
    )
    minimum_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Minimum stock level before reorder alert",
        validators=[
            MinValueValidator(Decimal("0"), "Minimum quantity cannot be negative"),
        ],
    )
    # Percentage fields
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0"),
        validators=[
            MinValueValidator(Decimal("0"), "Discount cannot be negative"),
            MaxValueValidator(100, "Discount cannot exceed 100%"),
        ],
    )
    commission_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0"),
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0"), "Commission cannot be negative"),
            MaxValueValidator(100, "Commission cannot exceed 100%"),
        ],
    )
    status = models.CharField(
        max_length=20, choices=VariantStatus.choices, default=VariantStatus.ACTIVE
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_variants",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductVariantManager()

    def __str__(self):
        """Simple, bulletproof string representation"""
        try:
            # Get product name safely
            product_name = getattr(self.product, "brand", "Unknown Product")

            # Build variant info safely
            variant_parts = []

            if self.size and hasattr(self.size, "name"):
                variant_parts.append(self.size.name)

            if self.color and hasattr(self.color, "name"):
                variant_parts.append(self.color.name)

            # Add extra attributes safely
            if self.extra_attributes and isinstance(self.extra_attributes, dict):
                for key, value in self.extra_attributes.items():
                    if key and value:
                        variant_parts.append(f"{key}: {value}")

            # Build final string
            if variant_parts:
                variant_info = f" ({', '.join(variant_parts)})"
            else:
                variant_info = ""

            barcode = getattr(self, "barcode", "No Barcode")
            return f"{product_name}{variant_info} - {barcode}"

        except (AttributeError, TypeError):
            # Fallback if anything goes wrong
            return f"Product Variant #{self.id}"

    def clean(self):
        """Custom validation"""
        from django.core.exceptions import ValidationError

        # Validate barcode uniqueness
        if self.barcode:
            existing = ProductVariant.objects.filter(barcode=self.barcode)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError("Barcode must be unique")

    def create_barcode(self, save=True):
        """
        Create a new barcode based on the object's ID.
        If a barcode already exists, it will be replaced with a new one.

        Args:
            save (bool): Whether to save the barcode to the database.
                        If False, only sets the barcode on the instance.

        Returns:
            str: The newly created barcode
        """
        # Ensure object has an ID (save if needed)
        if not self.pk:
            super(ProductVariant, self).save()

        # Generate barcode: 6 digits with zero padding + suffix "3"
        self.barcode = f"{self.id:03d}99"

        # Save the barcode if requested
        if save:
            super(ProductVariant, self).save(update_fields=["barcode"])

        return self.barcode

    def save(self, *args, **kwargs):
        """Override save to include validation"""
        self.clean()

        # If new record and no barcode, generate after getting ID
        if not self.pk and not self.barcode:
            super().save(*args, **kwargs)  # First save to get ID
            self.create_barcode(save=True)  # Generate and save barcode
        else:
            super().save(*args, **kwargs)


class VariantMedia(models.Model):
    """Media (image or video) associated with a product variant."""

    class MediaType(models.TextChoices):
        """Type of media file."""

        IMAGE = "IMAGE", "Image"
        VIDEO = "VIDEO", "Video"

    IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "gif"]
    VIDEO_EXTENSIONS = ["mp4", "webm", "mov"]
    THUMBNAIL_MAX_SIZE = (400, 400)
    THUMBNAIL_QUALITY = 70

    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name="media_files",
    )
    file = models.FileField(
        upload_to="variant_media/%Y/%m/originals/",
        help_text="Original uploaded file (kept at full quality).",
    )
    thumbnail = models.ImageField(
        upload_to="variant_media/%Y/%m/thumbnails/",
        blank=True,
        help_text="Auto-generated optimised thumbnail for gallery view.",
    )
    media_type = models.CharField(
        max_length=5,
        choices=MediaType.choices,
        default=MediaType.IMAGE,
    )
    alt_text = models.CharField(
        max_length=255,
        blank=True,
        help_text="Alternative text for accessibility.",
    )
    is_featured = models.BooleanField(
        default=False,
        help_text="Is this the main media for the variant?",
    )
    sort_order = models.PositiveIntegerField(default=0)
    file_size = models.PositiveIntegerField(
        default=0,
        help_text="Original file size in bytes.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_featured", "sort_order"]

    def __str__(self):
        return f"{self.get_media_type_display()} for {self.variant}"

    @property
    def is_image(self):
        """Check if the media is an image."""
        return self.media_type == self.MediaType.IMAGE

    @property
    def is_video(self):
        """Check if the media is a video."""
        return self.media_type == self.MediaType.VIDEO

    @property
    def file_size_display(self):
        """Return human-readable file size."""
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        return f"{self.file_size / (1024 * 1024):.1f} MB"

    @property
    def gallery_url(self):
        """URL for gallery grid view — thumbnail if available, else original."""
        if self.thumbnail:
            return self.thumbnail.url
        return self.file.url

    @property
    def original_url(self):
        """URL for full-resolution view / download."""
        return self.file.url

    def _generate_thumbnail(self):
        """Create an optimised WebP thumbnail from the original image."""
        import io
        from pathlib import Path

        from django.core.files.base import ContentFile
        from PIL import Image as PilImage

        try:
            self.file.seek(0)
            img = PilImage.open(self.file)
            img.thumbnail(self.THUMBNAIL_MAX_SIZE, PilImage.Resampling.LANCZOS)

            # Convert to RGB if needed (e.g. RGBA PNGs)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            buffer = io.BytesIO()
            img.save(buffer, format="WEBP", quality=self.THUMBNAIL_QUALITY)
            buffer.seek(0)

            # Derive thumbnail filename from original
            original_name = Path(self.file.name).stem
            thumb_name = f"{original_name}_thumb.webp"

            self.thumbnail.save(thumb_name, ContentFile(buffer.read()), save=False)
        except Exception:  # noqa: BLE001
            # If thumbnail generation fails, leave it blank — original will be used
            pass

    def save(self, *args, **kwargs):
        """Auto-detect media type, generate thumbnail, enforce single featured."""
        if self.file:
            # Track file size
            try:
                self.file_size = self.file.size
            except (OSError, AttributeError):
                pass

            # Auto-detect media type from extension
            ext = self.file.name.rsplit(".", 1)[-1].lower()
            if ext in self.VIDEO_EXTENSIONS:
                self.media_type = self.MediaType.VIDEO
            else:
                self.media_type = self.MediaType.IMAGE

        # Ensure only one featured media per variant
        if self.is_featured:
            VariantMedia.objects.filter(variant=self.variant, is_featured=True).exclude(
                pk=self.pk
            ).update(is_featured=False)

        # Save first so the file is on disk
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # Generate thumbnail for new images (not videos)
        if is_new and self.is_image and self.file and not self.thumbnail:
            self._generate_thumbnail()
            if self.thumbnail:
                # Save again to persist thumbnail field (skip re-running full save)
                super().save(update_fields=["thumbnail"])


class InventoryLog(SoftDeleteModel):
    """Audit trail for every stock movement (in, out, adjustment, damage)."""

    class TransactionTypes(models.TextChoices):
        """Types of inventory transactions."""

        STOCK_IN = "STOCK_IN", "Stock In"
        SALE = "SALE", "Sale"
        RETURN = "RETURN", "Customer Return"
        CANCEL = "CANCEL", "Invoice Cancelled"
        ADJUSTMENT_IN = "ADJUSTMENT_IN", "Adjustment In"  # More specific
        ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Adjustment Out"  # More specific
        DAMAGE = "DAMAGE", "Mark as Damaged"
        INITIAL = "INITIAL", "Initial Stock"

    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="inventory_logs"
    )
    supplier_invoice = models.ForeignKey(
        SupplierInvoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_logs",
    )
    transaction_type = models.CharField(max_length=20, choices=TransactionTypes.choices)
    quantity_change = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0")
    )
    new_quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0")
    )
    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, default=Decimal("0")
    )
    mrp = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Selling price at time of transaction",
        default=Decimal("0"),
    )
    # Sale tracking (for SALE transactions)
    invoice_item = models.ForeignKey(
        "invoice.invoiceitem",  # Adjust app name as needed
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_logs",
        help_text="Customer invoice item for sale transactions",
    )
    selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Selling price per unit for sale transactions",
    )
    # FIFO tracking - links sale transactions to their source stock
    source_inventory_log = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="allocated_sales",
        help_text="For SALE transactions: points to the STOCK_IN/INITIAL log this sale is allocated from",
    )

    allocated_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="For SALE transactions: quantity allocated from source_inventory_log",
    )

    # Remaining quantity for FIFO allocation
    remaining_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="For STOCK_IN/INITIAL: remaining quantity available for allocation",
    )

    total_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total value of the transaction",
        default=Decimal("0"),
    )
    notes = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = InventoryLogManager()

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            # Existing indexes
            models.Index(fields=["variant", "timestamp"]),
            models.Index(fields=["transaction_type", "timestamp"]),
            models.Index(fields=["created_by", "timestamp"]),
            models.Index(
                fields=["supplier_invoice", "transaction_type", "quantity_change"]
            ),
            # New indexes for FIFO allocation optimization
            models.Index(fields=["transaction_type", "variant", "remaining_quantity"]),
            models.Index(fields=["variant", "transaction_type", "timestamp"]),
            # Performance indexes for cross-model FK lookups
            models.Index(fields=["invoice_item"]),
            models.Index(fields=["source_inventory_log"]),
        ]

    def __str__(self):
        date_str = (
            self.timestamp.strftime("%Y-%m-%d")  # pylint: disable=no-member
            if self.timestamp
            else "N/A"
        )
        return f"{self.variant} changed by {self.quantity_change} on {date_str}"

    def save(self, *args, **kwargs):
        # Auto-calculate total value
        if not self.total_value and self.quantity_change:
            if self.transaction_type in ["STOCK_IN", "INITIAL"] and self.purchase_price:
                self.total_value = abs(self.quantity_change) * self.purchase_price
            elif self.transaction_type == "SALE" and self.selling_price:
                self.total_value = abs(self.quantity_change) * self.selling_price

        # Initialize remaining quantity for stock in transactions
        if (
            self.transaction_type in ["STOCK_IN", "INITIAL"]
            and self.remaining_quantity is None
        ):
            self.remaining_quantity = abs(self.quantity_change)

        super().save(*args, **kwargs)


class FavoriteVariant(models.Model):
    """Track user-favourited product variants for quick access."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="favorite_variants"
    )
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="favorite_variants"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.full_name} - {self.variant.full_name}"

    class Meta:
        unique_together = ["user", "variant"]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["variant"]),
            models.Index(fields=["created_at"]),
        ]


class BarcodeMapping(models.Model):
    """Maps external/custom barcodes to product variants."""

    barcode = models.CharField(max_length=100, unique=True)
    variant = models.OneToOneField(
        ProductVariant, on_delete=models.CASCADE, related_name="barcode_mappings"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.barcode} - {self.variant.full_name}"

    class Meta:
        ordering = ["-created_at"]


class DamagedItemRecord(SoftDeleteModel):
    """Records damaged items with lifecycle tracking: pending, returned, written off, or repaired.

    Each record tracks a single damage incident for a product variant,
    including resolution status, linked supplier/invoice, and financial impact.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending Resolution"
        RETURNED = "RETURNED", "Returned to Supplier"
        WRITTEN_OFF = "WRITTEN_OFF", "Written Off (Loss)"
        REPAIRED = "REPAIRED", "Repaired & Restored"

    class DamageReason(models.TextChoices):
        GENERAL = "GENERAL", "General"
        EXPIRED = "EXPIRED", "Expired"
        BROKEN = "BROKEN", "Broken / Unusable"
        TRANSIT = "TRANSIT", "Transit Damage"
        WATER = "WATER", "Water Damage"
        MANUFACTURING = "MANUFACTURING", "Manufacturing Defect"
        OTHER = "OTHER", "Other"

    variant = models.ForeignKey(
        "ProductVariant",
        on_delete=models.CASCADE,
        related_name="damaged_records",
    )
    supplier = models.ForeignKey(
        "supplier.Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="damaged_records",
        help_text="Supplier from whom the damaged goods were purchased",
    )
    supplier_invoice = models.ForeignKey(
        "supplier.SupplierInvoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="damaged_records",
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    reason = models.CharField(
        max_length=30,
        choices=DamageReason.choices,
        default=DamageReason.GENERAL,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    notes = models.TextField(blank=True, null=True)

    # Resolution details
    resolution_notes = models.TextField(blank=True, null=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="damaged_resolved",
    )
    repair_cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0")
    )
    credit_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Credit received from supplier for returned items",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="damaged_created",
    )

    def __str__(self):
        return (
            f"{self.variant.full_name} — "
            f"{self.quantity} units [{self.get_status_display()}]"
        )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["variant"]),
            models.Index(fields=["supplier"]),
            models.Index(fields=["created_at"]),
        ]


class BulkUpload(SoftDeleteModel):
    """A batch for adding inventory stock-in entries against an existing SupplierInvoice."""

    class BatchStatus(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        COMMITTED = "COMMITTED", "Committed"

    supplier_invoice = models.ForeignKey(
        "supplier.SupplierInvoice", on_delete=models.PROTECT, related_name="batches"
    )
    status = models.CharField(
        max_length=20, choices=BatchStatus.choices, default=BatchStatus.DRAFT
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="bulk_uploads_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class BulkUploadItem(SoftDeleteModel):
    """One product row in a draft batch.

    Contains all input fields from ProductForm and VariantForm (except supplier_invoice
    which belongs to the parent BulkUpload batch).
    """

    class ItemStatus(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        COMMITTED = "COMMITTED", "Committed"

    bulk_upload = models.ForeignKey(
        BulkUpload, on_delete=models.CASCADE, related_name="items"
    )
    status = models.CharField(
        max_length=20,
        choices=ItemStatus.choices,
        default=ItemStatus.DRAFT,
        db_index=True,
    )
    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_items",
    )
    variant = models.ForeignKey(
        "inventory.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_items",
    )

    # Product Form Fields (except supplier_invoice)
    brand = models.CharField(max_length=255, blank=True, default="")
    name = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(
        "inventory.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_items",
    )
    cloth_type = models.ForeignKey(
        "inventory.ClothType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_items",
    )
    uom = models.ForeignKey(
        "inventory.UOM",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_items",
    )
    hsn_code = models.ForeignKey(
        "inventory.GSTHsnCode",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_items",
    )

    # Variant Form Fields
    size = models.ForeignKey(
        "inventory.Size",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_items",
    )
    color = models.ForeignKey(
        "inventory.Color",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_items",
    )
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("1")
    )
    minimum_quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0")
    )
    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0")
    )
    mrp = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0")
    )
    discount_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0")
    )
    commission_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0"), null=True, blank=True
    )

    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "created_at"]
        indexes = [
            models.Index(fields=["bulk_upload", "sort_order"]),
            models.Index(fields=["status"]),
            models.Index(fields=["variant"]),
            models.Index(fields=["product"]),
        ]

    @property
    def line_total(self):
        return self.quantity * self.purchase_price

    @property
    def is_committed(self):
        return self.status == self.ItemStatus.COMMITTED