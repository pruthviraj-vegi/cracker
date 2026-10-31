"""
Django admin configurations for the invoice app.
"""

from django.contrib import admin
from invoice.models import (
    AuditTable,
    Invoice,
    InvoiceAudit,
    InvoiceItem,
    PaymentAllocation,
    ReturnInvoice,
    ReturnInvoiceItem,
)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    """Admin interface for Invoice model."""

    list_display = (
        "invoice_number",
        "customer",
        "payment_type",
        "invoice_type",
        "payment_status",
        "payment_method",
        "amount",
        "discount_amount",
        "total_payable_display",
        "total_received_display",
        "remaining_amount_display",
        "invoice_date",
        "sold_by",
    )
    list_filter = (
        "payment_type",
        "invoice_type",
        "payment_status",
        "payment_method",
        "invoice_date",
        "sold_by",
    )
    search_fields = (
        "invoice_number",
        "cart_no",
        # Keep search safe by using IDs to avoid unknown field lookups
        "customer__id",
    )
    date_hierarchy = "invoice_date"
    ordering = ("-created_at",)
    readonly_fields = (
        "created_at",
        "updated_at",
    )

    def total_payable_display(self, obj):
        """Display the total payable amount for the invoice."""
        return obj.total_payable

    total_payable_display.short_description = "Total Payable"

    def total_received_display(self, obj):
        """Display the total received amount for the invoice."""
        return obj.total_received

    total_received_display.short_description = "Total Received"

    def remaining_amount_display(self, obj):
        """Display the remaining amount to be paid for the invoice."""
        return obj.remaining_amount

    remaining_amount_display.short_description = "Remaining"


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    """Admin interface for InvoiceItem model."""

    list_display = (
        "invoice",
        "product_variant",
        "quantity",
        "mrp",
        "unit_price",
        "purchase_price",
        "amount_display",
        "created_at",
    )
    list_filter = (
        # "invoice",
        # "product_variant",
        "created_at",
    )
    search_fields = (
        "invoice__invoice_number",
        "invoice__id",
        "product_variant__id",
    )
    ordering = ("id",)
    readonly_fields = (
        "created_at",
        "updated_at",
    )

    def amount_display(self, obj):
        """Display the total amount (quantity * unit price) for the invoice item."""
        return obj.amount

    amount_display.short_description = "Amount"


@admin.register(PaymentAllocation)
class PaymentAllocationAdmin(admin.ModelAdmin):
    """Admin interface for PaymentAllocation model."""

    list_display = [
        "id",
        "payment",
        "invoice",
        "amount_allocated",
        "created_by",
        "allocated_at",
    ]

    list_display_links = ["id", "payment"]

    search_fields = [
        "payment__customer__name",
        "payment__customer__phone_number",
        "invoice__invoice_number",
        "payment__id",
    ]

    list_filter = [
        ("allocated_at", admin.DateFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
        "created_by",
    ]

    date_hierarchy = "allocated_at"

    readonly_fields = ["allocated_at", "updated_at"]

    autocomplete_fields = ["payment", "invoice", "created_by"]

    list_per_page = 25
    ordering = ["-allocated_at"]
    list_select_related = ["payment", "invoice", "created_by"]

    fieldsets = (
        (
            "Allocation Details",
            {
                "fields": (
                    "payment",
                    "invoice",
                    "amount_allocated",
                )
            },
        ),
        (
            "System",
            {
                "fields": ("created_by", "allocated_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("payment__customer", "invoice", "created_by")
        )


@admin.register(AuditTable)
class AuditTableAdmin(admin.ModelAdmin):
    """Admin interface for AuditTable model."""

    list_display = [
        "id",
        "title",
        "audit_type",
        "status",
        "financial_year",
        "start_date",
        "end_date",
        "total_changes_display",
        "created_by",
        "created_at",
    ]

    list_display_links = ["id", "title"]

    search_fields = [
        "title",
        "description",
        "audit_type",
        "financial_year",
        "created_by__username",
    ]

    list_filter = [
        "audit_type",
        "status",
        "financial_year",
        ("start_date", admin.DateFieldListFilter),
        ("end_date", admin.DateFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
        "created_by",
    ]

    date_hierarchy = "created_at"

    readonly_fields = ["created_at", "total_changes_display"]

    autocomplete_fields = ["created_by"]

    list_per_page = 25
    ordering = ["-created_at"]
    list_select_related = ["created_by"]

    fieldsets = (
        (
            "Audit Session Details",
            {
                "fields": (
                    "title",
                    "description",
                    "audit_type",
                    "status",
                )
            },
        ),
        (
            "Date Range",
            {
                "fields": (
                    "start_date",
                    "end_date",
                    "financial_year",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "total_changes_display",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def total_changes_display(self, obj):
        """Display the total number of changes associated with this audit table."""
        return obj.total_changes

    total_changes_display.short_description = "Total Changes"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("created_by")


@admin.register(InvoiceAudit)
class InvoiceAuditAdmin(admin.ModelAdmin):
    """Admin interface for InvoiceAudit model."""

    list_display = [
        "id",
        "invoice",
        "audit_table",
        "old_invoice_no",
        "new_invoice_no",
        "change_type",
        "reason",
        "changed_by",
        "created_at",
    ]

    list_display_links = ["id", "invoice"]

    search_fields = [
        "invoice__invoice_number",
        "old_invoice_no",
        "new_invoice_no",
        "reason",
        "audit_table__title",
        "changed_by__username",
    ]

    list_filter = [
        "change_type",
        "audit_table",
        ("created_at", admin.DateFieldListFilter),
        "changed_by",
    ]

    date_hierarchy = "created_at"

    readonly_fields = ["created_at"]

    autocomplete_fields = ["invoice", "audit_table", "changed_by"]

    list_per_page = 25
    ordering = ["-created_at"]
    list_select_related = ["invoice", "audit_table", "changed_by"]

    fieldsets = (
        (
            "Invoice Change Details",
            {
                "fields": (
                    "invoice",
                    "audit_table",
                    "old_invoice_no",
                    "new_invoice_no",
                    "change_type",
                    "reason",
                )
            },
        ),
        (
            "Change Information",
            {
                "fields": (
                    "old_invoice_type",
                    "new_invoice_type",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "changed_by",
                    "created_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("invoice", "audit_table", "changed_by")
        )


@admin.register(ReturnInvoice)
class ReturnInvoiceAdmin(admin.ModelAdmin):
    """Admin interface for ReturnInvoice model."""

    list_display = [
        "return_number",
        "invoice",
        "customer",
        "status",
        "refund_type",
        "reason",
        "total_amount",
        "refund_amount",
        "restocking_fee",
        "return_date",
        "approved_date",
        "processed_date",
        "created_by",
        "created_at",
    ]

    list_display_links = ["return_number", "invoice"]

    search_fields = [
        "return_number",
        "invoice__invoice_number",
        "customer__name",
        "customer__phone_number",
        "notes",
        "internal_notes",
        "created_by__username",
    ]

    list_filter = [
        "status",
        "refund_type",
        "reason",
        "financial_year",
        ("return_date", admin.DateFieldListFilter),
        ("approved_date", admin.DateFieldListFilter),
        ("processed_date", admin.DateFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
        "created_by",
        "approved_by",
        "processed_by",
    ]

    date_hierarchy = "return_date"

    readonly_fields = [
        "return_number",
        "sequence_no",
        "financial_year",
        "created_at",
        "updated_at",
    ]

    autocomplete_fields = [
        "invoice",
        "customer",
        "created_by",
        "modified_by",
        "approved_by",
        "processed_by",
    ]

    list_per_page = 25
    ordering = ["-created_at"]
    list_select_related = [
        "invoice",
        "customer",
        "created_by",
        "approved_by",
        "processed_by",
    ]

    fieldsets = (
        (
            "Return Information",
            {
                "fields": (
                    "return_number",
                    "invoice",
                    "customer",
                    "sequence_no",
                    "financial_year",
                )
            },
        ),
        (
            "Return Details",
            {
                "fields": (
                    "refund_type",
                    "status",
                    "reason",
                    "return_date",
                )
            },
        ),
        (
            "Financial Information",
            {
                "fields": (
                    "total_amount",
                    "refund_amount",
                    "restocking_fee",
                )
            },
        ),
        (
            "Processing Dates",
            {
                "fields": (
                    "approved_date",
                    "processed_date",
                )
            },
        ),
        (
            "Notes",
            {
                "fields": (
                    "notes",
                    "internal_notes",
                )
            },
        ),
        (
            "Workflow",
            {
                "fields": (
                    "approved_by",
                    "processed_by",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_by",
                    "modified_by",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "invoice", "customer", "created_by", "approved_by", "processed_by"
            )
        )


@admin.register(ReturnInvoiceItem)
class ReturnInvoiceItemAdmin(admin.ModelAdmin):
    """Admin interface for ReturnInvoiceItem model."""

    list_display = [
        "return_invoice",
        "product_variant",
        "quantity_original",
        "quantity_returned",
        "unit_price",
        "total_amount",
        "condition",
        "return_reason",
        "created_at",
    ]

    list_display_links = ["return_invoice", "product_variant"]

    search_fields = [
        "return_invoice__return_number",
        "return_invoice__invoice__invoice_number",
        "product_variant__product__name",
        "product_variant__variant_name",
        "original_invoice_item__id",
        "notes",
    ]

    list_filter = [
        "condition",
        "return_reason",
        ("created_at", admin.DateFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
    ]

    date_hierarchy = "created_at"

    readonly_fields = [
        "original_invoice_item",
        "created_at",
        "updated_at",
    ]

    autocomplete_fields = [
        "return_invoice",
        "product_variant",
        "original_invoice_item",
    ]

    list_per_page = 25
    ordering = ["-created_at"]
    list_select_related = [
        "return_invoice",
        "product_variant",
        "original_invoice_item",
    ]

    fieldsets = (
        (
            "Return Item Information",
            {
                "fields": (
                    "return_invoice",
                    "product_variant",
                    "original_invoice_item",
                )
            },
        ),
        (
            "Quantities",
            {
                "fields": (
                    "quantity_original",
                    "quantity_returned",
                )
            },
        ),
        (
            "Pricing",
            {
                "fields": (
                    "unit_price",
                    "total_amount",
                )
            },
        ),
        (
            "Return Details",
            {
                "fields": (
                    "condition",
                    "return_reason",
                    "notes",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "return_invoice__invoice",
                "product_variant__product",
                "original_invoice_item",
            )
        )
