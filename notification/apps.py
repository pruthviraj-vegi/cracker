from django.apps import AppConfig


class NotificationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'notification'

    def ready(self):
        """Load signal handlers for notification cache invalidation."""
        import notification.signals  # noqa: F401
