"""Notification Middleware — Injects cached unread count into every request."""

from .models import Notification


class NotificationCountMiddleware:
    """Attach ``request.notification_count`` on every authenticated request.

    The count is cached in Redis for 5 minutes per user to avoid
    hitting the database on every page load.  Signals in ``signals.py``
    invalidate the cache whenever a Notification is created, updated,
    or deleted.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            request.notification_count = Notification.unread_count(request.user)
        else:
            request.notification_count = 0

        return self.get_response(request)
