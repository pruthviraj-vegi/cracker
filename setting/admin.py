"""
Admin interface for ShopDetails and ReportConfiguration models.
"""

from django.contrib import admin
from .models import ReportConfiguration, ShopDetails


@admin.register(ShopDetails)
class ShopDetailsAdmin(admin.ModelAdmin):
    """Admin interface for ShopDetails model."""

    list_display = [
        "shop_name",
        "city",
        "state",
        "pincode",
        "phone_number",
        "gst_no",
        "is_active",
        "created_at",
    ]
    list_filter = ["is_active", "state", "city", "created_at"]
    search_fields = ["shop_name", "city", "state", "phone_number", "gst_no"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("shop_name", "is_active")}),
        (
            "Address",
            {
                "fields": (
                    "first_line",
                    "second_line",
                    "city",
                    "state",
                    "pincode",
                    "country",
                )
            },
        ),
        (
            "Contact Information",
            {"fields": ("phone_number", "phone_two", "email", "website")},
        ),
        ("Business Details", {"fields": ("gst_no", "logo")}),
        (
            "System Information",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("created_by")

    def save_model(self, request, obj, form, change):
        """Set created_by user."""
        if not change:  # Only for new objects
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ReportConfiguration)
class ReportConfigurationAdmin(admin.ModelAdmin):
    """Admin interface for ReportConfiguration model."""

    list_display = [
        "report_type",
        "paper_size",
        "currency",
        "is_default",
        "is_active",
        "created_at",
    ]
    list_filter = [
        "report_type",
        "paper_size",
        "currency",
        "is_default",
        "is_active",
        "created_at",
    ]
    search_fields = ["report_type", "terms_conditions", "thank_you_message"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        (
            "Basic Settings",
            {
                "fields": (
                    "report_type",
                    "paper_size",
                    "currency",
                    "is_default",
                    "is_active",
                )
            },
        ),
        (
            "Header Settings",
            {
                "fields": (
                    "show_logo",
                    "show_shop_name",
                    "show_address",
                    "show_contact",
                    "show_gst",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Invoice Content",
            {
                "fields": (
                    "show_invoice_number",
                    "show_date",
                    "show_due_date",
                    "show_payment_method",
                    "show_customer_details",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Item Details",
            {
                "fields": (
                    "show_item_description",
                    "show_quantity",
                    "show_unit_price",
                    "show_discount",
                    "show_tax_breakdown",
                    "show_total",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Footer Settings",
            {
                "fields": (
                    "show_terms_conditions",
                    "show_qr_code",
                    "show_thank_you",
                    "show_signature",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Custom Text",
            {
                "fields": ("terms_conditions", "thank_you_message", "footer_note"),
                "classes": ("collapse",),
            },
        ),
        (
            "System Information",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related("created_by")

    def save_model(self, request, obj, form, change):
        """Set created_by user."""
        if not change:  # Only for new objects
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        """Make certain fields readonly based on conditions."""
        readonly_fields = list(self.readonly_fields)

        # If this is a default config, make is_default readonly
        if obj and obj.is_default:
            readonly_fields.append("is_default")

        return readonly_fields
