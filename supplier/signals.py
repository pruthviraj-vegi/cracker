"""
Signals for the supplier app to handle automatic reallocation of payments.

Signal handlers are thin dispatchers — all business logic lives in supplier/services.py.
"""

import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from supplier.services import SupplierPaymentService

from .models import SupplierInvoice, SupplierPayment, SupplierPaymentAllocation

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=SupplierPayment)
def track_payment_changes(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Track payment changes before saving for change detection."""
    if instance.pk:
        try:
            old_instance = SupplierPayment.all_objects.get(pk=instance.pk)
            instance._old_amount = old_instance.amount  # pylint: disable=protected-access
            instance._old_is_deleted = old_instance.is_deleted  # pylint: disable=protected-access
        except SupplierPayment.DoesNotExist:
            instance._old_amount = None  # pylint: disable=protected-access
            instance._old_is_deleted = None  # pylint: disable=protected-access
    else:
        instance._old_amount = None  # pylint: disable=protected-access
        instance._old_is_deleted = None  # pylint: disable=protected-access


@receiver(post_save, sender=SupplierPayment)
def reallocate_on_payment_change(sender, instance, created, **kwargs):  # pylint: disable=unused-argument
    """When a payment changes, reallocate via service layer."""
    if getattr(instance, "_skip_reallocation", False):
        return
    if not instance.supplier_id:
        return

    old_amount = getattr(instance, "_old_amount", None)
    old_is_deleted = getattr(instance, "_old_is_deleted", None)

    if (
        created
        or (old_amount is not None and old_amount != instance.amount)
        or (old_is_deleted is not None and old_is_deleted != instance.is_deleted)
    ):
        SupplierPaymentService.reallocate(instance.supplier)


@receiver(pre_save, sender=SupplierInvoice)
def track_invoice_changes(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Track old total_amount before saving for change detection."""
    if instance.pk:
        try:
            old_instance = SupplierInvoice.objects.get(pk=instance.pk)
            instance._old_total_amount = old_instance.total_amount  # pylint: disable=protected-access
        except SupplierInvoice.DoesNotExist:
            instance._old_total_amount = None  # pylint: disable=protected-access


@receiver(post_save, sender=SupplierInvoice)
def reallocate_on_invoice_change(sender, instance, created, **kwargs):  # pylint: disable=unused-argument
    """When an invoice is created or total changes, reallocate via service layer."""
    old_total = getattr(instance, "_old_total_amount", None)  # pylint: disable=protected-access
    if created or (old_total is not None and old_total != instance.total_amount):
        SupplierPaymentService.reallocate(instance.supplier)


@receiver(post_delete, sender=SupplierInvoice)
def reallocate_on_invoice_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """When an invoice is deleted, reallocate via service layer."""
    SupplierPaymentService.reallocate(instance.supplier)


@receiver(post_delete, sender=SupplierPaymentAllocation)
def reallocate_on_allocation_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """When an allocation is deleted, reallocate via service layer."""
    SupplierPaymentService.reallocate(instance.payment.supplier)
