"""Invoice views for dashboard, CRUD operations, and search."""

import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib import messages
from django.db import transaction
from django.db.models import (
    Case,
    Count,
    DecimalField,
    F,
    IntegerField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, Coalesce
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View

from base.comparison import get_comparison_data, get_period_data
from base.getDates import getDates
from base.utility import (
    build_search_filter,
    get_periodic_data,
    get_period_label,
    render_paginated_response,
    table_sorting,
)
from base.decorators import required_permission, RequiredPermissionMixin, query_debugger

from cart.models import Cart
from customer.forms import CustomerForm
from customer.models import Customer
from inventory.services import InventoryService


from invoice.choices import PaymentStatusChoices, RefundStatusChoices
from invoice.form import InvoiceForm
from invoice.models import Invoice, InvoiceItem, ReturnInvoice, ReturnInvoiceItem
from setting.models import ShopDetails, ReportConfiguration


logger = logging.getLogger(__name__)


@required_permission("invoice.view_dashboard")
def invoice_dashboard(request):
    """Invoice dashboard with date filtering and metrics"""

    return render(request, "invoice/dashboard.html")


@required_permission("invoice.view_dashboard")
def invoice_dashboard_fetch(request):
    """
    AJAX endpoint to fetch dashboard data

    Optimizations:
    - Reduced database queries using aggregations
    - Used Coalesce for cleaner null handling
    - Consolidated related queries
    - Improved readability with better variable names
    """

    # Get date filter and range
    date_filter = request.GET.get("date_filter", "this_month")
    start_date, end_date = getDates(request)

    # Base queryset: all invoices created in this period (excluding VOID)
    all_invoices = Invoice.objects.filter(
        invoice_date__date__range=[start_date, end_date]
    ).exclude(payment_status=PaymentStatusChoices.VOID)

    # Invoices that were active during this period (Closed-window rule):
    # An invoice is active for this period if it was never cancelled, OR if its cancellation
    # happened AFTER this period closed (cancelled_at__date > end_date).
    invoices = all_invoices.filter(
        Q(is_cancelled=False) | Q(cancelled_at__date__gt=end_date)
    )

    # Metrics for invoices billed in this period
    gross_metrics = all_invoices.aggregate(
        total_invoices=Count("id"),
        gross_total_amount=Coalesce(Sum("amount"), Decimal("0")),
    )
    active_metrics = invoices.aggregate(
        active_count=Count("id"),
        active_gross_amount=Coalesce(Sum("amount"), Decimal("0")),
        total_discount=Coalesce(Sum("discount_amount"), Decimal("0")),
        total_paid=Coalesce(Sum("paid_amount"), Decimal("0")),
    )

    # Cancelled metrics: based on WHEN the cancellation happened (cancelled_at).
    # This records all cancellations executed in this period regardless of when billed.
    cancelled_metrics = Invoice.objects.filter(
        cancelled_at__date__range=[start_date, end_date],
        is_cancelled=True,
    ).aggregate(
        total_cancelled_amount=Coalesce(Sum("amount"), Decimal("0")),
        total_cancelled_invoices=Count("id"),
    )

    # Return metrics: based on return_date (when return was executed),
    # counting approved/completed returns and excluding draft/rejected/cancelled
    return_metrics = ReturnInvoice.objects.filter(
        return_date__date__range=[start_date, end_date],
        invoice__is_cancelled=False,
        status__in=[
            RefundStatusChoices.APPROVED,
            RefundStatusChoices.PROCESSING,
            RefundStatusChoices.COMPLETED,
        ],
    ).aggregate(
        total_return_amount=Coalesce(Sum("refund_amount"), Decimal("0"))
    )

    metrics = {
        "total_invoices": gross_metrics["total_invoices"],
        "gross_total_amount": gross_metrics["gross_total_amount"],
        "active_count": active_metrics["active_count"],
        "active_gross_amount": active_metrics["active_gross_amount"],
        "total_discount": active_metrics["total_discount"],
        "total_paid": active_metrics["total_paid"],
        "total_cancelled_amount": cancelled_metrics["total_cancelled_amount"],
        "total_cancelled_invoices": cancelled_metrics["total_cancelled_invoices"],
    }

    # 1. Profit from items billed on invoices active in this period
    billed_items_profit = (
        InvoiceItem.objects.filter(
            invoice__in=invoices,
            unit_price__isnull=False,
            purchase_price__isnull=False,
        ).aggregate(
            total_profit=Coalesce(
                Sum(
                    (F("unit_price") - F("purchase_price")) * F("quantity"),
                    output_field=DecimalField(),
                ),
                Decimal("0"),
            )
        )
    )["total_profit"]

    # 2. Profit lost from returns executed in this period (event date basis)
    returned_profit_loss = (
        ReturnInvoiceItem.objects.filter(
            return_invoice__return_date__date__range=[start_date, end_date],
            return_invoice__status__in=[
                RefundStatusChoices.APPROVED,
                RefundStatusChoices.PROCESSING,
                RefundStatusChoices.COMPLETED,
            ],
            return_invoice__invoice__is_cancelled=False,
            quantity_returned__gt=0,
            original_invoice_item__unit_price__isnull=False,
            original_invoice_item__purchase_price__isnull=False,
        ).aggregate(
            lost_profit=Coalesce(
                Sum(
                    (
                        F("original_invoice_item__unit_price")
                        - F("original_invoice_item__purchase_price")
                    )
                    * F("quantity_returned"),
                    output_field=DecimalField(),
                ),
                Decimal("0"),
            )
        )
    )["lost_profit"]

    # 3. Profit lost from past invoices cancelled in this period
    past_cancelled_profit_loss = (
        InvoiceItem.objects.filter(
            invoice__cancelled_at__date__range=[start_date, end_date],
            invoice__is_cancelled=True,
            invoice__invoice_date__date__lt=start_date,
            unit_price__isnull=False,
            purchase_price__isnull=False,
        ).aggregate(
            lost_profit=Coalesce(
                Sum(
                    (F("unit_price") - F("purchase_price")) * F("quantity"),
                    output_field=DecimalField(),
                ),
                Decimal("0"),
            )
        )
    )["lost_profit"]

    # Extract metrics
    total_amount = metrics["gross_total_amount"]
    active_gross_amount = metrics["active_gross_amount"]
    active_count = metrics["active_count"]
    total_discount = metrics["total_discount"]
    total_paid = metrics["total_paid"]
    total_return_amount = return_metrics["total_return_amount"]
    total_cancelled_amount = metrics["total_cancelled_amount"]

    total_profit = max(
        Decimal("0"),
        billed_items_profit - total_discount - returned_profit_loss - past_cancelled_profit_loss,
    )

    # Net billed on active invoices in this period
    active_billed_net = max(Decimal("0"), active_gross_amount - total_discount)

    # Invoices billed in a past period that were cancelled in this period
    past_cancelled_amount = (
        Invoice.objects.filter(
            cancelled_at__date__range=[start_date, end_date],
            is_cancelled=True,
            invoice_date__date__lt=start_date,
        ).aggregate(
            total=Coalesce(Sum(F("amount") - F("discount_amount")), Decimal("0"))
        )
    )["total"]

    # Net Realized Revenue (Day-book closed-window basis):
    # Active net billed revenue in this period minus returns executed in this period
    # minus cancellations of past invoices executed in this period.
    net_amount = max(
        Decimal("0"),
        active_billed_net - total_return_amount - past_cancelled_amount,
    )

    # Outstanding due on active invoices billed in this period
    outstanding_amount = max(Decimal("0"), active_billed_net - total_paid)

    # Calculate margin percentage (Profit / Net Revenue * 100)
    margin_percentage = (
        (total_profit / net_amount * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if net_amount > 0
        else Decimal("0")
    )

    # Calculate Average Order Value (AOV) based on active billed invoices
    aov = (
        (active_billed_net / active_count).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if active_count > 0
        else Decimal("0")
    )

    # Calculate Recovery Rate (% of active billed net revenue collected as Paid)
    recovery_rate = (
        (total_paid / active_billed_net * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        if active_billed_net > 0
        else Decimal("0")
    )

    # Get comparison data for line chart
    base_qs = Invoice.objects.filter(is_cancelled=False).exclude(
        payment_status__in=[PaymentStatusChoices.VOID, PaymentStatusChoices.CANCELLED]
    )
    comparison_data = get_comparison_data(base_qs, date_filter, start_date, end_date)

    # Payment status breakdown with annotations
    payment_status_breakdown = list(
        invoices.values("payment_status")
        .annotate(count=Count("id"), amount=Coalesce(Sum("amount"), Decimal("0")))
        .order_by("payment_status")
    )

    # Payment type breakdown with annotations
    payment_type_breakdown = list(
        invoices.values("payment_type")
        .annotate(count=Count("id"), amount=Coalesce(Sum("amount"), Decimal("0")))
        .order_by("payment_type")
    )

    # Cash vs Credit split computation
    cash_amount = Decimal("0")
    credit_amount = Decimal("0")
    for pt in payment_type_breakdown:
        p_type = str(pt.get("payment_type", "")).upper()
        if p_type == "CASH":
            cash_amount = pt.get("amount", Decimal("0"))
        elif p_type == "CREDIT":
            credit_amount = pt.get("amount", Decimal("0"))

    active_type_total = cash_amount + credit_amount
    cash_percentage = (
        (cash_amount / active_type_total * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        if active_type_total > 0
        else Decimal("0")
    )
    credit_percentage = (
        (credit_amount / active_type_total * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        if active_type_total > 0
        else Decimal("0")
    )

    # Category breakdown from invoice items active in this period
    category_breakdown = list(
        InvoiceItem.objects.filter(
            invoice__in=invoices,
        )
        .select_related("product_variant__product__category")
        .values("product_variant__product__category__name")
        .annotate(
            count=Count("id"),
            amount=Coalesce(
                Sum(F("unit_price") * F("quantity"), output_field=DecimalField()),
                Decimal("0"),
            ),
        )
        .order_by("-count")
    )

    # Build stats dictionary
    stats = {
        "total_invoices": metrics["total_invoices"],
        "total_amount": float(total_amount),
        "total_discount": float(total_discount),
        "total_paid": float(total_paid),
        "net_amount": float(net_amount),
        "outstanding_amount": float(outstanding_amount),
        "total_profit": float(total_profit),
        "margin_percentage": float(margin_percentage),
        "total_return_amount": float(total_return_amount),
        "total_cancelled_amount": float(total_cancelled_amount),
        "total_cancelled_invoices": metrics["total_cancelled_invoices"],
        "aov": float(aov),
        "recovery_rate": float(recovery_rate),
        "cash_amount": float(cash_amount),
        "credit_amount": float(credit_amount),
        "cash_percentage": float(cash_percentage),
        "credit_percentage": float(credit_percentage),
    }

    # Process payment status breakdown
    payment_status_data = _process_breakdown_data(
        payment_status_breakdown, active_gross_amount, "payment_status"
    )

    # Process payment type breakdown
    payment_type_data = _process_breakdown_data(
        payment_type_breakdown, active_gross_amount, "payment_type"
    )

    # Process category breakdown
    category_total = sum(float(cat["amount"]) for cat in category_breakdown)
    category_data = _process_category_data(category_breakdown, category_total)

    # Return response
    return JsonResponse(
        {
            "success": True,
            "stats": stats,
            "payment_status_breakdown": payment_status_data,
            "payment_type_breakdown": payment_type_data,
            "category_breakdown": category_data,
            "comparison_data": comparison_data,
            "date_range": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "filter": date_filter,
            },
        }
    )


def _process_breakdown_data(breakdown_list, total_amount, field_name):
    """
    Helper function to process payment status/type breakdown data

    Args:
        breakdown_list: List of breakdown dictionaries
        total_amount: Total amount for percentage calculation
        field_name: Name of the field (payment_status or payment_type)

    Returns:
        List of processed breakdown data with percentages
    """
    processed_data = []
    total_amount_float = float(total_amount)

    for item in breakdown_list:
        amount = float(item["amount"])
        percentage = (
            (amount / total_amount_float * 100) if total_amount_float > 0 else 0
        )

        processed_data.append(
            {
                field_name: item[field_name].title(),
                "count": item["count"],
                "amount": amount,
                "percentage": round(percentage, 1),
            }
        )

    return processed_data


def _process_category_data(category_breakdown, category_total):
    """
    Helper function to process category breakdown data

    Args:
        category_breakdown: List of category dictionaries
        category_total: Total amount for percentage calculation

    Returns:
        List of processed category data with percentages
    """
    category_data = []

    for category in category_breakdown:
        category_name = (
            category["product_variant__product__category__name"] or "Uncategorized"
        )
        category_amount = float(category["amount"])
        percentage = (
            (category_amount / category_total * 100) if category_total > 0 else 0
        )

        category_data.append(
            {
                "category_name": category_name,
                "count": category["count"],
                "amount": category_amount,
                "percentage": round(percentage, 1),
            }
        )

    return category_data


# ALTERNATIVE: If you need to fill in missing dates with zeros
def get_period_data_with_zeros(invoices, start_date, end_date, period_type):
    """
    Same as get_period_data but fills in missing dates with zero values

    Use this version if you need a data point for every period even when
    there are no invoices (e.g., for continuous chart lines)
    """

    if period_type == "daily":
        # Single day - same as original
        aggregated = invoices.aggregate(
            total_amount=Coalesce(Sum("amount"), Decimal("0")),
            total_invoices=Count("id"),
        )

        return [
            {
                "date": start_date.strftime("%Y-%m-%d"),
                "amount": float(aggregated["total_amount"]),
                "invoices": aggregated["total_invoices"],
            }
        ]

    elif period_type == "monthly":
        # Get daily data from database
        daily_data = (
            invoices.annotate(day=TruncDate("invoice_date"))
            .values("day")
            .annotate(
                amount=Coalesce(Sum("amount"), Decimal("0")), invoices=Count("id")
            )
        )

        # Create lookup dictionary
        data_dict = {
            item["day"]: {"amount": float(item["amount"]), "invoices": item["invoices"]}
            for item in daily_data
        }

        # Fill in all dates
        result = []
        current_date = start_date
        while current_date <= end_date:
            if current_date in data_dict:
                result.append(
                    {
                        "date": current_date.strftime("%Y-%m-%d"),
                        **data_dict[current_date],
                    }
                )
            else:
                result.append(
                    {
                        "date": current_date.strftime("%Y-%m-%d"),
                        "amount": 0.0,
                        "invoices": 0,
                    }
                )
            current_date += timedelta(days=1)

        return result

    elif period_type == "quarterly":
        # Get weekly data from database
        weekly_data = (
            invoices.annotate(week=TruncWeek("invoice_date"))
            .values("week")
            .annotate(
                amount=Coalesce(Sum("amount"), Decimal("0")), invoices=Count("id")
            )
        )

        # Create lookup dictionary
        data_dict = {
            item["week"]: {
                "amount": float(item["amount"]),
                "invoices": item["invoices"],
            }
            for item in weekly_data
        }

        # Fill in all weeks
        result = []
        current_date = start_date
        # Adjust to start of week (Monday)
        current_date = current_date - timedelta(days=current_date.weekday())

        while current_date <= end_date:
            if current_date in data_dict:
                result.append(
                    {
                        "date": current_date.strftime("%Y-%m-%d"),
                        **data_dict[current_date],
                    }
                )
            else:
                result.append(
                    {
                        "date": current_date.strftime("%Y-%m-%d"),
                        "amount": 0.0,
                        "invoices": 0,
                    }
                )
            current_date += timedelta(weeks=1)

        return result

    else:  # yearly
        # Get monthly data from database
        monthly_data = (
            invoices.annotate(month=TruncMonth("invoice_date"))
            .values("month")
            .annotate(
                amount=Coalesce(Sum("amount"), Decimal("0")), invoices=Count("id")
            )
        )

        # Create lookup dictionary
        data_dict = {
            item["month"]: {
                "amount": float(item["amount"]),
                "invoices": item["invoices"],
            }
            for item in monthly_data
        }

        # Fill in all months
        result = []
        current_date = start_date.replace(day=1)

        while current_date <= end_date:
            if current_date in data_dict:
                result.append(
                    {
                        "date": current_date.strftime("%Y-%m-%d"),
                        **data_dict[current_date],
                    }
                )
            else:
                result.append(
                    {
                        "date": current_date.strftime("%Y-%m-%d"),
                        "amount": 0.0,
                        "invoices": 0,
                    }
                )

            # Move to next month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)

        return result


# Create your views here.

VALID_SORT_FIELDS = {
    "id",
    "invoice_number",
    "customer__name",
    "amount",
    "payment_status",
    "payment_type",
    "invoice_date",
    "due_date",
    "created_at",
    "created_by__first_name",
    "sold_by__username",
    "created_by__username",
}


@required_permission("invoice.view_invoice")
def invoice_home(request):
    """Invoice management main page with search, filter drawer, and sorting functionality."""
    financial_years = (
        Invoice.objects.values_list("financial_year", flat=True)
        .distinct()
        .filter(financial_year__isnull=False)
        .order_by("-financial_year")
    )
    # Dynamic slider max amount calculation
    stats = Invoice.objects.aggregate(
        max_amt=Coalesce(Max("amount"), Value(Decimal("100000")))
    )
    raw_max_amt = float(stats["max_amt"] or 100000)
    slider_max_amount = max(10000, int((raw_max_amt + 9999) // 10000) * 10000)

    context = {
        "payment_type_choices": Invoice.PaymentType.choices,
        "bill_types": Invoice.Invoice_type.choices,
        "payment_status_choices": Invoice.PaymentStatus.choices,
        "financial_years": financial_years,
        "slider_max_amount": slider_max_amount,
    }
    return render(request, "invoice/home.html", context)


def get_data(request):
    """Build filtered and sorted invoice queryset from request params with drawer filters."""
    # Get search and filter parameters
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()
    payment_type_filter = request.GET.get("payment_type", "").strip()
    bill_types_filter = request.GET.get("bill_types", "").strip()
    financial_year = request.GET.get("financial_year", "").strip()
    is_cancelled = request.GET.get("is_cancelled", "").strip()
    min_amount = request.GET.get("min_amount", "").strip()
    max_amount = request.GET.get("max_amount", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    due_date_from = request.GET.get("due_date_from", "").strip()
    due_date_to = request.GET.get("due_date_to", "").strip()
    sort_by = request.GET.get("sort", "-id").strip()

    # Apply search filter
    filters = build_search_filter(
        search_query,
        [
            "invoice_number",
            "customer__name",
            "customer__phone_number",
            "customer__address",
            "notes",
        ],
    )

    # Apply status filter
    if status_filter:
        if status_filter == "CANCELLED":
            filters &= Q(is_cancelled=True)
        else:
            filters &= Q(payment_status=status_filter)

    # Cancelled only toggle
    if is_cancelled in ("1", "true", "on", True):
        filters &= Q(is_cancelled=True)

    # Apply payment type filter
    if payment_type_filter:
        filters &= Q(payment_type=payment_type_filter)

    # Apply bill types filter
    if bill_types_filter:
        filters &= Q(invoice_type=bill_types_filter)

    # Apply financial year filter
    if financial_year:
        filters &= Q(financial_year=financial_year)

    # Apply amount range
    if min_amount:
        try:
            filters &= Q(amount__gte=Decimal(min_amount))
        except (InvalidOperation, ValueError):
            pass

    if max_amount:
        try:
            filters &= Q(amount__lte=Decimal(max_amount))
        except (InvalidOperation, ValueError):
            pass

    # Apply invoice date range
    if date_from:
        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
            filters &= Q(invoice_date__date__gte=d_from)
        except ValueError:
            pass

    if date_to:
        try:
            d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
            filters &= Q(invoice_date__date__lte=d_to)
        except ValueError:
            pass

    # Apply due date range
    if due_date_from:
        try:
            d_due_from = datetime.strptime(due_date_from, "%Y-%m-%d").date()
            filters &= Q(due_date__date__gte=d_due_from)
        except ValueError:
            pass

    if due_date_to:
        try:
            d_due_to = datetime.strptime(due_date_to, "%Y-%m-%d").date()
            filters &= Q(due_date__date__lte=d_due_to)
        except ValueError:
            pass

    invoices = Invoice.objects.select_related("customer", "sold_by").filter(filters)

    # ---------------- SORTING MAP ----------------
    sort_map = {
        "gst_bills": ("invoice_type", Invoice.Invoice_type.GST),
        "cash_bills": ("invoice_type", Invoice.Invoice_type.CASH),
    }

    # Special type sorting
    if sort_by in sort_map:
        field, value = sort_map[sort_by]
        invoices = invoices.filter(**{field: value}).order_by("-invoice_date")

    # Validate sort field
    final_order_by = table_sorting(request, VALID_SORT_FIELDS, "-invoice_date")
    invoices = invoices.order_by(*final_order_by)

    return invoices


@required_permission("invoice.view_invoice")
def fetch_invoices(request):
    """AJAX endpoint to fetch invoices with search, filter, and pagination."""
    invoices = get_data(request)

    return render_paginated_response(
        request,
        invoices,
        "invoice/fetch.html",
    )


class CreateInvoice(RequiredPermissionMixin, View):
    """Create a new invoice from a cart."""

    template_name = "invoice/form.html"
    form_class = InvoiceForm
    required_permission = "invoice.add_invoice"

    def get(self, request, pk):
        """Display the invoice creation form for a given cart."""
        cart = get_object_or_404(Cart, id=pk)
        cart_total = cart.total_amount  # cache to avoid repeated DB aggregate
        if int(cart_total) <= 0:
            messages.error(request, "Cart is empty")
            return redirect("cart:get_cart_data", pk=cart.id)
        form = self.form_class(
            initial={
                "payment_type": Invoice.PaymentType.CASH,
                "amount": cart_total,
                "due_date": timezone.now() + timedelta(days=30),
            }
        )
        context = {
            "cart": cart,
            "form": form,
            "title": "Create Invoice",
            "customer_form": CustomerForm(),
            "default_customer": Customer.get_default_customer(),
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        """Process invoice creation from cart items."""
        cart = get_object_or_404(Cart, id=pk)
        cart_total = cart.total_amount  # cache to avoid repeated DB aggregate
        if int(cart_total) <= 0:
            messages.error(request, "Cart is empty")
            return redirect("cart:get_cart_data", pk=cart.id)
        form = self.form_class(request.POST)
        if form.is_valid():
            with transaction.atomic():
                invoice = form.save(commit=False)
                invoice.cart_no = cart.id
                invoice.amount = cart_total
                invoice.modified_by = request.user
                invoice.created_by = request.user
                invoice.save()

                for item in cart.cart_items.select_related(
                    "product_variant__product"
                ).all():
                    invoice_item = InvoiceItem.objects.create(
                        invoice=invoice,
                        product_variant=item.product_variant,
                        quantity=item.quantity,
                        unit_price=item.price,
                        purchase_price=item.product_variant.purchase_price,
                        mrp=item.product_variant.mrp,
                        commission_percentage=item.product_variant.commission_percentage,
                    )
                    InventoryService.sale(
                        variant=item.product_variant,
                        quantity_sold=item.quantity,
                        user=request.user,
                        notes=(
                            f"Invoice {invoice.invoice_number}"
                            f" - {item.product_variant.product.name}"
                        ),
                        invoice_item=invoice_item,
                    )

                cart.delete()
                messages.success(request, "Invoice created successfully")
                shop_details = ShopDetails.get_active()
                report_config = ReportConfiguration.get_default_config(
                    ReportConfiguration.ReportType.INVOICE
                )
                is_direct_print_enabled = bool(
                    report_config and report_config.is_direct_print_enabled
                ) or bool(
                    shop_details and getattr(shop_details, "is_direct_print_enabled", False)
                )
                return render(
                    request,
                    "intermediate_page.html",
                    {
                        "invoice_no": invoice.id,
                        "shop_details": shop_details,
                        "report_config": report_config,
                        "is_direct_print_enabled": is_direct_print_enabled,
                    },
                )

        else:
            context = {"cart": cart, "form": form, "title": "Create Invoice"}
            logger.error("Form invalid: %s", form.errors)
            return render(request, self.template_name, context)


class InvoiceDetail(RequiredPermissionMixin, View):
    """Display detailed view of a single invoice."""

    template_name = "invoice/detail.html"
    required_permission = "invoice.view_invoice"

    def get(self, request, pk):
        """Render invoice detail page with return history."""
        invoice = get_object_or_404(Invoice, id=pk)

        return_invoices = list(
            invoice.return_invoices.select_related(
                "created_by", "approved_by", "processed_by"
            )
            .prefetch_related("return_invoice_items")
            .annotate(
                returned_items_count=Count(
                    "return_invoice_items",
                    filter=Q(return_invoice_items__quantity_returned__gt=0),
                )
            )
            .order_by("-created_at")
        )

        total_return_amount = sum(ret.refund_amount for ret in return_invoices)
        total_return_items = sum(ret.returned_items_count for ret in return_invoices)

        # Get return items with details
        return_items_with_details = []
        for return_invoice in return_invoices:
            items = return_invoice.return_invoice_items.filter(
                quantity_returned__gt=0
            ).select_related("product_variant__product", "original_invoice_item")
            return_items_with_details.extend(items)

        # Calculate adjusted invoice total (original amount minus returns)
        adjusted_invoice_total = invoice.total_payable - total_return_amount

        # Get active shop details for direct printing status
        shop_details = ShopDetails.get_active()

        context = {
            "invoice": invoice,
            "title": f"Invoice {invoice.invoice_number}",
            "return_invoices": return_invoices,
            "total_return_amount": total_return_amount,
            "total_return_items": total_return_items,
            "return_items_with_details": return_items_with_details,
            "adjusted_invoice_total": adjusted_invoice_total,
            "shop_details": shop_details,
        }
        return render(request, self.template_name, context)


class InvoiceEdit(RequiredPermissionMixin, View):
    """Edit an existing invoice."""

    template_name = "invoice/form.html"
    form_class = InvoiceForm
    required_permission = "invoice.change_invoice"

    def get(self, request, pk):
        """Display the edit form for an existing invoice."""
        invoice = get_object_or_404(Invoice, id=pk)
        form = self.form_class(instance=invoice)
        context = {
            "invoice": invoice,
            "form": form,
            "title": f"Edit Invoice {invoice.invoice_number}",
            "customer_form": CustomerForm(),
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        """Process invoice update with payment type change handling."""
        invoice = get_object_or_404(Invoice, id=pk)
        form = self.form_class(request.POST, instance=invoice)

        new_payment_type = request.POST.get("payment_type")
        old_payment_type = invoice.payment_type

        if form.is_valid():
            # Handle payment type changes and set paid_amount accordingly
            invoice_instance = form.save(commit=False)

            if (
                new_payment_type == Invoice.PaymentType.CREDIT
                and old_payment_type == Invoice.PaymentType.CASH
            ):
                # When changing from CASH to CREDIT: reset paid_amount to 0
                # For CASH invoices, paid_amount = amount - discount_amount
                # For CREDIT invoices, paid_amount should start at 0
                invoice_instance.paid_amount = Decimal("0")

            # Model's save() will handle CASH invoices automatically
            # (setting paid_amount = amount - discount_amount and advance_amount = 0)
            invoice_instance.save()

            messages.success(request, "Invoice updated successfully")
            return redirect("invoice:detail", pk=invoice.id)

        logger.error("Form invalid: %s", form.errors)

        context = {
            "invoice": invoice,
            "form": form,
            "title": f"Edit Invoice {invoice.invoice_number}",
        }
        return render(request, self.template_name, context)


class InvoiceDelete(RequiredPermissionMixin, View):
    """Delete an invoice."""

    required_permission = "invoice.delete_invoice"

    def get(self, request, pk):
        """Delete the specified invoice and redirect to home."""
        invoice = get_object_or_404(Invoice, id=pk)
        invoice.delete()
        messages.success(request, "Invoice deleted successfully")
        return redirect("invoice:home")


def search_invoices_home(request):
    """Render the invoice search page."""
    return render(request, "search_invoice/home.html")


def fetch_search_invoices(request):
    """AJAX endpoint to search invoices by barcode."""
    search_query = request.GET.get("search", "")
    invoice_items = (
        InvoiceItem.objects.filter(product_variant__barcode__iexact=search_query)
        .select_related("product_variant__product", "invoice__customer", "invoice__sold_by")
        .order_by("-id")
    )
    return render_paginated_response(
        request, invoice_items, "search_invoice/fetch.html"
    )
