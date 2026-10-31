"""
Form definitions for the customer application.

This module provides forms to manage customers and their payments, ensuring
proper validation for fields such as phone numbers, emails, and payment amounts.
"""

from django import forms

from base.forms import ThemedFormMixin
from base.widgets import AnimatedDatePickerWidget
from .models import Customer, Payment


class CustomerForm(forms.ModelForm):
    """
    Form for creating and updating Customer instances.

    Handles customer details such as name, phone number, email, address, and
    referral, providing comprehensive validations for unique field constraints.
    """

    class Meta:
        model = Customer
        fields = ["name", "phone_number", "email", "address", "referred_by"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Enter full name",
                    "autofocus": True,
                }
            ),
            "phone_number": forms.TextInput(
                attrs={
                    "type": "tel",
                    "placeholder": "Enter 10-digit phone number",
                    "maxlength": "10",
                    "pattern": "[0-9]{10}",
                    "inputmode": "numeric",
                }
            ),
            "email": forms.EmailInput(attrs={"placeholder": "Enter email address"}),
            "address": forms.Textarea(
                attrs={
                    "placeholder": "Enter complete address",
                    "rows": "4",
                }
            ),
            "referred_by": forms.Select(attrs={}),
        }

    def __init__(self, *args, **kwargs):
        """
        Initializes the CustomerForm with appropriate widget attributes and logic.

        Sets required indicators, applies CSS classes, and manipulates the
        referral choices based on whether the customer is being edited or created.
        """
        super().__init__(*args, **kwargs)

        # Add required field indicators
        for _, field in self.fields.items():
            if field.required:
                field.label = f"{field.label} *"

        # Adding form-control class to all fields
        for visible in self.visible_fields():
            visible.field.widget.attrs["class"] = "form-input"

        # Override maxlength for phone_number to enforce 10 digits
        self.fields["phone_number"].widget.attrs["maxlength"] = "10"

        # Referred by is optional; exclude self from choices if editing
        self.fields["referred_by"].required = False
        if self.instance.pk:
            self.fields["referred_by"].queryset = Customer.objects.exclude(
                pk=self.instance.pk
            )
        else:
            self.fields["referred_by"].queryset = Customer.objects.all()

    def clean_phone_number(self):
        """
        Validates the phone_number field for proper format and uniqueness.

        Returns:
            str: The validated 10-digit phone number.

        Raises:
            ValidationError: If the phone number is not 10 digits or is already used.
        """
        phone_number = self.cleaned_data.get("phone_number")
        if not phone_number:
            raise forms.ValidationError("Phone number is required.")

        # Check if phone number is exactly 10 digits
        if not phone_number.isdigit() or len(phone_number) != 10:
            raise forms.ValidationError(
                "Phone number must be exactly 10 digits (e.g., 9876543210)."
            )

        # Check for duplicate phone number, excluding current instance
        existing_customer = Customer.objects.filter(phone_number=phone_number)
        if self.instance.pk:
            existing_customer = existing_customer.exclude(pk=self.instance.pk)

        if existing_customer.exists():
            raise forms.ValidationError(
                "This phone number is already in use by another customer."
            )

        return phone_number

    def clean_email(self):
        """
        Validates the email and ensures it's stored in lowercase.

        Returns:
            str: The validated lowercase email, if provided.

        Raises:
            ValidationError: If the provided email format is invalid.
        """
        email = self.cleaned_data.get("email")
        if email:
            # Additional validation (Django's EmailField already validates basic format)
            if "@" not in email:
                raise forms.ValidationError("Please enter a valid email address.")
            return email.lower()
        return email


class PaymentForm(ThemedFormMixin, forms.ModelForm):
    """
    Form for processing and logging customer Payments.

    Handles fields like customer, payment type, amount, method, and transaction
    details. Enforces validation to ensure payment amounts are strictly positive.
    """

    class Meta:
        model = Payment
        fields = [
            "customer",
            "payment_type",
            "amount",
            "method",
            "transaction_id",
            "payment_date",
            "notes",
        ]
        widgets = {
            "customer": forms.Select(
                attrs={
                    "placeholder": "Select customer",
                    "help_text": "Select the customer for the payment",
                }
            ),
            "payment_type": forms.Select(
                attrs={
                    "placeholder": "Select payment type",
                    "help_text": "Select the payment type for the payment",
                }
            ),
            "amount": forms.TextInput(
                attrs={
                    "placeholder": "Enter amount",
                    "autofocus": True,
                    "help_text": "Enter the amount for the payment",
                }
            ),
            "method": forms.Select(attrs={}),
            "transaction_id": forms.TextInput(
                attrs={
                    "placeholder": "Transaction reference (optional)",
                    "help_text": "Enter the transaction reference for the payment",
                }
            ),
            "payment_date": AnimatedDatePickerWidget(
                enable_time=True,
                icon_class="fa-calendar-days",
                attrs={"placeholder": "Select payment date & time"},
            ),
            "notes": forms.Textarea(
                attrs={
                    "placeholder": "Enter payment notes",
                    "rows": "2",
                    "help_text": "Enter the notes for the payment",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        """
        Initializes the PaymentForm by parsing custom arguments and applying styling.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments. Target argument is `customer`.
        """
        self.customer = kwargs.pop("customer", None)
        super().__init__(*args, **kwargs)

        # Add required field indicators
        for _, field in self.fields.items():
            if field.required:
                field.label = f"{field.label} *"

        # Apply theme classes via mixin
        self.apply_theme_classes()

        self.fields["customer"].widget.attrs["class"] = "form-select"
        self.fields["amount"].widget.attrs["class"] = "form-input indian-number"
        self.fields["payment_type"].widget.attrs["class"] = "select-toggle"
        self.fields["method"].widget.attrs["class"] = "select-toggle"

        # Handle customer field if provided or if editing an existing payment instance
        customer = self.customer or (
            self.instance.customer if self.instance and self.instance.pk else None
        )
        if customer:
            self.customer = customer
            self.fields["customer"].queryset = Customer.objects.filter(pk=customer.pk)
            self.fields["customer"].initial = customer
            self.fields["customer"].disabled = True

    def clean_amount(self):
        """
        Validates the payment amount to ensure it is positive.

        Returns:
            Decimal: The validated, positive payment amount.

        Raises:
            ValidationError: If the amount is zero or negative.
        """
        amount = self.cleaned_data.get("amount")
        if amount is None or amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount
