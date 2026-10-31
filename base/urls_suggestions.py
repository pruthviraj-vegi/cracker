"""
URL patterns for the suggestions app.
"""

from django.urls import path

from . import suggestions

app_name = "suggestions"

urlpatterns = [
    path("customers/", suggestions.customer_all_suggestions, name="customer_all"),
    path("invoices/", suggestions.invoice_all_suggestions, name="invoice_all"),
    path("products/", suggestions.product_all_suggestions, name="product_all"),
    path(
        "product-variants/",
        suggestions.product_variant_all_suggestions,
        name="product_variant_all",
    ),
    path("suppliers/", suggestions.supplier_all_suggestions, name="supplier_all"),
    path("categories/", suggestions.category_all_suggestions, name="category_all"),
    path("uom/", suggestions.uom_all_suggestions, name="uom_all"),
    path("gst-hsn/", suggestions.gst_hsn_all_suggestions, name="gst_hsn_all"),
]
