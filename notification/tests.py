from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from customer.models import Customer
from notification.models import MessageLog, MessageStatusChoices
from notification.services import notify
from Billing.tests.helpers import create_test_user


class MessageLogStaleCleanupTestCase(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name="Test Customer",
            phone_number="9876543210"
        )

    def test_cleanup_stale_messages(self):
        log = MessageLog.objects.create(
            customer=self.customer,
            message_type="balance",
            phone_number=self.customer.phone_number,
            status=MessageStatusChoices.PROCESSING,
        )
        # Backdate updated_at to 10 minutes ago
        MessageLog.objects.filter(id=log.id).update(
            updated_at=timezone.now() - timedelta(minutes=10)
        )

        cleaned_count = MessageLog.cleanup_stale_messages(minutes=5)
        self.assertEqual(cleaned_count, 1)

        log.refresh_from_db()
        self.assertEqual(log.status, MessageStatusChoices.FAILED)
        self.assertIn("Message processing timed out", log.error_message)

    def test_is_duplicate_in_flight_auto_cleans_stale_task(self):
        stale_log = MessageLog.objects.create(
            customer=self.customer,
            message_type="balance",
            phone_number=self.customer.phone_number,
            status=MessageStatusChoices.PROCESSING,
        )
        MessageLog.objects.filter(id=stale_log.id).update(
            updated_at=timezone.now() - timedelta(minutes=10)
        )

        # Calling is_duplicate_in_flight should clean the stale log and return False
        in_flight = MessageLog.is_duplicate_in_flight(self.customer, "balance")
        self.assertFalse(in_flight)

        stale_log.refresh_from_db()
        self.assertEqual(stale_log.status, MessageStatusChoices.FAILED)

    def test_is_duplicate_in_flight_blocks_recent_active_task(self):
        recent_log = MessageLog.objects.create(
            customer=self.customer,
            message_type="balance",
            phone_number=self.customer.phone_number,
            status=MessageStatusChoices.PROCESSING,
        )
        # Recent log updated now
        in_flight = MessageLog.is_duplicate_in_flight(self.customer, "balance")
        self.assertTrue(in_flight)


class NotifyTests(TestCase):
    """Tests for the notify() function."""

    def setUp(self):
        self.user = create_test_user(phone_number="9999999001")

    def test_notify_creates_notification(self):
        notification = notify(
            user=self.user,
            notification_type="test_type",
            title="Test Title",
            message="Test message body",
        )
        self.assertEqual(notification.user, self.user)
        self.assertEqual(notification.notification_type, "test_type")
        self.assertEqual(notification.title, "Test Title")
        self.assertEqual(notification.message, "Test message body")
        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.content_type)
        self.assertIsNone(notification.object_id)

    def test_notify_with_action_fields(self):
        notification = notify(
            user=self.user,
            notification_type="pdf_ready",
            title="PDF Ready",
            message="Your PDF is ready.",
            action_label="Download",
            action_url="/download/123",
        )
        self.assertEqual(notification.action_label, "Download")
        self.assertEqual(notification.action_url, "/download/123")

    def test_notify_with_linked_object(self):
        notification = notify(
            user=self.user,
            notification_type="low_stock",
            title="Low Stock",
            message="Stock is low.",
            linked_object=self.user,
        )
        self.assertIsNotNone(notification.content_type)
        self.assertIsNotNone(notification.object_id)
        ct = ContentType.objects.get_for_model(self.user)
        self.assertEqual(notification.content_type, ct)
        self.assertEqual(notification.object_id, self.user.pk)

    def test_notify_without_linked_object(self):
        notification = notify(
            user=self.user,
            notification_type="system",
            title="System Alert",
            message="Something happened.",
        )
        self.assertIsNone(notification.content_type)
        self.assertIsNone(notification.object_id)

    def test_notify_default_empty_strings_for_action(self):
        notification = notify(
            user=self.user,
            notification_type="test",
            title="Test",
            message="Test",
        )
        self.assertEqual(notification.action_label, "")
        self.assertEqual(notification.action_url, "")
