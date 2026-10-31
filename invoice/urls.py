"""
URL routing configuration for the invoice app.
"""

from django.urls import path

from invoice import (
    views,
    views_,
    views_cancellation,
    views_report,
    views_return,
)

app_name = "invoice"

urlpatterns = [
    path("", views.invoice_home, name="home"),
    path("dashboard/", views.invoice_dashboard, name="dashboard"),
    path("dashboard/fetch/", views.invoice_dashboard_fetch, name="dashboard_fetch"),
    path("fetch/", views.fetch_invoices, name="fetch"),
    path(
        "create-invoice/<int:pk>/", views.CreateInvoice.as_view(), name="create_invoice"
    ),
    path("detail/<int:pk>/", views.InvoiceDetail.as_view(), name="detail"),
    path("edit/<int:pk>/", views.InvoiceEdit.as_view(), name="edit"),
    path("delete/<int:pk>/", views.InvoiceDelete.as_view(), name="delete"),
    # Invoice Cancellation
    path("cancel/<int:pk>/", views_cancellation.cancel_invoice, name="cancel_invoice"),
    path(
        "cancelled/", views_cancellation.cancelled_invoices_list, name="cancelled_list"
    ),
    path(
        "cancellation/<int:pk>/",
        views_cancellation.cancellation_detail,
        name="cancellation_detail",
    ),
    # invoice audit
    path("audits/", views_.audit_home, name="audit_home"),
    path("audit-fetch/", views_.fetch_audit_tables, name="audit_fetch"),
    path("audits/create/", views_.AuditTableCreateView.as_view(), name="audit_create"),
    path(
        "audits/manager/<int:pk>/",
        views_.InvoiceManager.as_view(),
        name="invoice_manager",
    ),
    path("audits/detail/<int:pk>/", views_.audit_detail, name="audit_detail"),
    path(
        "audits/fetch-details/<int:pk>/",
        views_.fetch_audit_details,
        name="fetch_audit_details",
    ),
    path(
        "audits/delete/<int:pk>/",
        views_.AuditTableDeleteView.as_view(),
        name="audit_delete",
    ),
    # path("submit-conversions/", views_.submit_conversions_view, name="submit_conversions"),
    # Return Invoices
    path("returns/", views_return.home, name="return_home"),
    path(
        "returns/fetch/",
        views_return.fetch_return_invoices,
        name="fetch_return_invoices",
    ),
    path(
        "returns/create/",
        views_return.ReturnInvoiceCreateView.as_view(),
        name="return_create",
    ),
    path(
        "returns/detail/<int:pk>/",
        views_return.ReturnInvoiceDetailView.as_view(),
        name="return_detail",
    ),
    path(
        "returns/auto-create/<int:invoice_id>/",
        views_return.create_auto_return_invoice,
        name="create_auto_return_invoice",
    ),
    path(
        "returns/stock-adjustment/<int:pk>/",
        views_return.ReturnStockAdjustmentView.as_view(),
        name="return_stock_adjustment",
    ),
    path(
        "returns/update-item/<int:item_id>/",
        views_return.update_return_item,
        name="update_return_item",
    ),
    path(
        "returns/submit/<int:pk>/",
        views_return.submit_return_invoice,
        name="submit_return_invoice",
    ),
    path(
        "returns/delete/<int:pk>/",
        views_return.delete_return_invoice,
        name="delete_return_invoice",
    ),
    # Invoice Report
    path("report/", views_report.invoice_report, name="report"),
    path("report/fetch/", views_report.invoice_report_fetch, name="report_fetch"),
    path(
        "report/cancled/fetch/",
        views_report.invoice_cancled_report_fetch,
        name="report_cancled_fetch",
    ),
    path(
        "report/return/fetch/",
        views_report.invoice_return_report_fetch,
        name="report_return_fetch",
    ),
    # Search Invoices
    path("search_invoice/", views.search_invoices_home, name="search_invoices_home"),
    path(
        "search_invoice/fetch/",
        views.fetch_search_invoices,
        name="fetch_search_invoices",
    ),
]
