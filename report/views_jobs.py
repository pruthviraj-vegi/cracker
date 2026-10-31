"""Views for async PDF job management: request, status polling, downloads."""

import logging

from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST

from base.getDates import getDates
from base.utility import render_paginated_response

from .models import PdfJob, StatusChoices

logger = logging.getLogger(__name__)


@require_POST
def request_variants_pdf(request):
    """Create a PdfJob and fire Celery task for async variants PDF.

    Returns existing job if one is already pending/processing with
    the same filter parameters.
    """
    # Capture current filter/sort params from the request
    job_params = {}
    filter_keys = (
        "search",
        "category",
        "color",
        "size",
        "status",
        "stock",
        "sort",
        "min_price",
        "max_price",
        "discount_only",
        "discount_type",
        "min_discount",
        "max_discount",
    )
    for key in filter_keys:
        val = request.GET.get(key, "") or request.POST.get(key, "")
        if val:
            job_params[key] = val

    # ── Clean up stale jobs ────────────────────────────────────
    PdfJob.cleanup_stale_jobs()

    # ── Prevent duplicate jobs ─────────────────────────────────
    existing = PdfJob.objects.filter(
        created_by=request.user,
        job_type="variants_report",
        status__in=[StatusChoices.PENDING, StatusChoices.PROCESSING],
        parameters=job_params,
    ).first()

    if existing:
        return JsonResponse(
            {
                "job_id": str(existing.id),
                "status": existing.status,
                "message": "A report is already being generated.",
            }
        )

    # ── Create new job & dispatch ──────────────────────────────
    job = PdfJob.objects.create(
        created_by=request.user,
        job_type="variants_report",
        parameters=job_params,
    )

    from .tasks import generate_variants_pdf_task

    generate_variants_pdf_task.delay(str(job.id))

    return JsonResponse(
        {
            "job_id": str(job.id),
            "status": "pending",
            "message": "PDF generation started. You will be notified when ready.",
        }
    )


@require_POST
def request_invoice_report_pdf(request):
    """Create a PdfJob and fire Celery task for async invoice report PDF.

    Returns existing job if one is already pending/processing.
    """
    start_date, end_date = getDates(request)

    job_params = {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
    }

    # ── Clean up stale jobs (server/worker restarts) ──────────
    PdfJob.cleanup_stale_jobs()

    # ── Prevent duplicate jobs ─────────────────────────────────
    existing = PdfJob.objects.filter(
        created_by=request.user,
        job_type="invoice_report",
        status__in=[StatusChoices.PENDING, StatusChoices.PROCESSING],
        parameters=job_params,
    ).first()

    if existing:
        return JsonResponse(
            {
                "job_id": str(existing.id),
                "status": existing.status,
                "message": "A report is already being generated.",
            }
        )

    # ── Create new job & dispatch ──────────────────────────────
    job = PdfJob.objects.create(
        created_by=request.user,
        job_type="invoice_report",
        parameters=job_params,
    )

    from .tasks import generate_invoice_report_pdf_task

    generate_invoice_report_pdf_task.delay(str(job.id))

    return JsonResponse(
        {
            "job_id": str(job.id),
            "status": "pending",
            "message": "PDF generation started. You will be notified when ready.",
        }
    )


def check_pdf_job_status(request, job_id):
    """Poll this endpoint to check PDF generation progress."""
    job = get_object_or_404(PdfJob, id=job_id, created_by=request.user)

    response_data = {
        "job_id": str(job.id),
        "status": job.status,
    }

    if job.status == StatusChoices.DONE and job.file:
        response_data["download_url"] = job.file.url
    elif job.status == StatusChoices.FAILED:
        response_data["error"] = job.error_message

    return JsonResponse(response_data)


def downloads_page(request):
    """Render the main downloads page layout."""
    return render(request, "report/downloads_page.html")


def downloads_fetch(request):
    """Fetch PDF jobs for the table over AJAX."""
    PdfJob.cleanup_stale_jobs()
    jobs = PdfJob.objects.filter(created_by=request.user).order_by("-created_at")

    return render_paginated_response(request, jobs, "report/downloads_fetch.html", 20)


@require_POST
def delete_pdf_job(request, job_id):
    """Delete a PdfJob and its associated PDF file from disk/storage."""
    job = get_object_or_404(PdfJob, id=job_id, created_by=request.user)
    job.delete_file_and_job()
    return JsonResponse({"success": True, "message": "PDF file deleted successfully."})
