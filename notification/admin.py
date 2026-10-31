"""Notification Admin Configuration."""

from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Admin interface for Notification model."""

    list_display = (
        "title",
        "user",
        "notification_type",
        "is_read",
        "created_at",
    )
    list_filter = ("notification_type", "is_read", "created_at")
    search_fields = ("title", "message", "user__username")
    list_per_page = 30
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
