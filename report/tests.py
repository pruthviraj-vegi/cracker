from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from customer.models import Customer, CustomerCreditSummary
from notification.models import MessageLog, MessageStatusChoices, Notification
from notification.tasks import send_customer_message_task

User = get_user_model()


class ReportStatementsTests(TestCase):
    """
    Test cases for asynchronous report statements and messaging endpoints.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            first_name="Test",
            phone_number="1234567890",
            password="testpassword",
            email="test@example.com",
        )
        self.customer = Customer.objects.create(
            name="Test Customer", phone_number="9999999999", created_by=self.user
        )

    def test_balance_requires_login(self):
        response = self.client.get(
            reverse("report:send_balance", kwargs={"pk": self.customer.pk})
        )
        self.assertEqual(response.status_code, 302)

    @patch("report.statements.send_customer_message_task.delay")
    def test_balance_queues_task_and_creates_log(self, mock_delay):
        summary, _ = CustomerCreditSummary.objects.get_or_create(customer=self.customer)
        summary.balance_amount = 250.50
        summary.save()

        self.client.login(phone_number="1234567890", password="testpassword")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(
                reverse("report:send_balance", kwargs={"pk": self.customer.pk})
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("queued in background", data["message"])

        mock_delay.assert_called_once()

        log = MessageLog.objects.get(id=data["log_id"])
        self.assertEqual(log.customer, self.customer)
        self.assertEqual(log.message_type, "balance")

    @patch("report.statements.send_customer_message_task.delay")
    def test_balance_prevents_duplicate_sending(self, mock_delay):
        self.client.login(phone_number="1234567890", password="testpassword")

        with self.captureOnCommitCallbacks(execute=True):
            res1 = self.client.get(
                reverse("report:send_balance", kwargs={"pk": self.customer.pk})
            )
        self.assertTrue(res1.json()["success"])
        self.assertEqual(mock_delay.call_count, 1)

        with self.captureOnCommitCallbacks(execute=True):
            res2 = self.client.get(
                reverse("report:send_balance", kwargs={"pk": self.customer.pk})
            )
        self.assertFalse(res2.json()["success"])
        self.assertIn("already in progress or was sent recently", res2.json()["message"])
        self.assertEqual(mock_delay.call_count, 1)

    @patch("notification.tasks.send_template")
    def test_send_customer_message_task_executes_successfully(self, mock_send_template):
        mock_send_template.return_value = {"success": True}

        log = MessageLog.objects.create(
            user=self.user,
            customer=self.customer,
            message_type="balance",
            phone_number=self.customer.phone_number,
        )

        send_customer_message_task(log.id)

        log.refresh_from_db()
        self.assertEqual(log.status, MessageStatusChoices.SENT)

        notif = Notification.objects.filter(user=self.user).first()
        self.assertIsNotNone(notif)
        self.assertIn("Balance Sent Successfully", notif.title)

    @patch("report.statements.send_customer_message_task.delay")
    def test_broker_down_marks_log_as_failed(self, mock_delay):
        mock_delay.side_effect = Exception("Connection to Redis refused")

        self.client.login(phone_number="1234567890", password="testpassword")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(
                reverse("report:send_balance", kwargs={"pk": self.customer.pk})
            )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        log = MessageLog.objects.get(id=data["log_id"])
        self.assertEqual(log.status, MessageStatusChoices.FAILED)
        self.assertIn("Broker unavailable", log.error_message)

    @patch("notification.tasks.send_template")
    def test_task_failure_marks_log_failed_and_notifies(self, mock_send_template):
        mock_send_template.return_value = {"success": False, "detail": "Invalid phone number"}

        log = MessageLog.objects.create(
            user=self.user,
            customer=self.customer,
            message_type="balance",
            phone_number=self.customer.phone_number,
        )

        with patch.object(send_customer_message_task.request, "retries", 2):
            send_customer_message_task(log.id)

        log.refresh_from_db()
        self.assertEqual(log.status, MessageStatusChoices.FAILED)

        notif = Notification.objects.filter(user=self.user, notification_type="balance_failed").first()
        self.assertIsNotNone(notif)
        self.assertIn("Delivery Failed", notif.title)

    @patch("notification.tasks.send_template")
    @patch("notification.tasks.generate_statement_pdf")
    def test_statement_message_type_execution(self, mock_pdf, mock_send_template):
        mock_pdf.return_value = {"url": "http://example.com/stmt.pdf", "filename": "stmt.pdf"}
        mock_send_template.return_value = {"success": True}

        log = MessageLog.objects.create(
            user=self.user,
            customer=self.customer,
            message_type="statement",
            phone_number=self.customer.phone_number,
            payload_data={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        )

        send_customer_message_task(log.id)

        log.refresh_from_db()
        self.assertEqual(log.status, MessageStatusChoices.SENT)
        mock_pdf.assert_called_once()
        mock_send_template.assert_called_once()


class PdfCleanupServiceTests(TestCase):
    """Tests for PdfCleanupService.cleanup_stale_jobs() and .cleanup_old()."""

    def setUp(self):
        from report.models import PdfJob, StatusChoices
        self.StatusChoices = StatusChoices
        self.PdfJob = PdfJob
        self.user = User.objects.create_user(
            first_name="Cleanup",
            phone_number="9999999991",
            password="testpass123",
        )

    def test_cleanup_stale_marks_old_pending_as_failed(self):
        job = self.PdfJob.objects.create(
            created_by=self.user,
            job_type="test_job",
            status=self.StatusChoices.PENDING,
        )
        self.PdfJob.objects.filter(id=job.id).update(
            created_at=timezone.now() - timedelta(minutes=20)
        )
        from report.services import PdfCleanupService
        count = PdfCleanupService.cleanup_stale_jobs(minutes=10)
        self.assertEqual(count, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, self.StatusChoices.FAILED)
        self.assertIn("timed out", job.error_message)

    def test_cleanup_stale_ignores_recent_jobs(self):
        job = self.PdfJob.objects.create(
            created_by=self.user,
            job_type="test_job",
            status=self.StatusChoices.PENDING,
        )
        from report.services import PdfCleanupService
        count = PdfCleanupService.cleanup_stale_jobs(minutes=30)
        self.assertEqual(count, 0)
        job.refresh_from_db()
        self.assertEqual(job.status, self.StatusChoices.PENDING)

    def test_cleanup_stale_marks_processing_as_failed(self):
        job = self.PdfJob.objects.create(
            created_by=self.user,
            job_type="test_job",
            status=self.StatusChoices.PROCESSING,
        )
        self.PdfJob.objects.filter(id=job.id).update(
            created_at=timezone.now() - timedelta(minutes=15)
        )
        from report.services import PdfCleanupService
        count = PdfCleanupService.cleanup_stale_jobs(minutes=5)
        self.assertEqual(count, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, self.StatusChoices.FAILED)

    def test_cleanup_stale_ignores_done_jobs(self):
        job = self.PdfJob.objects.create(
            created_by=self.user,
            job_type="test_job",
            status=self.StatusChoices.DONE,
        )
        self.PdfJob.objects.filter(id=job.id).update(
            created_at=timezone.now() - timedelta(minutes=20)
        )
        from report.services import PdfCleanupService
        count = PdfCleanupService.cleanup_stale_jobs(minutes=10)
        self.assertEqual(count, 0)

    def test_cleanup_old_deletes_completed_jobs(self):
        job = self.PdfJob.objects.create(
            created_by=self.user,
            job_type="test_job",
            status=self.StatusChoices.DONE,
        )
        self.PdfJob.objects.filter(id=job.id).update(
            created_at=timezone.now() - timedelta(days=40)
        )
        from report.services import PdfCleanupService
        count = PdfCleanupService.cleanup_old(days=30)
        self.assertEqual(count, 1)
        self.assertFalse(self.PdfJob.objects.filter(id=job.id).exists())

    def test_cleanup_old_ignores_recent_completed(self):
        job = self.PdfJob.objects.create(
            created_by=self.user,
            job_type="test_job",
            status=self.StatusChoices.DONE,
        )
        from report.services import PdfCleanupService
        count = PdfCleanupService.cleanup_old(days=30)
        self.assertEqual(count, 0)
        self.assertTrue(self.PdfJob.objects.filter(id=job.id).exists())

    def test_cleanup_old_deletes_failed_jobs(self):
        job = self.PdfJob.objects.create(
            created_by=self.user,
            job_type="test_job",
            status=self.StatusChoices.FAILED,
        )
        self.PdfJob.objects.filter(id=job.id).update(
            created_at=timezone.now() - timedelta(days=40)
        )
        from report.services import PdfCleanupService
        count = PdfCleanupService.cleanup_old(days=30)
        self.assertEqual(count, 1)


class PdfJobViewsTests(TestCase):
    """Tests for PdfJob views including delete_pdf_job."""

    def setUp(self):
        from report.models import PdfJob, StatusChoices
        self.PdfJob = PdfJob
        self.StatusChoices = StatusChoices
        self.user = User.objects.create_user(
            first_name="JobUser",
            phone_number="9999999992",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            first_name="OtherUser",
            phone_number="9999999993",
            password="testpass123",
        )

    def test_delete_pdf_job_requires_post(self):
        self.client.login(phone_number="9999999992", password="testpass123")
        job = self.PdfJob.objects.create(
            created_by=self.user,
            job_type="test_job",
            status=self.StatusChoices.DONE,
        )
        response = self.client.get(
            reverse("report:delete_pdf_job", kwargs={"job_id": job.id})
        )
        self.assertEqual(response.status_code, 405)

    def test_delete_pdf_job_success(self):
        self.client.login(phone_number="9999999992", password="testpass123")
        job = self.PdfJob.objects.create(
            created_by=self.user,
            job_type="test_job",
            status=self.StatusChoices.DONE,
        )
        response = self.client.post(
            reverse("report:delete_pdf_job", kwargs={"job_id": job.id})
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertFalse(self.PdfJob.objects.filter(id=job.id).exists())

    def test_delete_pdf_job_other_user_forbidden(self):
        self.client.login(phone_number="9999999993", password="testpass123")
        job = self.PdfJob.objects.create(
            created_by=self.user,
            job_type="test_job",
            status=self.StatusChoices.DONE,
        )
        response = self.client.post(
            reverse("report:delete_pdf_job", kwargs={"job_id": job.id})
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(self.PdfJob.objects.filter(id=job.id).exists())

    @patch("report.tasks.generate_variants_pdf_task.delay")
    def test_request_variants_pdf_captures_all_filter_parameters(self, mock_task):
        """Ensure request_variants_pdf captures price, discount, and attribute filters."""
        from report.views import build_variants_context

        self.client.login(phone_number="9999999992", password="testpass123")
        payload = {
            "search": "cotton",
            "category": "1",
            "color": "2",
            "size": "3",
            "status": "available",
            "stock": "in_stock",
            "sort": "-mrp",
            "min_price": "100.00",
            "max_price": "500.00",
            "discount_only": "1",
            "discount_type": "percent",
            "min_discount": "10",
            "max_discount": "50",
        }
        response = self.client.post(reverse("report:request_variants_pdf"), data=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("job_id", data)

        job = self.PdfJob.objects.get(id=data["job_id"])
        self.assertEqual(job.job_type, "variants_report")
        for key, val in payload.items():
            self.assertEqual(job.parameters.get(key), val)

        mock_task.assert_called_once_with(str(job.id))

        # Also verify build_variants_context accepts these parameters cleanly
        context = build_variants_context(job.parameters)
        self.assertIn("variants", context)
        self.assertIn("total_outstanding", context)
        self.assertIn("total_count", context)


