"""
Invoice model constraints and validation rules
"""

from django.db import models


class InvoiceConstraints:
    """Invoice model constraints"""

    @staticmethod
    def get_all_constraints():
        """Return all constraints for Invoice model"""
        return [
            # Ensure advance amount doesn't exceed total payable for credit invoices
            models.CheckConstraint(
                check=models.Q(
                    models.Q(payment_type="CASH")
                    | models.Q(
                        advance_amount__lte=models.F("amount")
                        - models.F("discount_amount")
                    )
                ),
                name="advance_amount_check",
            ),
            # Ensure paid amount doesn't exceed remaining amount
            # For CASH: paid_amount <= amount - discount_amount (advance_amount is 0)
            # For CREDIT: paid_amount <= amount - discount_amount - advance_amount
            models.CheckConstraint(
                check=(
                    models.Q(payment_type="CASH")
                    & models.Q(
                        paid_amount__lte=models.F("amount")
                        - models.F("discount_amount")
                    )
                )
                | models.Q(
                    payment_type="CREDIT",
                    paid_amount__lte=models.F("amount")
                    - models.F("discount_amount")
                    - models.F("advance_amount"),
                ),
                name="paid_amount_check",
            ),
            # Ensure due date is after invoice date for credit invoices
            models.CheckConstraint(
                check=models.Q(
                    models.Q(payment_type="CASH")
                    | models.Q(due_date__isnull=True)
                    | models.Q(due_date__gte=models.F("invoice_date"))
                ),
                name="due_date_check",
            ),
            models.UniqueConstraint(
                fields=["invoice_type", "financial_year", "sequence_no"],
                name="unique_invoice_sequence",
            ),
        ]


class InvoiceIndexes:
    """Invoice model indexes"""

    @staticmethod
    def get_all_indexes():
        """Return all indexes for Invoice model"""
        return [
            models.Index(fields=["customer", "payment_status"]),
            models.Index(fields=["invoice_date"]),
            models.Index(fields=["payment_status"]),
            models.Index(fields=["invoice_type"]),
            models.Index(fields=["invoice_number"]),
            models.Index(fields=["financial_year"]),
            models.Index(fields=["payment_type", "financial_year"]),
            models.Index(fields=["due_date"]),
            models.Index(fields=["is_cancelled", "payment_type", "invoice_date"]),
        ]


class InvoiceItemConstraints:
    """InvoiceItem model constraints"""

    @staticmethod
    def get_all_indexes():
        """Return all indexes for InvoiceItem model"""
        return [
            models.Index(fields=["invoice", "product_variant"]),
            models.Index(fields=["product_variant"]),
            models.Index(fields=["invoice"]),
        ]


class AuditTableConstraints:
    """AuditTable model constraints"""

    @staticmethod
    def get_all_indexes():
        """Return all indexes for AuditTable model"""
        return [
            models.Index(fields=["start_date", "end_date"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["created_by"]),
            models.Index(fields=["audit_type"]),
            models.Index(fields=["status"]),
        ]


class InvoiceAuditConstraints:
    """InvoiceAudit model constraints"""

    @staticmethod
    def get_all_indexes():
        """Return all indexes for InvoiceAudit model"""
        return [
            models.Index(fields=["invoice", "created_at"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["change_type"]),
        ]


class InvoiceSequenceConstraints:
    """InvoiceSequence model constraints"""

    @staticmethod
    def get_all_indexes():
        """Return all indexes for InvoiceSequence model"""
        return [
            models.Index(fields=["invoice_type", "financial_year"]),
        ]
