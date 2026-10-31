"""
URL patterns for the cart app.
"""

from django.urls import path
from . import views

app_name = "cart"

urlpatterns = [
    # Template view for main cart page
    path("", views.CartMainPageView.as_view(), name="main_page"),
    path("create/", views.CreateCart.as_view(), name="create_cart"),
    path("auto-create/", views.auto_cart_create, name="auto_cart_create"),
    path("<int:pk>/", views.get_cart_data, name="get_cart_data"),
    path("<int:pk>/edit/", views.EditCart.as_view(), name="edit_cart"),
    # API endpoints
    path("api/scan-barcode/", views.scan_barcode, name="scan_barcode"),
    path(
        "api/cart-item/<int:item_id>/", views.manage_cart_item, name="manage_cart_item"
    ),
    path("api/archive-cart/<int:cart_id>/", views.archive_cart, name="archive_cart"),
    path("api/clear-cart/<int:cart_id>/", views.clear_cart, name="clear_cart"),
    path("barcode-suggestions/", views.barcode_suggestions, name="barcode_suggestions"),
]
