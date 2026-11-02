"""
Forms for creating and managing invoices, returns, and audit trails.
"""

import logging
from datetime import timedelta

from django import forms
from django.utils import timezone

from base.forms import ThemedFormMixin
from base.widgets import AnimatedDatePickerWidget
from customer.models import Customer
from invoice.models import AuditTable, Invoice, InvoiceAudit, ReturnInvoice
from user.models import CustomUser

logger = logging.getLogger(__name__)


class InvoiceForm(ThemedFormMixin, forms.ModelForm):
    """Form for creating and editing standard invoices."""

    class Meta:
        model = Invoice
        fields = [
            "customer",
            "amount",
            "discount_amount",
            "payment_type",
            "advance_amount",
            "payment_method",
            "notes",
        ]
        widgets = {
            "customer": forms.Select(attrs={"placeholder": "Select customer"}),
            "payment_type": forms.Select(),
            "amount": forms.TextInput(attrs={"readonly": True}),
            "discount_amount": forms.TextInput(
                attrs={
                    "placeholder": "0.00",
                    "autofocus": True,
                }
            ),
            "advance_amount": forms.TextInput(
                attrs={
                    "placeholder": "0.00",
                    "readonly": True,
                }
            ),
            "payment_method": forms.Select(),
            "notes": forms.Textarea(
                attrs={
                    "placeholder": "Enter any additional notes",
                    "rows": "3",
                }
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

        # Add required field indicators
        for field in self.fields.values():
            if field.required:
                field.label = f"{field.label} *"

        # Apply theme classes via mixin
        self.apply_theme_classes()

        self.fields["payment_type"].widget.attrs["class"] = "select-toggle"
        self.fields["payment_method"].widget.attrs["class"] = "select-toggle"
        self.fields["discount_amount"].widget.attrs[
            "class"
        ] = " form-input indian-number"
        self.fields["advance_amount"].widget.attrs["class"] = "form-input indian-number"
        self.fields["amount"].widget.attrs["class"] = "form-input indian-number"

        # Set initial customer for new invoices
        try:
            if not self.instance.pk:
                default_customer = Customer.get_default_customer()
                if default_customer:
                    self.fields["customer"].initial = default_customer
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Error setting initial customer: %s", e)

    def save(self, commit=True):
        """Save invoice instance and assign sold_by, invoice_date, and due_date if not already set."""
        instance = super().save(commit=False)
        if not getattr(instance, "sold_by_id", None) and self.user:
            instance.sold_by = self.user
        if not getattr(instance, "invoice_date", None):
            instance.invoice_date = timezone.now()
        if instance.payment_type == Invoice.PaymentType.CREDIT:
            if not getattr(instance, "due_date", None):
                instance.due_date = timezone.now() + timedelta(days=30)
        elif instance.payment_type == Invoice.PaymentType.CASH:
            instance.due_date = None
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    def clean_amount(self):
        """Validate amount is not negative"""
        amount = self.cleaned_data.get("amount")
        if amount and amount < 0:
            raise forms.ValidationError({"amount": "Amount cannot be negative"})
        return amount

    def clean_discount_amount(self):
        """Validate discount amount and default to 0 if empty"""
        discount_amount = self.cleaned_data.get("discount_amount")
        if discount_amount is None or discount_amount == "":
            return 0
        if discount_amount < 0:
            raise forms.ValidationError(
                {"discount_amount": "Discount amount cannot be negative"}
            )
        return discount_amount

    def clean_advance_amount(self):
        """Validate advance amount and default to 0 if empty"""
        advance_amount = self.cleaned_data.get("advance_amount")
        if advance_amount is None or advance_amount == "":
            return 0
        if advance_amount < 0:
            raise forms.ValidationError(
                {"advance_amount": "Advance amount cannot be negative"}
            )
        return advance_amount

    def clean(self):
        """Cross-field validation and business logic"""
        cleaned_data = super().clean()
        amount = cleaned_data.get("amount")
        discount_amount = cleaned_data.get("discount_amount", 0)
        payment_type = cleaned_data.get("payment_type")
        customer = cleaned_data.get("customer")

        # Walk-in customer (default ID) must use CASH payment type
        if (
            customer
            and customer.id == Customer.get_default_customer().id
            and payment_type == Invoice.PaymentType.CREDIT
        ):
            cleaned_data["payment_type"] = Invoice.PaymentType.CASH
            payment_type = Invoice.PaymentType.CASH

        # For cash invoices, advance_amount must be 0
        if payment_type == Invoice.PaymentType.CASH:
            cleaned_data["advance_amount"] = 0

        # Validate discount doesn't exceed amount
        if amount and discount_amount and discount_amount > amount:
            raise forms.ValidationError(
                {"discount_amount": "Discount amount cannot exceed invoice amount"}
            )

        return cleaned_data



class AuditTableForm(forms.ModelForm):
    """Form for creating audit table sessions"""

    class Meta:
        model = AuditTable
        fields = [
            "title",
            "description",
            "audit_type",
            "start_date",
            "end_date",
            "financial_year",
            "status",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-input",
                    "placeholder": "Enter audit session title...",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-textarea",
                    "placeholder": "Describe the purpose of this audit session...",
                    "rows": 3,
                }
            ),
            "audit_type": forms.Select(attrs={"class": "form-select"}),
            "start_date": AnimatedDatePickerWidget(
                enable_time=False,
                icon_class="fa-calendar-days",
                attrs={"placeholder": "Select start date"},
            ),
            "end_date": AnimatedDatePickerWidget(
                enable_time=False,
                icon_class="fa-calendar-check",
                attrs={"placeholder": "Select end date"},
            ),
            "financial_year": forms.TextInput(
                attrs={"class": "form-input", "placeholder": "e.g., 24-25"}
            ),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add required field indicators
        for _, field in self.fields.items():
            if field.required:
                field.label = f"{field.label} *"


class AuditFilterForm(forms.Form):
    """Form for filtering audit trail records"""

    # Search field
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-input",
                "placeholder": "Search by invoice number, reason, or user name...",
            }
        ),
    )

    # Date range fields
    start_date = forms.DateField(
        required=False,
        widget=AnimatedDatePickerWidget(
            enable_time=False,
            attrs={"placeholder": "Start date"},
        ),
    )

    end_date = forms.DateField(
        required=False,
        widget=AnimatedDatePickerWidget(
            enable_time=False,
            attrs={"placeholder": "End date"},
        ),
    )

    changed_by = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        required=False,
        empty_label="All Users",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    financial_year = forms.ChoiceField(
        required=False,
        choices=[("", "All Financial Years")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Populate financial year choices dynamically
        current_year = timezone.now().year
        fy_choices = [("", "All Financial Years")]

        # Add current and previous financial years
        for year in range(current_year - 2, current_year + 1):
            fy_choices.append((str(year), str(year)))

        self.fields["financial_year"].choices = fy_choices

        # Populate changed_by queryset with users who have made audit records
        if "changed_by" in self.fields:
            audit_users = CustomUser.objects.filter(
                id__in=InvoiceAudit.objects.values_list("changed_by", flat=True).distinct()
            ).order_by("first_name", "last_name")
            self.fields["changed_by"].queryset = audit_users


class ReturnInvoiceForm(forms.ModelForm):
    """Form for creating return invoices"""

    class Meta:
        model = ReturnInvoice
        fields = [
            "invoice",
            "refund_type",
            "status",
            "reason",
            "total_amount",
            "refund_amount",
            "restocking_fee",
            "return_date",
            "notes",
            "internal_notes",
        ]
        widgets = {
            "invoice": forms.Select(
                attrs={"class": "form-select", "placeholder": "Select original invoice"}
            ),
            "refund_type": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "reason": forms.Select(attrs={"class": "form-select"}),
            "total_amount": forms.NumberInput(
                attrs={
                    "class": "form-input",
                    "placeholder": "0.00",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "refund_amount": forms.NumberInput(
                attrs={
                    "class": "form-input",
                    "placeholder": "0.00",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "restocking_fee": forms.NumberInput(
                attrs={
                    "class": "form-input",
                    "placeholder": "0.00",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "return_date": AnimatedDatePickerWidget(
                enable_time=True,
                icon_class="fa-calendar-days",
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-textarea",
                    "placeholder": "Enter any additional notes for the customer",
                    "rows": "3",
                }
            ),
            "internal_notes": forms.Textarea(
                attrs={
                    "class": "form-textarea",
                    "placeholder": "Enter internal notes for staff only",
                    "rows": "3",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add required field indicators
        for _, field in self.fields.items():
            if field.required:
                field.label = f"{field.label} *"

        # Set default values
        self.fields["status"].initial = ReturnInvoice.RefundStatus.PENDING
        self.fields["refund_type"].initial = ReturnInvoice.RefundType.CASH_REFUND
        self.fields["reason"].initial = ReturnInvoice.RefundReason.CUSTOMER_REQUEST
        self.fields["return_date"].initial = timezone.now()

        # Make some fields not required
        self.fields["restocking_fee"].required = False
        self.fields["notes"].required = False
        self.fields["internal_notes"].required = False

    def clean(self):
        cleaned_data = super().clean()
        total_amount = cleaned_data.get("total_amount")
        refund_amount = cleaned_data.get("refund_amount")
        restocking_fee = cleaned_data.get("restocking_fee")

        # Handle empty fields by setting them to 0
        if restocking_fee is None or restocking_fee == "":
            cleaned_data["restocking_fee"] = 0

        # Validate refund amount doesn't exceed total amount
        if total_amount and refund_amount and refund_amount > total_amount:
            raise forms.ValidationError("Refund amount cannot exceed total amount")

        return cleaned_data

    def clean_total_amount(self):
        """Clean and validate the total amount field."""
        total_amount = self.cleaned_data.get("total_amount")
        if total_amount and total_amount < 0:
            raise forms.ValidationError("Total amount cannot be negative")
        return total_amount

    def clean_refund_amount(self):
        """Clean and validate the refund amount field."""
        refund_amount = self.cleaned_data.get("refund_amount")
        if refund_amount is None or refund_amount == "":
            return 0
        if refund_amount < 0:
            raise forms.ValidationError("Refund amount cannot be negative")
        return refund_amount

    def clean_restocking_fee(self):
        """Clean and validate the restocking fee field."""
        restocking_fee = self.cleaned_data.get("restocking_fee")
        if restocking_fee is None or restocking_fee == "":
            return 0
        if restocking_fee < 0:
            raise forms.ValidationError("Restocking fee cannot be negative")
        return restocking_fee

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Auto-populate customer from the selected invoice
        if instance.invoice:
            instance.customer = instance.invoice.customer
        if commit:
            instance.save()
        return instance


class InvoiceCancellationForm(forms.Form):
    """Form for cancelling invoices"""

    cancellation_reason = forms.CharField(
        required=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-textarea",
                "placeholder": "Please provide a detailed reason for cancelling this invoice...",
                "rows": "4",
                "autofocus": True,
            }
        ),
        label="Cancellation Reason *",
        help_text="This reason will be permanently recorded in the audit trail",
    )

    confirm_cancellation = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
        label="I confirm that I want to cancel this invoice",
        error_messages={"required": "You must confirm the cancellation to proceed"},
    )

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice

    def clean_cancellation_reason(self):
        """Clean and validate the cancellation reason field."""
        reason = self.cleaned_data.get("cancellation_reason")
        if reason and len(reason.strip()) < 10:
            raise forms.ValidationError(
                "Please provide a more detailed reason (at least 10 characters)"
            )
        return reason.strip()

    def clean(self):
        cleaned_data = super().clean()

        # Validate invoice can be cancelled
        if self.invoice:
            can_cancel, error_msg = self.invoice.can_be_cancelled()
            if not can_cancel:
                raise forms.ValidationError(error_msg)

        return cleaned_data
