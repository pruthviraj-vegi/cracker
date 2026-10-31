"""
Utility functions for the base app.
"""

from datetime import date, datetime, timedelta

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.template.loader import render_to_string

from base.getDates import DatesManipulation, quarter_start_end


def parse_flexible_date(value, default=None):
    """
    Parse a date from string, date, or datetime into a datetime.date object.
    Supports multiple date formats (ISO, Indian/UK, US, etc.).

    Args:
        value (str | datetime | date | None): Input date string or object.
        default (date | None): Default fallback if parsing fails or input is empty.

    Returns:
        date | None: Parsed date or default fallback.
    """
    if value is None:
        return default
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return default

    cleaned = value.strip()
    if not cleaned:
        return default

    # If ISO format with time e.g. 2026-08-31T00:00:00 or with space
    if "T" in cleaned:
        cleaned = cleaned.split("T")[0].strip()
    elif " " in cleaned and (cleaned.count("-") >= 2 or cleaned.count("/") >= 2 or cleaned.count(".") >= 2):
        cleaned = cleaned.split(" ")[0].strip()

    formats = (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%d.%m.%Y",
        "%Y.%m.%d",
        "%m-%d-%Y",
        "%m/%d/%Y",
        "%b %d, %Y",
        "%d %b %Y",
        "%b %d %Y",
        "%d %b, %Y",
        "%B %d, %Y",
        "%d %B %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return default


def get_financial_year(value):
    """
    Get financial year from a given date.
    Financial year is considered from April (4) to March (3).

    Args:
        value (str | datetime | date): Input date. If string,
                                       accepted formats include "YYYY-MM-DD",
                                       "DD/MM/YYYY", "DD-MM-YYYY".

    Returns:
        str: Financial year in format 'YYYY-YY' (e.g. '2024-25')

    Raises:
        ValueError: If the input cannot be parsed as a valid date.
    """

    # --- Step 1: Parse the input into a datetime.date object ---
    parsed_date = parse_flexible_date(value)
    if parsed_date is None:
        raise ValueError(f"Unrecognized date format or invalid input: {value}")

    # --- Step 2: Calculate the financial year ---
    if parsed_date.month >= 4:  # April to Dec
        start_year = parsed_date.year
        end_year = parsed_date.year + 1
    else:  # Jan to March
        start_year = parsed_date.year - 1
        end_year = parsed_date.year

    return f"{str(start_year)[2:]}-{str(end_year)[2:]}"


def _clean_str(s):
    """Normalize whitespace, strip /?, then uppercase."""
    if not s:
        return ""
    cleaned = " ".join(str(s).split())
    return cleaned.replace("/", "").replace("?", "").replace(",", "").upper()


class StringProcessor:
    """Processes strings by cleaning and converting cases."""

    def __init__(self, s=None):
        self.input_string = s or ""
        self.cleaned_string = _clean_str(self.input_string)

    def clean(self):
        self.cleaned_string = _clean_str(self.input_string)

    def toUppercase(self):  # pylint: disable=invalid-name
        return self.cleaned_string.upper()

    def toLowercase(self):  # pylint: disable=invalid-name
        return self.cleaned_string.lower()

    def toTitle(self):  # pylint: disable=invalid-name
        return self.cleaned_string.title()

    def toCapitalize(self):  # pylint: disable=invalid-name
        return self.cleaned_string.capitalize()


def get_periodic_data(date_filter, current_start, current_end):
    """
    Return previous_start, previous_end, period_type for a given date filter.
    Uses the existing DatesManipulation class to avoid code duplication.
    """

    dates = DatesManipulation()

    # Map date filters to period types and get previous period dates
    period_map = {
        "today": ("daily", dates.yesterday_date),
        "yesterday": (
            "daily",
            (current_start - timedelta(days=1), current_end - timedelta(days=1)),
        ),
        "this_month": ("monthly", dates.last_month),
        "last_month": ("monthly", None),  # Need to calculate 2 months ago
        "this_quarter": ("quarterly", dates.last_quarter),
        "last_quarter": ("quarterly", None),  # Need to calculate 2 quarters ago
        "this_finance": ("yearly", dates.last_finance),
        "last_finance": ("yearly", None),  # Need to calculate 2 FY ago
    }

    if date_filter in period_map:
        period_type, previous_dates = period_map[date_filter]

        if previous_dates:
            previous_start, previous_end = previous_dates
            return (
                (
                    previous_start.date()
                    if hasattr(previous_start, "date")
                    else previous_start
                ),
                previous_end.date() if hasattr(previous_end, "date") else previous_end,
                period_type,
            )

    # Handle special cases that need calculation
    if date_filter == "last_month":
        # Get 2 months ago
        if current_start.month <= 2:
            previous_start = current_start.replace(
                year=current_start.year - 1,
                month=current_start.month + 10 if current_start.month == 2 else 11,
            )
        else:
            previous_start = current_start.replace(month=current_start.month - 2)

        # Calculate end of that month
        if previous_start.month == 12:
            next_month = previous_start.replace(year=previous_start.year + 1, month=1)
        else:
            next_month = previous_start.replace(month=previous_start.month + 1)
        previous_end = next_month - timedelta(days=1)

        return previous_start, previous_end, "monthly"

    elif date_filter == "last_quarter":
        # Get 2 quarters ago (6 months back)

        last_month = current_start.month - 6
        year = current_start.year
        if last_month <= 0:
            last_month += 12
            year -= 1
        previous_start, previous_end = quarter_start_end(year, last_month)
        return (
            (
                previous_start.date()
                if hasattr(previous_start, "date")
                else previous_start
            ),
            previous_end.date() if hasattr(previous_end, "date") else previous_end,
            "quarterly",
        )

    elif date_filter == "last_finance":
        # Get 2 financial years ago
        if current_start.month >= 4:
            previous_start = current_start.replace(
                year=current_start.year - 2, month=4, day=1
            )
            previous_end = current_start.replace(
                year=current_start.year - 1, month=3, day=31
            )
        else:
            previous_start = current_start.replace(
                year=current_start.year - 3, month=4, day=1
            )
            previous_end = current_start.replace(
                year=current_start.year - 2, month=3, day=31
            )
        return previous_start, previous_end, "yearly"

    # Default: monthly (same as "this_month" case)
    previous_start, previous_end = dates.last_month
    return (
        previous_start.date() if hasattr(previous_start, "date") else previous_start,
        previous_end.date() if hasattr(previous_end, "date") else previous_end,
        "monthly",
    )


def get_period_label(start_date, end_date, period_type):
    """
    Format a readable label for a given date range and period type.
    """
    if period_type == "daily":
        return start_date.strftime("%B %d, %Y")
    elif period_type == "monthly":
        return f"{start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"
    elif period_type == "quarterly":
        return f"Q{((start_date.month - 1) // 3) + 1} {start_date.year}"
    else:  # yearly
        return f"FY {start_date.year}-{end_date.year}"


def render_paginated_response(
    request,
    queryset,
    table_template,
    per_page=20,
    pagination_template="common/_pagination.html",
    **kwargs,
):
    """
    Reusable pagination + HTML rendering helper for HTMX/AJAX.

    Args:
        request: Django request object
        queryset: List/QuerySet to paginate
        table_template: Path to table HTML template
        per_page: Number of items per page
        pagination_template: Path to pagination template (optional)
        **kwargs: Additional context variables to pass to template

    Returns:
        JsonResponse with HTML table + pagination
    """
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_count": paginator.count,
    }
    # Merge additional context from kwargs
    context.update(kwargs)

    # Render table
    table_html = render_to_string(table_template, context, request=request)

    # Render pagination if needed
    pagination_html = ""
    if page_obj and page_obj.paginator.num_pages > 1:
        pagination_html = render_to_string(
            pagination_template, context, request=request
        )

    return JsonResponse(
        {
            "html": table_html,
            "pagination": pagination_html,
            "success": True,
        }
    )


def table_sorting(request, valid_sorts=None, default_sort="-id"):
    """
    Generalized sorting helper for multi-column sort.
    """
    is_mapping = isinstance(valid_sorts, dict)
    if valid_sorts is None:
        valid_keys = set()
    elif is_mapping:
        valid_keys = set(valid_sorts.keys())
    else:
        valid_keys = set(valid_sorts)

    sort_param = request.GET.get("sort", "")
    if not sort_param:
        return [default_sort]

    sort_fields = [f.strip() for f in sort_param.split(",") if f.strip()]
    final_sorts = []

    for field in sort_fields:
        is_desc = field.startswith("-")
        clean_field = field.lstrip("-")

        if clean_field in valid_keys:
            if is_mapping:
                # Get the DB field from the map
                db_field = valid_sorts[clean_field]
                # Apply direction to the DB field
                if is_desc:
                    final_sorts.append(f"-{db_field}")
                else:
                    final_sorts.append(db_field)
            else:
                final_sorts.append(field)

    if not final_sorts:
        return [default_sort]

    return final_sorts


def build_search_filter(search_query: str, fields: list[str]) -> Q:
    """
    Splits search_query into individual terms, strips punctuation (brackets, parentheses, commas),
    and builds an AND-combined Q object matching any of the specified model fields.
    """
    filters = Q()
    if search_query:
        # Strip punctuation like brackets, parentheses, commas to prevent SQL failure on formatted suggestions
        terms = [t.strip("(),[]{}") for t in search_query.strip().split() if t.strip("(),[]{}")]
        for word in terms:
            term_q = Q()
            for field in fields:
                term_q |= Q(**{f"{field}__icontains": word})
            filters &= term_q
    return filters


def process_breakdown_data(breakdown_qs, total: float, field_key: str = "field"):
    """
    Formats breakdown queryset items with rounded percentage calculation.
    """
    total_val = float(total) if total else 0.0
    return [
        {
            "field_name": str(item[field_key]).title().replace("_", " "),
            "count": item.get("count", 0),
            "amount": float(item.get("amount", 0)),
            "percentage": round((float(item.get("amount", 0)) / total_val * 100), 1) if total_val > 0 else 0,
        }
        for item in breakdown_qs
    ]


def resolve_user(request):
    """
    Extract and return authenticated user from request, or None if unauthenticated.
    """
    if not request:
        return None
    user = getattr(request, "user", None)
    return user if user and getattr(user, "is_authenticated", False) else None

