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


class EstimateInvoiceViewTests(TestCase):
    """Tests for estimate_invoice view and template paper size selection."""

    def setUp(self):
        from decimal import Decimal
        from Billing.tests.helpers import create_test_user, create_test_variant
        from cart.models import Cart, CartItem
        from setting.models import ShopDetails

        self.user = create_test_user()
        self.shop_details = ShopDetails.objects.create(
            shop_name="My Shop",
            first_line="Main Street",
            city="City",
            state="State",
            pincode="123456",
            country="India",
            phone_number="9876543210",
            is_active=True,
        )
        self.variant = create_test_variant(user=self.user)
        self.cart = Cart.objects.create(name="Customer Cart", created_by=self.user)
        self.cart_item = CartItem.objects.create(
            cart=self.cart,
            product_variant=self.variant,
            quantity=Decimal("2"),
            price=Decimal("150.00"),
        )

    def test_estimate_80mm_template_selection(self):
        from setting.models import ReportConfiguration
        ReportConfiguration.objects.filter(
            report_type=ReportConfiguration.ReportType.ESTIMATE
        ).delete()
        ReportConfiguration.objects.create(
            report_type=ReportConfiguration.ReportType.ESTIMATE,
            paper_size=ReportConfiguration.PaperSize.MM80,
            is_default=True,
            is_active=True,
        )
        self.client.login(phone_number=self.user.phone_number, password="testpass123")
        response = self.client.get(
            reverse("report:estimate_pdf", kwargs={"pk": self.cart.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "report/estimate_80mm.html")
        self.assertContains(response, "80mm.css")
        self.assertContains(response, "Customer Cart")
        self.assertContains(response, "300.00")

    def test_estimate_58mm_template_selection(self):
        from setting.models import ReportConfiguration
        ReportConfiguration.objects.filter(
            report_type=ReportConfiguration.ReportType.ESTIMATE
        ).delete()
        ReportConfiguration.objects.create(
            report_type=ReportConfiguration.ReportType.ESTIMATE,
            paper_size=ReportConfiguration.PaperSize.MM58,
            is_default=True,
            is_active=True,
        )
        self.client.login(phone_number=self.user.phone_number, password="testpass123")
        response = self.client.get(
            reverse("report:estimate_pdf", kwargs={"pk": self.cart.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "report/estimate_58mm.html")
        self.assertContains(response, "58mm.css")

    def test_estimate_a5_template_selection(self):
        from setting.models import ReportConfiguration
        ReportConfiguration.objects.filter(
            report_type=ReportConfiguration.ReportType.ESTIMATE
        ).delete()
        ReportConfiguration.objects.create(
            report_type=ReportConfiguration.ReportType.ESTIMATE,
            paper_size=ReportConfiguration.PaperSize.A5,
            is_default=True,
            is_active=True,
        )
        self.client.login(phone_number=self.user.phone_number, password="testpass123")
        response = self.client.get(
            reverse("report:estimate_pdf", kwargs={"pk": self.cart.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "report/estimate.html")
        self.assertContains(response, "A5.css")


class DirectPrint80mmTests(TestCase):
    """Tests for 80mm thermal direct print formatting and template structure."""

    def setUp(self):
        from decimal import Decimal
        from Billing.tests.helpers import (
            create_test_user,
            create_test_customer,
            create_test_variant,
            create_test_invoice,
            create_test_invoice_item,
        )
        from cart.models import Cart, CartItem
        from setting.models import ShopDetails, ReportConfiguration

        self.user = create_test_user()
        self.customer = create_test_customer(name="Ramesh", created_by=self.user)
        self.shop_details = ShopDetails.objects.create(
            shop_name="Crackers World",
            first_line="123 Main Bazaar",
            city="Sivakasi",
            state="Tamil Nadu",
            pincode="626123",
            country="India",
            phone_number="9876543210",
            gst_no="33AAAAA0000A1Z5",
            is_active=True,
        )
        self.variant = create_test_variant(user=self.user)
        self.cart = Cart.objects.create(name="Walk In", created_by=self.user)
        self.cart_item = CartItem.objects.create(
            cart=self.cart,
            product_variant=self.variant,
            quantity=Decimal("3"),
            price=Decimal("250.00"),
        )
        self.invoice = create_test_invoice(
            customer=self.customer,
            created_by=self.user,
            amount=Decimal("750.00"),
        )
        self.invoice_item = create_test_invoice_item(
            invoice=self.invoice,
            product_variant=self.variant,
            quantity=Decimal("3"),
            unit_price=Decimal("250.00"),
        )
        ReportConfiguration.objects.all().delete()
        self.inv_config = ReportConfiguration.objects.create(
            report_type=ReportConfiguration.ReportType.INVOICE,
            paper_size=ReportConfiguration.PaperSize.MM80,
            is_default=True,
            is_active=True,
            show_shop_name=True,
            show_address=True,
            show_contact=True,
            show_gst=True,
            show_thank_you=True,
        )
        self.est_config = ReportConfiguration.objects.create(
            report_type=ReportConfiguration.ReportType.ESTIMATE,
            paper_size=ReportConfiguration.PaperSize.MM80,
            is_default=True,
            is_active=True,
            show_shop_name=True,
            show_address=True,
            show_thank_you=True,
        )

    def test_80mm_invoice_template_elements(self):
        """Verify 80mm invoice HTML uses 80mm.css, proper columns, cutter space, and no ₹ symbol."""
        self.client.login(phone_number=self.user.phone_number, password="testpass123")
        response = self.client.get(
            reverse("report:invoice_pdf", kwargs={"pk": self.invoice.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "report/80mm.html")
        self.assertContains(response, "80mm.css")
        self.assertContains(response, "col-sno")
        self.assertContains(response, "col-item")
        self.assertContains(response, "col-qty")
        self.assertContains(response, "col-rate")
        self.assertContains(response, "col-amount")
        self.assertContains(response, "feed-cut-space")
        self.assertNotContains(response, "₹")

    def test_80mm_estimate_template_elements(self):
        """Verify 80mm estimate HTML uses 80mm.css, proper columns, cutter space, and no ₹ symbol."""
        self.client.login(phone_number=self.user.phone_number, password="testpass123")
        response = self.client.get(
            reverse("report:estimate_pdf", kwargs={"pk": self.cart.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "report/estimate_80mm.html")
        self.assertContains(response, "80mm.css")
        self.assertContains(response, "col-sno")
        self.assertContains(response, "col-item")
        self.assertContains(response, "col-qty")
        self.assertContains(response, "col-rate")
        self.assertContains(response, "col-amount")
        self.assertContains(response, "feed-cut-space")
        self.assertNotContains(response, "₹")

    def test_format_item_rows_wrapping(self):
        """Verify format_item_rows wraps long names across lines instead of truncating."""
        from report.printing import format_item_rows

        short_rows = format_item_rows("Sparklers", "2.00", "50.00", "100.00", width=48)
        self.assertEqual(len(short_rows), 1)
        self.assertIn("Sparklers", short_rows[0])
        self.assertIn("100.00", short_rows[0])

        long_name = "Standard Fireworks 5000 Deluxe Giant Mega Crackers"
        long_rows = format_item_rows(long_name, "1.00", "500.00", "500.00", width=48)
        self.assertGreater(len(long_rows), 1)
        self.assertIn("500.00", long_rows[0])
        combined = " ".join(long_rows)
        self.assertIn("Deluxe", combined)
        self.assertIn("Mega", combined)

    def test_format_invoice_for_direct_print(self):
        """Verify format_invoice_for_direct_print outputs non-empty ESC/POS bytes."""
        from report.printing import format_invoice_for_direct_print

        data = format_invoice_for_direct_print(
            self.invoice, self.shop_details, self.inv_config, width=48
        )
        self.assertIsInstance(data, bytes)
        self.assertGreater(len(data), 50)
        self.assertIn(b"Crackers World", data)
        self.assertIn(self.invoice.invoice_number.encode("ascii"), data)

    def test_format_estimate_for_direct_print(self):
        """Verify format_estimate_for_direct_print outputs non-empty ESC/POS bytes."""
        from report.printing import format_estimate_for_direct_print

        data = format_estimate_for_direct_print(
            self.cart, self.shop_details, self.est_config, width=48
        )
        self.assertIsInstance(data, bytes)
        self.assertGreater(len(data), 50)
        self.assertIn(b"Crackers World", data)
        self.assertIn(b"ESTIMATE", data)




