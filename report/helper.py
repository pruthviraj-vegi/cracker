"""Helper functions for report views."""

from decimal import Decimal
from invoice.services import (
    get_invoice_report_data,
    get_invoice_cancled_data,
    get_invoice_return_data,
)


def build_invoice_report_context(start_date, end_date):
    """
    Pure function — no request needed.
    Returns the full context dict for the invoice report template.
    """
    date_range = [start_date, end_date]

    def sum_invoice_data(queryset, amount_field="total_payable"):
        """Evaluate queryset once, sum totals in single pass."""
        total_net = Decimal("0")
        total_cgst = Decimal("0")
        total_gst = Decimal("0")
        total_amount = Decimal("0")

        # Force evaluation once — avoids double DB hit
        invoice_list = list(queryset)

        for inv in invoice_list:
            total_net += inv.total_tax_value
            total_cgst += inv.cgst_amount
            total_gst += inv.total_gst_amount
            total_amount += getattr(inv, amount_field)
        return {
            "data": invoice_list,
            "start_date": start_date,
            "end_date": end_date,
            "total_count": len(invoice_list),
            "total_net": total_net,
            "total_cgst_amount": total_cgst,
            "total_gst": total_gst,
            "total_amount": total_amount,
        }

    invoices = sum_invoice_data(get_invoice_report_data(date_range))
    invoices_cancelled = sum_invoice_data(get_invoice_cancled_data(date_range))
    invoices_return = sum_invoice_data(
        get_invoice_return_data(date_range), "refund_amount"
    )

    # Invoices billed in a past period that were cancelled in this period
    from invoice.models import Invoice

    past_cancelled = sum_invoice_data(
        Invoice.objects.filter(
            invoice_type=Invoice.Invoice_type.GST,
            cancelled_at__date__range=date_range,
            is_cancelled=True,
            invoice_date__date__lt=start_date,
        )
    )

    grand_total_net = max(
        Decimal("0"),
        invoices["total_net"] - invoices_return["total_net"] - past_cancelled["total_net"],
    )
    grand_total_cgst = max(
        Decimal("0"),
        invoices["total_cgst_amount"] - invoices_return["total_cgst_amount"] - past_cancelled["total_cgst_amount"],
    )
    grand_total_gst = max(
        Decimal("0"),
        invoices["total_gst"] - invoices_return["total_gst"] - past_cancelled["total_gst"],
    )
    grand_total_amount = max(
        Decimal("0"),
        invoices["total_amount"] - invoices_return["total_amount"] - past_cancelled["total_amount"],
    )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "invoices": invoices,
        "invoices_cancelled": invoices_cancelled,
        "invoices_return": invoices_return,
        "summery": {
            "count": invoices["total_count"]
            + invoices_cancelled["total_count"]
            + invoices_return["total_count"],
            "net": grand_total_net,
            "cgst": grand_total_cgst,
            "gst": grand_total_gst,
            "amount": grand_total_amount,
        },
    }
