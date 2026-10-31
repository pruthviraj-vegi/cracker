"""Models for the user app."""

from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from base.manager import SoftDeleteModel
from base.utility import StringProcessor

from .managers import CustomUserManager

User = settings.AUTH_USER_MODEL


class CustomUser(AbstractBaseUser, PermissionsMixin, SoftDeleteModel):
    """Custom User model for the application."""

    first_name = models.CharField(max_length=255, null=True, blank=True)
    last_name = models.CharField(max_length=255, null=True, blank=True)

    profile_id = models.CharField(max_length=255, unique=True, null=True, blank=True)

    email = models.EmailField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        verbose_name=_("Email Address (Optional)"),
        help_text=_("Optional email address. Leave blank if not needed."),
    )
    phone_number = models.CharField(
        max_length=15, unique=True, verbose_name=_("Phone Number")
    )
    address = models.TextField(max_length=255, null=True, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    # --- ADDED TO FIX MIGRATION ERROR ---
    # These fields are required to avoid clashes with the default User model's
    # reverse accessors when you have a custom user model.
    groups = models.ManyToManyField(
        "auth.Group",
        verbose_name=_("groups"),
        blank=True,
        help_text=_(
            "The groups this user belongs to. A user will get all permissions "
            "granted to each of their groups."
        ),
        related_name="customuser_set",  # Unique related_name
        related_query_name="user",
    )
    user_permissions = models.ManyToManyField(
        "auth.Permission",
        verbose_name=_("user permissions"),
        blank=True,
        help_text=_("Specific permissions for this user."),
        related_name="customuser_permissions_set",  # Unique related_name
        related_query_name="user",
    )

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = ["first_name"]
    objects = CustomUserManager()

    def save(self, *args, **kwargs):

        self.first_name = StringProcessor(self.first_name).toTitle()
        self.last_name = StringProcessor(self.last_name).toTitle()
        processed_email = StringProcessor(self.email).toLowercase()
        self.email = processed_email if processed_email else None
        self.address = StringProcessor(self.address).toTitle()

        # Save first to get pk if it doesn't exist (for new instances)
        is_new = self.pk is None
        if is_new:
            super().save(*args, **kwargs)

        # Generate profile_id with pk
        if not self.profile_id:
            self.profile_id = StringProcessor(f"SSC@{self.pk}").toUppercase()
        else:
            self.profile_id = StringProcessor(self.profile_id).toUppercase()

        # Save again if this was a new instance to update profile_id, otherwise just save
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def username(self):
        """Return the username of the user (first name)."""
        return self.first_name

    @property
    def full_name(self):
        """Return the full name of the user."""
        return str(self.first_name) + " " + str(self.last_name)

    @property
    def current_salary(self):
        """Get the current active salary record (effective_to is None) with prefetch support."""
        if hasattr(self, "current_salaries"):
            salaries = self.current_salaries
            return salaries[0] if salaries else None

        if hasattr(self, "_prefetched_objects_cache") and "salaries" in self._prefetched_objects_cache:
            for s in self.salaries.all():
                if s.effective_to is None:
                    return s
            return None

        return self.salaries.filter(effective_to__isnull=True).first()

    @property
    def commission(self):
        """Get commission status from current salary (inactive if user is inactive)."""
        if not self.is_active:
            return False
        current = self.current_salary
        return current.commission if current else False

    class Meta:
        permissions = [
            ("view_dashboard", "Can view user dashboard"),
        ]

    @property
    def is_commission_eligible(self):
        """Check if the user is eligible for commission (inactive if user is inactive)."""
        if not self.is_active:
            return False
        return self.current_salary.commission if self.current_salary else False


class Salary(models.Model):
    """Salary model to track user compensations."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="salaries")
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    commission = models.BooleanField(default=False)
    effective_from = models.DateTimeField(default=timezone.now)
    effective_to = models.DateTimeField(null=True, blank=True)  # null = current salary
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_salaries",
    )

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self):
        return f"{self.user.full_name} - {self.amount} ({self.effective_from})"

    def is_eligible_for_salary(self):
        """Check if the salary is active and eligible."""
        if self.user.is_commission_eligible:
            return True
        return False


class Transaction(models.Model):
    """Transaction model to track financial operations."""

    class TransactionType(models.TextChoices):
        """Choices for transaction types."""

        SALE = "SALE", "Sale"
        REFUND = "REFUND", "Refund"
        PAYMENT = "PAYMENT", "Payment"
        WITHDRAWAL = "WITHDRAWAL", "Withdrawal"
        DEPOSIT = "DEPOSIT", "Deposit"
        COMMISSION = "COMMISSION", "Commission"
        SALARY = "SALARY", "Salary"
        EXPENSE = "EXPENSE", "Expense"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    class PaymentMethod(models.TextChoices):
        """Choices for payment methods."""

        CASH = "CASH", "Cash"
        CARD = "CARD", "Card"
        UPI = "UPI", "UPI"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
        CHEQUE = "CHEQUE", "Cheque"
        OTHER = "OTHER", "Other"

    # Transaction identification
    transaction_id = models.CharField(
        max_length=100,
        unique=True,
        editable=False,
        help_text="Auto-generated unique transaction ID",
    )

    # User who performed/is associated with the transaction
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="transactions",
        help_text="User associated with this transaction",
    )

    # Transaction details
    transaction_type = models.CharField(
        max_length=20, choices=TransactionType.choices, default=TransactionType.SALE
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Transaction amount",
    )
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )

    # Optional fields
    description = models.TextField(
        blank=True, null=True, help_text="Additional details about the transaction"
    )
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="External reference number (e.g., invoice number, receipt number)",
    )

    date = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Tracking
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_transactions",
        help_text="User who created this transaction record",
    )

    # Notes for internal use
    notes = models.TextField(
        blank=True, null=True, help_text="Internal notes (not visible to customer)"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["transaction_type", "-created_at"]),
        ]
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"

    def save(self, *args, **kwargs):
        # Generate unique transaction ID if not exists
        if not self.transaction_id:
            self.transaction_id = self.generate_transaction_id()
        super().save(*args, **kwargs)

    def generate_transaction_id(self):
        """Generate a unique transaction ID"""
        import uuid
        from datetime import datetime

        # Format: TXN-YYYYMMDD-XXXXXXXX
        date_part = datetime.now().strftime("%Y%m%d")
        unique_part = uuid.uuid4().hex[:8].upper()
        return f"TXN-{date_part}-{unique_part}"

    def __str__(self):
        return f"{self.transaction_id} - {self.user.full_name} - {self.amount}"

    @property
    def is_credit(self):
        """Check if transaction adds money (credit)"""
        credit_types = [
            self.TransactionType.SALE,
            self.TransactionType.DEPOSIT,
            self.TransactionType.PAYMENT,
            self.TransactionType.SALARY,
            self.TransactionType.COMMISSION,
        ]
        return self.transaction_type in credit_types

    @property
    def is_debit(self):
        """Check if transaction removes money (debit)"""
        debit_types = [
            self.TransactionType.REFUND,
            self.TransactionType.WITHDRAWAL,
            self.TransactionType.EXPENSE,
        ]
        return self.transaction_type in debit_types

    def get_display_amount(self):
        """Return amount with proper sign for display"""
        if self.is_debit:
            return self.amount * -1
        return self.amount

