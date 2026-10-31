"""Models for storing generated PDF records (invoices and customer statements)."""

import logging

from django.contrib.auth import get_user_model
from django.db import models

from customer.models import Customer
from invoice.models import Invoice

logger = logging.getLogger(__name__)


User = get_user_model()


class InvoicePDF(models.Model):
    """Stores generated PDF URLs for invoices"""

    invoice = models.OneToOneField(
        Invoice,
        on_delete=models.CASCADE,
        related_name="pdf",
        help_text="Associated invoice",
    )
    pdf_url = models.URLField(
        max_length=500, help_text="Cloudflare R2 URL of the generated PDF"
    )
    filename = models.CharField(max_length=255, help_text="PDF filename in storage")
    generated_at = models.DateTimeField(
        auto_now_add=True, help_text="When the PDF was generated"
    )
    generated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_pdfs",
        help_text="User who triggered PDF generation",
    )
    last_invoice_updated_at = models.DateTimeField(
        help_text="Invoice updated_at timestamp when PDF was generated"
    )
    file_size = models.PositiveIntegerField(
        null=True, blank=True, help_text="PDF file size in bytes"
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether this PDF is the current active version"
    )

    class Meta:
        db_table = "invoice_pdf"
        ordering = ["-generated_at"]
        indexes = [
            models.Index(fields=["invoice", "is_active"]),
            models.Index(fields=["generated_at"]),
            models.Index(fields=["last_invoice_updated_at"]),
        ]
        verbose_name = "Invoice PDF"
        verbose_name_plural = "Invoice PDFs"

    def __str__(self):
        return f"PDF for {self.invoice.invoice_number}"

    def delete_file_and_record(self):
        """Delete PDF file from R2 storage (if exists) and hard-delete record."""
        if self.pdf_url:
            try:
                from api.cloudflare import delete_from_r2, BucketType
                delete_from_r2(self.pdf_url, bucket_type=BucketType.INVOICE)
            except Exception as e:
                logger.warning("Failed to delete R2 file for InvoicePDF %s: %s", self.id, e)
        return super().delete()

    def delete(self, using=None, keep_parents=False):
        """Override delete to ensure R2 file deletion and hard delete."""
        return self.delete_file_and_record()

    def is_pdf_outdated(self):
        """
        Check if the invoice has been modified since PDF generation.
        Returns True if PDF needs regeneration, False otherwise.
        """
        if not self.last_invoice_updated_at:
            return True

        # Compare invoice's current updated_at with stored timestamp
        return self.invoice.updated_at > self.last_invoice_updated_at

    @classmethod
    def get_valid_pdf(cls, invoice):
        """
        Get existing PDF if valid, return None if needs regeneration.
        A PDF is valid if:
        1. It exists
        2. It's active
        3. Invoice hasn't been modified since PDF generation
        """
        try:
            pdf = cls.objects.get(invoice=invoice, is_active=True)

            # Check if PDF is outdated
            if pdf.is_pdf_outdated():
                logger.debug("PDF for invoice %s is outdated", invoice.invoice_number)
                return None

            return pdf

        except cls.DoesNotExist:
            return None

    @classmethod
    def create_pdf_record(
        cls, invoice, pdf_url, filename, generated_by=None, file_size=None
    ):
        """
        Create or update PDF record with current invoice timestamp.
        Uses update_or_create to avoid duplicate key errors.
        """
        pdf_record, created = cls.objects.update_or_create(
            invoice=invoice,
            defaults={
                "pdf_url": pdf_url,
                "filename": filename,
                "last_invoice_updated_at": invoice.updated_at,
                "generated_by": generated_by,
                "file_size": file_size,
                "is_active": True,
            },
        )

        action = "Created" if created else "Updated"
        logger.debug("%s PDF record for invoice %s", action, invoice.invoice_number)

        return pdf_record


class CustomerStatementPDF(models.Model):
    """Stores generated PDF URLs for customer statements"""

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="statement_pdfs",
        help_text="Associated customer",
    )
    from_date = models.DateField(help_text="Statement start date")
    to_date = models.DateField(help_text="Statement end date")
    closing_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Customer's balance at to_date when PDF was generated",
    )
    pdf_url = models.URLField(
        max_length=500, help_text="Cloudflare R2 URL of the generated PDF"
    )
    filename = models.CharField(max_length=255, help_text="PDF filename in storage")
    generated_at = models.DateTimeField(
        auto_now_add=True, help_text="When the PDF was generated"
    )
    generated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_statement_pdfs",
        help_text="User who triggered PDF generation",
    )
    file_size = models.PositiveIntegerField(
        null=True, blank=True, help_text="PDF file size in bytes"
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether this PDF is the current active version"
    )

    class Meta:
        db_table = "statement_pdf"
        ordering = ["-generated_at"]
        indexes = [
            models.Index(fields=["customer", "from_date", "to_date", "is_active"]),
            models.Index(fields=["customer", "closing_balance"]),
            models.Index(fields=["generated_at"]),
        ]
        # Ensure one active statement per customer per date range
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "from_date", "to_date"],
                condition=models.Q(is_active=True),
                name="unique_active_statement_per_date_range",
            )
        ]
        verbose_name = "Statement PDF"
        verbose_name_plural = "Statement PDFs"

    def __str__(self):
        return f"Statement for {self.customer} ({self.from_date} to {self.to_date})"

    def delete_file_and_record(self):
        """Delete statement PDF file from R2 storage (if exists) and hard-delete record."""
        if self.pdf_url:
            try:
                from api.cloudflare import delete_from_r2, BucketType
                delete_from_r2(self.pdf_url, bucket_type=BucketType.STATEMENT)
            except Exception as e:
                logger.warning("Failed to delete R2 file for CustomerStatementPDF %s: %s", self.id, e)
        return super().delete()

    def delete(self, using=None, keep_parents=False):
        """Override delete to ensure R2 file deletion and hard delete."""
        return self.delete_file_and_record()

    def is_balance_outdated(self, current_balance):
        """
        Check if the customer's balance has changed since PDF generation.
        Returns True if PDF needs regeneration, False otherwise.
        """
        return self.closing_balance != current_balance

    @classmethod
    def get_valid_pdf(cls, customer, from_date, to_date, current_balance):
        """
        Get existing PDF if valid, return None if needs regeneration.
        A PDF is valid if:
        1. It exists for this customer and date range
        2. It's active
        3. Balance hasn't changed since PDF generation
        """
        try:
            pdf = cls.objects.get(
                customer=customer,
                from_date=from_date,
                to_date=to_date,
                is_active=True,
            )

            # Check if balance has changed
            if pdf.is_balance_outdated(current_balance):
                logger.debug(
                    "Statement PDF for customer %s is outdated "
                    "(balance changed from %s to %s)",
                    customer.id,
                    pdf.closing_balance,
                    current_balance,
                )
                pdf.delete()
                return None

            logger.debug(
                "Using cached statement PDF for customer %s (%s to %s)",
                customer.id,
                from_date,
                to_date,
            )
            return pdf

        except cls.DoesNotExist:
            return None

    @classmethod
    def invalidate_all_customer_pdfs(cls, customer):
        """
        Delete all cached PDFs for a customer when balance changes.
        This ensures no outdated statements exist in R2 or database.
        """
        deleted_count = 0
        for pdf in cls.objects.filter(customer=customer):
            pdf.delete()
            deleted_count += 1
        if deleted_count > 0:
            logger.debug(
                "Invalidated %s cached statement PDFs for customer %s",
                deleted_count,
                customer.id,
            )
        return deleted_count

    @classmethod
    def create_pdf_record(
        cls,
        customer,
        from_date,
        to_date,
        closing_balance,
        pdf_url,
        filename,
        generated_by=None,
        file_size=None,
    ):
        """
        Create PDF record with current balance.
        Uses update_or_create to handle the date range uniqueness.
        """
        pdf_record, created = cls.objects.update_or_create(
            customer=customer,
            from_date=from_date,
            to_date=to_date,
            defaults={
                "closing_balance": closing_balance,
                "pdf_url": pdf_url,
                "filename": filename,
                "generated_by": generated_by,
                "file_size": file_size,
                "is_active": True,
            },
        )

        action = "Created" if created else "Updated"
        logger.debug(
            "%s statement PDF record for customer %s (%s to %s, balance: %s)",
            action,
            customer.id,
            from_date,
            to_date,
            closing_balance,
        )

        return pdf_record


class StatusChoices(models.TextChoices):
    """Status choices for PDF job"""

    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"


class PdfJob(models.Model):
    """PDF job model"""

    status = models.CharField(
        max_length=20, choices=StatusChoices.choices, default=StatusChoices.PENDING
    )
    job_type = models.CharField(max_length=100)  # e.g. 'invoice_report'
    parameters = models.JSONField(default=dict)  # start_date, end_date, filters etc.

    file = models.FileField(upload_to="pdf_jobs/", null=True, blank=True)
    error_message = models.TextField(blank=True)

    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def title(self):
        """Returns a human-readable title including dates if available."""
        name = self.job_type.replace("_", " ").title()
        start = self.parameters.get("start_date")
        end = self.parameters.get("end_date")
        if start and end:
            return f"{name} ({start} to {end})"
        return name

    def __str__(self):
        return f"{self.job_type} | {self.status} | {self.created_by}"

    @classmethod
    def cleanup_stale_jobs(cls, minutes=10):
        """Mark jobs stuck in pending/processing for too long as failed.
        Delegates to PdfCleanupService.
        """
        from report.services import PdfCleanupService

        return PdfCleanupService.cleanup_stale_jobs(minutes=minutes)

    @classmethod
    def cleanup_old(cls, days=30):
        """Delete completed/failed PDF jobs older than `days` days.
        Delegates to PdfCleanupService.
        """
        from report.services import PdfCleanupService

        return PdfCleanupService.cleanup_old(days=days)

    def delete_file_and_job(self):
        """Delete file from storage / Cloudflare R2 (if exists) and hard-delete DB row."""
        if self.file:
            # 1. Delete from Django storage (local filesystem or storage backend)
            try:
                self.file.delete(save=False)
            except Exception as e:
                logger.warning("Could not delete file for PdfJob %s: %s", self.id, e)

            # 2. Delete from Cloudflare R2 storage if file URL exists
            try:
                from api.cloudflare import delete_from_r2, BucketType
                if hasattr(self.file, "url") and self.file.url:
                    delete_from_r2(self.file.url, bucket_type=BucketType.INVOICE)
            except Exception as e:
                logger.debug("R2 file deletion skipped/failed for PdfJob %s: %s", self.id, e)

        # 3. Hard delete database row
        return super().delete()

    def delete(self, using=None, keep_parents=False):
        """Override delete to ensure storage/R2 file cleanup and hard delete."""
        return self.delete_file_and_job()
