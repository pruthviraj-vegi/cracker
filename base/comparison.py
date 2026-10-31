"""
Period aggregation and comparison utilities for dashboard charts and metrics.
"""

from decimal import Decimal
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce, TruncDate, TruncMonth, TruncWeek
from base.utility import get_periodic_data, get_period_label


def get_period_data(queryset, start_date, _end_date, period_type, date_field="invoice_date", amount_field="amount", count_field="id"):
    """
    Get aggregated time-series data for a specific period using database-level grouping.

    Args:
        queryset: Django QuerySet
        start_date: Period start date
        _end_date: Period end date
        period_type: One of 'daily', 'monthly', 'quarterly', 'yearly'
        date_field: Name of date field on model
        amount_field: Name of amount/sum field on model
        count_field: Name of ID/count field on model

    Returns:
        List of dictionaries containing date, amount, and item count
    """
    if period_type == "daily":
        aggregated = queryset.aggregate(
            total_amount=Coalesce(Sum(amount_field), Decimal("0")),
            total_count=Count(count_field),
        )
        return [
            {
                "date": start_date.strftime("%Y-%m-%d"),
                "amount": float(aggregated["total_amount"]),
                "count": aggregated["total_count"],
            }
        ]

    trunc_map = {
        "monthly": (TruncDate(date_field), "day"),
        "quarterly": (TruncWeek(date_field), "week"),
    }

    trunc_expr, alias = trunc_map.get(period_type, (TruncMonth(date_field), "month"))

    data = (
        queryset.annotate(**{alias: trunc_expr})
        .values(alias)
        .annotate(
            amount=Coalesce(Sum(amount_field), Decimal("0")),
            count=Count(count_field),
        )
        .order_by(alias)
    )

    return [
        {
            "date": item[alias].strftime("%Y-%m-%d"),
            "amount": float(item["amount"]),
            "count": item["count"],
        }
        for item in data
    ]


def get_comparison_data(base_queryset, date_filter, current_start, current_end, date_field="invoice_date", amount_field="amount"):
    """
    Generate comparison data for current vs previous period based on date filter.
    """
    previous_start, previous_end, period_type = get_periodic_data(
        date_filter, current_start, current_end
    )

    current_qs = base_queryset.filter(
        **{f"{date_field}__date__range": [current_start, current_end]}
    )
    current_data = get_period_data(
        current_qs, current_start, current_end, period_type, date_field=date_field, amount_field=amount_field
    )

    previous_qs = base_queryset.filter(
        **{f"{date_field}__date__range": [previous_start, previous_end]}
    )
    previous_data = get_period_data(
        previous_qs, previous_start, previous_end, period_type, date_field=date_field, amount_field=amount_field
    )

    return {
        "current_period": {
            "label": get_period_label(current_start, current_end, period_type),
            "data": current_data,
            "start_date": current_start.isoformat(),
            "end_date": current_end.isoformat(),
        },
        "previous_period": {
            "label": get_period_label(previous_start, previous_end, period_type),
            "data": previous_data,
            "start_date": previous_start.isoformat(),
            "end_date": previous_end.isoformat(),
        },
        "period_type": period_type,
    }
