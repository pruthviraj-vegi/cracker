"""Notification Models."""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import models

User = settings.AUTH_USER_MODEL


class Notification(models.Model):
    """A flexible notification that can link to ANY model via GenericForeignKey.

    Notification types are free strings registered in registry.py,
    so new types can be added without database migrations.
    """

    # ── Core ──────────────────────────────────────────
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # ── Type / Category ───────────────────────────────
    notification_type = models.CharField(max_length=100, db_index=True)

    # ── Optional Action (CTA button in the notification) ──
    action_label = models.CharField(max_length=100, blank=True)
    action_url = models.CharField(max_length=500, blank=True)

    # ── Generic link to ANY model ─────────────────────
    content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    linked_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        """Return a string representation of the notification."""
        return f"[{self.notification_type}] {self.title} → {self.user}"

    def mark_read(self):
        """Mark this notification as read (no-op if already read)."""
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=["is_read"])

    @classmethod
    def bulk_mark_read(cls, user):
        """Mark all unread notifications for a user as read.

        Uses queryset ``.update()`` which bypasses ``post_save`` signals,
        so the Redis cache is manually reset to 0 afterwards.

        Returns:
            int: Number of notifications updated.
        """
        from django.core.cache import cache

        updated_count = cls.objects.filter(
            user=user, is_read=False
        ).update(is_read=True)

        if updated_count > 0:
            # .update() bypasses signals — manually reset cache to 0
            cache_key = f"user_{user.id}_unread_notifs"
            cache.set(cache_key, 0, timeout=300)

        return updated_count

    @classmethod
    def unread_count(cls, user):
        """Get the count of unread notifications for a user, cached for 5 minutes."""
        if not user or not user.is_authenticated:
            return 0
        cache_key = f"user_{user.id}_unread_notifs"
        return cache.get_or_set(
            cache_key,
            lambda: cls.objects.filter(user=user, is_read=False).count(),
            timeout=300,
        )

    @classmethod
    def cleanup_old(cls, days=30):
        """Delete notifications older than `days` days.

        Returns:
            int: Number of notifications deleted.
        """
        from django.utils import timezone
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(days=days)
        count, _ = cls.objects.filter(created_at__lt=cutoff).delete()
        return count


class MessageStatusChoices(models.TextChoices):
    """Status choices for outgoing customer messages."""

    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


class MessageLog(models.Model):
    """Tracks status, parameters, and errors for outgoing customer messages."""

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="message_logs"
    )
    customer = models.ForeignKey(
        "customer.Customer", on_delete=models.CASCADE, related_name="message_logs"
    )
    message_type = models.CharField(
        max_length=50, db_index=True, help_text="e.g. 'statement', 'invoice', 'balance', 'payment'"
    )
    phone_number = models.CharField(max_length=20)
    status = models.CharField(
        max_length=20,
        choices=MessageStatusChoices.choices,
        default=MessageStatusChoices.PENDING,
        db_index=True,
    )
    error_message = models.TextField(blank=True)
    payload_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "message_type", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"[{self.message_type}] {self.customer} - {self.status}"

    @classmethod
    def cleanup_stale_messages(cls, minutes=5):
        """Mark messages stuck in pending/processing for too long as failed.

        Handles orphaned messages caused by missing worker restarts or crashes.
        """
        from datetime import timedelta
        from django.utils import timezone

        stale_cutoff = timezone.now() - timedelta(minutes=minutes)
        return cls.objects.filter(
            status__in=[MessageStatusChoices.PENDING, MessageStatusChoices.PROCESSING],
            updated_at__lt=stale_cutoff,
        ).update(
            status=MessageStatusChoices.FAILED,
            error_message="Message processing timed out — Celery worker was likely restarted or unavailable.",
        )

    @classmethod
    def is_duplicate_in_flight(cls, customer, message_type, cooldown_seconds=60, timeout_seconds=300):
        """Check if a message for this customer and message_type is currently PENDING/PROCESSING,
        or was SENT within `cooldown_seconds`.

        Auto-cleans stale pending/processing messages older than `timeout_seconds`.
        """
        from datetime import timedelta
        from django.utils import timezone

        # 0. Clean up stale messages older than timeout_seconds
        cls.cleanup_stale_messages(minutes=max(1, timeout_seconds // 60))

        # 1. Active in-flight check (only within timeout window)
        active_cutoff = timezone.now() - timedelta(seconds=timeout_seconds)
        if cls.objects.filter(
            customer=customer,
            message_type=message_type,
            status__in=[MessageStatusChoices.PENDING, MessageStatusChoices.PROCESSING],
            updated_at__gte=active_cutoff,
        ).exists():
            return True

        # 2. Recent cooldown check
        cutoff = timezone.now() - timedelta(seconds=cooldown_seconds)
        return cls.objects.filter(
            customer=customer,
            message_type=message_type,
            status=MessageStatusChoices.SENT,
            created_at__gte=cutoff,
        ).exists()


