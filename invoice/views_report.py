"""
Views for invoice report generation.
"""

import logging

from django.shortcuts import render

from base.decorators import required_permission
from base.getDates import getDates
from base.utility import render_paginated_response
from invoice.services import (
    get_invoice_cancled_data,
    get_invoice_report_data,
    get_invoice_return_data,
)


logger = logging.getLogger(__name__)


@required_permission("invoice.view_audits")
def invoice_report(request):
    """Render the invoice report main page."""
    return render(request, "invoice_report/main.html")


@required_permission("invoice.view_audits")
def invoice_report_fetch(request):
    """AJAX endpoint to fetch invoice report data."""
    start_date, end_date = getDates(request)
    date_range = [start_date, end_date]
    invoices = get_invoice_report_data(date_range)

    return render_paginated_response(
        request,
        invoices,
        "invoice_report/fetch.html",
        10,
    )


@required_permission("invoice.view_audits")
def invoice_cancled_report_fetch(request):
    """AJAX endpoint to fetch cancelled invoice report data."""
    start_date, end_date = getDates(request)
    date_range = [start_date, end_date]
    invoices = get_invoice_cancled_data(date_range)

    return render_paginated_response(
        request,
        invoices,
        "invoice_report/fetch.html",
        10,
    )


@required_permission("invoice.view_audits")
def invoice_return_report_fetch(request):
    """AJAX endpoint to fetch return invoice report data."""
    start_date, end_date = getDates(request)
    date_range = [start_date, end_date]
    invoices = get_invoice_return_data(date_range)

    return render_paginated_response(
        request,
        invoices,
        "invoice_report/return_fetch.html",
        10,
    )
