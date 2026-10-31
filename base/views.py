"""Views for authentication, home page, dashboard stats, and error handling."""

import calendar
import datetime
import logging
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.views import LoginView
from django.core.signing import BadSignature, SignatureExpired
from django.db.models import Count, DecimalField, F, Q, Sum, OuterRef, Subquery
from django.db.models.functions import Abs, Coalesce, TruncDate, TruncMonth, TruncWeek
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import TemplateView

from base.decorators import RequiredPermissionMixin
from base.getDates import getDates
from base.utility import get_period_label, get_periodic_data

from customer.models import Customer, CustomerCreditSummary, Payment
from inventory.models import InventoryLog, ProductVariant
from invoice.models import Invoice, ReturnInvoice
from invoice.choices import PaymentStatusChoices, PaymentTypeChoices
from supplier.models import SupplierInvoice, SupplierPayment

from .forms import CustomLoginForm

logger = logging.getLogger(__name__)


class CustomLoginView(LoginView):
    """Handle user login with remember-me, remembered account, and safe redirect support."""

    form_class = CustomLoginForm
    template_name = "base/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        """Add remembered account details to context if a valid signed cookie exists."""
        context = super().get_context_data(**kwargs)
        remembered_user = None
        switch_account = self.request.GET.get("switch") == "1"

        try:
            phone = self.request.get_signed_cookie(
                "remembered_account",
                salt="remembered_account_salt",
                max_age=30 * 24 * 60 * 60,
            )
        except (BadSignature, SignatureExpired, KeyError):
            phone = None

        if phone:
            user_model = get_user_model()
            user_obj = user_model.objects.filter(
                phone_number=phone, is_active=True
            ).first()
            if user_obj:
                name = user_obj.full_name.strip() or user_obj.first_name or "User"
                parts = name.split()
                initials = (
                    "".join([part[0].upper() for part in parts[:2]])
                    if parts
                    else "U"
                )
                masked_phone = f"•••••• {phone[-4:]}" if len(phone) >= 4 else phone
                remembered_user = {
                    "phone_number": phone,
                    "full_name": name,
                    "first_name": user_obj.first_name or name,
                    "masked_phone": masked_phone,
                    "initials": initials,
                }

        context["remembered_user"] = remembered_user
        context["switch_account"] = switch_account
        return context

    def get_success_url(self):
        """
        Redirect to the exact page after login.
        Priority:
        1. 'next' parameter from POST request (form submission)
        2. 'next' URL parameter from GET request
        3. 'next' stored in session (by middleware)
        4. Default to home page
        """
        redirect_url = self.request.POST.get("next") or self.request.GET.get("next")

        # If not in GET/POST, check session (stored by middleware)
        if not redirect_url:
            redirect_url = self.request.session.get("next")
            # Clean up session after retrieving
            if redirect_url:
                del self.request.session["next"]

        # Validate the redirect URL for security
        if redirect_url:
            # Check if URL is safe (same host, allowed scheme)
            if url_has_allowed_host_and_scheme(redirect_url, allowed_hosts=None):
                return redirect_url

        # Default to home page
        return reverse_lazy("base:home")

    def form_valid(self, form):
        remember = form.cleaned_data.get("remember")
        if not remember:
            # Set session to expire when browser closes
            self.request.session.set_expiry(0)

        # Call parent form_valid to handle login
        response = super().form_valid(form)

        # Add success message
        messages.success(self.request, f"Welcome back, {self.request.user.full_name}!")

        # Handle remembered account signed cookie
        user = self.request.user
        if remember:
            response.set_signed_cookie(
                "remembered_account",
                str(user.phone_number),
                salt="remembered_account_salt",
                max_age=30 * 24 * 60 * 60,
                httponly=True,
                samesite="Lax",
                secure=getattr(settings, "SESSION_COOKIE_SECURE", False),
            )
        else:
            response.delete_cookie("remembered_account")

        return response

    def form_invalid(self, form):
        # Add error message for invalid login
        messages.error(
            self.request, "Invalid phone number or password. Please try again."
        )

        return super().form_invalid(form)


def forget_remembered_account(request):
    """Clear remembered account cookie and return to login page."""
    response = redirect("base:login")
    response.delete_cookie("remembered_account")
    return response


class HomeView(TemplateView):
    """Dashboard home page, accessible to all authenticated roles."""

    template_name = "base/home.html"
    login_url = "base:login"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer_receivable = CustomerCreditSummary.objects.aggregate(
            total=Coalesce(
                Sum("balance_amount", filter=Q(balance_amount__gt=0)), Decimal("0")
            )
        )["total"]

        # Total active customers
        total_customers = (
            Customer.objects.filter(is_deleted=False).exclude(phone_number="3").count()
        )

        # Supplier balance (all-time outstanding)
        supplier_invoiced = SupplierInvoice.objects.filter(is_deleted=False).aggregate(
            total=Coalesce(Sum("total_amount"), Decimal("0"))
        )["total"]

        supplier_paid = SupplierPayment.objects.filter(is_deleted=False).aggregate(
            total=Coalesce(Sum("amount"), Decimal("0"))
        )["total"]

        supplier_balance = supplier_invoiced - supplier_paid

        # Total active products (variants)
        total_products = ProductVariant.objects.filter(
            is_deleted=False, status=ProductVariant.VariantStatus.ACTIVE
        ).count()

        context["user"] = self.request.user
        context["customer_receivable"] = customer_receivable
        context["total_customers"] = total_customers
        context["supplier_balance"] = supplier_balance
        context["total_products"] = total_products

        return context


def custom_404_view(request, exception=None):
    """
    Custom 404 error handler.
    Django error handlers must be function-based views that accept:
    - handler404: (request, exception)
    - handler500: (request)
    - handler403: (request, exception)
    - handler400: (request, exception)
    """
    return render(request, "404.html", status=404)


def logout_view(request):
    """Log the user out and redirect to the login page."""
    logout(request)
    return redirect("base:login")


def dashboard_stats(request):
    """Return date-dependent dashboard statistics for the main dashboard.

    AJAX endpoint that returns invoice stats, combined payment method breakdown,
    and comparison data for the revenue chart based on the selected date filter.
    """
    date_filter = request.GET.get("date_filter", "this_month")
    start_date, end_date = getDates(request)

    # Invoice stats for the period (cash invoices only)
    invoices = Invoice.objects.filter(
        invoice_date__date__range=[start_date, end_date],
        is_cancelled=False,
        payment_type=PaymentTypeChoices.CASH,
    )

    invoice_stats = invoices.aggregate(
        total_invoices=Count("id"),
        total_amount=Coalesce(
            Sum(F("amount") - F("discount_amount")),
            Decimal("0"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
    )

    # Invoice payment method breakdown
    invoice_method_breakdown = list(
        invoices.values("payment_method")
        .annotate(
            count=Count("id"),
            amount=Coalesce(
                Sum(F("amount") - F("discount_amount")),
                Decimal("0"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
        )
        .order_by("payment_method")
    )

    # Received payments (from Payment model - credit payments received)
    received_payments = Payment.objects.filter(
        payment_type=Payment.PaymentType.Paid,
        payment_date__date__range=[start_date, end_date],
    )

    total_received_payments = received_payments.aggregate(
        total=Coalesce(
            Sum("amount"),
            Decimal("0"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
    )["total"]

    received_method_breakdown = list(
        received_payments.values("method")
        .annotate(
            count=Count("id"),
            amount=Coalesce(
                Sum("amount"),
                Decimal("0"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
        )
        .order_by("method")
    )

    # Merge both sources into a single breakdown by method
    combined = {}
    for item in invoice_method_breakdown:
        method = item["payment_method"].title().replace("_", " ")
        combined[method] = {
            "count": item["count"],
            "amount": float(item["amount"]),
        }

    for item in received_method_breakdown:
        method = item["method"].title().replace("_", " ")
        if method in combined:
            combined[method]["count"] += item["count"]
            combined[method]["amount"] += float(item["amount"])
        else:
            combined[method] = {
                "count": item["count"],
                "amount": float(item["amount"]),
            }

    # Calculate total received (invoices + payments)
    total_received = float(invoice_stats["total_amount"]) + float(
        total_received_payments
    )

    # Build final breakdown list with percentages
    combined_breakdown = [
        {
            "payment_method": method,
            "count": data["count"],
            "amount": data["amount"],
            "percentage": (
                round(data["amount"] / total_received * 100, 1)
                if total_received > 0
                else 0
            ),
        }
        for method, data in sorted(combined.items())
    ]

    # Comparison data for stock in vs stock out chart
    comparison_data = get_inventory_comparison_data(date_filter, start_date, end_date)

    return JsonResponse(
        {
            "success": True,
            "stats": {
                "total_invoices": invoice_stats["total_invoices"],
                "total_received": total_received,
            },
            "payment_method_breakdown": combined_breakdown,
            "comparison_data": comparison_data,
            "date_range": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "filter": date_filter,
            },
        }
    )


def get_inventory_comparison_data(date_filter, current_start, current_end):
    """Generate stock in vs stock out comparison data for the line chart.

    Returns current and previous period data in the same format as
    ``customer.views.get_comparison_data`` so the frontend can reuse
    ``ModernCharts.updateRevenueChart``.
    """
    previous_start, previous_end, period_type = get_periodic_data(
        date_filter, current_start, current_end
    )

    current_logs = InventoryLog.objects.filter(
        variant__is_deleted=False,
        timestamp__date__range=[current_start, current_end],
    )
    current_data = _get_inventory_period_data(
        current_logs, current_start, current_end, period_type
    )

    previous_logs = InventoryLog.objects.filter(
        variant__is_deleted=False,
        timestamp__date__range=[previous_start, previous_end],
    )
    previous_data = _get_inventory_period_data(
        previous_logs, previous_start, previous_end, period_type
    )

    return {
        "current_period": {
            "label": get_period_label(current_start, current_end, period_type),
            "data": current_data,
        },
        "previous_period": {
            "label": get_period_label(previous_start, previous_end, period_type),
            "data": previous_data,
        },
        "period_type": period_type,
    }


def _get_inventory_period_data(logs_qs, start_date, _end_date, period_type):
    """Aggregate stock-in and stock-out values by time bucket.

    Each data point contains both ``amount`` (stock in value) and
    ``stock_out`` (stock out value) so the frontend can plot two lines.
    """
    amount_field = DecimalField(max_digits=16, decimal_places=2)

    stock_in_sum = Coalesce(
        Sum(
            Abs(F("quantity_change")) * F("purchase_price"),
            filter=Q(transaction_type__in=["STOCK_IN", "INITIAL"]),
            output_field=amount_field,
        ),
        Decimal("0"),
    )
    stock_out_sum = Coalesce(
        Sum(
            Abs(F("quantity_change")) * F("purchase_price"),
            filter=Q(transaction_type="SALE"),
            output_field=amount_field,
        ),
        Decimal("0"),
    )

    if period_type == "daily":
        agg = logs_qs.aggregate(stock_in=stock_in_sum, stock_out=stock_out_sum)
        return [
            {
                "date": start_date.strftime("%Y-%m-%d"),
                "amount": float(agg["stock_in"]),
                "stock_out": float(agg["stock_out"]),
            }
        ]

    # Choose the truncation function
    trunc_map = {
        "monthly": ("day", TruncDate("timestamp")),
        "quarterly": ("week", TruncWeek("timestamp")),
        "yearly": ("month", TruncMonth("timestamp")),
    }
    bucket_name, trunc_fn = trunc_map.get(period_type, ("day", TruncDate("timestamp")))

    rows = (
        logs_qs.annotate(bucket=trunc_fn)
        .values("bucket")
        .annotate(stock_in=stock_in_sum, stock_out=stock_out_sum)
        .order_by("bucket")
    )

    return [
        {
            "date": row["bucket"].strftime("%Y-%m-%d"),
            "amount": float(row["stock_in"]),
            "stock_out": float(row["stock_out"]),
        }
        for row in rows
    ]


class CalendarView(RequiredPermissionMixin, TemplateView):
    """Calendar page showing invoices by date."""

    required_permission = "invoice.view_invoice"
    template_name = "base/calendar.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        try:
            year = int(self.request.GET.get("year", today.year))
            month = int(self.request.GET.get("month", today.month))
        except (ValueError, TypeError):
            year = today.year
            month = today.month

        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1

        import datetime
        _, num_days = calendar.monthrange(year, month)
        first_day = datetime.date(year, month, 1)
        last_day = datetime.date(year, month, num_days)

        # Extend start and end by 7 days to cover leading/trailing dates in calendar grid
        grid_start = first_day - datetime.timedelta(days=7)
        grid_end = last_day + datetime.timedelta(days=7)

        invoices = (
            Invoice.objects.filter(
                invoice_date__date__range=[grid_start, grid_end],
                is_cancelled=False,
            )
            .exclude(payment_status__in=[PaymentStatusChoices.VOID, PaymentStatusChoices.CANCELLED])
            .select_related("customer")
        )

        calendar_data = {}
        curr = grid_start
        while curr <= grid_end:
            calendar_data[curr.strftime("%Y-%m-%d")] = {
                "amount": 0.0,
                "completed": 0.0,
                "events": [],
            }
            curr += datetime.timedelta(days=1)

        for inv in invoices:
            if not inv.invoice_date:
                continue
            inv_dt = inv.invoice_date
            if timezone.is_naive(inv_dt):
                inv_dt = timezone.make_aware(inv_dt, timezone.get_current_timezone())
            local_dt = timezone.localtime(inv_dt)
            date_key = local_dt.strftime("%Y-%m-%d")
            if date_key not in calendar_data:
                continue
            gross_amount = float(inv.amount)
            discount_amount = float(inv.discount_amount)
            net_amount = float(inv.amount - inv.discount_amount)
            paid_amount = float(inv.paid_amount)

            calendar_data[date_key]["amount"] += net_amount
            calendar_data[date_key]["completed"] += paid_amount

            calendar_data[date_key]["events"].append({
                "invoice_number": inv.invoice_number,
                "customer_name": inv.customer.name,
                "gross_amount": round(gross_amount, 2),
                "discount_amount": round(discount_amount, 2),
                "amount": round(net_amount, 2),
                "paid_amount": round(paid_amount, 2),
                "status": inv.payment_status,
                "status_display": inv.get_payment_status_display(),
                "url": reverse("invoice:detail", args=[inv.pk]),
            })

        # Month KPI metrics calculation for target year/month
        month_invoices = Invoice.objects.filter(
            invoice_date__year=year,
            invoice_date__month=month,
            is_cancelled=False,
        ).exclude(payment_status__in=[PaymentStatusChoices.VOID, PaymentStatusChoices.CANCELLED])

        month_stats = month_invoices.aggregate(
            total_invoices=Count("id"),
            total_amount=Coalesce(Sum("amount"), Decimal("0")),
            total_discount=Coalesce(Sum("discount_amount"), Decimal("0")),
            total_paid=Coalesce(Sum("paid_amount"), Decimal("0")),
        )

        month_returns = ReturnInvoice.objects.filter(
            return_date__year=year,
            return_date__month=month,
            invoice__is_cancelled=False,
        ).aggregate(total_return_amount=Coalesce(Sum("refund_amount"), Decimal("0")))

        total_amt = month_stats["total_amount"]
        total_disc = month_stats["total_discount"]
        total_paid = month_stats["total_paid"]
        total_return = month_returns["total_return_amount"]

        net_billing = float(total_amt - total_disc - total_return)
        paid_amt = float(total_paid)
        pending_amt = max(0.0, net_billing - paid_amt)
        collection_rate = round((paid_amt / net_billing * 100), 1) if net_billing > 0 else 0.0
        pending_rate = round(100.0 - collection_rate, 1) if net_billing > 0 else 0.0
        avg_daily_billing = round(net_billing / num_days, 2) if num_days > 0 else 0.0

        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1

        months_list = [(i, calendar.month_name[i]) for i in range(1, 13)]
        years_list = list(range(today.year - 5, today.year + 6))
        if year not in years_list:
            years_list.append(year)
            years_list.sort()

        context["user"] = self.request.user
        context["year"] = year
        context["month"] = month
        context["month_name"] = calendar.month_name[month]
        context["prev_year"] = prev_year
        context["prev_month"] = prev_month
        context["next_year"] = next_year
        context["next_month"] = next_month
        context["months_list"] = months_list
        context["years_list"] = years_list
        context["calendar_data"] = calendar_data
        context["month_kpi"] = {
            "total_billing": round(net_billing, 2),
            "total_invoices": month_stats["total_invoices"],
            "paid_amount": round(paid_amt, 2),
            "pending_amount": round(pending_amt, 2),
            "collection_rate": collection_rate,
            "pending_rate": pending_rate,
            "avg_daily_billing": avg_daily_billing,
            "days_in_month": num_days,
        }
        return context


def calendar_stats_api(request):
    """Return overall calendar progress for the progress bar (JSON)."""

    from invoice.choices import PaymentStatusChoices as PSC

    year = int(request.GET.get("year", timezone.now().year))
    month = int(request.GET.get("month", timezone.now().month))

    invoices = (
        Invoice.objects.filter(
            invoice_date__year=year,
            invoice_date__month=month,
            is_cancelled=False,
        )
        .exclude(payment_status__in=[PSC.VOID, PSC.CANCELLED])
    )

    total_count = invoices.count()
    completed_count = invoices.filter(payment_status=PSC.PAID).count()

    pct = round(completed_count / total_count * 100, 1) if total_count > 0 else 0

    return JsonResponse({
        "total_count": total_count,
        "completed_count": completed_count,
        "percentage": pct,
    })


def calendar_details_page(request):
    """Calendar details page with range-based analytics."""
    from invoice.choices import PaymentStatusChoices as PSC

    return render(request, "base/calendar_details.html", {
        "user": request.user,
    })


def calendar_details_api(request):
    """API endpoint returning analytics for a selected date range."""
    from invoice.choices import PaymentStatusChoices as PSC
    from invoice.models import Invoice, InvoiceItem
    from invoice.models import ReturnInvoice, ReturnInvoiceItem
    from customer.models import Customer
    from base.utility import parse_flexible_date

    start_str = request.GET.get("start", "")
    end_str = request.GET.get("end", "")
    date_filter = request.GET.get("date_filter", "")

    today = timezone.now().date()
    start_date = parse_flexible_date(start_str, default=None)
    end_date = parse_flexible_date(end_str, default=None)

    if date_filter and (start_date is None or end_date is None):
        from base.getDates import getDates
        dt_start, dt_end = getDates(request)
        if dt_start and dt_end:
            start_date = dt_start.date() if hasattr(dt_start, "date") else dt_start
            end_date = dt_end.date() if hasattr(dt_end, "date") else dt_end

    if start_date is None and end_date is None:
        start_date = today.replace(day=1)
        _, num_days = calendar.monthrange(today.year, today.month)
        end_date = today.replace(day=num_days)
    elif start_date is None:
        start_date = end_date
    elif end_date is None:
        end_date = start_date

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    # Base invoice queryset for the range
    invoices = Invoice.objects.filter(
        invoice_date__date__range=[start_date, end_date],
        is_cancelled=False,
    ).exclude(payment_status__in=[PSC.VOID, PSC.CANCELLED])

    # Invoice items for the range
    items = InvoiceItem.objects.filter(
        invoice__invoice_date__date__range=[start_date, end_date],
        invoice__is_cancelled=False,
    ).exclude(
        invoice__payment_status__in=[PSC.VOID, PSC.CANCELLED]
    ).select_related(
        "product_variant__product__category",
        "invoice__customer",
    )

    # ── Returns (for profit adjustment) ──
    returned_subquery = (
        ReturnInvoiceItem.objects.filter(
            original_invoice_item=OuterRef("pk"), quantity_returned__gt=0
        )
        .values("original_invoice_item")
        .annotate(total_returned=Sum("quantity_returned"))
        .values("total_returned")
    )

    profit_data = (
        items.filter(unit_price__isnull=False, purchase_price__isnull=False)
        .annotate(
            returned_quantity=Coalesce(Subquery(returned_subquery), Decimal("0")),
            actual_qty=F("quantity") - F("returned_quantity"),
        )
        .aggregate(
            total_profit=Coalesce(
                Sum((F("unit_price") - F("purchase_price")) * F("actual_qty"),
                    output_field=DecimalField()),
                Decimal("0"),
            )
        )
    )

    # ── Invoice-level metrics ──
    metrics = invoices.aggregate(
        total_invoices=Count("id"),
        total_amount=Coalesce(Sum("amount"), Decimal("0")),
        total_discount=Coalesce(Sum("discount_amount"), Decimal("0")),
        total_paid=Coalesce(Sum("paid_amount"), Decimal("0")),
    )

    return_metrics = ReturnInvoice.objects.filter(
        return_date__date__range=[start_date, end_date],
        invoice__is_cancelled=False,
    ).aggregate(total_return_amount=Coalesce(Sum("refund_amount"), Decimal("0")))

    total_amount = metrics["total_amount"]
    total_discount = metrics["total_discount"]
    total_paid = metrics["total_paid"]
    total_return = return_metrics["total_return_amount"]
    gross_profit = profit_data["total_profit"]
    net_profit = gross_profit - total_discount
    net_amount = total_amount - total_discount - total_return

    margin = (net_profit / net_amount * 100).quantize(Decimal("0.01")) if net_amount > 0 else Decimal("0")

    # ── Payment status breakdown ──
    payment_status_bd = list(
        invoices.values("payment_status")
        .annotate(count=Count("id"), amount=Coalesce(Sum("amount"), Decimal("0")))
        .order_by("payment_status")
    )

    total_amt_float = float(total_amount)
    payment_status_data = []
    for ps in payment_status_bd:
        amt = float(ps["amount"])
        payment_status_data.append({
            "status": ps["payment_status"].title().replace("_", " "),
            "count": ps["count"],
            "amount": amt,
            "percentage": round(amt / total_amt_float * 100, 1) if total_amt_float > 0 else 0,
        })

    # ── Payment type breakdown ──
    payment_type_bd = list(
        invoices.values("payment_type")
        .annotate(count=Count("id"), amount=Coalesce(Sum("amount"), Decimal("0")))
        .order_by("payment_type")
    )
    payment_type_data = []
    for pt in payment_type_bd:
        amt = float(pt["amount"])
        payment_type_data.append({
            "type": pt["payment_type"].title().replace("_", " "),
            "count": pt["count"],
            "amount": amt,
            "percentage": round(amt / total_amt_float * 100, 1) if total_amt_float > 0 else 0,
        })

    # ── Daily trend ──
    daily_trend = (
        invoices.annotate(date=TruncDate("invoice_date"))
        .values("date")
        .annotate(
            day_amount=Coalesce(Sum("amount"), Decimal("0")),
            day_count=Count("id"),
        )
        .order_by("date")
    )

    daily_items_profit = (
        items.filter(unit_price__isnull=False, purchase_price__isnull=False)
        .annotate(
            date=TruncDate("invoice__invoice_date"),
            returned_q=Coalesce(Subquery(returned_subquery), Decimal("0")),
            act_qty=F("quantity") - F("returned_q"),
        )
        .values("date")
        .annotate(
            day_profit=Coalesce(
                Sum((F("unit_price") - F("purchase_price")) * F("act_qty"),
                    output_field=DecimalField()),
                Decimal("0"),
            )
        )
        .order_by("date")
    )

    profit_by_date = {d["date"].isoformat(): float(d["day_profit"]) for d in daily_items_profit}

    trend_data = []
    for d in daily_trend:
        date_iso = d["date"].isoformat()
        day_amt = float(d["day_amount"])
        day_prof = profit_by_date.get(date_iso, 0)
        day_prof_pct = round((day_prof / day_amt * 100), 1) if day_amt > 0 else 0.0
        trend_data.append({
            "date": date_iso,
            "amount": day_amt,
            "count": d["day_count"],
            "profit": day_prof,
            "profit_percentage": day_prof_pct,
        })

    # ── Top customers (for pie chart) ──
    top_customers_qs = (
        invoices.values("customer__name")
        .annotate(
            total_amount=Coalesce(Sum("amount"), Decimal("0")),
            invoice_count=Count("id"),
            total_paid=Coalesce(Sum("paid_amount"), Decimal("0")),
        )
        .order_by("-total_amount")[:10]
    )
    top_customers = []
    for c in top_customers_qs:
        top_customers.append({
            "name": c["customer__name"] or "Unknown",
            "amount": float(c["total_amount"]),
            "count": c["invoice_count"],
            "paid": float(c["total_paid"]),
        })

    # ── Category breakdown ──
    category_bd = (
        items.values("product_variant__product__category__name")
        .annotate(
            count=Count("id"),
            amount=Coalesce(
                Sum(F("unit_price") * F("quantity"), output_field=DecimalField()),
                Decimal("0"),
            ),
        )
        .order_by("-amount")
    )
    cat_total = sum(float(c["amount"]) for c in category_bd)
    categories = []
    for cat in category_bd:
        amt = float(cat["amount"])
        categories.append({
            "name": cat["product_variant__product__category__name"] or "Uncategorized",
            "count": cat["count"],
            "amount": amt,
            "percentage": round(amt / cat_total * 100, 1) if cat_total > 0 else 0,
        })

    day_diff = (end_date - start_date).days + 1
    avg_invoice_amount = round(float(total_amount) / metrics["total_invoices"], 2) if metrics["total_invoices"] > 0 else 0.0
    avg_invoices_per_day = round(metrics["total_invoices"] / day_diff, 1) if day_diff > 0 else 0.0

    return JsonResponse({
        "success": True,
        "stats": {
            "total_invoices": metrics["total_invoices"],
            "total_amount": float(total_amount),
            "total_discount": float(total_discount),
            "total_paid": float(total_paid),
            "total_return": float(total_return),
            "net_amount": float(net_amount),
            "gross_profit": float(gross_profit),
            "net_profit": float(net_profit),
            "margin": float(margin),
            "avg_invoice_amount": avg_invoice_amount,
            "avg_invoices_per_day": avg_invoices_per_day,
        },
        "payment_status_breakdown": payment_status_data,
        "payment_type_breakdown": payment_type_data,
        "daily_trend": trend_data,
        "top_customers": top_customers,
        "categories": categories,
        "date_range": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
    })
