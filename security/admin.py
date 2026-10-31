"""
Admin configurations for the security app.
"""

from django.contrib import admin

from .models import LoginEvent, UnauthorizedAccess


@admin.register(LoginEvent)
class LoginEventAdmin(admin.ModelAdmin):
    """Admin interface for viewing login events."""

    list_display = ("occurred_at", "user", "event_type", "ip_address", "session_key")
    list_filter = ("event_type", "occurred_at")
    search_fields = (
        "user__first_name",
        "user__phone_number",
        "ip_address",
        "session_key",
    )
    date_hierarchy = "occurred_at"


@admin.register(UnauthorizedAccess)
class UnauthorizedAccessAdmin(admin.ModelAdmin):
    """Admin interface for viewing unauthorized access attempts."""

    list_display = ("user", "view_name", "timestamp", "ip_address")
    search_fields = ("user__first_name", "view_name")
