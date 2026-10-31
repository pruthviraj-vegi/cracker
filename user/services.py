"""
Service layer for User commission calculations, salary summaries, and user dashboard aggregation.
"""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from invoice.models import Invoice, InvoiceItem


class CommissionService:
    """Encapsulates commission aggregation and user sales breakdown logic."""

    @staticmethod
    def get_user_commission_summary(user, start_datetime, end_datetime):
        """
        Calculates monthly commission breakdown for a specific user within a date range.
        """
        invoices = Invoice.objects.filter(sold_by=user).filter(
            invoice_date__gte=start_datetime, invoice_date__lte=end_datetime
        )
        invoice_items_all = InvoiceItem.objects.filter(
            invoice__in=invoices, commission_percentage__gt=0
        ).select_related("invoice")

        monthly_totals = defaultdict(
            lambda: {
                "total_sales": Decimal("0"),
                "total_commission": Decimal("0"),
                "invoice_ids": set(),
                "item_count": 0,
            }
        )

        for item in invoice_items_all:
            item_amount = item.discounted_amount
            commission_amount = item.commission_amount
            invoice_date = item.invoice.invoice_date
            month_key = invoice_date.strftime("%Y-%m")

            monthly_totals[month_key]["total_sales"] += item_amount
            monthly_totals[month_key]["total_commission"] += commission_amount
            monthly_totals[month_key]["invoice_ids"].add(item.invoice.id)
            monthly_totals[month_key]["item_count"] += 1

        monthly_summary = []
        for month_key, totals in sorted(monthly_totals.items(), reverse=True):
            year, month = map(int, month_key.split("-"))
            totals["invoice_count"] = len(totals["invoice_ids"])
            totals["month_key"] = month_key
            totals["month_label"] = datetime(year, month, 1).strftime("%B %Y")
            monthly_summary.append(totals)

        total_sales = sum(data["total_sales"] for data in monthly_totals.values())
        total_commission = sum(data["total_commission"] for data in monthly_totals.values())

        return {
            "total_sales": float(total_sales),
            "total_commission": float(total_commission),
            "monthly_summary": [
                {
                    "month_label": s["month_label"],
                    "invoice_count": s["invoice_count"],
                    "item_count": s["item_count"],
                    "total_sales": float(s["total_sales"]),
                    "total_commission": float(s["total_commission"]),
                }
                for s in monthly_summary
            ],
        }
