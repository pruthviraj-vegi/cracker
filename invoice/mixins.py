"""
Mixins for Invoice models to organize related functionality
"""

import logging
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


class InvoiceFinancialMixin:
    """Mixin containing all financial calculation properties and methods for Invoice"""

    @property
    def total_returned_amount(self):
        """Total amount of returned items"""
        try:
            return self.return_invoices.filter(
                status__in=["APPROVED", "COMPLETED"]
            ).aggregate(total=Sum("refund_amount"))["total"] or Decimal("0")
        except Exception:  # pylint: disable=broad-except
            return Decimal("0")

    @property
    def total_payable(self):
        """Total amount customer owes after discount"""
        return self.amount - self.discount_amount

    @property
    def net_amount_due(self):
        """Amount still owed after advance payments"""
        return self.total_payable - self.advance_amount - self.total_returned_amount

    @property
    def remaining_amount(self):
        """Final amount still owed by customer"""
        return self.net_amount_due - getattr(self, "paid_amount", Decimal("0"))

    @property
    def amount_cleared(self):
        """Amount cleared from customer"""
        return self.remaining_amount <= 0

    @property
    def total_received(self):
        """Total amount received from customer (advance + payments)"""
        return (
            getattr(self, "advance_amount", Decimal("0"))
            + getattr(self, "paid_amount", Decimal("0"))
            + self.total_returned_amount
        )  #

    @property
    def is_fully_paid(self):
        """Check if invoice is fully paid"""
        return self.remaining_amount <= 0

    @property
    def is_overdue(self):
        """Check if credit invoice is overdue"""
        if self.payment_type == "CREDIT" and self.due_date and not self.is_fully_paid:
            return timezone.now().date() > self.due_date.date()
        return False

    def _update_payment_status(self):
        """Internal method to update payment status"""
        if self.total_received >= self.total_payable:
            self.payment_status = "PAID"
        elif self.total_received > 0:
            self.payment_status = "PARTIALLY_PAID"
        else:
            self.payment_status = "UNPAID"

    def update_payment_status(self):
        """Public method to update payment status and save"""
        self._update_payment_status()
        self.save(update_fields=["payment_status"])

    @transaction.atomic
    def make_payment(self, amount, payment_method=None):
        """Add a payment to this invoice with proper transaction handling"""
        if amount <= 0:
            raise ValidationError("Payment amount must be positive")

        if amount > self.remaining_amount:
            raise ValidationError("Payment amount exceeds remaining balance")

        # Refresh from database to avoid race conditions
        self.refresh_from_db()

        current_paid = getattr(self, "paid_amount", Decimal("0"))
        self.paid_amount = current_paid + Decimal(str(amount))
        if payment_method:
            self.payment_method = payment_method

        self.save()
        return self.remaining_amount

    ## calculation for the invoice
    @property
    def _cached_invoice_items(self):
        """Cache invoice_items queryset to avoid repeated DB hits."""
        if not hasattr(self, "_items_cache"):
            self._items_cache = list(self.invoice_items.all())
        return self._items_cache

    @property
    def get_total_quantity(self):
        """Total quantity for the invoice"""
        return self.invoice_items.aggregate(total_quantity=Sum("quantity"))[
            "total_quantity"
        ]

    @property
    def total_tax_value(self):
        """Total tax value (sum of tax_value from all invoice items)"""
        return round(
            sum(item.tax_value for item in self._cached_invoice_items), 2
        )

    @property
    def total_gst_amount(self):
        """Total GST amount (sum of gst_amount from all invoice items)"""
        return round(
            sum(item.gst_amount for item in self._cached_invoice_items), 2
        )

    @property
    def cgst_amount(self):
        """CGST amount (sum of cgst_amount from all invoice items)"""
        return round(self.total_gst_amount / 2, 2)

    @property
    def tax_values_by_gst(self):
        """
        Calculate tax values grouped by GST rate
        """
        gst_groups: dict[int | str, dict[str, Decimal]] = defaultdict(
            lambda: {"tax_value": Decimal("0.00"), "total_tax_value": Decimal("0.00")}
        )

        for item in self._cached_invoice_items:
            gst_rate = item.gst_percentage
            gst_groups[gst_rate]["tax_value"] += item.tax_value
            gst_groups[gst_rate]["total_tax_value"] += item.gst_amount

        data = {
            "details": {
                gst: {
                    "tax_value": round(values["tax_value"], 2),
                    "total_tax_value": round(values["total_tax_value"], 2),
                }
                for gst, values in gst_groups.items()
            }
        }
        return data


class InvoiceItemFinancialMixin:
    """Mixin containing all financial calculation properties for InvoiceItem"""

    @property
    def actual_quantity(self):
        """Actual quantity for the invoice item"""
        qty = self.return_items.aggregate(total=Sum("quantity_returned"))[
            "total"
        ] or Decimal("0")
        return self.quantity - qty

    @property
    def actual_amount(self):
        """Actual amount for the invoice item"""
        return self.actual_quantity * self.unit_price

    @property
    def amount(self):
        """Total amount before any discounts"""
        return self.quantity * self.unit_price

    @property
    def discount_amount_per_unit(self):
        """Discount amount per unit"""
        return self.mrp - self.unit_price

    @property
    def total_discount_amount(self):
        """Total discount amount for this line item"""
        return self.discount_amount_per_unit * self.quantity

    @property
    def discount_share(self):
        """
        Proportional share of invoice-level discount for this stock item.
        """
        return (
            (Decimal(self.amount) / self.invoice.amount * self.invoice.discount_amount)
            if self.invoice.amount
            else Decimal(0)
        )

    @property
    def discounted_amount(self):
        """
        Amount after subtracting discount share.
        """
        return Decimal(self.amount) - self.discount_share

    @property
    def tax_value(self):
        """Taxable value after discount share"""
        return self.discounted_amount / (1 + (self.gst_percentage / 100))

    @property
    def gst_amount(self):
        """
        GST amount (total of CGST + SGST or IGST).
        """
        return round(self.discounted_amount - self.tax_value, 2)

    @property
    def commission_amount(self):
        """
        Commission amount for this line item.
        Calculated as (commission_percentage / 100) * discounted_amount.
        """
        if self.commission_percentage and self.commission_percentage > 0:
            return (
                self.commission_percentage / Decimal("100")
            ) * self.discounted_amount
        return Decimal("0.00")

    # @property
    # def cgst(self):
    #     return round(self.gst_amount / 2, 2)

    # @property
    # def get_gst_percentage(self):
    #     """Total amount for this line item"""
    #     if self.invoice.invoice_type == "IGST":
    #         return self.gst_percentage
    #     elif self.invoice.invoice_type == "CGST_SGST":
    #         return self.gst_percentage / 2
    #     return Decimal("0")

    # @property
    # def discount_percentage(self):
    #     """Discount percentage based on MRP vs Selling Price"""
    #     logger.debug(f"Discount percentage: {((self.mrp - self.unit_price) / self.mrp) * 100}")
    #     if self.mrp > 0:
    #         return ((self.mrp - self.unit_price) / self.mrp) * 100
    #     return Decimal("0")

    # @property
    # def gross_amount(self):
    #     """Total at MRP (before discount)"""
    #     logger.debug(f"Gross amount: {self.quantity * self.mrp}")
    #     return self.quantity * self.mrp

    # @property
    # def tax_rate(self):
    #     """Get tax rate from product"""
    #     return self.get_gst_percentage

    # @property
    # def calculated_tax_amount(self):
    #     """Tax amount based on net amount and product tax rate"""
    #     if self.tax_rate > 0:
    #         return (self.net_amount * self.tax_rate) / 100
    #     return Decimal("0")

    # @property
    # def total_amount(self):
    #     """Final total including tax"""
    #     return self.net_amount + self.calculated_tax_amount

    # @property
    # def profit_amount_per_unit(self):
    #     """Profit per unit"""
    #     return self.unit_price - self.purchase_price

    # @property
    # def total_profit(self):
    #     """Total profit for this line item"""
    #     return self.profit_amount_per_unit * self.quantity

    # @property
    # def profit_margin_percentage(self):
    #     """Profit margin as percentage of selling price"""
    #     if self.unit_price > 0:
    #         return (self.profit_amount_per_unit / self.unit_price) * 100
    #     return Decimal("0")

    # @property
    # def markup_percentage(self):
    #     """Markup percentage on purchase price"""
    #     if self.purchase_price > 0:
    #         return (self.profit_amount_per_unit / self.purchase_price) * 100
    #     return Decimal("0")

    ## calculation for tax values


class InvoiceValidationMixin:
    """Mixin containing validation methods for Invoice"""

    def validate_financial_amounts(self):
        """Validate all financial amounts"""
        # Validate discount doesn't exceed amount
        if self.discount_amount and self.discount_amount > self.amount:
            raise ValidationError("Discount amount cannot exceed invoice amount")

        if self.discount_amount and self.discount_amount < 0:
            raise ValidationError("Discount amount cannot be negative")

        # Validate advance amount
        if self.advance_amount and self.advance_amount < 0:
            raise ValidationError("Advance amount cannot be negative")

        # Validate advance amount for credit invoices
        if self.payment_type == "CREDIT":
            if self.advance_amount and self.advance_amount > self.total_payable:
                raise ValidationError(
                    {
                        "advance_amount": "Advance amount cannot exceed total payable amount"
                    }
                )

        # Validate due date for credit invoices
        if (
            self.payment_type == "CREDIT"
            and self.due_date
            and self.due_date.date() <= self.invoice_date.date()
        ):
            raise ValidationError(
                "Due date must be after invoice date for credit invoices"
            )

        # Validate payment method for cash invoices
        if self.payment_type == "CASH" and self.payment_method in ["CASH_ON_DELIVERY"]:
            raise ValidationError("Cash on Delivery is not valid for cash invoices")


class InvoiceItemValidationMixin:
    """Mixin containing validation methods for InvoiceItem"""

    def validate_item_amounts(self):
        """Validate all item amounts"""
        # Validate unit price doesn't exceed MRP
        if self.unit_price and self.mrp and self.unit_price > self.mrp:
            raise ValidationError("Unit price cannot exceed MRP")

        # Validate quantity is positive
        if self.quantity <= 0:
            raise ValidationError("Quantity must be greater than 0")

        # Validate prices are non-negative
        if self.unit_price < 0:
            raise ValidationError("Unit price cannot be negative")

        if self.mrp < 0:
            raise ValidationError("MRP cannot be negative")

        if self.purchase_price < 0:
            raise ValidationError("Purchase price cannot be negative")
