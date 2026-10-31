"""Django admin configuration for the Inventory app.

Registers all inventory models (Category, Product, ProductVariant, etc.)
with the Django admin site and configures list displays, filters, search,
fieldsets, inlines, and custom admin actions.
"""

from django.contrib import admin

from .models import (
    Category,
    ClothType,
    Color,
    DamagedItemRecord,
    GSTHsnCode,
    InventoryLog,
    Product,
    ProductVariant,
    Size,
    VariantMedia,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin configuration for the Category model."""

    list_display = ["name", "description", "created_at", "updated_at"]
    list_filter = ["created_at", "updated_at"]
    search_fields = ["name", "description"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(GSTHsnCode)
class GSTHsnCodeAdmin(admin.ModelAdmin):
    """Admin configuration for the GSTHsnCode model."""

    list_display = ["code", "description", "created_at", "updated_at"]
    list_filter = ["created_at", "updated_at"]
    search_fields = ["code", "description"]
    ordering = ["code"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ClothType)
class ClothTypeAdmin(admin.ModelAdmin):
    """Admin configuration for the ClothType model."""

    list_display = ["name", "description", "created_at", "updated_at"]
    list_filter = ["created_at", "updated_at"]
    search_fields = ["name", "description"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Color)
class ColorAdmin(admin.ModelAdmin):
    """Admin configuration for the Color model."""

    list_display = ["name", "hex_code", "created_at", "updated_at"]
    list_filter = ["created_at", "updated_at"]
    search_fields = ["name"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Size)
class SizeAdmin(admin.ModelAdmin):
    """Admin configuration for the Size model."""

    list_display = ["name", "description", "created_at", "updated_at"]
    list_filter = ["created_at", "updated_at"]
    search_fields = ["name", "description"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]


class VariantMediaInline(admin.TabularInline):
    """Inline admin for VariantMedia within ProductVariantAdmin."""

    model = VariantMedia
    extra = 1
    fields = ["file", "thumbnail", "media_type", "alt_text", "is_featured", "sort_order"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin configuration for the Product model."""

    list_display = [
        "display_name",
        "brand",
        "category",
        "cloth_type",
        "hsn_code",
        "status",
        "created_at",
    ]
    list_filter = [
        "status",
        "category",
        "cloth_type",
        "hsn_code",
        "created_at",
        "updated_at",
    ]
    search_fields = ["name", "brand", "description", "hsn_code"]
    ordering = ["brand", "name"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = []

    fieldsets = (
        ("Basic Information", {"fields": ("brand", "name", "description", "status")}),
        ("Classification", {"fields": ("category", "cloth_type")}),
        ("Tax Information", {"fields": ("hsn_code",)}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )


class InventoryLogInline(admin.TabularInline):
    """Inline admin for InventoryLog within ProductVariantAdmin."""

    model = InventoryLog
    extra = 0
    readonly_fields = [
        "timestamp",
        "created_by",
        "transaction_type",
        "quantity_change",
        "new_quantity",
        "total_value",
    ]
    fields = [
        "timestamp",
        "transaction_type",
        "quantity_change",
        "new_quantity",
        "total_value",
        "notes",
    ]
    can_delete = False
    max_num = 10

    def has_add_permission(self, request, obj=None):
        """Prevent adding inventory logs directly via inline."""
        return False


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    """Admin configuration for the ProductVariant model."""

    list_display = [
        "get_product_name",
        "barcode",
        "size",
        "color",
        "quantity",
        "damaged_quantity",
        "purchase_price",
        "mrp",
        "final_price",
        "stock_status",
        "status",
        "created_at",
    ]
    list_filter = [
        "status",
        "product__category",
        "product__cloth_type",
        "size",
        "color",
        "created_at",
        "updated_at",
    ]
    search_fields = [
        "product__name",
        "product__brand",
        "barcode",
        "product__category__name",
    ]
    ordering = ["product__brand", "product__name"]
    readonly_fields = [
        "created_at",
        "updated_at",
        "final_price",
        "profit_margin",
        "total_value",
        "damaged_value",
        "stock_health",
        "is_low_stock",
        "available_quantity",
        "total_quantity",
        "damage_percentage",
    ]
    inlines = [VariantMediaInline, InventoryLogInline]

    fieldsets = (
        (
            "Product Information",
            {"fields": ("product", "barcode", "size", "color", "extra_attributes")},
        ),
        (
            "Pricing",
            {
                "fields": (
                    "purchase_price",
                    "mrp",
                    "discount_percentage",
                    "final_price",
                )
            },
        ),
        ("Inventory", {"fields": ("quantity", "damaged_quantity", "minimum_quantity")}),
        (
            "Calculated Fields",
            {
                "fields": (
                    "total_value",
                    "damaged_value",
                    "profit_margin",
                    "available_quantity",
                    "total_quantity",
                    "damage_percentage",
                ),
                "classes": ("collapse",),
            },
        ),
        ("Status", {"fields": ("status", "stock_health", "is_low_stock")}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def get_product_name(self, obj):
        """Return the display name for the product variant."""
        return obj.get_name(include_barcode=False, include_variants=True)

    get_product_name.short_description = "Product Name"
    get_product_name.admin_order_field = "product__name"

    def get_queryset(self, request):
        """Optimize queryset with select_related for list display."""
        return (
            super()
            .get_queryset(request)
            .select_related(
                "product", "product__category", "product__cloth_type", "size", "color"
            )
        )

    actions = ["mark_as_active", "mark_as_discontinued", "adjust_quantities"]

    def mark_as_active(self, request, queryset):
        """Bulk-mark selected variants as active."""
        updated = queryset.update(status=ProductVariant.VariantStatus.ACTIVE)
        self.message_user(request, f"{updated} variants marked as active.")

    mark_as_active.short_description = "Mark selected variants as active"

    def mark_as_discontinued(self, request, queryset):
        """Bulk-mark selected variants as discontinued."""
        updated = queryset.update(status=ProductVariant.VariantStatus.DISCONTINUED)
        self.message_user(request, f"{updated} variants marked as discontinued.")

    mark_as_discontinued.short_description = "Mark selected variants as discontinued"

    def adjust_quantities(self, request, _queryset):
        """Placeholder action for bulk quantity adjustment."""
        self.message_user(
            request, "Quantity adjustment feature would be implemented here."
        )

    adjust_quantities.short_description = "Adjust quantities for selected variants"


@admin.register(InventoryLog)
class InventoryLogAdmin(admin.ModelAdmin):
    """Admin configuration for the InventoryLog model."""

    list_display = [
        "variant",
        "transaction_type",
        "quantity_change",
        "new_quantity",
        "total_value",
        "created_by",
        "timestamp",
    ]
    list_filter = [
        "transaction_type",
        "timestamp",
        "variant__product__category",
        "created_by",
    ]
    search_fields = [
        "variant__product__name",
        "variant__product__brand",
        "variant__barcode",
        "notes",
    ]
    ordering = ["-timestamp"]
    readonly_fields = ["timestamp", "created_at", "updated_at"]

    fieldsets = (
        (
            "Transaction Details",
            {
                "fields": (
                    "variant",
                    "transaction_type",
                    "quantity_change",
                    "new_quantity",
                )
            },
        ),
        (
            "Financial Information",
            {"fields": ("purchase_price", "mrp", "total_value")},
        ),
        (
            "Additional Information",
            {"fields": ("supplier_invoice", "created_by", "notes")},
        ),
        (
            "Timestamps",
            {
                "fields": ("timestamp", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        """Optimize queryset with select_related for list display."""
        return (
            super()
            .get_queryset(request)
            .select_related(
                "variant", "variant__product", "created_by", "supplier_invoice"
            )
        )

    def has_add_permission(self, request):
        """Prevent manual creation; logs are created via application logic."""
        return False


@admin.register(VariantMedia)
class VariantMediaAdmin(admin.ModelAdmin):
    """Admin configuration for the VariantMedia model."""

    list_display = ["variant", "media_type", "is_featured", "file_size_display", "created_at"]
    list_filter = ["media_type", "is_featured", "created_at"]
    search_fields = ["variant__product__name", "variant__product__brand", "alt_text"]
    ordering = ["-created_at"]




# Custom admin site configuration
admin.site.site_header = "Inventory Management System"
admin.site.site_title = "Inventory Admin"
admin.site.index_title = "Welcome to Inventory Management"


# Add custom admin actions and statistics
def get_inventory_stats():
    """Get inventory statistics for admin dashboard."""
    from django.db.models import Sum, F
    from django.utils import timezone
    from datetime import timedelta

    # Basic counts
    total_products = Product.objects.count()
    total_variants = ProductVariant.objects.count()
    total_categories = Category.objects.count()
    total_colors = Color.objects.count()
    total_sizes = Size.objects.count()

    # Inventory statistics
    active_variants = ProductVariant.objects.filter(
        status=ProductVariant.VariantStatus.ACTIVE
    ).count()
    out_of_stock = ProductVariant.objects.filter(
        quantity=0, status=ProductVariant.VariantStatus.ACTIVE
    ).count()
    low_stock = ProductVariant.objects.filter(
        quantity__lte=F("minimum_quantity"),
        status=ProductVariant.VariantStatus.ACTIVE,
    ).count()

    # Financial statistics
    total_inventory_value = (
        ProductVariant.objects.aggregate(
            total=Sum(F("quantity") * F("purchase_price"))
        )["total"]
        or 0
    )

    total_damaged_value = (
        ProductVariant.objects.aggregate(
            total=Sum(F("damaged_quantity") * F("purchase_price"))
        )["total"]
        or 0
    )

    # Recent activity (last 30 days) - only for active variants
    thirty_days_ago = timezone.now() - timedelta(days=30)
    recent_transactions = InventoryLog.objects.filter(
        timestamp__gte=thirty_days_ago, variant__is_deleted=False
    ).count()

    recent_sales = (
        InventoryLog.objects.filter(
            transaction_type=InventoryLog.TransactionTypes.SALE,
            timestamp__gte=thirty_days_ago,
            variant__is_deleted=False,
        ).aggregate(total=Sum("quantity_change"))["total"]
        or 0
    )

    recent_stock_in = (
        InventoryLog.objects.filter(
            transaction_type=InventoryLog.TransactionTypes.STOCK_IN,
            timestamp__gte=thirty_days_ago,
            variant__is_deleted=False,
        ).aggregate(total=Sum("quantity_change"))["total"]
        or 0
    )

    return {
        "total_products": total_products,
        "total_variants": total_variants,
        "total_categories": total_categories,
        "total_colors": total_colors,
        "total_sizes": total_sizes,
        "active_variants": active_variants,
        "out_of_stock": out_of_stock,
        "low_stock": low_stock,
        "total_inventory_value": total_inventory_value,
        "total_damaged_value": total_damaged_value,
        "recent_transactions": recent_transactions,
        "recent_sales": abs(recent_sales),
        "recent_stock_in": recent_stock_in,
    }


@admin.register(DamagedItemRecord)
class DamagedItemRecordAdmin(admin.ModelAdmin):
    list_display = [
        "id", "variant", "quantity", "reason", "status",
        "supplier", "credit_amount", "created_at",
    ]
    list_filter = ["status", "reason", "supplier", "created_at"]
    search_fields = ["variant__full_name", "variant__barcode", "supplier__name"]
    readonly_fields = ["created_at", "updated_at", "resolved_at"]
