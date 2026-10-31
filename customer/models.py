"""Models for the customer app, including Customer, Payment, and CustomerCreditSummary."""

from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from base.manager import SoftDeleteModel, phone_regex
from base.utility import StringProcessor

User = settings.AUTH_USER_MODEL


class Customer(SoftDeleteModel):
    """Customer model for storing customer information."""

    name = models.CharField(
        max_length=255, null=True, blank=True, help_text="Customer's full name"
    )
    phone_number = models.CharField(
        max_length=20,
        unique=True,
        validators=[phone_regex],
        help_text="Customer's phone number (unique)",
    )
    email = models.EmailField(
        blank=True, null=True, help_text="Customer's email address"
    )
    address = models.TextField(blank=True, null=True, help_text="Customer's address")
    store_credit_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Customer's store credit balance",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customers",
        help_text="User who created this customer record",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Referral linkage: which customer referred this customer
    referred_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referrals",
        help_text="Referring customer (who brought this customer)",
    )

    def __str__(self):
        """Return a string representation of the customer."""
        name_part = self.name or "Unknown"
        phone_part = self.phone_number or "No Phone"

        if self.address:
            return f"{name_part} ({self.address}) {phone_part}"
        return f"{name_part} {phone_part}"

    @property
    def display_name(self):
        """Return formatted display name."""
        return self.name or "Unknown Customer"

    @property
    def short_address(self):
        """Return shortened address for display."""
        if not self.address:
            return "No Address"
        return self.address[:50] + "..." if len(self.address) > 50 else self.address

    @property
    def has_credit(self):
        """Check if customer has store credit."""
        return self.store_credit_balance > 0

    @classmethod
    def get_default_customer(cls):
        """
        Get or create the default 'Walk-in' customer.
        This provides a reliable anchor for anonymous or quick POS sales.
        """
        customer, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "name": "Walk in",
                "phone_number": "3",
            },
        )
        return customer

    class Meta:
        indexes = [
            models.Index(fields=["name"], name="customer_name_idx"),
            models.Index(fields=["phone_number"], name="customer_phone_number_idx"),
            models.Index(fields=["created_at"], name="customer_created_at_idx"),
            models.Index(fields=["store_credit_balance"], name="customer_credit_idx"),
            models.Index(fields=["is_deleted"]),
        ]
        ordering = ["-created_at"]
        verbose_name = "Customer"
        verbose_name_plural = "Customers"
        permissions = [
            ("view_dashboard", "View Dashboard"),
            ("export_customers", "Export Customers"),
        ]

    def save(self, *args, **kwargs):
        """Override save method to clean and format data."""
        self.phone_number = StringProcessor(self.phone_number).cleaned_string
        self.name = StringProcessor(self.name).toTitle()
        self.email = StringProcessor(self.email).toLowercase()
        self.address = StringProcessor(self.address).toTitle()

        super().save(*args, **kwargs)

    def clean(self):
        """Custom validation."""
        # Ensure phone number is not empty
        if not self.phone_number:
            raise ValidationError("Phone number is required.")

        # Validate email format if provided
        if self.email and "@" not in self.email:
            raise ValidationError("Please enter a valid email address.")

        # Prevent setting self as referrer
        if self.pk and self.referred_by_id == self.pk:
            raise ValidationError("A customer cannot refer themselves.")

    def delete(self, *args, **kwargs):
        """Prevent deletion of the default Walk-in customer."""
        if self.pk == 1 or self.phone_number == "3":
            raise ValidationError("The default Walk-in customer cannot be deleted.")
        return super().delete(*args, **kwargs)


class Payment(SoftDeleteModel):
    """Records payments associated with a customer, including paid and purchased types."""

    class PaymentType(models.TextChoices):
        """Enumeration of payment types: Paid (received) or Purchased (owed)."""

        Paid = "PAID", "Paid"  # pylint: disable=C0103
        Purchased = "PURCHASED", "Purchased"  # pylint: disable=C0103

    class PaymentMethod(models.TextChoices):
        """Enumeration of accepted payment methods (Cash, UPI, Bank Transfer, etc.)."""

        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
        UPI = "UPI", "UPI"
        # CHEQUE = "CHEQUE", "Cheque"
        # CREDIT_CARD = "CREDIT_CARD", "Credit Card"
        # DEBIT_CARD = "DEBIT_CARD", "Debit Card"
        # ONLINE_PAYMENT = "ONLINE_PAYMENT", "Online Payment"

    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="credit_payments"
    )
    payment_type = models.TextField(
        max_length=20, choices=PaymentType.choices, default=PaymentType.Paid
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Enter the Amount",
    )
    method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
        help_text="Payment method used",
    )
    transaction_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Bank transaction reference number.",
    )
    unallocated_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Amount not yet allocated to invoices",
    )

    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_credit_payments",
    )
    payment_date = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Clean notes text and initialise unallocated_amount for new payments."""
        self.notes = StringProcessor(self.notes).toTitle()
        if not self.pk:
            # For both Paid and Purchased payments, initialize unallocated_amount
            # For Paid: amount not allocated to invoices or used to cover purchased payments
            # For Purchased: amount not yet covered by paid payments
            self.unallocated_amount = self.amount
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.customer} - {self.amount} ({self.get_payment_type_display()}) via {self.get_method_display()}"

    class Meta:
        indexes = [
            models.Index(fields=["customer", "payment_type", "is_deleted"]),
            models.Index(fields=["payment_type", "payment_date"]),
            models.Index(fields=["customer", "payment_date", "id"]),
            models.Index(fields=["is_deleted", "payment_type"]),
        ]


class CustomerCreditSummary(models.Model):
    """
    HIGH-PERFORMANCE denormalized summary table for customer credit data.
    Optimized with proper indexes, constraints, and field choices.
    """

    # Primary relationship
    customer = models.OneToOneField(
        "Customer",
        on_delete=models.CASCADE,
        related_name="credit_summary",
        primary_key=True,
        db_index=True,  # Explicit index for faster lookups
    )

    # ===== CREDIT BREAKDOWN =====
    credit_invoices_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        db_index=True,
        help_text="Sum of all credit invoices (after discount/advance)",
    )

    credit_purchased_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Sum of all purchased payments",
    )

    returns_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Sum of all approved returns",
    )

    # ===== CALCULATED TOTALS =====
    credit_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        db_index=True,  # Index for sorting/filtering
        help_text="Total credit = invoices + purchased - returns",
    )

    debit_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        db_index=True,  # Index for sorting/filtering
        help_text="Total payments made by customer",
    )

    balance_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        db_index=True,  # CRITICAL: Index for filtering customers with debt
        help_text="Outstanding balance = credit - debit (negative = customer has credit)",
    )

    # ===== ADDITIONAL METRICS =====
    total_invoices_count = models.PositiveIntegerField(
        default=0, help_text="Number of credit invoices"
    )

    unpaid_invoices_count = models.PositiveIntegerField(
        default=0, db_index=True, help_text="Number of unpaid/partially paid invoices"
    )

    last_invoice_date = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,  # Index for overdue filtering
        help_text="Date of first unpaid credit invoice (if balance > 500)",
    )

    last_payment_date = models.DateTimeField(
        null=True, blank=True, help_text="Date of most recent payment"
    )

    # ===== STATUS FLAGS =====
    is_overdue = models.BooleanField(
        default=False,
        db_index=True,  # Index for filtering overdue customers
        help_text="True if last_invoice_date > 6 months old",
    )

    has_outstanding_balance = models.BooleanField(
        default=False,
        db_index=True,  # Index for filtering customers with debt
        help_text="True if balance_amount > 0",
    )

    # ===== METADATA =====
    last_calculated = models.DateTimeField(
        auto_now=True,
        db_index=True,
        help_text="Last time this summary was recalculated",
    )

    calculation_version = models.PositiveIntegerField(
        default=1, help_text="Incremented each time calculation logic changes"
    )

    class Meta:
        db_table = "customer_credit_summary"
        verbose_name = "Customer Credit Summary"
        verbose_name_plural = "Customer Credit Summaries"

        # ===== COMPOSITE INDEXES for common queries =====
        indexes = [
            # For filtering customers with outstanding balance
            models.Index(
                fields=["has_outstanding_balance", "-balance_amount"],
                name="idx_outstanding_bal",
            ),
            # For filtering overdue customers
            models.Index(
                fields=["is_overdue", "-last_invoice_date"], name="idx_overdue"
            ),
            # For sorting by credit amount
            models.Index(fields=["-credit_amount"], name="idx_credit_desc"),
            # For sorting by balance
            models.Index(fields=["-balance_amount"], name="idx_balance_desc"),
            # For recent activity
            models.Index(fields=["-last_calculated"], name="idx_last_calc"),
        ]

        # ===== CONSTRAINTS =====
        constraints = [
            # Balance can be positive (customer owes) or negative (customer has credit)
            # No constraint needed - allow any decimal value
            # Ensure credit/debit component amounts are non-negative
            # (individual components should never be negative)
            models.CheckConstraint(
                check=models.Q(credit_invoices_total__gte=0),
                name="credit_invoices_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(credit_purchased_total__gte=0),
                name="purchased_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(returns_total__gte=0), name="returns_non_negative"
            ),
            models.CheckConstraint(
                check=models.Q(debit_amount__gte=0), name="debit_non_negative"
            ),
        ]
        permissions = [
            ("export_summery", "Customer Summery Details"),
        ]

    def __str__(self):
        return f"{self.customer.name} - Balance: {self.balance_amount:,.2f}"

    @classmethod
    def recalculate_for_customer(cls, customer, save=True):
        """
        OPTIMIZED recalculation with minimal queries.
        Uses select_for_update to prevent race conditions.
        """
        from django.db.models import Sum, F, Q, Count, Max  # pylint: disable=C0415
        from django.db.models.functions import Coalesce  # pylint: disable=C0415
        from django.db import transaction
        from invoice.models import Invoice

        with transaction.atomic():
            # Lock the summary row to prevent concurrent updates
            try:
                summary = cls.objects.select_for_update().get(customer=customer)
            except cls.DoesNotExist:
                summary = cls(customer=customer)

            # ===== SINGLE AGGREGATION QUERY for invoices =====
            invoice_stats = customer.invoices.filter(
                payment_type=Invoice.PaymentType.CREDIT, is_cancelled=False
            ).aggregate(
                total_amount=Coalesce(
                    Sum(F("amount") - F("discount_amount") - F("advance_amount")),
                    Decimal("0"),
                ),
                count=Count("id"),
                unpaid_count=Count(
                    "id",
                    filter=Q(
                        payment_status__in=[
                            Invoice.PaymentStatus.UNPAID,
                            Invoice.PaymentStatus.PARTIALLY_PAID,
                        ]
                    ),
                ),
            )

            # ===== SINGLE AGGREGATION QUERY for payments =====
            payment_stats = customer.credit_payments.aggregate(
                purchased=Coalesce(
                    Sum("amount", filter=Q(payment_type=Payment.PaymentType.Purchased)),
                    Decimal("0"),
                ),
                paid=Coalesce(
                    Sum("amount", filter=Q(payment_type=Payment.PaymentType.Paid)),
                    Decimal("0"),
                ),
                last_payment=Max(
                    "payment_date", filter=Q(payment_type=Payment.PaymentType.Paid)
                ),
            )

            # ===== SINGLE AGGREGATION QUERY for returns =====
            returns_stats = customer.return_invoices.filter(
                invoice__payment_type=Invoice.PaymentType.CREDIT,
                invoice__is_cancelled=False,
                status__in=["APPROVED", "COMPLETED"],
            ).aggregate(total=Coalesce(Sum("refund_amount"), Decimal("0")))

            # ===== CALCULATE TOTALS =====
            credit_invoices = invoice_stats["total_amount"]
            credit_purchased = payment_stats["purchased"]
            returns = returns_stats["total"]
            paid = payment_stats["paid"]

            credit_total = credit_invoices + credit_purchased - returns
            balance_total = credit_total - paid

            # ===== FIND LAST INVOICE DATE (only if balance > 500) =====
            last_inv_date = None
            if balance_total > 500:
                first_unpaid = (
                    customer.invoices.filter(
                        payment_type=Invoice.PaymentType.CREDIT,
                        is_cancelled=False,
                        payment_status__in=[
                            Invoice.PaymentStatus.UNPAID,
                            Invoice.PaymentStatus.PARTIALLY_PAID,
                        ],
                    )
                    .order_by("invoice_date")
                    .values("invoice_date")
                    .first()
                )

                if first_unpaid:
                    last_inv_date = first_unpaid["invoice_date"]

            # ===== CALCULATE OVERDUE STATUS =====

            six_months_ago = timezone.now() - timedelta(days=180)
            is_overdue = bool(last_inv_date and last_inv_date < six_months_ago)

            # ===== UPDATE SUMMARY =====
            summary.credit_invoices_total = credit_invoices
            summary.credit_purchased_total = credit_purchased
            summary.returns_total = returns
            summary.credit_amount = credit_total
            summary.debit_amount = paid
            summary.balance_amount = balance_total
            summary.total_invoices_count = invoice_stats["count"]
            summary.unpaid_invoices_count = invoice_stats["unpaid_count"]
            summary.last_invoice_date = last_inv_date
            summary.last_payment_date = payment_stats["last_payment"]
            summary.is_overdue = is_overdue
            summary.has_outstanding_balance = balance_total > 0

            if save:
                summary.save()

            return summary

    def get_status_display(self):
        if self.balance_amount < 0:
            return f"Credit Balance: {abs(self.balance_amount):,.2f}"
        if self.balance_amount == 0:
            return "Cleared"
        return "Overdue" if self.is_overdue else "Outstanding"

    @property
    def has_credit_balance(self):
        """Customer has overpaid and has credit"""
        return self.balance_amount < 0

    @property
    def customer_owes(self):
        """Amount customer owes (positive balance)"""
        return max(self.balance_amount, Decimal("0"))

    @property
    def customer_credit(self):
        """Amount customer has as credit (negative balance converted to positive)"""
        return abs(min(self.balance_amount, Decimal("0")))
