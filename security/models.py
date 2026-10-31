"""Models for the security app."""

from django.conf import settings
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class LoginEvent(models.Model):
    """Audit log of user login/logout events."""

    class EventType(models.TextChoices):
        """Choices for login event types."""

        LOGIN = "LOGIN", "Login"
        LOGOUT = "LOGOUT", "Logout"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="login_events"
    )
    event_type = models.CharField(max_length=10, choices=EventType.choices)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, null=True, blank=True)
    session_key = models.CharField(max_length=40, null=True, blank=True)

    class Meta:
        app_label = 'security'
        db_table = 'user_loginevent'
        ordering = ("-occurred_at",)
        indexes = [
            models.Index(fields=["user", "occurred_at"]),
            models.Index(fields=["event_type", "occurred_at"]),
        ]

    def __str__(self):
        return f"{self.user_id} {self.event_type} {self.occurred_at}"


class UnauthorizedAccess(models.Model):
    """Model to log unauthorized access attempts."""

    user = models.ForeignKey(
        'user.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who attempted unauthorized access",
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    view_name = models.CharField(max_length=255, help_text="Name of the view/function")
    required_roles = models.CharField(
        max_length=255, help_text="Roles that were required"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    url_path = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        app_label = 'security'
        db_table = 'user_unauthorizedaccess'
        ordering = ["-timestamp"]
        verbose_name = "Unauthorized Access Attempt"
        verbose_name_plural = "Unauthorized Access Attempts"

    def __str__(self):
        return f"{self.user} - {self.view_name} at {self.timestamp}"
