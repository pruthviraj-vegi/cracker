"""
Views for invoice cancellation operations.
"""

import logging

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from invoice.form import InvoiceCancellationForm
from invoice.models import Invoice, InvoiceCancellation

from base.decorators import required_permission
from base.utility import build_search_filter

logger = logging.getLogger(__name__)


@required_permission("invoice.add_invoice")
@require_http_methods(["GET", "POST"])
def cancel_invoice(request, pk):
    """
    View to cancel an invoice.
    GET: Display cancellation form
    POST: Process cancellation
    """
    invoice = get_object_or_404(Invoice, pk=pk)

    # Check if invoice can be cancelled
    can_cancel, error_msg = invoice.can_be_cancelled()
    if not can_cancel:
        messages.error(request, error_msg)
        return redirect("invoice:invoice_detail", pk=pk)

    if request.method == "POST":
        form = InvoiceCancellationForm(request.POST, invoice=invoice)
        try:
            reason = None
            if form.is_valid():
                reason = form.cleaned_data["cancellation_reason"]

            # Cancel the invoice (service handles transaction.atomic)
            success, message = invoice.cancel(user=request.user, reason=reason)

            if success:
                messages.success(
                    request,
                    f"Invoice {invoice.invoice_number} has been cancelled successfully.",
                )
                return redirect("invoice:detail", pk=pk)

            messages.error(request, f"Failed to cancel invoice: {message}")
            logger.error(
                "Failed to cancel invoice %s: %s",
                invoice.invoice_number,
                message,
            )
        except Exception as e:  # pylint: disable=broad-except
            messages.error(request, f"Failed to cancel invoice: {str(e)}")
            logger.error(
                "Failed to cancel invoice %s: %s", invoice.invoice_number, str(e)
            )
    else:
        form = InvoiceCancellationForm(invoice=invoice)

    # Calculate financial impact
    context = {
        "invoice": invoice,
        "form": form,
        "financial_impact": {
            "original_amount": invoice.amount,
            "discount": invoice.discount_amount,
            "advance": invoice.advance_amount,
            "paid": invoice.paid_amount,
            "net_amount": invoice.net_amount_due,
            "remaining": invoice.remaining_amount,
        },
    }

    return render(request, "invoice/cancel_invoice.html", context)


@required_permission("invoice.view_invoice")
def cancelled_invoices_list(request):
    """List all cancelled invoices"""

    # Get search and filter parameters
    search_query = request.GET.get("search", "")
    payment_type = request.GET.get("payment_type", "")

    # Apply search
    filters = build_search_filter(
        search_query,
        [
            "invoice_number",
            "customer__name",
            "cancellation_reason",
        ],
    )

    # Apply payment type filter
    if payment_type:
        filters &= Q(payment_type=payment_type)

    # Order by cancellation date
    invoices = (
        Invoice.objects.filter(is_cancelled=True)
        .select_related("customer", "cancelled_by", "cancellation_record")
        .filter(filters)
        .order_by("-cancelled_at")
    )

    # Calculate statistics
    stats = invoices.aggregate(
        total_count=Count("id"),
        total_amount=Sum("amount"),
        cash_count=Count("id", filter=Q(payment_type=Invoice.PaymentType.CASH)),
        credit_count=Count("id", filter=Q(payment_type=Invoice.PaymentType.CREDIT)),
    )

    context = {
        "invoices": invoices,
        "stats": stats,
        "search_query": search_query,
        "payment_type": payment_type,
    }

    return render(request, "invoice/cancelled_invoices_list.html", context)


@required_permission("invoice.view_invoice")
def cancellation_detail(request, pk):
    """View details of a cancelled invoice"""
    invoice = get_object_or_404(Invoice, pk=pk, is_cancelled=True)

    try:
        cancellation_record = invoice.cancellation_record
    except InvoiceCancellation.DoesNotExist:
        cancellation_record = None

    context = {
        "invoice": invoice,
        "cancellation_record": cancellation_record,
    }

    return render(request, "invoice/cancellation_detail.html", context)
