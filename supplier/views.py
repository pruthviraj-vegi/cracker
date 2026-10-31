"""
Views for the supplier app,
handling suppliers, invoices,
payments, and reporting.
"""

import json
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView, DeleteView, UpdateView

from base.decorators import required_permission, RequiredPermissionMixin
from base.getDates import getDates
from base.comparison import get_comparison_data
from base.utility import (
    build_search_filter,
    render_paginated_response,
    table_sorting,
)

from supplier.services import SupplierPaymentService

from .forms import SupplierForm, SupplierInvoiceForm, SupplierPaymentForm
from .models import MediaFile, Supplier, SupplierInvoice, SupplierPayment

logger = logging.getLogger(__name__)


def get_total_outstanding_balance():
    """Calculate the total outstanding balance for all suppliers."""
    total_all_invoiced = SupplierInvoice.objects.filter(is_deleted=False).aggregate(
        total=Coalesce(
            Sum("total_amount"),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
    )["total"]

    total_all_paid = SupplierPayment.objects.filter(is_deleted=False).aggregate(
        total=Coalesce(
            Sum("amount"),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
    )["total"]

    return (total_all_invoiced - total_all_paid).quantize(Decimal("0.01"))


@required_permission("supplier.view_dashboard")
def dashboard(request):
    """Supplier management dashboard with analytics and insights."""

    # Calculate full balance due (all invoices - all payments, regardless of status)
    # This matches the logic in Supplier.balance_due property
    total_outstanding = get_total_outstanding_balance()

    # Calculate total suppliers (static, doesn't change with date filter)
    total_suppliers = Supplier.objects.filter(is_deleted=False).count()

    context = {
        "total_outstanding": total_outstanding,
        "total_suppliers": total_suppliers,
    }
    return render(request, "supplier/dashboard.html", context)


@required_permission("supplier.view_dashboard")
def dashboard_fetch(request):
    """
    AJAX endpoint to fetch supplier dashboard data

    OPTIMIZED: Combines multiple aggregations into fewer queries and uses
    single-pass list comprehensions for percentage calculations.
    """
    date_filter = request.GET.get("date_filter", "this_month")
    start_date, end_date = getDates(request)

    # Filter invoices by date range (for period-based stats)
    invoices = SupplierInvoice.objects.filter(
        is_deleted=False, invoice_date__date__range=[start_date, end_date]
    ).select_related("supplier")

    payments = SupplierPayment.objects.filter(
        is_deleted=False, payment_date__date__range=[start_date, end_date]
    )

    # Calculate PERIOD-BASED totals in a single query
    invoice_metrics = invoices.aggregate(
        total_invoiced=Coalesce(
            Sum("total_amount"),
            Decimal("0"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
        total_invoices=Count("id"),
    )

    # Get period-based payments
    total_paid = payments.aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
    )["total"]

    # Calculate ALL-TIME totals (for "Total Outstanding" calculation) - not used in response but kept for reference
    # total_all_invoiced = SupplierInvoice.objects.filter(is_deleted=False).aggregate(...)
    # total_all_paid = SupplierPayment.objects.filter(is_deleted=False).aggregate(...)

    # Calculate metrics
    total_invoiced = invoice_metrics["total_invoiced"]
    total_invoices = invoice_metrics["total_invoices"]
    outstanding_balance = total_invoiced - total_paid

    # Calculate comparison data for line chart
    comparison_data = get_comparison_data(
        SupplierInvoice.objects.filter(is_deleted=False),
        date_filter,
        start_date,
        end_date,
        amount_field="total_amount",
    )

    # Invoice status breakdown (period-based)
    invoice_status_breakdown = (
        invoices.values("status")
        .annotate(
            count=Count("id"),
            amount=Coalesce(
                Sum("total_amount"),
                Decimal("0"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
        )
        .order_by("status")
    )

    # Invoice type breakdown (period-based)
    invoice_type_breakdown = (
        invoices.values("invoice_type")
        .annotate(
            count=Count("id"),
            amount=Coalesce(
                Sum("total_amount"),
                Decimal("0"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
        )
        .order_by("invoice_type")
    )

    # Supplier breakdown (period-based) - invoices purchased by supplier
    supplier_breakdown = (
        invoices.values("supplier__name")
        .annotate(
            count=Count("id"),
            amount=Coalesce(
                Sum("total_amount"),
                Decimal("0"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
        )
        .order_by("-amount")[:10]  # Top 10 suppliers by amount
    )

    # Prepare response data
    all_time_outstanding = get_total_outstanding_balance()
    stats = {
        "total_invoices": total_invoices,
        "total_invoiced": float(total_invoiced),
        "total_paid": float(total_paid),
        "outstanding_balance": float(outstanding_balance),
        "total_outstanding": float(all_time_outstanding),
        "net_amount": float(total_paid),
        "total_profit": float(outstanding_balance),
        "total_discount": float(Decimal("0")),
    }

    # Convert total_invoiced to float once for reuse
    total_invoiced_float = float(total_invoiced)

    # Invoice status data processing - single pass with list comprehension
    invoice_status_data = [
        {
            "payment_status": status["status"].replace("_", " ").title(),
            "count": status["count"],
            "amount": float(status["amount"]),
            "percentage": (
                round((float(status["amount"]) / total_invoiced_float * 100), 1)
                if total_invoiced_float > 0
                else 0
            ),
        }
        for status in invoice_status_breakdown
    ]

    # Supplier breakdown data processing - single pass with list comprehension
    supplier_list = list(supplier_breakdown)
    top10_total = float(sum(float(s["amount"]) for s in supplier_list))

    supplier_data = [
        {
            "supplier_name": supplier["supplier__name"] or "Unknown",
            "count": supplier["count"],
            "amount": float(supplier["amount"]),
            "percentage": (
                round((float(supplier["amount"]) / top10_total * 100), 1)
                if top10_total > 0
                else 0
            ),
        }
        for supplier in supplier_list
    ]

    # Invoice type data processing - single pass with list comprehension
    invoice_type_data = [
        {
            "category_name": inv_type["invoice_type"].replace("_", " ").title(),
            "invoice_type": inv_type["invoice_type"].replace("_", " ").title(),
            "label": inv_type["invoice_type"].replace("_", " ").title(),
            "count": inv_type["count"],
            "amount": float(inv_type["amount"]),
            "percentage": (
                round((float(inv_type["amount"]) / total_invoiced_float * 100), 1)
                if total_invoiced_float > 0
                else 0
            ),
        }
        for inv_type in invoice_type_breakdown
    ]

    return JsonResponse(
        {
            "success": True,
            "stats": stats,
            "payment_status_breakdown": invoice_status_data,
            "supplier_breakdown": supplier_data,
            "category_breakdown": invoice_type_data,
            "invoice_type_breakdown": invoice_type_data,
            "comparison_data": comparison_data,
            "date_range": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "filter": date_filter,
            },
        }
    )


@required_permission("supplier.view_supplier")
def home(request):
    """Supplier management main page with search, filter drawer, and sorting functionality."""
    cities = list(
        Supplier.objects.exclude(city__isnull=True)
        .exclude(city="")
        .values_list("city", flat=True)
        .distinct()
        .order_by("city")
    )
    slider_max_balance = 1200000

    context = {
        "cities": cities,
        "slider_max_balance": slider_max_balance,
    }
    return render(request, "supplier/home.html", context)


# Constants for AJAX fetch
SUPPLIERS_PER_PAGE = 25
VALID_SORT_FIELDS = {
    "id",
    "name",
    "created_at",
    "phone",
    "contact_person",
    "gstin",
    "balance_due",
    "annotated_balance_due",
}


def get_suppliers_data(request):
    """
    Get filtered and sorted suppliers data with advanced filter drawer support.

    OPTIMIZED:
    - Uses table_sorting utility for consistent sort handling
    - Annotates balance_due and last_invoice to prevent N+1 queries
    - Filters by status, balance due status, GST registration, balance range, city, and created date
    - Reduces queries from 77 to 2-3 regardless of supplier count
    """
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()
    balance_status = request.GET.get("balance_status", "").strip()
    gst_only = request.GET.get("gst_only", "").strip()
    city_filter = request.GET.get("city", "").strip()
    min_balance = request.GET.get("min_balance", "").strip()
    max_balance = request.GET.get("max_balance", "").strip()
    created_from = request.GET.get("created_from", "").strip()
    created_to = request.GET.get("created_to", "").strip()

    # Use table_sorting utility for consistent sort handling (returns a list)
    sort_fields = table_sorting(request, VALID_SORT_FIELDS, "-id")

    # Map old field names to new annotated names for backward compatibility
    sort_fields = [
        field.replace("balance_due", "annotated_balance_due") for field in sort_fields
    ]

    # Build search filters
    filters = build_search_filter(
        search_query,
        [
            # Contact information
            "name",
            "contact_person",
            "phone",
            "email",
            "gstin",
            # Address fields
            "first_line",
            "second_line",
            "city",
            "state",
            "pincode",
            "country",
        ],
    )

    # City filter
    if city_filter:
        filters &= Q(city__iexact=city_filter)

    # GST Registered Only
    if gst_only in ("1", "true", "on", True):
        filters &= Q(gstin__isnull=False) & ~Q(gstin="")

    # Created date range
    if created_from:
        try:
            d_from = datetime.strptime(created_from, "%Y-%m-%d").date()
            filters &= Q(created_at__date__gte=d_from)
        except ValueError:
            pass

    if created_to:
        try:
            d_to = datetime.strptime(created_to, "%Y-%m-%d").date()
            filters &= Q(created_at__date__lte=d_to)
        except ValueError:
            pass

    # Status filter (Active vs Inactive vs All)
    if status_filter == "inactive":
        suppliers = Supplier.all_objects.filter(filters, is_deleted=True)
    elif status_filter == "all":
        suppliers = Supplier.all_objects.filter(filters)
    else:
        # Default: active only
        suppliers = Supplier.objects.filter(filters)

    # Subqueries for balance_due calculation (used for both display and optional sorting)
    invoice_totals_subquery = (
        SupplierInvoice.objects.filter(supplier=OuterRef("pk"), is_deleted=False)
        .order_by()
        .values("supplier")
        .annotate(total=Sum("total_amount"))
        .values("total")
    )

    payment_totals_subquery = (
        SupplierPayment.objects.filter(supplier=OuterRef("pk"), is_deleted=False)
        .order_by()
        .values("supplier")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    # Subquery for last_invoice (earliest unpaid/partially paid invoice date)
    last_invoice_subquery = (
        SupplierInvoice.objects.filter(
            supplier=OuterRef("pk"),
            is_deleted=False,
            status__in=["UNPAID", "PARTIALLY_PAID"],
        )
        .order_by("invoice_date")
        .values("invoice_date")[:1]
    )

    # Always annotate to prevent N+1 queries from template accessing properties
    suppliers = suppliers.annotate(
        # Calculate invoice and payment totals
        total_invoiced=Coalesce(
            Subquery(
                invoice_totals_subquery[:1],
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
        total_paid=Coalesce(
            Subquery(
                payment_totals_subquery[:1],
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
        # Precompute balance_due (template uses annotated_balance_due to avoid property)
        annotated_balance_due=ExpressionWrapper(
            F("total_invoiced") - F("total_paid"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
        # Precompute last_invoice (template uses annotated_last_invoice to avoid property)
        annotated_last_invoice=Subquery(last_invoice_subquery),
    )

    # Filter by balance due status & range on annotated balance
    if balance_status == "outstanding":
        suppliers = suppliers.filter(annotated_balance_due__gt=0)
    elif balance_status == "cleared":
        suppliers = suppliers.filter(annotated_balance_due=0)
    elif balance_status == "advance":
        suppliers = suppliers.filter(annotated_balance_due__lt=0)

    if min_balance:
        try:
            suppliers = suppliers.filter(
                annotated_balance_due__gte=Decimal(min_balance)
            )
        except (InvalidOperation, ValueError):
            pass

    if max_balance:
        try:
            suppliers = suppliers.filter(
                annotated_balance_due__lte=Decimal(max_balance)
            )
        except (InvalidOperation, ValueError):
            pass

    return suppliers.order_by(*sort_fields)


@required_permission("supplier.view_supplier")
def fetch_suppliers(request):
    """AJAX endpoint to fetch suppliers with search, filter, sorting, and pagination."""

    suppliers = get_suppliers_data(request)

    return render_paginated_response(
        request,
        suppliers,
        "supplier/fetch.html",
        per_page=SUPPLIERS_PER_PAGE,
    )


@required_permission("supplier.view_supplierinvoice")
def fetch_supplier_invoices(request, pk):
    """AJAX: fetch invoices for a supplier with pagination and optional sorting."""
    supplier = get_object_or_404(Supplier, id=pk)

    valid_sort_fields = {
        "invoice_date",
        "total_amount",
        "sub_total",
        "status",
        "invoice_number",
    }

    valid_sorts = table_sorting(request, valid_sort_fields, "-invoice_date")

    queryset = (
        supplier.invoices.filter(is_deleted=False)
        .prefetch_related("media_files")
        .annotate(media_count=Count("media_files"))
        .order_by(*valid_sorts)
    )

    return render_paginated_response(
        request,
        queryset,
        "supplier/invoice/fetch.html",
        per_page=8,
        supplier=supplier,
    )


@required_permission("supplier.view_supplierpayment")
def fetch_supplier_payments(request, pk):
    """AJAX: fetch payments for a supplier with pagination and optional sorting."""
    supplier = get_object_or_404(Supplier, id=pk)

    valid_sort_fields = {
        "payment_date",
        "amount",
        "unallocated_amount",
        "id",
        "method",
    }

    valid_sorts = table_sorting(request, valid_sort_fields, "-payment_date")

    queryset = (
        supplier.payments_made.filter(is_deleted=False)
        .prefetch_related("media_files")
        .annotate(media_count=Count("media_files"))
        .order_by(*valid_sorts)
    )

    return render_paginated_response(
        request,
        queryset,
        "supplier/payment/fetch.html",
        per_page=8,
        supplier=supplier,
    )


@required_permission("supplier.view_supplier")
def supplier_detail(request, pk):
    """
    View supplier details with invoices and payments tables.

    OPTIMIZED:
    - Single aggregation query for all invoice metrics
    - Single aggregation query for all payment metrics
    - Removed unnecessary queryset fetching (tables load via AJAX)
    - Reduced queries from ~6 to ~3
    """
    supplier = get_object_or_404(Supplier, id=pk)

    # Calculate all invoice metrics in a single aggregation query
    invoice_metrics = supplier.invoices.filter(is_deleted=False).aggregate(
        total_count=Count("id"),
        total_amount=Coalesce(
            Sum("total_amount"),
            Decimal("0"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
        unpaid_count=Count("id", filter=Q(status__in=["UNPAID", "PARTIALLY_PAID"])),
    )

    # Calculate all payment metrics in a single aggregation query
    payment_metrics = supplier.payments_made.filter(is_deleted=False).aggregate(
        total_count=Count("id"),
        total_amount=Coalesce(
            Sum("amount"),
            Decimal("0"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
    )

    # Extract values from aggregation results
    invoice_count = invoice_metrics["total_count"]
    total_invoice_amount = invoice_metrics["total_amount"]
    unpaid_invoices_count = invoice_metrics["unpaid_count"]

    payment_count = payment_metrics["total_count"]
    total_payment_amount = payment_metrics["total_amount"]

    # Calculate outstanding amount
    outstanding_amount = total_invoice_amount - total_payment_amount

    context = {
        "supplier": supplier,
        # Counts for summary cards (no queryset evaluation needed)
        "invoice_count": invoice_count,
        "payment_count": payment_count,
        # Financial metrics
        "total_invoice_amount": total_invoice_amount,
        "unpaid_invoices_count": unpaid_invoices_count,
        "total_payment_amount": total_payment_amount,
        "outstanding_amount": outstanding_amount,
    }

    return render(request, "supplier/detail.html", context)


@required_permission("supplier.delete_supplierinvoice")
def delete_invoice(request, supplier_pk, invoice_pk):
    """Delete an invoice."""
    supplier = get_object_or_404(Supplier, id=supplier_pk)
    invoice = get_object_or_404(SupplierInvoice, id=invoice_pk, supplier=supplier)

    if request.method == "POST":
        invoice_number = invoice.invoice_number
        invoice.delete()
        messages.success(request, f"Invoice {invoice_number} deleted successfully!")
        return redirect("supplier:detail", pk=supplier_pk)

    context = {"supplier": supplier, "invoice": invoice}

    return render(request, "supplier/invoice/delete.html", context)


class CreateSupplier(RequiredPermissionMixin, CreateView):
    """View to create a new supplier."""

    model = Supplier
    form_class = SupplierForm
    template_name = "supplier/form.html"
    success_url = reverse_lazy("supplier:home")
    required_permission = "supplier.add_supplier"

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Supplier created successfully!")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Supplier"
        context["supplier"] = None  # For breadcrumb compatibility
        return context


class EditSupplier(RequiredPermissionMixin, UpdateView):
    """View to edit an existing supplier."""

    model = Supplier
    form_class = SupplierForm
    template_name = "supplier/form.html"
    success_url = reverse_lazy("supplier:home")
    required_permission = "supplier.change_supplier"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Edit Supplier"
        context["supplier"] = self.get_object()  # For breadcrumb compatibility
        return context

    def form_valid(self, form):
        messages.success(self.request, "Supplier updated successfully!")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class DeleteSupplier(RequiredPermissionMixin, DeleteView):
    """View to delete an existing supplier."""

    model = Supplier
    success_url = reverse_lazy("supplier:home")
    template_name = "supplier/delete.html"
    required_permission = "supplier.delete_supplier"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["supplier"] = self.get_object()
        return context

    def delete(self, request, *args, **kwargs):
        supplier = self.get_object()
        messages.success(request, f"Supplier '{supplier.name}' deleted successfully!")
        return super().delete(request, *args, **kwargs)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


# Payment Views
class CreatePayment(RequiredPermissionMixin, CreateView):
    """View to record a payment made to a supplier."""

    model = SupplierPayment
    form_class = SupplierPaymentForm
    template_name = "supplier/payment/form.html"
    required_permission = "supplier.add_supplierpayment"

    def get_success_url(self):
        return reverse_lazy("supplier:detail", kwargs={"pk": self.supplier.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Payment"
        context["supplier"] = self.supplier
        context["payment"] = None
        context["media_files"] = []
        # Most repeated payment amounts
        top_payments = (
            self.supplier.payments_made.filter(is_deleted=False)
            .values("amount")
            .annotate(count=Count("amount"))
            .order_by("-count", "-amount")[:5]
        )
        context["top_payments"] = [p["amount"] for p in top_payments]
        context["present_balance"] = self.supplier.balance_due
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["supplier"] = self.supplier
        return kwargs

    def form_valid(self, form):
        form.instance.supplier = self.supplier
        form.instance.created_by = self.request.user
        # Let super().form_valid() handle the save - it will trigger the signal correctly
        response = super().form_valid(form)

        # Save any uploaded attachments
        files = form.cleaned_data.get("attachments") or []
        for f in files:
            media = MediaFile(supplier_payment=self.object, media_file=f)
            media.full_clean()
            media.save()

        messages.success(
            self.request,
            f"Payment of {form.instance.amount} recorded successfully!",
        )
        return response

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

    def dispatch(self, request, *args, **kwargs):
        self.supplier = get_object_or_404(Supplier, id=kwargs["supplier_pk"])
        return super().dispatch(request, *args, **kwargs)


class EditPayment(RequiredPermissionMixin, UpdateView):
    """View to edit a payment record."""

    model = SupplierPayment
    form_class = SupplierPaymentForm
    template_name = "supplier/payment/form.html"
    pk_url_kwarg = "payment_pk"
    required_permission = "supplier.change_supplierpayment"

    def get_success_url(self):
        return reverse_lazy("supplier:detail", kwargs={"pk": self.supplier.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Edit Payment"
        context["supplier"] = self.supplier
        payment = self.get_object()
        context["payment"] = payment
        context["media_files"] = list(payment.media_files.all())

        # Get allocation information for warnings
        total_allocated = (
            payment.allocations.aggregate(total=Sum("amount_allocated"))["total"] or 0
        )
        context["total_allocated"] = total_allocated
        context["has_allocations"] = total_allocated > 0

        # Most repeated payment amounts
        top_payments = (
            self.supplier.payments_made.filter(is_deleted=False)
            .values("amount")
            .annotate(count=Count("amount"))
            .order_by("-count", "-amount")[:5]
        )
        context["top_payments"] = [p["amount"] for p in top_payments]
        context["present_balance"] = self.supplier.balance_due

        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["supplier"] = self.supplier
        return kwargs

    def form_valid(self, form):
        # Save the payment - signals will handle reallocation automatically
        response = super().form_valid(form)

        # Save any uploaded attachments
        files = form.cleaned_data.get("attachments") or []
        for f in files:
            media = MediaFile(supplier_payment=self.object, media_file=f)
            media.full_clean()
            media.save()

        messages.success(
            self.request,
            "Payment updated successfully!",
        )
        return response

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(
            self.request, "Invalid form submission. Please check your inputs."
        )
        return super().form_invalid(form)

    def dispatch(self, request, *args, **kwargs):
        self.supplier = get_object_or_404(Supplier, id=kwargs["supplier_pk"])
        return super().dispatch(request, *args, **kwargs)


class CreateInvoice(RequiredPermissionMixin, CreateView):
    """View to create a new supplier invoice."""

    model = SupplierInvoice
    form_class = SupplierInvoiceForm
    template_name = "supplier/invoice/form.html"
    required_permission = "supplier.add_supplierinvoice"

    def get_success_url(self):
        return reverse_lazy("supplier:detail", kwargs={"pk": self.supplier.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Invoice"
        context["supplier"] = self.supplier
        context["invoice"] = None
        context["media_files"] = []
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["supplier"] = self.supplier
        return kwargs

    def form_valid(self, form):
        form.instance.supplier = self.supplier
        form.instance.created_by = self.request.user
        form.instance.total_amount = form.cleaned_data["total_amount"]
        response = super().form_valid(form)

        # Save any uploaded attachments
        files = form.cleaned_data.get("attachments") or []
        for f in files:
            media = MediaFile(supplier_invoice=self.object, media_file=f)
            media.full_clean()
            media.save()

        messages.success(
            self.request,
            f"Invoice {form.instance.invoice_number} created successfully!",
        )
        return response

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

    def dispatch(self, request, *args, **kwargs):
        self.supplier = get_object_or_404(Supplier, id=kwargs["supplier_pk"])
        return super().dispatch(request, *args, **kwargs)


class EditInvoice(RequiredPermissionMixin, UpdateView):
    """View to edit an existing supplier invoice."""

    model = SupplierInvoice
    form_class = SupplierInvoiceForm
    template_name = "supplier/invoice/form.html"
    pk_url_kwarg = "invoice_pk"  # Use invoice_pk instead of pk
    required_permission = "supplier.change_supplierinvoice"

    def get_success_url(self):
        return reverse_lazy("supplier:detail", kwargs={"pk": self.supplier.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Edit Invoice"
        context["supplier"] = self.supplier
        invoice = self.get_object()
        context["invoice"] = invoice
        context["media_files"] = list(invoice.media_files.all())
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["supplier"] = self.supplier
        return kwargs

    def form_valid(self, form):
        form.instance.total_amount = form.cleaned_data["total_amount"]
        response = super().form_valid(form)

        # Save any uploaded attachments
        files = form.cleaned_data.get("attachments") or []
        for f in files:
            media = MediaFile(supplier_invoice=self.object, media_file=f)
            media.full_clean()
            media.save()

        messages.success(
            self.request,
            f"Invoice {form.instance.invoice_number} updated successfully!",
        )
        return response

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

    def dispatch(self, request, *args, **kwargs):
        self.supplier = get_object_or_404(Supplier, id=kwargs["supplier_pk"])
        return super().dispatch(request, *args, **kwargs)


@required_permission("supplier.delete_supplierpayment")
def delete_payment(request, supplier_pk, payment_pk):
    """Delete a payment."""
    supplier = get_object_or_404(Supplier, id=supplier_pk)
    payment = get_object_or_404(SupplierPayment, id=payment_pk, supplier=supplier)

    if request.method == "POST":
        payment_amount = payment.amount
        payment.delete()
        messages.success(request, f"Payment of {payment_amount} deleted successfully!")
        return redirect("supplier:detail", pk=supplier_pk)

    context = {"supplier": supplier, "payment": payment}

    return render(request, "supplier/payment/delete.html", context)


def get_opening_balance(supplier, start_date):
    """
    Get the opening balance for a supplier at a specific date.

    OPTIMIZED: Removed unnecessary ordering and uses Coalesce for null handling.
    """
    invoice_filters = Q(is_deleted=False) & Q(invoice_date__date__lt=start_date)
    payment_filters = Q(is_deleted=False) & Q(payment_date__date__lt=start_date)

    # Aggregate without ordering (ordering not needed for aggregation)
    total_invoiced = supplier.invoices.filter(invoice_filters).aggregate(
        total=Coalesce(
            Sum("total_amount"),
            Decimal("0"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
    )["total"]

    total_paid = supplier.payments_made.filter(payment_filters).aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
    )["total"]

    return total_invoiced - total_paid


def get_supplier_report_data(supplier, date_range):
    """Get processed ledger data for a supplier within a date range."""
    # Fetch only necessary fields

    opening_balance = get_opening_balance(supplier, date_range[0])

    invoices = (
        supplier.invoices.filter(is_deleted=False, invoice_date__date__range=date_range)
        .only("id", "invoice_date", "total_amount", "invoice_number", "status", "notes")
        .order_by("invoice_date")
    )

    payments = (
        supplier.payments_made.filter(
            is_deleted=False, payment_date__date__range=date_range
        )
        .only("id", "payment_date", "amount", "transaction_id")
        .order_by("payment_date")
    )

    # Build transactions list using list comprehension
    transactions = []

    # Add invoices
    transactions.extend(
        [
            {
                "date": invoice.invoice_date,
                "type": "invoice",
                "invoice_id": invoice.id,
                "credit": invoice.total_amount,
                "debit": Decimal("0"),
                "description": invoice.invoice_number,
                "status": invoice.status,
                "reference": invoice.invoice_number,
                "notes": invoice.notes or "",
            }
            for invoice in invoices
        ]
    )

    # Add payments
    transactions.extend(
        [
            {
                "date": payment.payment_date,
                "type": "payment",
                "payment_id": payment.id,
                "credit": Decimal("0"),
                "debit": payment.amount,
                "description": f"Payment #{payment.id}",
                "status": "",
                "reference": payment.transaction_id or "",
                "notes": "",
            }
            for payment in payments
        ]
    )

    # Sort by date (oldest first)
    transactions.sort(key=lambda x: x["date"])

    # Single-pass calculation: running balance and totals
    running_balance = opening_balance
    total_invoiced = Decimal("0")
    total_paid = Decimal("0")

    for transaction in transactions:
        credit = transaction["credit"]
        debit = transaction["debit"]

        running_balance += credit - debit
        transaction["running_balance"] = running_balance

        total_invoiced += credit
        total_paid += debit

    outstanding_balance = total_invoiced - total_paid

    context = {
        "transactions": transactions,
        "total_invoiced": total_invoiced,
        "total_paid": total_paid,
        "outstanding_balance": outstanding_balance,
        "opening_balance": opening_balance,
    }

    return context


def supplier_report(request, pk):
    """Generate a comprehensive report showing all purchases and payments for a supplier sorted by date."""
    supplier = get_object_or_404(Supplier, id=pk)

    # Get date filter from request (default value)
    date_filter = request.GET.get("date_filter", "this_month")

    # Only pass supplier details - all transaction data will be loaded via AJAX
    context = {
        "supplier": supplier,
        "date_filter": date_filter,
    }

    return render(request, "supplier/report.html", context)


def supplier_report_fetch(request, pk):
    """AJAX endpoint to fetch supplier report data - optimized version"""

    supplier = get_object_or_404(Supplier, id=pk)
    start_date, end_date = getDates(request)

    # Get opening balance

    # Define filters
    date_range = [start_date, end_date]

    # Get report data
    context = get_supplier_report_data(supplier, date_range)

    # Render paginated table
    paginated_data = render_paginated_response(
        request=request,
        queryset=context["transactions"],
        table_template="supplier/report/fetch.html",
        per_page=20,
        supplier=supplier,
        opening_balance=context["opening_balance"],
        start_date=start_date,
    )

    # render_paginated_response returns a JsonResponse, we need to get its content

    paginated_content = json.loads(paginated_data.content.decode("utf-8"))

    return JsonResponse(
        {
            "success": True,
            "total_invoiced": float(context["total_invoiced"]),
            "total_paid": float(context["total_paid"]),
            "outstanding_balance": float(context["outstanding_balance"]),
            "opening_balance": float(context["opening_balance"]),
            "transaction_count": len(context["transactions"]),
            "table_html": paginated_content.get("html", ""),
            "pagination": paginated_content.get("pagination", ""),
        }
    )


def auto_reallocate(request, pk):
    """
    Auto reallocate payments using FIFO method.

    Delegates to SupplierPaymentService.reallocate() which is the single
    source of truth for payment allocation logic.
    """

    supplier = get_object_or_404(Supplier, id=pk)

    SupplierPaymentService.reallocate(supplier)

    messages.success(
        request,
        f"Successfully reallocated payments for {supplier.name} using FIFO method.",
    )
    return redirect("supplier:detail", pk=pk)


# ─── Media File Views ─────────────────────────────────────────────────────────


@required_permission("supplier.delete_supplierinvoice")
def delete_invoice_media(request, supplier_pk, invoice_pk, media_pk):
    """AJAX: Delete a MediaFile attached to a SupplierInvoice."""
    if request.method != "POST":
        return JsonResponse(
            {"success": False, "error": "Method not allowed."}, status=405
        )

    media = get_object_or_404(MediaFile, pk=media_pk, supplier_invoice_id=invoice_pk)
    # Remove the physical file from disk before deleting the record
    if media.media_file and media.media_file.storage.exists(media.media_file.name):
        media.media_file.delete(save=False)
    media.delete()
    return JsonResponse({"success": True})


@required_permission("supplier.delete_supplierpayment")
def delete_payment_media(request, supplier_pk, payment_pk, media_pk):
    """AJAX: Delete a MediaFile attached to a SupplierPayment."""
    if request.method != "POST":
        return JsonResponse(
            {"success": False, "error": "Method not allowed."}, status=405
        )

    media = get_object_or_404(MediaFile, pk=media_pk, supplier_payment_id=payment_pk)
    if media.media_file and media.media_file.storage.exists(media.media_file.name):
        media.media_file.delete(save=False)
    media.delete()
    return JsonResponse({"success": True})
