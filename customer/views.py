"""
Views for customer management, dashboard analytics, and CRUD operations.

Provides the customer dashboard with sales analytics and comparison charts,
customer listing with search/sort/pagination, and customer create/update/delete
flows using Django class-based views.
"""

import logging
from decimal import Decimal

from django.contrib import messages
from django.db.models import Case, Count, DecimalField, F, Q, Sum, When
from django.db.models.functions import Coalesce, TruncDate, TruncMonth, TruncWeek
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView, DeleteView, UpdateView

from base.comparison import get_comparison_data
from base.decorators import required_permission, RequiredPermissionMixin

from base.getDates import getDates
from base.utility import (
    build_search_filter,
    get_period_label,
    get_periodic_data,
    render_paginated_response,
    table_sorting,
)
from invoice.models import Invoice

from .forms import CustomerForm
from .models import Customer, CustomerCreditSummary, Payment

logger = logging.getLogger(__name__)


@required_permission("customer.view_dashboard")
def dashboard(request):
    """
    Customer management dashboard with analytics and insights.

    OPTIMIZED: Uses single query with multiple aggregations instead of separate queries.
    """
    date_filter = request.GET.get("date_filter", "this_month")

    # Calculate total outstanding using customer model's balance_amount method
    # balance_amount = credit_amount - debit_amount
    # where credit_amount = (credit invoices - discount - advance) + purchased payments
    # and debit_amount = paid payments

    # Get both metrics in a single query
    metrics = Customer.objects.filter(is_deleted=False).aggregate(
        total_outstanding=Coalesce(Sum("credit_summary__balance_amount"), Decimal("0")),
        total_customers=Count("id"),
    )

    context = {
        "date_filter": date_filter,
        "total_outstanding": metrics["total_outstanding"],
        "total_customers": metrics["total_customers"],
    }
    return render(request, "customer/dashboard.html", context)



@required_permission("customer.view_dashboard")
def dashboard_fetch(request):
    """
    AJAX endpoint to fetch customer dashboard data

    OPTIMIZED: Combines multiple aggregations into fewer queries and uses
    single-pass list comprehensions for percentage calculations.
    """
    date_filter = request.GET.get("date_filter", "this_month")
    start_date, end_date = getDates(request)

    # Filter invoices by date range
    invoices = Invoice.objects.filter(
        invoice_date__date__range=[start_date, end_date]
    ).select_related("customer")

    payments = Payment.objects.filter(
        payment_type=Payment.PaymentType.Paid,
        payment_date__date__range=[start_date, end_date],
    )

    # Calculate PERIOD-BASED totals in a single query
    invoice_metrics = invoices.aggregate(
        total_sales=Coalesce(
            Sum(F("amount") - F("discount_amount")),
            Decimal("0"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
        total_received_from_invoices=Coalesce(
            Sum("paid_amount"),
            Decimal("0"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
        total_invoices=Count("id"),
    )

    # Get payments received
    payments_received = payments.aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
    )["total"]

    # Calculate final metrics
    total_sales = invoice_metrics["total_sales"]
    total_received = invoice_metrics["total_received_from_invoices"] + payments_received
    total_invoices = invoice_metrics["total_invoices"]
    outstanding_balance = total_sales - total_received

    # Calculate comparison data for line chart
    comparison_data = get_comparison_data(Invoice.objects.all(), date_filter, start_date, end_date)

    # Payment status breakdown
    payment_status_breakdown = (
        invoices.values("payment_status")
        .annotate(
            count=Count("id"),
            amount=Coalesce(
                Sum(F("amount") - F("discount_amount")),
                Decimal("0"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
        )
        .order_by("payment_status")
    )

    # Payment type breakdown (Cash vs Credit)
    payment_type_breakdown = (
        invoices.values("payment_type")
        .annotate(
            count=Count("id"),
            amount=Coalesce(
                Sum(F("amount") - F("discount_amount")),
                Decimal("0"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
        )
        .order_by("payment_type")
    )

    # Customer breakdown (sales by customer)
    customer_breakdown = (
        invoices.values("customer__name")
        .annotate(
            count=Count("id"),
            amount=Coalesce(
                Sum(F("amount") - F("discount_amount")),
                Decimal("0"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
        )
        .order_by("-amount")[:10]  # Top 10 customers by sales amount
    )

    # Prepare response data
    stats = {
        "total_invoices": total_invoices,
        "total_sales": float(total_sales),
        "total_received": float(total_received),
        "outstanding_balance": float(outstanding_balance),
    }

    # Convert total_sales to float once for reuse
    total_sales_float = float(total_sales)

    # Payment status data processing - single pass with list comprehension
    payment_status_data = [
        {
            "payment_status": status["payment_status"].replace("_", " ").title(),
            "count": status["count"],
            "amount": float(status["amount"]),
            "percentage": (
                round((float(status["amount"]) / total_sales_float * 100), 1)
                if total_sales_float > 0
                else 0
            ),
        }
        for status in payment_status_breakdown
    ]

    # Payment type data processing - single pass with list comprehension
    payment_type_data = [
        {
            "payment_type": ptype["payment_type"].replace("_", " ").title(),
            "count": ptype["count"],
            "amount": float(ptype["amount"]),
            "percentage": (
                round((float(ptype["amount"]) / total_sales_float * 100), 1)
                if total_sales_float > 0
                else 0
            ),
        }
        for ptype in payment_type_breakdown
    ]

    # Customer breakdown data processing - single pass with list comprehension
    customer_list = list(customer_breakdown)
    top10_customer_total = float(sum(float(c["amount"]) for c in customer_list))

    customer_data = [
        {
            "customer_name": customer["customer__name"] or "Unknown",
            "count": customer["count"],
            "amount": float(customer["amount"]),
            "percentage": (
                round((float(customer["amount"]) / top10_customer_total * 100), 1)
                if top10_customer_total > 0
                else 0
            ),
        }
        for customer in customer_list
    ]

    return JsonResponse(
        {
            "success": True,
            "stats": stats,
            "payment_status_breakdown": payment_status_data,
            "payment_type_breakdown": payment_type_data,
            "customer_breakdown": customer_data,
            "comparison_data": comparison_data,
            "date_range": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "filter": date_filter,
            },
        }
    )


VALID_SORT_FIELDS = {
    "id",
    "name",
    "email",
    "created_at",
    "phone_number",
    "address",
}

CUSTOMERS_PER_PAGE = 20


@required_permission("customer.view_customer")
def home(request):
    """Customer management main page - initial load only."""
    # For initial page load, just render the template with empty data
    return render(request, "customer/home.html")


def get_data(request):
    """Build and return a filtered, sorted queryset of customers based on request params."""
    # Get search and filter parameters
    search_query = request.GET.get("search", "")

    # Apply search filter
    filters = build_search_filter(search_query, ["name", "phone_number", "email", "address"])
    # Apply sorting (Multi-column support)
    valid_sorts = table_sorting(request, VALID_SORT_FIELDS, "-created_at")

    customers = (
        Customer.objects.filter(filters)
        .select_related("referred_by")
        .order_by(*valid_sorts)
    )

    return customers


@required_permission("customer.view_customer")
def fetch_customers(request):
    """AJAX endpoint to fetch customers with search, filter, and pagination."""
    customers = get_data(request)

    return render_paginated_response(
        request,
        customers,
        "customer/fetch.html",
    )


class CreateCustomer(RequiredPermissionMixin, CreateView):
    """CBV to create a new customer record."""

    model = Customer
    form_class = CustomerForm
    template_name = "customer/form.html"
    success_url = reverse_lazy("customer:home")
    required_permission = "customer.add_customer"

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Customer created successfully!")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Customer"
        context["customer"] = None  # For breadcrumb compatibility
        return context

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse_lazy("customer:home")


class EditCustomer(RequiredPermissionMixin, UpdateView):
    """CBV to update an existing customer record."""

    model = Customer
    form_class = CustomerForm
    template_name = "customer/form.html"
    success_url = reverse_lazy("customer:home")
    required_permission = "customer.change_customer"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Edit Customer"
        context["customer"] = self.get_object()  # For breadcrumb compatibility

        return context

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        messages.success(self.request, "Customer updated successfully!")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class DeleteCustomer(RequiredPermissionMixin, DeleteView):
    """CBV to delete a customer record with confirmation."""

    model = Customer
    template_name = "customer/delete.html"
    required_permission = "customer.delete_customer"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["customer"] = self.get_object()
        return context

    def delete(self, request, *args, **kwargs):
        customer = self.get_object()

        if customer.pk == 1 or customer.phone_number == "3":
            messages.error(request, "The default Walk-in customer cannot be deleted.")
            return redirect("customer:home")

        messages.success(request, f"Customer '{customer.name}' deleted successfully!")
        return super().delete(request, *args, **kwargs)

    def get_success_url(self):
        return reverse_lazy("customer:home")

    def form_valid(self, form):
        messages.success(self.request, "Customer deleted successfully!")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


@required_permission("customer.view_customer")
def customer_detail(request, pk):
    """View customer details."""
    customer = get_object_or_404(Customer, id=pk)

    # Get customer payments (FIFO system)
    context = {"customer": customer}
    context.update(get_calculations(pk))
    return render(request, "customer/detail.html", context)


@required_permission("customer.view_customer")
def fetch_customer_invoices(request, pk):
    """AJAX: fetch invoices for a customer with pagination and optional sorting."""
    customer = get_object_or_404(Customer, id=pk)

    valid_sort_fields = {
        "invoice_date",
        "invoice_number",
        "amount",
        "total_payable",
    }

    valid_sorts = table_sorting(request, valid_sort_fields, "-invoice_date")

    queryset = Invoice.objects.filter(customer=customer).order_by(*valid_sorts)

    return render_paginated_response(
        request,
        queryset,
        "customer/invoice/fetch.html",
    )


def get_calculations(pk):
    """Return aggregated invoice totals (count, amount, cash, credit) for a customer."""
    customer = get_object_or_404(Customer, id=pk)
    invoices = Invoice.objects.filter(customer=customer)

    aggregates = invoices.aggregate(
        total_invoices=Count("id"),
        invoices_amount=Sum("amount"),
        cash_amount=Sum(
            Case(
                When(payment_type="CASH", then="amount"),
                default=0,
                output_field=DecimalField(),
            )
        ),
        credit_amount=Sum(
            Case(
                When(payment_type="CREDIT", then="amount"),
                default=0,
                output_field=DecimalField(),
            )
        ),
    )

    return {
        "total_invoices": aggregates["total_invoices"] or 0,
        "invoices_amount": aggregates["invoices_amount"] or 0,
        "cash_amount": aggregates["cash_amount"] or 0,
        "credit_amount": aggregates["credit_amount"] or 0,
    }


@required_permission("customer.delete_customer")
def customer_delete(request, customer_id):
    """Delete customer (soft delete)."""
    if request.method == "POST":
        customer = get_object_or_404(Customer, id=customer_id)

        if customer.pk == 1 or customer.phone_number == "3":
            messages.error(request, "The default Walk-in customer cannot be deleted.")
            return redirect("customer:home")

        customer.delete()  # This will use soft delete
        messages.success(request, "Customer deleted successfully!")
        return redirect("customer:home")

    return redirect("customer:home")


@required_permission("customer.add_customer")
def create_customer_ajax(request):
    """AJAX endpoint for creating customers via modal"""
    try:
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save()
            return JsonResponse(
                {
                    "success": True,
                    "message": "Customer created successfully",
                    "data": {"id": customer.id, "name": customer.name},
                }
            )
        return JsonResponse({"success": False, "message": str(form.errors)})
    except Exception:  # pylint: disable=broad-except
        logger.exception("Failed to create customer via AJAX")
        return JsonResponse(
            {"success": False, "message": "An error occurred. Please try again."}
        )


def get_customer_balance(request, pk):
    """
    AJAX endpoint to fetch the current credit balance for a customer.

    Args:
        request: The HTTP request object.
        pk (int): Customer primary key.

    Returns:
        JsonResponse: JSON object containing customer id, name, phone, and balance.
    """
    if not (
        request.user.has_perm("customer.view_customer")
        or request.user.has_perm("invoice.add_invoice")
        or request.user.has_perm("cart.view_cart")
    ):
        return JsonResponse({"error": "Permission denied"}, status=403)

    customer = get_object_or_404(Customer, pk=pk, is_deleted=False)
    summary = getattr(customer, "credit_summary", None)
    if not summary:
        summary = CustomerCreditSummary.update_or_create_summary(customer)

    return JsonResponse(
        {
            "success": True,
            "id": customer.id,
            "name": customer.name or "Unknown",
            "phone_number": customer.phone_number,
            "balance": float(summary.balance_amount),
        }
    )

