"""
Custom managers for Invoice models
"""

from decimal import Decimal

from django.db import models
from django.db.models import Count, Q, Sum


class InvoiceManager(models.Manager):
    """Custom manager for Invoice model"""

    def get_queryset(self):
        return super().get_queryset()

    def paid(self):
        """Return paid invoices"""
        return self.filter(payment_status="PAID")

    def unpaid(self):
        """Return unpaid invoices"""
        return self.filter(payment_status="UNPAID")

    def partially_paid(self):
        """Return partially paid invoices"""
        return self.filter(payment_status="PARTIALLY_PAID")

    def credit_invoices(self):
        """Return credit invoices"""
        return self.filter(payment_type="CREDIT")

    def cash_invoices(self):
        """Return cash invoices"""
        return self.filter(payment_type="CASH")

    def overdue(self):
        """Return overdue credit invoices"""
        from django.utils import timezone

        return self.filter(
            payment_type="CREDIT",
            due_date__lt=timezone.now().date(),
            payment_status__in=["UNPAID", "PARTIALLY_PAID"],
        )

    def by_financial_year(self, financial_year):
        """Return invoices for specific financial year"""
        return self.filter(financial_year=financial_year)

    def by_customer(self, customer):
        """Return invoices for specific customer"""
        return self.filter(customer=customer)

    def with_outstanding_balance(self):
        """Return invoices with outstanding balance"""
        return self.filter(
            Q(payment_status="UNPAID") | Q(payment_status="PARTIALLY_PAID")
        )

    def total_amount_by_status(self):
        """Return total amount grouped by payment status"""
        return self.values("payment_status").annotate(
            total_amount=Sum("amount"), count=Count("id")
        )


class InvoiceItemManager(models.Manager):
    """Custom manager for InvoiceItem model"""

    def get_queryset(self):
        """Return a queryset with related product, category, and invoice objects pre-fetched."""
        return (
            super()
            .get_queryset()
            .select_related(
                "product_variant__product",
                "product_variant__product__category",
                "invoice",
            )
        )

    def by_invoice(self, invoice):
        """Return items for specific invoice"""
        return self.filter(invoice=invoice)

    def by_product_variant(self, product_variant):
        """Return items for specific product variant"""
        return self.filter(product_variant=product_variant)

    def profitable_items(self):
        """Return items with positive profit"""
        return self.filter(unit_price__gt=models.F("purchase_price"))

    def high_discount_items(self, min_discount_percentage=20):
        """Return items with high discount"""
        return self.extra(
            where=["((mrp - unit_price) / mrp * 100) >= %s"],
            params=[min_discount_percentage],
        )


class AuditTableManager(models.Manager):
    """Custom manager for AuditTable model"""

    def get_queryset(self):
        return super().get_queryset()

    def pending(self):
        """Return pending audits"""
        return self.filter(status="PENDING")

    def in_progress(self):
        """Return in-progress audits"""
        return self.filter(status="IN_PROGRESS")

    def completed(self):
        """Return completed audits"""
        return self.filter(status="COMPLETED")

    def conversions(self):
        """Return conversion audits"""
        return self.filter(audit_type="CONVERSION")

    def renumbering(self):
        """Return renumbering audits"""
        return self.filter(audit_type="RENUMBER")


class InvoiceAuditManager(models.Manager):
    """Custom manager for InvoiceAudit model"""

    def get_queryset(self):
        """Return a queryset with related invoice, audit_table, and changed_by objects pre-fetched."""
        return (
            super()
            .get_queryset()
            .select_related("invoice", "audit_table", "changed_by")
        )

    def conversions(self):
        """Return conversion audits"""
        return self.filter(change_type="CONVERSION")

    def renumbering(self):
        """Return renumbering audits"""
        return self.filter(change_type="RENUMBER")

    def modifications(self):
        """Return modification audits"""
        return self.filter(change_type="MODIFICATION")

    def by_audit_table(self, audit_table):
        """Return audits for specific audit table"""
        return self.filter(audit_table=audit_table)

    def by_invoice(self, invoice):
        """Return audits for specific invoice"""
        return self.filter(invoice=invoice)


class PaymentAllocationManager(models.Manager):
    """Custom manager for PaymentAllocation model"""

    def get_queryset(self):
        """Return a queryset with related payment, invoice, and created_by objects pre-fetched."""
        return super().get_queryset().select_related("payment", "invoice", "created_by")

    def by_payment(self, payment):
        """Return allocations for specific payment"""
        return self.filter(payment=payment)

    def by_invoice(self, invoice):
        """Return allocations for specific invoice"""
        return self.filter(invoice=invoice)

    def total_allocated_by_payment(self, payment):
        """Return total allocated amount for a payment"""
        return self.filter(payment=payment).aggregate(total=Sum("amount_allocated"))[
            "total"
        ] or Decimal("0")

    def total_allocated_by_invoice(self, invoice):
        """Return total allocated amount for an invoice"""
        return self.filter(invoice=invoice).aggregate(total=Sum("amount_allocated"))[
            "total"
        ] or Decimal("0")


class ReturnInvoiceManager(models.Manager):
    """Custom manager for ReturnInvoice model"""

    def get_queryset(self):
        """Return a queryset with related invoice, customer, and user objects pre-fetched."""
        return (
            super()
            .get_queryset()
            .select_related(
                "invoice", "customer", "created_by", "approved_by", "processed_by"
            )
        )

    def pending(self):
        """Return pending returns"""
        return self.filter(status="PENDING")

    def approved(self):
        """Return approved returns"""
        return self.filter(status="APPROVED")

    def processing(self):
        """Return processing returns"""
        return self.filter(status="PROCESSING")

    def completed(self):
        """Return completed returns"""
        return self.filter(status="COMPLETED")

    def cancelled(self):
        """Return cancelled returns"""
        return self.filter(status="CANCELLED")

    def rejected(self):
        """Return rejected returns"""
        return self.filter(status="REJECTED")

    def by_customer(self, customer):
        """Return returns for specific customer"""
        return self.filter(customer=customer)

    def by_invoice(self, invoice):
        """Return returns for specific invoice"""
        return self.filter(invoice=invoice)

    def by_financial_year(self, financial_year):
        """Return returns for specific financial year"""
        return self.filter(financial_year=financial_year)

    def by_refund_type(self, refund_type):
        """Return returns by refund type"""
        return self.filter(refund_type=refund_type)

    def awaiting_approval(self):
        """Return returns awaiting approval"""
        return self.filter(status="PENDING")

    def awaiting_processing(self):
        """Return returns awaiting processing"""
        return self.filter(status="APPROVED")


class ReturnInvoiceItemManager(models.Manager):
    """Custom manager for ReturnInvoiceItem model"""

    def get_queryset(self):
        return super().get_queryset()

    def by_return_invoice(self, return_invoice):
        """Return items for specific return invoice"""
        return self.filter(return_invoice=return_invoice)

    def by_product_variant(self, product_variant):
        """Return items for specific product variant"""
        return self.filter(product_variant=product_variant)

    def full_returns(self):
        """Return items that are full returns"""
        return self.filter(quantity_returned=models.F("quantity_original"))

    def partial_returns(self):
        """Return items that are partial returns"""
        return self.filter(quantity_returned__lt=models.F("quantity_original"))

    def by_condition(self, condition):
        """Return items by condition"""
        return self.filter(condition=condition)

    def defective_items(self):
        """Return defective items"""
        return self.filter(condition="DEFECTIVE")

    def damaged_items(self):
        """Return damaged items"""
        return self.filter(condition="DAMAGED")
