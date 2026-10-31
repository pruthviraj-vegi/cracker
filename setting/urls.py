"""
URL patterns for the setting app.
"""

from django.urls import path
from . import views


app_name = "setting"

urlpatterns = [
    # Shop Details URLs
    path("shop-details/", views.shop_details_list, name="shop_details_list"),
    path("shop-details/create/", views.shop_details_create, name="shop_details_create"),
    path(
        "shop-details/<int:pk>/", views.shop_details_detail, name="shop_details_detail"
    ),
    path(
        "shop-details/<int:pk>/edit/", views.shop_details_edit, name="shop_details_edit"
    ),
    path(
        "shop-details/<int:pk>/delete/",
        views.shop_details_delete,
        name="shop_details_delete",
    ),
    # Report Configuration URLs
    path("report-configs/", views.report_config_list, name="report_config_list"),
    path(
        "report-configs/create/",
        views.report_config_create,
        name="report_config_create",
    ),
    path(
        "report-configs/<int:pk>/",
        views.report_config_detail,
        name="report_config_detail",
    ),
    path(
        "report-configs/<int:pk>/edit/",
        views.report_config_edit,
        name="report_config_edit",
    ),
    path(
        "report-configs/<int:pk>/delete/",
        views.report_config_delete,
        name="report_config_delete",
    ),
    path(
        "report-configs/<int:pk>/set-default/",
        views.set_default_config,
        name="set_default_config",
    ),
    # Dashboard
    path(
        "shop-settings/", views.shop_settings_dashboard, name="shop_settings_dashboard"
    ),
    # Payment Details URLs
    path("payment-details/", views.payment_details_list, name="payment_details_list"),
    path(
        "payment-details/create/",
        views.payment_details_create,
        name="payment_details_create",
    ),
    path(
        "payment-details/<int:pk>/",
        views.payment_details_detail,
        name="payment_details_detail",
    ),
    path(
        "payment-details/<int:pk>/edit/",
        views.payment_details_edit,
        name="payment_details_edit",
    ),
    path(
        "payment-details/<int:pk>/delete/",
        views.payment_details_delete,
        name="payment_details_delete",
    ),
    # Barcode Configuration URLs
    path("barcode-configs/", views.barcode_config_list, name="barcode_config_list"),
    path(
        "barcode-configs/create/",
        views.barcode_config_create,
        name="barcode_config_create",
    ),
    path(
        "barcode-configs/<int:pk>/",
        views.barcode_config_detail,
        name="barcode_config_detail",
    ),
    path(
        "barcode-configs/<int:pk>/edit/",
        views.barcode_config_edit,
        name="barcode_config_edit",
    ),
    path(
        "barcode-configs/<int:pk>/delete/",
        views.barcode_config_delete,
        name="barcode_config_delete",
    ),
]
