"""
Admin configurations for supplier-related models.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import (
    Supplier,
    SupplierInvoice,
    SupplierPayment,
    SupplierPaymentAllocation,
    MediaFile,
)


class MediaFileInline(admin.TabularInline):
    """Inline admin for MediaFile model"""

    model = MediaFile
    extra = 1
    fields = ("media_file", "created_at")
    readonly_fields = ("created_at",)


class SupplierPaymentAllocationInline(admin.TabularInline):
    """Inline admin for SupplierPaymentAllocation model"""

    model = SupplierPaymentAllocation
    extra = 1
    fields = ("invoice", "amount_allocated", "allocated_at")
    readonly_fields = ("allocated_at",)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    """Admin configuration for Supplier model"""

    list_display = (
        "name",
        "contact_person",
        "phone",
        "gstin",
        "balance_due",
        "created_at",
        "is_deleted",
    )
    list_filter = (
        "is_deleted",
        "created_at",
        "updated_at",
    )
    search_fields = (
        "name",
        "contact_person",
        "phone",
        "gstin",
        "email",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "balance_due",
    )
    fieldsets = (
        ("Basic Information", {"fields": ("name", "contact_person", "phone", "email")}),
        ("Business Information", {"fields": ("gstin", "address")}),
        (
            "System Information",
            {
                "fields": ("created_by", "created_at", "updated_at", "is_deleted"),
                "classes": ("collapse",),
            },
        ),
    )
    ordering = ("name",)
    list_per_page = 25

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("created_by")


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    """Admin configuration for SupplierInvoice model"""

    list_display = (
        "invoice_number",
        "supplier_link",
        "invoice_date",
        "invoice_type",
        "gst_type",
        "total_amount",
        "paid_amount",
        "status",
        "created_at",
        "is_deleted",
    )
    list_filter = (
        "invoice_type",
        "gst_type",
        "status",
        "invoice_date",
        "is_deleted",
        "created_at",
    )
    search_fields = (
        "invoice_number",
        "supplier__name",
        "supplier__contact_person",
        "notes",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "paid_amount",
    )
    fieldsets = (
        (
            "Invoice Information",
            {"fields": ("supplier", "invoice_number", "invoice_date", "invoice_type")},
        ),
        (
            "GST Information",
            {
                "fields": ("gst_type", "cgst_amount", "igst_amount"),
                "classes": ("collapse",),
            },
        ),
        (
            "Amount Details",
            {"fields": ("sub_total", "adjustment_amount", "total_amount")},
        ),
        ("Payment Status", {"fields": ("status", "paid_amount")}),
        (
            "Additional Information",
            {"fields": ("notes", "created_by"), "classes": ("collapse",)},
        ),
        (
            "System Information",
            {
                "fields": ("created_at", "updated_at", "is_deleted"),
                "classes": ("collapse",),
            },
        ),
    )
    inlines = [MediaFileInline]
    ordering = ("-invoice_date",)
    list_per_page = 25

    def supplier_link(self, obj):
        """Create a link to the supplier admin page"""
        if obj.supplier:
            url = reverse("admin:supplier_supplier_change", args=[obj.supplier.id])
            return format_html('<a href="{}">{}</a>', url, obj.supplier.name)
        return "-"

    supplier_link.short_description = "Supplier"
    supplier_link.admin_order_field = "supplier__name"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("supplier", "created_by")


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    """Admin configuration for SupplierPayment model"""

    list_display = (
        "id",
        "supplier_link",
        "amount",
        "method",
        "transaction_id",
        "unallocated_amount",
        "payment_date",
        "created_at",
        "is_deleted",
    )
    list_filter = (
        "method",
        "payment_date",
        "is_deleted",
        "created_at",
    )
    search_fields = (
        "supplier__name",
        "supplier__contact_person",
        "transaction_id",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "unallocated_amount",
    )
    fieldsets = (
        (
            "Payment Information",
            {"fields": ("supplier", "amount", "method", "transaction_id")},
        ),
        ("Allocation", {"fields": ("unallocated_amount", "payment_date")}),
        (
            "Additional Information",
            {"fields": ("created_by",), "classes": ("collapse",)},
        ),
        (
            "System Information",
            {
                "fields": ("created_at", "updated_at", "is_deleted"),
                "classes": ("collapse",),
            },
        ),
    )
    inlines = [SupplierPaymentAllocationInline]
    ordering = ("-payment_date",)
    list_per_page = 25

    def supplier_link(self, obj):
        """Create a link to the supplier admin page"""
        if obj.supplier:
            url = reverse("admin:supplier_supplier_change", args=[obj.supplier.id])
            return format_html('<a href="{}">{}</a>', url, obj.supplier.name)
        return "-"

    supplier_link.short_description = "Supplier"
    supplier_link.admin_order_field = "supplier__name"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("supplier", "created_by")


@admin.register(SupplierPaymentAllocation)
class SupplierPaymentAllocationAdmin(admin.ModelAdmin):
    """Admin configuration for SupplierPaymentAllocation model"""

    list_display = (
        "id",
        "payment_link",
        "invoice_link",
        "amount_allocated",
        "allocated_at",
        "is_deleted",
    )
    list_filter = (
        "allocated_at",
        "is_deleted",
    )
    search_fields = (
        "payment__supplier__name",
        "invoice__invoice_number",
        "invoice__supplier__name",
    )
    readonly_fields = (
        "allocated_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Allocation Information",
            {"fields": ("payment", "invoice", "amount_allocated")},
        ),
        (
            "Additional Information",
            {"fields": ("created_by",), "classes": ("collapse",)},
        ),
        (
            "System Information",
            {
                "fields": ("allocated_at", "updated_at", "is_deleted"),
                "classes": ("collapse",),
            },
        ),
    )
    ordering = ("-allocated_at",)
    list_per_page = 25

    def payment_link(self, obj):
        """Create a link to the payment admin page"""
        if obj.payment:
            url = reverse(
                "admin:supplier_supplierpayment_change", args=[obj.payment.id]
            )
            return format_html('<a href="{}">Payment #{}</a>', url, obj.payment.id)
        return "-"

    payment_link.short_description = "Payment"
    payment_link.admin_order_field = "payment__id"

    def invoice_link(self, obj):
        """Create a link to the invoice admin page"""
        if obj.invoice:
            url = reverse(
                "admin:supplier_supplierinvoice_change", args=[obj.invoice.id]
            )
            return format_html('<a href="{}">{}</a>', url, obj.invoice.invoice_number)
        return "-"

    invoice_link.short_description = "Invoice"
    invoice_link.admin_order_field = "invoice__invoice_number"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("payment__supplier", "invoice__supplier", "created_by")
        )


@admin.register(MediaFile)
class MediaFileAdmin(admin.ModelAdmin):
    """Admin configuration for MediaFile model"""

    list_display = (
        "id",
        "invoice_link",
        "media_file",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = (
        "supplier_invoice__invoice_number",
        "supplier_invoice__supplier__name",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("File Information", {"fields": ("supplier_invoice", "media_file")}),
        (
            "System Information",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
    ordering = ("-created_at",)
    list_per_page = 25

    def invoice_link(self, obj):
        """Create a link to the invoice admin page"""
        if obj.supplier_invoice:
            url = reverse(
                "admin:supplier_supplierinvoice_change", args=[obj.supplier_invoice.id]
            )
            return format_html(
                '<a href="{}">{}</a>', url, obj.supplier_invoice.invoice_number
            )
        return "-"

    invoice_link.short_description = "Invoice"
    invoice_link.admin_order_field = "supplier_invoice__invoice_number"

    def get_queryset(self, request):
        return (
            super().get_queryset(request).select_related("supplier_invoice__supplier")
        )


# Customize admin site
admin.site.site_header = "Supplier Management Admin"
admin.site.site_title = "Supplier Management Admin Portal"
admin.site.index_title = "Welcome to Supplier Management Portal"
