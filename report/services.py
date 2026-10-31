"""Services for PDF job management and cleanup operations."""

import logging

from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


class PdfCleanupService:
    """Handles cleanup and maintenance of PDF jobs."""

    @staticmethod
    def cleanup_stale_jobs(minutes=10):
        """Mark jobs stuck in pending/processing for too long as failed.

        Handles orphaned jobs caused by server/worker restarts during
        development or unexpected crashes in production.

        Args:
            minutes: How many minutes before a job is considered stale.

        Returns:
            int: Number of jobs marked as failed.
        """
        from report.models import PdfJob, StatusChoices

        stale_cutoff = timezone.now() - timedelta(minutes=minutes)
        count = PdfJob.objects.filter(
            status__in=[StatusChoices.PENDING, StatusChoices.PROCESSING],
            created_at__lt=stale_cutoff,
        ).update(
            status=StatusChoices.FAILED,
            error_message="Job timed out — likely caused by a server or worker restart.",
        )
        if count:
            logger.warning("Cleaned up %d stale PDF job(s).", count)
        return count

    @staticmethod
    def cleanup_old(days=30):
        """Delete completed/failed PDF jobs older than `days` days.

        Also removes the associated PDF files from storage.

        Returns:
            int: Number of jobs deleted.
        """
        from report.models import PdfJob, StatusChoices

        cutoff = timezone.now() - timedelta(days=days)
        old_jobs = PdfJob.objects.filter(
            created_at__lt=cutoff,
            status__in=[StatusChoices.DONE, StatusChoices.FAILED],
        )

        ids_to_delete = []
        for job in old_jobs.iterator():
            if job.file:
                try:
                    job.file.delete(save=False)
                except Exception:
                    logger.warning("Could not delete file for PdfJob %s.", job.id)
            ids_to_delete.append(job.id)

        count = 0
        if ids_to_delete:
            count, _ = PdfJob.objects.filter(id__in=ids_to_delete).delete()
        if count:
            logger.info("Deleted %d old PDF job(s) older than %d days.", count, days)
        return count
