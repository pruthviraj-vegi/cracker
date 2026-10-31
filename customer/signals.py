"""
Django signals for customer payment allocation, invoice tracking, and credit summary updates.

Signal handlers are thin dispatchers — all business logic lives in customer/services.py.
"""

import logging
from collections import defaultdict

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from customer.models import CustomerCreditSummary
from customer.services import CustomerPaymentService
from invoice.models import Invoice, PaymentAllocation

from .models import Customer, Payment

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Payment)
def track_payment_changes(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Track payment changes before saving for change detection."""
    if instance.pk:
        try:
            old_instance = Payment.all_objects.get(pk=instance.pk)
            instance._old_amount = old_instance.amount  # pylint: disable=protected-access
            instance._old_is_deleted = old_instance.is_deleted  # pylint: disable=protected-access
            instance._old_payment_type = old_instance.payment_type  # pylint: disable=protected-access
        except Payment.DoesNotExist:
            instance._old_amount = None  # pylint: disable=protected-access
            instance._old_is_deleted = None  # pylint: disable=protected-access
            instance._old_payment_type = None  # pylint: disable=protected-access
    else:
        instance._old_amount = None  # pylint: disable=protected-access
        instance._old_is_deleted = None  # pylint: disable=protected-access
        instance._old_payment_type = None  # pylint: disable=protected-access


@receiver(post_save, sender=Payment)
def reallocate_on_payment_change(sender, instance, created, **kwargs):  # pylint: disable=unused-argument
    """When a payment changes, reallocate via service layer."""
    if getattr(instance, "_skip_reallocation", False):
        return
    if not instance.customer_id:
        return

    if CustomerPaymentService.should_reallocate_payment(
        instance,
        getattr(instance, "_old_amount", None),
        getattr(instance, "_old_is_deleted", None),
        getattr(instance, "_old_payment_type", None),
        created,
    ):
        CustomerPaymentService.reallocate(instance.customer)


@receiver(pre_save, sender=Invoice)
def track_invoice_changes(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Track old invoice values before saving for change detection."""
    if instance.pk:
        try:
            old_instance = Invoice.objects.get(pk=instance.pk)
            instance._old_payment_type = old_instance.payment_type  # pylint: disable=protected-access
            instance._old_amount = old_instance.amount  # pylint: disable=protected-access
            instance._old_discount_amount = old_instance.discount_amount  # pylint: disable=protected-access
            instance._old_advance_amount = old_instance.advance_amount  # pylint: disable=protected-access
            instance._old_customer = old_instance.customer  # pylint: disable=protected-access
        except Invoice.DoesNotExist:
            instance._old_payment_type = None  # pylint: disable=protected-access
            instance._old_amount = None  # pylint: disable=protected-access
            instance._old_discount_amount = None  # pylint: disable=protected-access
            instance._old_advance_amount = None  # pylint: disable=protected-access
            instance._old_customer = None  # pylint: disable=protected-access
    else:
        instance._old_payment_type = None  # pylint: disable=protected-access
        instance._old_amount = None  # pylint: disable=protected-access
        instance._old_discount_amount = None  # pylint: disable=protected-access
        instance._old_advance_amount = None  # pylint: disable=protected-access
        instance._old_customer = None  # pylint: disable=protected-access


@receiver(post_save, sender=Invoice)
def reallocate_on_invoice_change(sender, instance, created, **kwargs):  # pylint: disable=unused-argument
    """When a credit invoice changes, reallocate via service layer."""
    if getattr(instance, "_skip_reallocation", False):
        return

    old_values = {
        "payment_type": getattr(instance, "_old_payment_type", None),
        "amount": getattr(instance, "_old_amount", None),
        "discount_amount": getattr(instance, "_old_discount_amount", None),
        "advance_amount": getattr(instance, "_old_advance_amount", None),
        "customer": getattr(instance, "_old_customer", None),
    }

    needs_reallocation, old_customer = CustomerPaymentService.should_reallocate_invoice(
        instance, old_values, created
    )

    if needs_reallocation:
        CustomerPaymentService.reallocate(instance.customer)
        if old_customer:
            CustomerPaymentService.reallocate(old_customer)


@receiver(post_delete, sender=Invoice)
def reallocate_on_invoice_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """When a credit invoice is deleted, reallocate via service layer."""
    if instance.payment_type == Invoice.PaymentType.CREDIT:
        CustomerPaymentService.reallocate(instance.customer)


@receiver(post_delete, sender=PaymentAllocation)
def reallocate_on_allocation_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """When an allocation is deleted, reallocate via service layer."""
    CustomerPaymentService.reallocate(instance.payment.customer)


# ── Batch update queue (for return invoice changes) ──

_pending_updates: dict[str, set[int]] = defaultdict(set)


def queue_customer_update(customer_id: int) -> None:
    """Queue customer for batch credit summary update."""
    _pending_updates[transaction.get_connection().alias].add(customer_id)


def process_queued_updates() -> None:
    """Process all queued credit summary updates in a single batch."""
    connection_alias = transaction.get_connection().alias
    customer_ids = _pending_updates.pop(connection_alias, set())

    if not customer_ids:
        return

    for customer_id in customer_ids:
        try:
            customer = Customer.objects.get(id=customer_id)
            CustomerCreditSummary.recalculate_for_customer(customer)
        except (Customer.DoesNotExist, ValueError, TypeError) as e:
            logger.error("Failed to update summary for customer %s: %s", customer_id, e)


@receiver([post_save, post_delete], sender="invoice.ReturnInvoice")
def handle_return_change(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Queue credit summary update when return invoice changes."""
    if instance.status in ("APPROVED", "COMPLETED"):
        queue_customer_update(instance.customer_id)
        transaction.on_commit(process_queued_updates)


@receiver(post_save, sender="customer.Customer")
def create_summary_for_new_customer(sender, instance, created, **kwargs):  # pylint: disable=unused-argument
    """Create empty credit summary when a new customer is created."""
    if created:
        CustomerCreditSummary.objects.get_or_create(customer=instance)
