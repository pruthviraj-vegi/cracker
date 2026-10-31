"""
Django admin configuration for Customer models.

This module provides the admin interface configuration for the Customer, Payment,
and CustomerCreditSummary models, enabling custom views, filters, and actions.
"""

from datetime import timedelta

from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import Customer, CustomerCreditSummary, Payment


class CustomerStatusFilter(SimpleListFilter):
    """Filter customers by their active/inactive status."""

    title = "Status"
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return (
            ("active", "Active"),
            ("inactive", "Inactive"),
        )

    def queryset(self, request, queryset):
        if self.value() == "active":
            return queryset.filter(is_deleted=False)
        if self.value() == "inactive":
            return queryset.filter(is_deleted=True)


class CustomerCreditFilter(SimpleListFilter):
    """Filter customers by their credit balance."""

    title = "Credit Balance"
    parameter_name = "credit"

    def lookups(self, request, model_admin):
        return (
            ("has_credit", "Has Credit"),
            ("no_credit", "No Credit"),
            ("high_credit", "High Credit (>1000)"),
        )

    def queryset(self, request, queryset):
        if self.value() == "has_credit":
            return queryset.filter(store_credit_balance__gt=0)
        if self.value() == "no_credit":
            return queryset.filter(store_credit_balance=0)
        if self.value() == "high_credit":
            return queryset.filter(store_credit_balance__gt=1000)


class CustomerDateFilter(SimpleListFilter):
    """Filter customers by creation date."""

    title = "Created Date"
    parameter_name = "created_date"

    def lookups(self, request, model_admin):
        return (
            ("today", "Today"),
            ("yesterday", "Yesterday"),
            ("this_week", "This Week"),
            ("this_month", "This Month"),
            ("last_month", "Last Month"),
        )

    def queryset(self, request, queryset):
        now = timezone.now()
        if self.value() == "today":
            return queryset.filter(created_at__date=now.date())
        if self.value() == "yesterday":
            yesterday = now.date() - timedelta(days=1)
            return queryset.filter(created_at__date=yesterday)
        if self.value() == "this_week":
            return queryset.filter(created_at__gte=now - timedelta(days=7))
        if self.value() == "this_month":
            return queryset.filter(
                created_at__month=now.month, created_at__year=now.year
            )
        if self.value() == "last_month":
            last_month = now.replace(day=1) - timedelta(days=1)
            return queryset.filter(
                created_at__month=last_month.month, created_at__year=last_month.year
            )


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """Admin interface for Customer model."""

    # List display configuration
    list_display = [
        "id",
        "name",
        "phone_number",
        "email_display",
        "address_display",
        "credit_balance_display",
        "payment_allocation_info",
        "status_display",
        "created_at",
        "actions_display",
    ]

    # List display links
    list_display_links = ["id", "name"]

    # Search fields
    search_fields = ["name", "phone_number", "email", "address"]

    # Filters
    list_filter = [
        CustomerStatusFilter,
        CustomerCreditFilter,
        CustomerDateFilter,
        ("created_at", admin.DateFieldListFilter),
    ]

    # Fieldsets for add/edit form
    fieldsets = (
        (
            "Basic Information",
            {"fields": ("name", "phone_number", "email"), "classes": ("wide",)},
        ),
        ("Address Information", {"fields": ("address",), "classes": ("wide",)}),
        (
            "Financial Information",
            {"fields": ("store_credit_balance",), "classes": ("wide",)},
        ),
        (
            "System Information",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
                "description": "System-generated information",
            },
        ),
    )

    # Read-only fields
    readonly_fields = ["created_at", "updated_at"]

    # Admin actions
    actions = [
        "activate_customers",
        "deactivate_customers",
        "reset_credit_balance",
        "add_credit_to_selected",
        "export_customer_data",
        "auto_reallocate_payments",
    ]

    # Pagination
    list_per_page = 25

    # Ordering
    ordering = ["-created_at"]

    # Date hierarchy
    date_hierarchy = "created_at"

    # Autocomplete fields
    autocomplete_fields = ["created_by"]

    # Save on top
    save_on_top = True

    # Custom admin site title
    def get_admin_site_title(self):
        """Return a custom title string for the customer admin site header."""
        return "Customer Management"

    # Custom methods for list display
    def email_display(self, obj):
        """Display email with proper formatting."""
        if obj.email:
            return format_html('<a href="mailto:{}">{}</a>', obj.email, obj.email)
        return "No Email"

    email_display.short_description = "Email"
    email_display.admin_order_field = "email"

    def address_display(self, obj):
        """Display shortened address."""
        if obj.address:
            return obj.address[:50] + "..." if len(obj.address) > 50 else obj.address
        return "No Address"

    address_display.short_description = "Address"

    def credit_balance_display(self, obj):
        """Display credit balance."""
        return f"{obj.store_credit_balance}"

    credit_balance_display.short_description = "Credit Balance"
    credit_balance_display.admin_order_field = "store_credit_balance"

    def payment_allocation_info(self, obj):
        """Display payment allocation information."""
        # Count payments and allocations
        payments = Payment.objects.filter(
            customer=obj, payment_type=Payment.PaymentType.Paid, is_deleted=False
        )

        total_payments = payments.count()
        total_unallocated = sum(payment.unallocated_amount for payment in payments)

        if total_payments > 0:
            return f"Payments: {total_payments}, Unallocated: {total_unallocated}"
        return "No payments"

    payment_allocation_info.short_description = "Payment Info"

    def status_display(self, obj):
        """Display status."""
        return "INACTIVE" if obj.is_deleted else "ACTIVE"

    status_display.short_description = "Status"
    status_display.admin_order_field = "is_deleted"

    def actions_display(self, obj):
        """Display action buttons."""
        view_url = reverse("admin:customer_customer_change", args=[obj.id])
        delete_url = reverse("admin:customer_customer_delete", args=[obj.id])

        return format_html(
            '<a href="{}" title="View/Edit">Edit</a> | '
            '<a href="{}" title="Delete" onclick="return confirm(\'Are you sure?\')">Delete</a>',
            view_url,
            delete_url,
        )

    actions_display.short_description = "Actions"
    actions_display.allow_tags = True

    # Admin actions
    def activate_customers(self, request, queryset):
        """Activate selected customers."""
        updated = queryset.update(is_deleted=False)
        self.message_user(
            request, f"Successfully activated {updated} customer(s).", level="SUCCESS"
        )

    activate_customers.short_description = "Activate selected customers"

    def deactivate_customers(self, request, queryset):
        """Deactivate selected customers."""
        updated = queryset.update(is_deleted=True)
        self.message_user(
            request, f"Successfully deactivated {updated} customer(s).", level="SUCCESS"
        )

    deactivate_customers.short_description = "Deactivate selected customers"

    def reset_credit_balance(self, request, queryset):
        """Reset credit balance to zero for selected customers."""
        updated = queryset.update(store_credit_balance=0)
        self.message_user(
            request,
            f"Successfully reset credit balance for {updated} customer(s).",
            level="SUCCESS",
        )

    reset_credit_balance.short_description = "Reset credit balance to zero"

    def add_credit_to_selected(self, request, queryset):
        """Add credit to selected customers."""
        # This would typically open a form to input the amount
        # For now, we'll add a fixed amount of 100
        for customer in queryset:
            customer.add_credit(100)
        self.message_user(
            request,
            f"Successfully added 100 credit to {queryset.count()} customer(s).",
            level="SUCCESS",
        )

    add_credit_to_selected.short_description = "Add 100 credit to selected customers"

    def export_customer_data(self, request, queryset):
        """Export customer data (placeholder for CSV export)."""
        self.message_user(
            request,
            f"Export functionality for {queryset.count()} customer(s) would be implemented here.",
            level="INFO",
        )

    export_customer_data.short_description = "Export customer data"

    def auto_reallocate_payments(self, request, queryset):
        """Auto reallocate payments using FIFO method for selected customers."""
        from customer.signals import reallocate_customer_payments

        total_customers = 0

        for customer in queryset:
            try:
                # Use signal-based reallocation (skips signals to avoid recursion)
                reallocate_customer_payments(customer, skip_signals=True)
                total_customers += 1
            except Exception as e:  # pylint: disable=broad-exception-caught
                self.message_user(
                    request,
                    f"Error reallocating for {customer.name}: {str(e)}",
                    level="ERROR",
                )

        if total_customers > 0:
            self.message_user(
                request,
                f"Successfully auto-allocated payments for {total_customers} customer(s) using FIFO method.",
                level="SUCCESS",
            )
        else:
            self.message_user(
                request,
                "No customers with payments found for auto-allocation.",
                level="WARNING",
            )

    auto_reallocate_payments.short_description = "Auto reallocate payments (FIFO)"

    def auto_reallocate_single_customer(self, request, customer_id):
        """Auto reallocate payments for a single customer."""
        from .views_credit import auto_reallocate
        from django.shortcuts import redirect
        from django.contrib import messages

        try:
            # Call the auto_reallocate view function
            response = auto_reallocate(request, customer_id)
            return response
        except Exception as e:  # pylint: disable=broad-exception-caught
            messages.error(request, f"Error during auto reallocation: {str(e)}")
            return redirect("admin:customer_customer_change", customer_id)

    # Override get_queryset to include related data
    def get_queryset(self, request):
        return super().get_queryset(request).select_related("created_by")

    # Override change form template
    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_save_and_continue"] = True
        extra_context["show_save_and_add_another"] = True

        # Add auto reallocate button context
        customer = self.get_object(request, object_id)
        if customer:
            payments = Payment.objects.filter(
                customer=customer,
                payment_type=Payment.PaymentType.Paid,
                is_deleted=False,
            )
            extra_context["has_payments"] = payments.exists()
            extra_context["customer_id"] = customer.id

        return super().change_view(request, object_id, form_url, extra_context)

    # Override add form template
    def add_view(self, request, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_save_and_add_another"] = True
        return super().add_view(request, form_url, extra_context)


# Inline payments on customer detail for quick entry/visibility
class PaymentInline(admin.TabularInline):
    """Inline admin for Customer Payments."""

    model = Payment
    fields = [
        "payment_date",
        "payment_type",
        "amount",
        "notes",
        "created_by",
    ]
    readonly_fields = []
    extra = 0
    show_change_link = True
    autocomplete_fields = ["created_by"]
    ordering = ["-payment_date", "-created_at"]


# Attach payments inline to the customer admin
CustomerAdmin.inlines = [PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Admin interface for Payment model."""

    list_display = [
        "id",
        "customer",
        "payment_type",
        "amount",
        "payment_date",
        "created_by",
        "created_at",
    ]

    list_display_links = ["id", "customer"]

    search_fields = [
        "customer__name",
        "customer__phone_number",
        "notes",
    ]

    list_filter = [
        "payment_type",
        ("payment_date", admin.DateFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
        "created_by",
    ]

    date_hierarchy = "payment_date"

    readonly_fields = ["created_at", "updated_at"]

    autocomplete_fields = ["customer", "created_by"]

    list_per_page = 25
    ordering = ["-payment_date", "-created_at"]
    list_select_related = ["customer", "created_by"]

    # Admin actions
    actions = ["auto_reallocate_selected_payments"]

    # Keep the admin uncluttered
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "customer",
                    "payment_type",
                    "amount",
                    "payment_date",
                    "notes",
                )
            },
        ),
        (
            "System",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def auto_reallocate_selected_payments(self, request, queryset):
        """Auto reallocate selected payments using FIFO method."""
        from customer.signals import reallocate_customer_payments

        # Group payments by customer
        customers = set()
        for payment in queryset.filter(payment_type=Payment.PaymentType.Paid):
            customers.add(payment.customer)

        total_customers = 0

        for customer in customers:
            try:
                # Use signal-based reallocation (skips signals to avoid recursion)
                # This will reallocate ALL payments for the customer, not just selected ones
                # This ensures proper FIFO ordering across all payments
                reallocate_customer_payments(customer, skip_signals=True)
                total_customers += 1
            except Exception as e:  # pylint: disable=broad-exception-caught
                self.message_user(
                    request,
                    f"Error reallocating for {customer.name}: {str(e)}",
                    level="ERROR",
                )

        if total_customers > 0:
            self.message_user(
                request,
                f"Successfully auto-allocated payments for {total_customers} customer(s) using FIFO method.",
                level="SUCCESS",
            )
        else:
            self.message_user(
                request,
                "No 'Paid' payments found in selection for auto-allocation.",
                level="WARNING",
            )

    auto_reallocate_selected_payments.short_description = (
        "Auto reallocate selected payments (FIFO)"
    )


@admin.register(CustomerCreditSummary)
class CustommerySummery(admin.ModelAdmin):
    """Admin configuration for the Customer Credit Summary representation."""

    list_display = [
        "customer",
        "credit_amount",
        "debit_amount",
        "balance_amount",
        "last_payment_date",
        "last_invoice_date",
        "is_overdue",
    ]


# Customize admin site
admin.site.site_header = "Billing System Administration"
admin.site.site_title = "Billing System Admin"
admin.site.index_title = "Welcome to Billing System Administration"


# Add custom admin site statistics
def get_admin_site_stats():
    """Get statistics for admin dashboard."""
    total_customers = Customer.objects.count()
    active_customers = Customer.objects.filter(is_deleted=False).count()
    total_credit = (
        Customer.objects.aggregate(total=Sum("store_credit_balance"))["total"] or 0
    )
    customers_with_credit = Customer.objects.filter(store_credit_balance__gt=0).count()

    return {
        "total_customers": total_customers,
        "active_customers": active_customers,
        "total_credit": total_credit,
        "customers_with_credit": customers_with_credit,
    }
