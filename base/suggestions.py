"""
View layer for search suggestion endpoints.

All search logic, caching, and scoring lives in ``base.weighted_search``.
This module provides thin Django view functions that serve JSON suggestion
responses consumed by ``wordSuggestion.js``.
"""

from django.http import JsonResponse

from base.weighted_search import (
    get_category_suggestions,
    get_customer_suggestions,
    get_gst_hsn_suggestions,
    get_invoice_suggestions,
    get_supplier_suggestions,
    get_uom_suggestions,
    get_weighted_product_suggestions,
    get_weighted_variant_suggestions,
)


def _suggestion_view(request, suggestion_fn):
    """
    Shared view logic for all suggestion endpoints.

    Reads ``q`` from the query string, calls the given ``suggestion_fn``
    with ``rich=True``, and returns a JSON response in the standard format::

        {"success": true, "data": [{"label": "...", "type": "..."}, ...]}
    """
    query = request.GET.get("q", "").strip()

    if not query or len(query) < 2:
        return JsonResponse({"success": True, "data": []})

    suggestions = suggestion_fn(query=query, rich=True)

    return JsonResponse({"success": True, "data": suggestions})


def customer_all_suggestions(request):
    """View to return JSON suggestions for customers using weighted search."""
    return _suggestion_view(request, get_customer_suggestions)


def invoice_all_suggestions(request):
    """View to return JSON suggestions for invoices using weighted search."""
    return _suggestion_view(request, get_invoice_suggestions)


def product_all_suggestions(request):
    """View to return JSON suggestions for products using weighted search."""
    return _suggestion_view(request, get_weighted_product_suggestions)


def product_variant_all_suggestions(request):
    """View to return JSON suggestions for product variants using weighted search."""
    return _suggestion_view(request, get_weighted_variant_suggestions)


def supplier_all_suggestions(request):
    """View to return JSON suggestions for suppliers using weighted search."""
    return _suggestion_view(request, get_supplier_suggestions)


def category_all_suggestions(request):
    """View to return JSON suggestions for categories using weighted search."""
    return _suggestion_view(request, get_category_suggestions)


def uom_all_suggestions(request):
    """View to return JSON suggestions for UOM using weighted search."""
    return _suggestion_view(request, get_uom_suggestions)


def gst_hsn_all_suggestions(request):
    """View to return JSON suggestions for GST/HSN codes using weighted search."""
    return _suggestion_view(request, get_gst_hsn_suggestions)
