"""
Admin configuration for the cart app.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Cart, CartItem


class CartItemInline(admin.TabularInline):
    """Inline admin for CartItem within Cart admin"""

    model = CartItem
    extra = 0
    readonly_fields = ["created_at", "updated_at"]
    fields = ["product_variant", "quantity", "price"]


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    """Admin configuration for Cart model"""

    list_display = [
        "id",
        "name",
        "status",
        "created_by",
        "total_amount_display",
        "item_count",
        "created_at",
        "updated_at",
    ]
    list_filter = ["status", "created_at", "updated_at", "created_by"]
    search_fields = ["name", "notes", "created_by__username"]
    readonly_fields = ["created_at", "updated_at"]
    list_per_page = 25
    ordering = ["-created_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("name", "status", "notes")}),
        ("User Information", {"fields": ("created_by",)}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    inlines = [CartItemInline]

    def total_amount_display(self, obj):
        """Display total amount with currency formatting"""
        # Calculate total manually since the model method has an issue
        total = sum(item.amount() for item in obj.cart_items.all())
        if total:
            return format_html(
                '<span style="font-weight: bold; color: #28a745;">${}</span>',
                f"{total:.2f}",
            )
        return format_html('<span style="color: #6c757d;">$0.00</span>')

    total_amount_display.short_description = "Total Amount"

    def item_count(self, obj):
        """Display count of items in the cart"""
        count = obj.cart_items.count()
        return format_html('<span style="font-weight: bold;">{}</span>', count)

    item_count.short_description = "Items"

    def get_queryset(self, request):
        """Optimize queryset with related fields"""
        return (
            super()
            .get_queryset(request)
            .select_related("created_by")
            .prefetch_related("cart_items")
        )


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    """Admin configuration for CartItem model"""

    list_display = [
        "id",
        "cart_link",
        "product_variant_link",
        "quantity",
        "price",
        "amount_display",
        "created_at",
    ]
    list_filter = [
        "cart__status",
        "created_at",
        "updated_at",
        "product_variant__product__category",
    ]
    search_fields = [
        "cart__name",
        "product_variant__full_name",
        "product_variant__barcode",
    ]
    readonly_fields = ["created_at", "updated_at"]
    list_per_page = 50
    ordering = ["-created_at"]

    fieldsets = (
        ("Cart Information", {"fields": ("cart",)}),
        ("Product Information", {"fields": ("product_variant",)}),
        ("Pricing", {"fields": ("quantity", "price")}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def cart_link(self, obj):
        """Create a clickable link to the cart"""
        if obj.cart:
            url = reverse("admin:cart_cart_change", args=[obj.cart.id])
            return format_html('<a href="{}">{}</a>', url, obj.cart.name)
        return "-"

    cart_link.short_description = "Cart"
    cart_link.admin_order_field = "cart__name"

    def product_variant_link(self, obj):
        """Create a clickable link to the product variant"""
        if obj.product_variant:
            url = reverse(
                "admin:inventory_productvariant_change", args=[obj.product_variant.id]
            )
            return format_html(
                '<a href="{}">{}</a>', url, obj.product_variant.full_name
            )
        return "-"

    product_variant_link.short_description = "Product"
    product_variant_link.admin_order_field = "product_variant__full_name"

    def amount_display(self, obj):
        """Display calculated amount with currency formatting"""
        if obj.pk:
            amount = obj.amount()
            if amount is not None:
                return format_html(
                    '<span style="font-weight: bold; color: #28a745;">${}</span>',
                    f"{amount:.2f}",
                )
            return format_html('<span style="color: #6c757d;">$0.00</span>')
        return "-"

    amount_display.short_description = "Amount"

    def get_queryset(self, request):
        """Optimize queryset with related fields"""
        return (
            super()
            .get_queryset(request)
            .select_related(
                "cart",
                "product_variant",
                "product_variant__product",
                "product_variant__product__category",
            )
        )
