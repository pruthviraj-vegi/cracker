"""
Service layer for supplier payment allocation and supplier analytics.

Extracts business logic from signals into reusable services.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import Signal

from .models import Supplier, SupplierInvoice, SupplierPayment, SupplierPaymentAllocation

logger = logging.getLogger(__name__)

reallocation_complete = Signal()


class SupplierPaymentService:
    """
    Handles FIFO payment allocation for supplier invoices.

    Originally embedded in supplier/signals.py (~223 lines), now extracted
    for testability and separation of concerns.
    """

    @staticmethod
    @transaction.atomic
    def reallocate(supplier: Supplier) -> None:
        """
        Reallocate all supplier payments to outstanding invoices using FIFO.

        Args:
            supplier: The Supplier whose payments to reallocate.
        """
        invoices = list(
            supplier.invoices.filter(is_deleted=False)
            .select_for_update()
            .order_by("invoice_date", "id")
        )

        payments = list(
            supplier.payments_made.filter(is_deleted=False)
            .select_for_update()
            .order_by("payment_date", "id")
        )

        if not invoices or not payments:
            return

        # Temporarily disconnect allocation-delete signal to prevent recursion
        from supplier.signals import (  # pylint: disable=import-outside-toplevel,cyclic-import
            reallocate_on_allocation_delete,
        )

        post_delete.disconnect(
            reallocate_on_allocation_delete, sender=SupplierPaymentAllocation
        )
        try:
            SupplierPaymentService._perform_reallocation(
                supplier=supplier,
                invoices=invoices,
                payments=payments,
            )
        finally:
            post_delete.connect(
                reallocate_on_allocation_delete, sender=SupplierPaymentAllocation
            )

        reallocation_complete.send(
            sender=SupplierPaymentService, supplier=supplier
        )

    @staticmethod
    def _perform_reallocation(
        supplier: Supplier,
        invoices: list[SupplierInvoice],
        payments: list[SupplierPayment],
    ) -> None:
        """Internal: execute the FIFO allocation after signal disconnection."""

        # Delete existing allocations for this supplier
        SupplierPaymentAllocation.objects.filter(
            payment__supplier=supplier, payment__is_deleted=False
        ).delete()

        # Reset invoice states
        for inv in invoices:
            inv.paid_amount = Decimal("0")
            inv.status = "UNPAID"

        # Reset payment states
        for payment in payments:
            payment.unallocated_amount = payment.amount

        allocations_to_create: list[SupplierPaymentAllocation] = []
        invoice_idx = 0

        for payment in payments:
            remaining = payment.unallocated_amount

            while invoice_idx < len(invoices) and remaining > 0:
                inv = invoices[invoice_idx]
                amount_owed = inv.total_amount - inv.paid_amount

                if amount_owed <= 0:
                    invoice_idx += 1
                    continue

                allocation_amount = min(remaining, amount_owed)

                allocations_to_create.append(
                    SupplierPaymentAllocation(
                        payment=payment,
                        invoice=inv,
                        amount_allocated=allocation_amount,
                        created_by_id=payment.created_by_id,
                    )
                )

                inv.paid_amount += allocation_amount
                if inv.paid_amount >= inv.total_amount:
                    inv.status = "PAID"
                    invoice_idx += 1
                else:
                    inv.status = "PARTIALLY_PAID"

                remaining -= allocation_amount
                payment.unallocated_amount = remaining

        # Bulk persist
        if allocations_to_create:
            SupplierPaymentAllocation.objects.bulk_create(allocations_to_create)

        if invoices:
            SupplierInvoice.objects.bulk_update(
                invoices, ["paid_amount", "status"], batch_size=100
            )

        if payments:
            SupplierPayment.objects.bulk_update(
                payments, ["unallocated_amount"], batch_size=100
            )
