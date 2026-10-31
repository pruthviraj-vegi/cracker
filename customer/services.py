"""
Service layer for customer payment allocation, credit summary management,
and customer analytics.

Extracts business logic from signals and views into reusable, testable services.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import (
    Case,
    DecimalField,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.db.models.signals import post_delete
from django.dispatch import Signal

from customer.models import CustomerCreditSummary
from invoice.models import Invoice, PaymentAllocation, ReturnInvoice

from .models import Customer, Payment

logger = logging.getLogger(__name__)

reallocation_complete = Signal()


class CustomerPaymentService:
    """
    Handles FIFO payment allocation for customer credit invoices.

    Originally embedded in customer/signals.py (~485 lines), now extracted
    for testability and separation of concerns.
    """

    @staticmethod
    @transaction.atomic
    def reallocate(customer: Customer, skip_signals: bool = False) -> None:
        """
        Reallocate all customer payments to credit invoices using FIFO.

        Paid payments first cover Purchased payments, then allocate to invoices.
        Items are handled in chronological order (oldest first).

        Args:
            customer: The Customer whose payments to reallocate.
            skip_signals: If True, mark instances to suppress signal re-triggers.
        """
        CustomerCreditSummary.recalculate_for_customer(customer, save=True)

        returned_subquery = ReturnInvoice.objects.filter(
            invoice=OuterRef("pk"),
            status__in=["APPROVED", "COMPLETED"],
        ).values("invoice").annotate(total=Sum("refund_amount")).values("total")

        invoices = list(
            Invoice.objects.filter(
                customer=customer,
                payment_type=Invoice.PaymentType.CREDIT,
                is_cancelled=False,
            )
            .annotate(
                _prefetched_returned=Coalesce(
                    Subquery(returned_subquery, output_field=DecimalField()),
                    Decimal("0"),
                )
            )
            .select_for_update()
            .order_by("invoice_date", "id")
        )

        paid_payments = list(
            Payment.objects.filter(
                customer=customer,
                payment_type=Payment.PaymentType.Paid,
                is_deleted=False,
            )
            .select_for_update()
            .order_by("payment_date", "id")
        )

        purchased_payments = list(
            Payment.objects.filter(
                customer=customer,
                payment_type=Payment.PaymentType.Purchased,
                is_deleted=False,
            )
            .select_for_update()
            .order_by("payment_date", "id")
        )

        if not paid_payments and not purchased_payments:
            for inv in invoices:
                inv.paid_amount = Decimal("0")
                inv.payment_status = Invoice.PaymentStatus.UNPAID
            if invoices:
                Invoice.objects.bulk_update(
                    invoices,
                    ["paid_amount", "payment_status", "updated_at"],
                    batch_size=100,
                )
            return

        # Temporarily disconnect allocation-delete signal to prevent recursion
        from customer.signals import (  # pylint: disable=import-outside-toplevel,cyclic-import
            reallocate_on_allocation_delete,
        )

        post_delete.disconnect(reallocate_on_allocation_delete, sender=PaymentAllocation)
        try:
            CustomerPaymentService._perform_reallocation(
                customer=customer,
                invoices=invoices,
                paid_payments=paid_payments,
                purchased_payments=purchased_payments,
                skip_signals=skip_signals,
            )
        finally:
            post_delete.connect(
                reallocate_on_allocation_delete, sender=PaymentAllocation
            )

        reallocation_complete.send(sender=CustomerPaymentService, customer=customer)

    @staticmethod
    def _perform_reallocation(
        customer: Customer,
        invoices: list[Invoice],
        paid_payments: list[Payment],
        purchased_payments: list[Payment],
        skip_signals: bool,
    ) -> None:
        """Internal: execute the FIFO allocation after signal disconnection."""

        # Delete existing allocations for this customer
        PaymentAllocation.objects.filter(
            payment__customer=customer, payment__is_deleted=False
        ).delete()

        # Reset invoice states
        for inv in invoices:
            inv.paid_amount = Decimal("0")
            inv.payment_status = Invoice.PaymentStatus.UNPAID
            if skip_signals:
                inv._skip_reallocation = True  # pylint: disable=protected-access

        # Reset paid payment states
        for payment in paid_payments:
            payment.unallocated_amount = payment.amount
            if skip_signals:
                payment._skip_reallocation = True  # pylint: disable=protected-access

        # Reset purchased payment states
        for pp in purchased_payments:
            pp.unallocated_amount = pp.amount
            if skip_signals:
                pp._skip_reallocation = True  # pylint: disable=protected-access

        allocations_to_create: list[PaymentAllocation] = []

        # Build unified FIFO list: invoices + purchased payments
        unified_items: list[dict] = []

        for inv in invoices:
            remaining = (
                inv.amount
                - inv.discount_amount
                - inv.advance_amount
                - getattr(inv, "_prefetched_returned", Decimal("0"))
                - inv.paid_amount
            )
            unified_items.append(
                {
                    "type": "invoice",
                    "date": inv.invoice_date,
                    "id": inv.id,
                    "object": inv,
                    "amount_owed": remaining,
                }
            )

        for pp in purchased_payments:
            unified_items.append(
                {
                    "type": "purchased_payment",
                    "date": pp.payment_date,
                    "id": pp.id,
                    "object": pp,
                    "amount_owed": pp.unallocated_amount,
                }
            )

        unified_items.sort(key=lambda x: (x["date"], x["id"]))

        # FIFO allocation
        for paid_payment in paid_payments:
            remaining = paid_payment.unallocated_amount
            item_idx = 0

            while item_idx < len(unified_items) and remaining > 0:
                item = unified_items[item_idx]
                amount_owed = item["amount_owed"]

                if amount_owed <= 0:
                    item_idx += 1
                    continue

                allocation_amount = min(remaining, amount_owed)

                if item["type"] == "invoice":
                    inv = item["object"]
                    allocations_to_create.append(
                        PaymentAllocation(
                            payment=paid_payment,
                            invoice=inv,
                            amount_allocated=allocation_amount,
                            created_by_id=paid_payment.created_by_id,
                        )
                    )
                    inv.paid_amount += allocation_amount
                    net_due = (
                        inv.amount
                        - inv.discount_amount
                        - inv.advance_amount
                        - getattr(inv, "_prefetched_returned", Decimal("0"))
                    )
                    if inv.paid_amount >= net_due:
                        inv.payment_status = Invoice.PaymentStatus.PAID
                        item["amount_owed"] = Decimal("0")
                        item_idx += 1
                    elif inv.paid_amount > 0:
                        inv.payment_status = Invoice.PaymentStatus.PARTIALLY_PAID
                        item["amount_owed"] = (
                            inv.amount
                            - inv.discount_amount
                            - inv.advance_amount
                            - getattr(inv, "_prefetched_returned", Decimal("0"))
                            - inv.paid_amount
                        )

                elif item["type"] == "purchased_payment":
                    pp = item["object"]
                    pp.unallocated_amount -= allocation_amount
                    item["amount_owed"] = pp.unallocated_amount
                    if item["amount_owed"] <= 0:
                        item_idx += 1

                remaining -= allocation_amount
                paid_payment.unallocated_amount = remaining

        # Bulk persist
        if allocations_to_create:
            PaymentAllocation.objects.bulk_create(allocations_to_create)

        if invoices:
            Invoice.objects.bulk_update(
                invoices,
                ["paid_amount", "payment_status", "updated_at"],
                batch_size=100,
            )

        if paid_payments:
            Payment.objects.bulk_update(
                paid_payments, ["unallocated_amount", "updated_at"], batch_size=100
            )

        if purchased_payments:
            Payment.objects.bulk_update(
                purchased_payments, ["unallocated_amount", "updated_at"], batch_size=100
            )

    @staticmethod
    def should_reallocate_payment(instance, old_amount, old_is_deleted, old_payment_type, created: bool) -> bool:
        """Determine if a payment change warrants reallocation."""
        if created:
            return True
        if old_amount is not None and old_amount != instance.amount:
            return True
        if old_is_deleted is not None and old_is_deleted != instance.is_deleted:
            return True
        if old_payment_type is not None and old_payment_type != instance.payment_type:
            return True
        return False

    @staticmethod
    def should_reallocate_invoice(instance, old_values: dict, created: bool) -> tuple[bool, Customer | None]:
        """Determine if an invoice change warrants reallocation.
        Returns (should_reallocate, old_customer_if_changed).
        """
        old_payment_type = old_values.get("payment_type")
        old_amount = old_values.get("amount")
        old_discount = old_values.get("discount_amount")
        old_advance = old_values.get("advance_amount")
        old_customer = old_values.get("customer")

        is_credit_now = instance.payment_type == Invoice.PaymentType.CREDIT
        was_credit_before = old_payment_type == Invoice.PaymentType.CREDIT

        # If the invoice changed FROM CREDIT to non-CREDIT (e.g. CASH),
        # we must still reallocate to clean up orphaned allocations and
        # recalculate the customer's credit summary.
        if not is_credit_now and not was_credit_before:
            return False, None

        payment_type_changed = (
            old_payment_type is not None and old_payment_type != instance.payment_type
        )
        amount_changed = old_amount is not None and old_amount != instance.amount
        discount_changed = old_discount is not None and old_discount != instance.discount_amount
        advance_changed = old_advance is not None and old_advance != instance.advance_amount
        customer_changed = old_customer is not None and old_customer != instance.customer

        needs_reallocation = (
            created
            or amount_changed
            or discount_changed
            or advance_changed
            or customer_changed
            or payment_type_changed
        )

        old_cust = old_customer if customer_changed else None
        return needs_reallocation, old_cust


def get_opening_balance(customer, start_date=None):
    """Calculate opening balance without loops using ORM aggregation."""

    invoice_qs = Invoice.objects.filter(
        customer=customer,
        payment_type=Invoice.PaymentType.CREDIT,
        is_cancelled=False,
    )
    if start_date is not None:
        invoice_qs = invoice_qs.filter(invoice_date__lt=start_date)

    # 1️⃣ CREDIT INVOICES NET AMOUNT
    invoice_net = (
        invoice_qs
        .annotate(
            net_amount=Coalesce(F("amount"), Decimal(0))
            - Coalesce(F("discount_amount"), Decimal(0))
            - Coalesce(F("advance_amount"), Decimal(0))
        )
        .aggregate(total=Coalesce(Sum("net_amount"), Decimal(0)))["total"]
    )

    payment_qs = Payment.objects.filter(customer=customer)
    if start_date is not None:
        payment_qs = payment_qs.filter(payment_date__lt=start_date)

    # 2️⃣ PAYMENT BALANCE (credit - debit)
    payment_balance = (
        payment_qs
        .annotate(
            credit=Case(
                When(
                    payment_type=Payment.PaymentType.Purchased,
                    then=Coalesce(F("amount"), Decimal(0)),
                ),
                default=Decimal(0),
            ),
            debit=Case(
                When(
                    payment_type=Payment.PaymentType.Paid,
                    then=Coalesce(F("amount"), Decimal(0)),
                ),
                default=Decimal(0),
            ),
        )
        .aggregate(total=Coalesce(Sum(F("credit") - F("debit")), Decimal(0)))["total"]
    )

    return invoice_net + payment_balance


def _build_ledger_rows(customer, start_date=None, end_date=None):
    """Helper function to build unified ledger rows from invoices and payments."""

    # -----------------------------------
    # 1️⃣ Build filters dynamically
    # -----------------------------------
    invoice_filters = Q(
        customer=customer, payment_type=Invoice.PaymentType.CREDIT, is_cancelled=False
    )
    payment_filters = Q(customer=customer)

    if start_date and end_date:
        invoice_filters &= Q(invoice_date__range=(start_date, end_date))
        payment_filters &= Q(payment_date__range=(start_date, end_date))

    # -----------------------------------
    # 2️⃣ Fetch Invoices (annotated)
    # -----------------------------------
    credit_invoices = (
        Invoice.objects.filter(invoice_filters)
        .annotate(
            gross=Coalesce(F("amount"), Decimal("0"), output_field=DecimalField()),
            discount=Coalesce(
                F("discount_amount"), Decimal("0"), output_field=DecimalField()
            ),
            advance=Coalesce(
                F("advance_amount"), Decimal("0"), output_field=DecimalField()
            ),
            # Calculate return amount from related ReturnInvoice records
            return_amt=Coalesce(
                Subquery(
                    ReturnInvoice.objects.filter(invoice=OuterRef("pk"))
                    .values("invoice")
                    .annotate(total=Sum("refund_amount"))
                    .values("total")[:1],
                    output_field=DecimalField(),
                ),
                Decimal("0"),
                output_field=DecimalField(),
            ),
            net_amount=Coalesce(F("amount"), Decimal("0"), output_field=DecimalField())
            - Coalesce(F("discount_amount"), Decimal("0"), output_field=DecimalField())
            - Coalesce(F("advance_amount"), Decimal("0"), output_field=DecimalField())
            - Coalesce(
                Subquery(
                    ReturnInvoice.objects.filter(invoice=OuterRef("pk"))
                    .values("invoice")
                    .annotate(total=Sum("refund_amount"))
                    .values("total")[:1],
                    output_field=DecimalField(),
                ),
                Decimal("0"),
                output_field=DecimalField(),
            ),
            paid_amt=Coalesce(
                F("paid_amount"), Decimal("0"), output_field=DecimalField()
            ),
            # Outstanding = Gross - Discount - Advance - Paid - Return
            outstanding=Coalesce(F("amount"), Decimal("0"), output_field=DecimalField())
            - Coalesce(F("discount_amount"), Decimal("0"), output_field=DecimalField())
            - Coalesce(F("advance_amount"), Decimal("0"), output_field=DecimalField())
            - Coalesce(F("paid_amount"), Decimal("0"), output_field=DecimalField())
            - Coalesce(
                Subquery(
                    ReturnInvoice.objects.filter(invoice=OuterRef("pk"))
                    .values("invoice")
                    .annotate(total=Sum("refund_amount"))
                    .values("total")[:1],
                    output_field=DecimalField(),
                ),
                Decimal("0"),
                output_field=DecimalField(),
            ),
        )
        .values(
            "id",
            "invoice_number",
            "invoice_date",
            "gross",
            "discount",
            "advance",
            "return_amt",
            "net_amount",
            "paid_amt",
            "outstanding",
            "payment_status",
            "notes",
        )
        .order_by("invoice_date")
    )

    # -----------------------------------
    # 3️⃣ Fetch Payments (annotated)
    # -----------------------------------
    payments = (
        Payment.objects.filter(payment_filters)
        .annotate(
            credit=Case(
                When(
                    payment_type=Payment.PaymentType.Purchased,
                    then=Coalesce(
                        F("amount"), Decimal("0"), output_field=DecimalField()
                    ),
                ),
                default=Value(Decimal("0")),
                output_field=DecimalField(),
            ),
            debit=Case(
                When(
                    payment_type=Payment.PaymentType.Paid,
                    then=Coalesce(
                        F("amount"), Decimal("0"), output_field=DecimalField()
                    ),
                ),
                default=Value(Decimal("0")),
                output_field=DecimalField(),
            ),
        )
        .values(
            "id",
            "payment_date",
            "payment_type",
            "credit",
            "debit",
            "method",
            "notes",
        )
        .order_by("payment_date")
    )

    # -----------------------------------
    # 4️⃣ Build Unified Ledger Rows
    # -----------------------------------
    rows = []

    for inv in credit_invoices:
        rows.append(
            {
                "id": inv["id"],
                "date": inv["invoice_date"],
                "type": "Invoice",
                "ref": inv["invoice_number"],
                "notes": inv["notes"],
                "credit": inv["net_amount"],
                "debit": Decimal("0"),
                "paid_amount": inv["paid_amt"],
                "payment_status": inv["payment_status"],
                "outstanding": inv["outstanding"],
                "gross_amount": inv["gross"],
                "discount_amount": inv["discount"],
                "advance_amount": inv["advance"],
            }
        )

    for pay in payments:
        rows.append(
            {
                "id": pay["id"],
                "date": pay["payment_date"],
                "type": pay["payment_type"].title(),
                "ref": pay["id"],
                "method": pay["method"],
                "notes": pay["notes"],
                "credit": pay["credit"],
                "debit": pay["debit"],
            }
        )

    return rows


