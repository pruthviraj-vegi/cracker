"""
Notification Services — Central function to create notifications.

Usage anywhere in the project:

    from notification.services import notify

    notify(
        user=request.user,
        notification_type="pdf_ready",
        title="Invoice PDF Ready",
        message="Your invoice #1042 PDF has been generated.",
        action_label="Download PDF",
        action_url="/media/pdf_jobs/invoice_1042.pdf",
        linked_object=invoice_instance,   # optional
    )
"""

from django.contrib.contenttypes.models import ContentType
from .models import Notification


def notify(
    user,
    notification_type: str,
    title: str,
    message: str,
    action_label: str = "",
    action_url: str = "",
    linked_object=None,
):
    """Create a notification for the given user.

    Args:
        user: The user to notify.
        notification_type: Registry key (e.g. 'pdf_ready', 'low_stock').
        title: Short notification title.
        message: Notification body text.
        action_label: Optional CTA button label (e.g. "Download PDF").
        action_url: Optional CTA URL.
        linked_object: Optional Django model instance to link via GenericForeignKey.

    Returns:
        The created Notification instance.
    """
    ct = None
    obj_id = None

    if linked_object is not None:
        ct = ContentType.objects.get_for_model(linked_object)
        obj_id = linked_object.pk

    return Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        message=message,
        action_label=action_label,
        action_url=action_url,
        content_type=ct,
        object_id=obj_id,
    )
