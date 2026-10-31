"""
Services for invoice operations, reporting queries, cancellation, and returns.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from invoice.choices import RefundStatusChoices
from invoice.models import Invoice, ReturnInvoice, ReturnInvoiceItem

logger = logging.getLogger(__name__)


class InvoiceCancellationService:
    """Handles cancellation of invoices including audit trail, payment cleanup,
    and inventory restoration."""

    @staticmethod
    @transaction.atomic
    def cancel(invoice, user, reason):
        """
        Cancel an invoice and reverse all financial impacts.

        Args:
            invoice: The Invoice instance to cancel.
            user: User performing the cancellation.
            reason: Reason for cancellation.

        Returns:
            tuple: (success: bool, message: str)
        """
        from invoice.choices import (  # pylint: disable=import-outside-toplevel
            PaymentStatusChoices,
            PaymentTypeChoices,
        )
        from invoice.models import (  # pylint: disable=import-outside-toplevel
            InvoiceCancellation,
            InvoiceItem,
            PaymentAllocation,
            ReturnInvoiceItem,
        )
        from django.db.models import Prefetch, Sum, OuterRef, Subquery, DecimalField as DjangoDecimalField
        from django.db.models.functions import Coalesce
        from inventory.services import InventoryService

        can_cancel, error_msg = invoice.can_be_cancelled()
        if not can_cancel:
            return False, error_msg

        invoice.is_cancelled = True
        invoice.cancelled_at = timezone.now()
        invoice.cancelled_by = user
        invoice.cancellation_reason = reason
        invoice.payment_status = PaymentStatusChoices.CANCELLED

        invoice.save(
            update_fields=[
                "is_cancelled",
                "cancelled_at",
                "cancelled_by",
                "cancellation_reason",
                "payment_status",
                "updated_at",
            ]
        )

        allocations = PaymentAllocation.objects.select_related("payment").filter(
            invoice=invoice, is_deleted=False
        )
        # Single bulk update instead of individual saves
        allocation_ids = list(allocations.values_list("id", flat=True))
        if allocation_ids:
            PaymentAllocation.objects.filter(id__in=allocation_ids).update(
                is_deleted=True
            )

        InvoiceCancellation.objects.create(
            invoice=invoice,
            cancelled_by=user,
            reason=reason,
            original_amount=invoice.amount,
            discount_amount=invoice.discount_amount,
            advance_amount=invoice.advance_amount,
            paid_amount=invoice.paid_amount,
            payment_type=invoice.payment_type,
        )

        invoice_items = InvoiceItem.objects.filter(invoice=invoice).select_related(
            "product_variant"
        ).prefetch_related(
            Prefetch(
                "return_items",
                queryset=ReturnInvoiceItem.objects.filter(
                    return_invoice__invoice=invoice, quantity_returned__gt=0
                ),
            )
        )

        for item in invoice_items:
            # Pre-populate cached property from prefetched data
            total_returned = sum(
                ri.quantity_returned for ri in item.return_items.all()
            )
            item._cached_return_available = max(  # pylint: disable=protected-access
                item.quantity - total_returned, Decimal("0")
            )

            if item.get_return_available_quantity > 0:
                InventoryService.cancelled_sale(
                    variant=item.product_variant,
                    quantity_cancelled=item.get_return_available_quantity,
                    user=user,
                    invoice_item=item,
                    notes=f"Cancelled Invoice: {invoice.invoice_number}",
                )

        if invoice.payment_type == PaymentTypeChoices.CREDIT:
            from customer.services import (  # pylint: disable=import-outside-toplevel
                CustomerPaymentService,
            )

            CustomerPaymentService.reallocate(invoice.customer)

        return True, "Invoice cancelled successfully"


class ReturnInvoiceService:
    """Handles state transitions for return invoices."""

    @staticmethod
    def approve(return_invoice, user):
        """Approve a pending return invoice.

        Args:
            return_invoice: The ReturnInvoice instance.
            user: User approving the return.

        Raises:
            ValidationError: If the return is not in PENDING status.
        """
        from django.core.exceptions import ValidationError

        from invoice.choices import RefundStatusChoices

        if return_invoice.status != RefundStatusChoices.PENDING:
            raise ValidationError("Only pending returns can be approved")

        return_invoice.status = RefundStatusChoices.APPROVED
        return_invoice.approved_by = user
        return_invoice.approved_date = timezone.now()
        return_invoice.save()

    @staticmethod
    def process(return_invoice, user):
        """Process an approved return invoice.

        Args:
            return_invoice: The ReturnInvoice instance.
            user: User processing the return.

        Raises:
            ValidationError: If the return is not in APPROVED status.
        """
        from django.core.exceptions import ValidationError

        if not return_invoice.can_be_processed:
            raise ValidationError("Return must be approved before processing")

        from invoice.choices import RefundStatusChoices

        return_invoice.status = RefundStatusChoices.COMPLETED
        return_invoice.processed_by = user
        return_invoice.processed_date = timezone.now()
        return_invoice.save()


def get_invoice_report_data(date_range):
    """Get GST invoices active during the given date range (closed-window rule)."""
    end_date = date_range[1] if len(date_range) > 1 else date_range[0]
    return (
        Invoice.objects.select_related("customer")
        .prefetch_related("invoice_items")
        .filter(
            invoice_type=Invoice.Invoice_type.GST,
            invoice_date__date__range=date_range,
        )
        .filter(
            Q(is_cancelled=False) | Q(cancelled_at__date__gt=end_date)
        )
    )


def get_invoice_cancled_data(date_range):
    """Get cancelled GST invoices within the given date range."""
    return (
        Invoice.objects.select_related("customer")
        .prefetch_related("invoice_items")
        .filter(
            invoice_type=Invoice.Invoice_type.GST,
            cancelled_at__date__range=date_range,
            is_cancelled=True,
        )
    )


def get_invoice_return_data(date_range):
    """Get approved/completed GST return invoices within the given date range."""
    return (
        ReturnInvoice.objects.select_related("customer", "invoice")
        .prefetch_related(
            Prefetch(
                "return_invoice_items",
                queryset=ReturnInvoiceItem.objects.select_related("original_invoice_item"),
            )
        )
        .filter(
            invoice__invoice_type=Invoice.Invoice_type.GST,
            return_date__date__range=date_range,
            invoice__is_cancelled=False,
            status__in=[
                RefundStatusChoices.APPROVED,
                RefundStatusChoices.PROCESSING,
                RefundStatusChoices.COMPLETED,
            ],
        )
    )

