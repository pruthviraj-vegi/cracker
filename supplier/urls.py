"""
URL patterns for the supplier app.
"""

from django.urls import path

from . import views


app_name = "supplier"

urlpatterns = [
    path("", views.home, name="home"),
    path("fetch/", views.fetch_suppliers, name="fetch"),
    path(
        "<int:pk>/invoices/fetch/", views.fetch_supplier_invoices, name="fetch_invoices"
    ),
    path(
        "<int:pk>/payments/fetch/", views.fetch_supplier_payments, name="fetch_payments"
    ),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/fetch/", views.dashboard_fetch, name="dashboard_fetch"),
    path("create/", views.CreateSupplier.as_view(), name="create"),
    path("<int:pk>/", views.supplier_detail, name="detail"),
    path("<int:pk>/edit/", views.EditSupplier.as_view(), name="edit"),
    path("<int:pk>/delete/", views.DeleteSupplier.as_view(), name="delete"),
    path("<int:pk>/report/", views.supplier_report, name="report"),
    path("<int:pk>/report/fetch/", views.supplier_report_fetch, name="report_fetch"),
    path("<int:pk>/auto-reallocate/", views.auto_reallocate, name="auto_reallocate"),
    # Invoice URLs
    path(
        "<int:supplier_pk>/invoices/create/",
        views.CreateInvoice.as_view(),
        name="create_invoice",
    ),
    path(
        "<int:supplier_pk>/invoices/<int:invoice_pk>/edit/",
        views.EditInvoice.as_view(),
        name="edit_invoice",
    ),
    path(
        "<int:supplier_pk>/invoices/<int:invoice_pk>/delete/",
        views.delete_invoice,
        name="delete_invoice",
    ),
    # Payment URLs
    path(
        "<int:supplier_pk>/payments/create/",
        views.CreatePayment.as_view(),
        name="create_payment",
    ),
    path(
        "<int:supplier_pk>/payments/<int:payment_pk>/edit/",
        views.EditPayment.as_view(),
        name="edit_payment",
    ),
    path(
        "<int:supplier_pk>/payments/<int:payment_pk>/delete/",
        views.delete_payment,
        name="delete_payment",
    ),
    # Invoice Media URLs
    path(
        "<int:supplier_pk>/invoices/<int:invoice_pk>/media/<int:media_pk>/delete/",
        views.delete_invoice_media,
        name="delete_invoice_media",
    ),
    # Payment Media URLs
    path(
        "<int:supplier_pk>/payments/<int:payment_pk>/media/<int:media_pk>/delete/",
        views.delete_payment_media,
        name="delete_payment_media",
    ),
]
