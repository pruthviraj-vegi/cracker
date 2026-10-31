"""Notification Views — JSON API endpoints for the notification panel."""

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404

from .models import Notification
from .registry import get_meta


def notification_count(request):
    """Return the unread notification count for the current user."""
    count = Notification.unread_count(request.user)
    return JsonResponse({"unread_count": count})


def notification_list(request):
    """Return the latest notifications for the current user (max 30)."""
    qs = Notification.objects.filter(user=request.user).values(
        "id",
        "title",
        "message",
        "notification_type",
        "is_read",
        "created_at",
        "action_label",
        "action_url",
    )[:30]

    notifications = []
    for n in qs:
        meta = get_meta(n["notification_type"])
        notifications.append(
            {
                **n,
                "created_at": n["created_at"].strftime("%d %b %Y, %I:%M %p"),
                "icon": meta["icon"],
                "color": meta["color"],
                "badge_label": meta["label"],
            }
        )

    return JsonResponse({"notifications": notifications})


@require_POST
def mark_read(request, notification_id):
    """Mark a single notification as read."""
    notif = get_object_or_404(Notification, id=notification_id, user=request.user)
    notif.mark_read()
    return JsonResponse({"success": True})


@require_POST
def mark_all_read(request):
    """Mark all notifications as read for the current user."""
    updated = Notification.bulk_mark_read(request.user)
    return JsonResponse({"success": True, "updated": updated})
