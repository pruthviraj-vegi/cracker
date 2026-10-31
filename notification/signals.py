"""Notification Signals — Keep the cached unread count in sync with the DB."""

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Notification


def refresh_notification_cache(user):
    """Delete stale cache and set the fresh unread count."""
    cache_key = f"user_{user.id}_unread_notifs"
    cache.delete(cache_key)
    new_count = Notification.unread_count(user)
    cache.set(cache_key, new_count, timeout=300)


@receiver(post_save, sender=Notification)
def handle_notification_save(sender, instance, created, **kwargs):
    """Refresh cache on notification creation or update (e.g. mark-as-read)."""
    refresh_notification_cache(instance.user)


@receiver(post_delete, sender=Notification)
def handle_notification_delete(sender, instance, **kwargs):
    """Refresh cache on deletion only if the deleted notification was unread."""
    if not instance.is_read:
        refresh_notification_cache(instance.user)
