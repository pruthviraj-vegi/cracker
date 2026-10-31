"""Celery tasks for async PDF generation.

Start the worker:
    celery -A Billing worker -l info
"""

import logging
from datetime import datetime, date

from celery import shared_task
from django.core.files.base import ContentFile
from django.utils import timezone

from notification.services import notify

from .models import PdfJob, StatusChoices
from .views import (
    build_variants_context,
    generate_pdf_bytes,
)
from .helper import build_invoice_report_context


logger = logging.getLogger(__name__)


def _parse_date(val):
    """Accept date object or flexible date string."""
    if isinstance(val, (datetime, timezone.datetime)):
        return val.date()
    if isinstance(val, date):
        return val
    from base.utility import parse_flexible_date
    res = parse_flexible_date(val)
    if res:
        return res
    return datetime.strptime(str(val), "%Y-%m-%d").date()


@shared_task(bind=True, max_retries=2)
def generate_invoice_report_pdf_task(self, job_id):
    """Generate invoice report PDF asynchronously."""
    try:
        job = PdfJob.objects.get(id=job_id)
    except PdfJob.DoesNotExist:
        logger.error("PdfJob %s not found — aborting.", job_id)
        return

    try:
        job.status = StatusChoices.PROCESSING
        job.save(update_fields=["status"])

        # ── Build context (pure, no request) ──────────────
        start_date = _parse_date(job.parameters["start_date"])
        end_date = _parse_date(job.parameters["end_date"])
        context = build_invoice_report_context(start_date, end_date)

        # ── Generate PDF bytes ─────────────────────────────
        pdf_bytes = generate_pdf_bytes("invoice_report_pdf.html", context)

        # ── Save to media/pdf_jobs/ ────────────────────────
        filename = (
            f"invoice_report_"
            f"{start_date.strftime('%Y%m%d')}_"
            f"{end_date.strftime('%Y%m%d')}_"
            f"{job.id}.pdf"
        )
        job.file.save(filename, ContentFile(pdf_bytes), save=False)
        job.status = StatusChoices.DONE
        job.save(update_fields=["status", "file"])

        # ── Notify user ────────────────────────────────────
        notify(
            user=job.created_by,
            notification_type="pdf_ready",
            title="Invoice Report Ready",
            message=(
                f'Invoice report from {start_date.strftime("%d %b %Y")} '
                f'to {end_date.strftime("%d %b %Y")} is ready.'
            ),
            action_label="Download PDF",
            action_url=job.file.url,
            linked_object=job,
        )

        logger.info("PdfJob %s completed successfully.", job_id)

    except Exception as exc:
        logger.exception(
            "PdfJob %s failed (attempt %s): %s", job_id, self.request.retries + 1, exc
        )

        # ── Retry if attempts remain (don't notify yet) ────
        if self.request.retries < self.max_retries:
            job.status = StatusChoices.PROCESSING
            job.error_message = f"Retry {self.request.retries + 1}: {str(exc)[:200]}"
            job.save(update_fields=["status", "error_message"])
            raise self.retry(exc=exc, countdown=10)

        # ── Final failure — notify user ────────────────────
        job.status = StatusChoices.FAILED
        job.error_message = str(exc)[:500]
        job.save(update_fields=["status", "error_message"])

        notify(
            user=job.created_by,
            notification_type="pdf_failed",
            title="Invoice Report Failed",
            message=f"Could not generate invoice report. Error: {str(exc)[:100]}",
            linked_object=job,
        )


@shared_task(bind=True, max_retries=2)
def generate_variants_pdf_task(self, job_id):
    """Generate variants PDF asynchronously."""
    try:
        job = PdfJob.objects.get(id=job_id)
    except PdfJob.DoesNotExist:
        logger.error("PdfJob %s not found — aborting.", job_id)
        return

    try:
        job.status = StatusChoices.PROCESSING
        job.save(update_fields=["status"])

        # ── Build context (pure, no request) ──────────────
        context = build_variants_context(job.parameters)

        # ── Generate PDF bytes ─────────────────────────────
        pdf_bytes = generate_pdf_bytes("variants_pdf.html", context)

        # ── Save to media/pdf_jobs/ ────────────────────────
        filename = f"variants_report_{job.id}.pdf"
        job.file.save(filename, ContentFile(pdf_bytes), save=False)
        job.status = StatusChoices.DONE
        job.save(update_fields=["status", "file"])

        # ── Notify user ────────────────────────────────────
        notify(
            user=job.created_by,
            notification_type="pdf_ready",
            title="Variants Report Ready",
            message="Your variants report is ready for download.",
            action_label="Download PDF",
            action_url=job.file.url,
            linked_object=job,
        )

        logger.info("PdfJob %s (variants) completed successfully.", job_id)

    except Exception as exc:
        logger.exception(
            "PdfJob %s failed (attempt %s): %s", job_id, self.request.retries + 1, exc
        )

        # ── Retry if attempts remain ───────────────────────
        if self.request.retries < self.max_retries:
            job.status = StatusChoices.PROCESSING
            job.error_message = f"Retry {self.request.retries + 1}: {str(exc)[:200]}"
            job.save(update_fields=["status", "error_message"])
            raise self.retry(exc=exc, countdown=10)

        # ── Final failure — notify user ────────────────────
        job.status = StatusChoices.FAILED
        job.error_message = str(exc)[:500]
        job.save(update_fields=["status", "error_message"])

        notify(
            user=job.created_by,
            notification_type="pdf_failed",
            title="Variants Report Failed",
            message=f"Could not generate variants report. Error: {str(exc)[:100]}",
            linked_object=job,
        )
