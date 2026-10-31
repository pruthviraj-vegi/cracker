"""Admin configuration for report models storing generated PDF records and jobs."""

from django.contrib import admin
from django.utils.html import format_html
from report.models import InvoicePDF, CustomerStatementPDF, PdfJob


@admin.register(InvoicePDF)
class InvoicePDFAdmin(admin.ModelAdmin):
    """Admin interface for InvoicePDF model."""

    list_display = (
        "id",
        "invoice",
        "filename",
        "file_size_display",
        "is_active",
        "is_outdated_display",
        "generated_by",
        "generated_at",
    )
    list_filter = (
        "is_active",
        "generated_at",
        "generated_by",
    )
    search_fields = (
        "invoice__invoice_number",
        "filename",
        "pdf_url",
    )
    date_hierarchy = "generated_at"
    ordering = ("-generated_at",)
    readonly_fields = (
        "generated_at",
        "last_invoice_updated_at",
        "view_pdf_link",
    )
    autocomplete_fields = (
        "invoice",
        "generated_by",
    )
    list_select_related = (
        "invoice",
        "generated_by",
    )

    fieldsets = (
        (
            "PDF Information",
            {
                "fields": (
                    "invoice",
                    "pdf_url",
                    "filename",
                    "file_size",
                    "is_active",
                )
            },
        ),
        (
            "System Metadata",
            {
                "fields": (
                    "generated_by",
                    "generated_at",
                    "last_invoice_updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def file_size_display(self, obj):
        """Format and display file size in KB or MB."""
        if obj.file_size is None:
            return "-"
        if obj.file_size < 1024:
            return f"{obj.file_size} B"
        if obj.file_size < 1024 * 1024:
            return f"{obj.file_size / 1024:.2f} KB"
        return f"{obj.file_size / (1024 * 1024):.2f} MB"

    file_size_display.short_description = "File Size"
    file_size_display.admin_order_field = "file_size"

    def is_outdated_display(self, obj):
        """Display whether the PDF is outdated and needs regeneration."""
        return obj.is_pdf_outdated()

    is_outdated_display.short_description = "Outdated"
    is_outdated_display.boolean = True

    def view_pdf_link(self, obj):
        """Provide a clickable link to view/download the generated PDF."""
        if obj.pdf_url:
            return format_html('<a href="{}" target="_blank">Open PDF Link</a>', obj.pdf_url)
        return "No PDF URL"

    view_pdf_link.short_description = "View PDF"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("invoice", "generated_by")


@admin.register(CustomerStatementPDF)
class CustomerStatementPDFAdmin(admin.ModelAdmin):
    """Admin interface for CustomerStatementPDF model."""

    list_display = (
        "id",
        "customer",
        "from_date",
        "to_date",
        "closing_balance",
        "filename",
        "file_size_display",
        "is_active",
        "generated_by",
        "generated_at",
    )
    list_filter = (
        "is_active",
        "generated_at",
        "generated_by",
        ("from_date", admin.DateFieldListFilter),
        ("to_date", admin.DateFieldListFilter),
    )
    search_fields = (
        "customer__name",
        "customer__phone_number",
        "filename",
        "pdf_url",
    )
    date_hierarchy = "generated_at"
    ordering = ("-generated_at",)
    readonly_fields = (
        "generated_at",
        "view_pdf_link",
    )
    autocomplete_fields = (
        "customer",
        "generated_by",
    )
    list_select_related = (
        "customer",
        "generated_by",
    )

    fieldsets = (
        (
            "Statement Details",
            {
                "fields": (
                    "customer",
                    "from_date",
                    "to_date",
                    "closing_balance",
                )
            },
        ),
        (
            "PDF File Info",
            {
                "fields": (
                    "pdf_url",
                    "filename",
                    "file_size",
                    "is_active",
                )
            },
        ),
        (
            "System Metadata",
            {
                "fields": (
                    "generated_by",
                    "generated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def file_size_display(self, obj):
        """Format and display file size in KB or MB."""
        if obj.file_size is None:
            return "-"
        if obj.file_size < 1024:
            return f"{obj.file_size} B"
        if obj.file_size < 1024 * 1024:
            return f"{obj.file_size / 1024:.2f} KB"
        return f"{obj.file_size / (1024 * 1024):.2f} MB"

    file_size_display.short_description = "File Size"
    file_size_display.admin_order_field = "file_size"

    def view_pdf_link(self, obj):
        """Provide a clickable link to view/download the generated PDF."""
        if obj.pdf_url:
            return format_html('<a href="{}" target="_blank">Open PDF Link</a>', obj.pdf_url)
        return "No PDF URL"

    view_pdf_link.short_description = "View PDF"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("customer", "generated_by")


@admin.register(PdfJob)
class PdfJobAdmin(admin.ModelAdmin):
    """Admin interface for PdfJob model."""

    list_display = (
        "id",
        "title",
        "status",
        "job_type",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "status",
        "job_type",
        "created_at",
        "created_by",
    )
    search_fields = (
        "job_type",
        "error_message",
        "created_by__username",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "created_by",
    )
    list_select_related = (
        "created_by",
    )

    actions = ["mark_as_failed_action"]

    fieldsets = (
        (
            "Job Information",
            {
                "fields": (
                    "job_type",
                    "status",
                    "parameters",
                    "file",
                    "error_message",
                )
            },
        ),
        (
            "System Metadata",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def mark_as_failed_action(self, request, queryset):
        """Mark selected jobs as failed with an admin reason."""
        updated = queryset.filter(
            status__in=["pending", "processing"]
        ).update(
            status="failed",
            error_message="Manually marked as failed by administrator."
        )
        self.message_user(
            request,
            f"Successfully marked {updated} active job(s) as failed.",
            level="SUCCESS"
        )

    mark_as_failed_action.short_description = "Mark selected pending/processing jobs as failed"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("created_by")
