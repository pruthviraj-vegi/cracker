"""
URL patterns for the report app.
"""

from django.urls import path
from . import statements, views, views_jobs

app_name = "report"

urlpatterns = [
    # ── PDF rendering (synchronous) ────────────────────────────
    path("invoice/<int:pk>/", views.create_invoice, name="invoice_pdf"),
    path("invoice/<int:pk>/direct-print/", views.direct_print_invoice, name="direct_print_invoice"),
    path("estimate/<int:pk>/", views.estimate_invoice, name="estimate_pdf"),
    path("estimate/<int:pk>/direct-print/", views.direct_print_estimate, name="direct_print_estimate"),
    path("barcode/<int:pk>/", views.generate_barcode, name="barcode"),
    path("customers/pdf/", views.generate_customers_pdf, name="customers_pdf"),
    path(
        "credit/customers/pdf/", views.generate_credit_pdf, name="credit_customers_pdf"
    ),
    path(
        "credit/individual/<int:pk>/",
        views.generate_credit_ind_pdf,
        name="credit_ind_pdf",
    ),
    path("suppliers/pdf/", views.generate_suppliers_pdf, name="suppliers_pdf"),
    path("variants/pdf/", views.generate_variants_pdf, name="variants_pdf"),
    path(
        "purchase-orders/pdf/",
        views.generate_purchase_orders_pdf,
        name="purchase_orders_pdf",
    ),
    path(
        "supplier/individual/<int:pk>/",
        views.generate_supplier_ind_pdf,
        name="supplier_ind_pdf",
    ),
    path(
        "invoice/report/pdf/",
        views.generate_invoice_report_pdf,
        name="invoice_report_pdf",
    ),
    path(
        "damaged-stock/pdf/",
        views.generate_damaged_stock_pdf,
        name="damaged_stock_pdf",
    ),
    # ── Async PDF jobs ─────────────────────────────────────────
    path(
        "variants/pdf/request/",
        views_jobs.request_variants_pdf,
        name="request_variants_pdf",
    ),
    path(
        "invoice/report/pdf/request/",
        views_jobs.request_invoice_report_pdf,
        name="request_invoice_report_pdf",
    ),
    path(
        "pdf-job/<int:job_id>/status/",
        views_jobs.check_pdf_job_status,
        name="pdf_job_status",
    ),
    path("downloads/", views_jobs.downloads_page, name="downloads_page"),
    path("downloads/fetch/", views_jobs.downloads_fetch, name="downloads_fetch"),
    path(
        "downloads/<int:job_id>/delete/",
        views_jobs.delete_pdf_job,
        name="delete_pdf_job",
    ),

    # ── WhatsApp / messaging ───────────────────────────────────
    path("send-invoice/<int:pk>/", statements.send_invoice, name="send_invoice"),
    path(
        "send-statement/<int:pk>/", statements.send_statement, name="send_pdf_statement"
    ),
    path("send-text/<int:pk>/", statements.send_text, name="send_text"),
    path("send-balance/<int:pk>/", statements.balance, name="send_balance"),
]
