"""
Forms for user management and related models.
"""

import logging

from django import forms
from django.utils import timezone

from base.forms import ThemedFormMixin
from base.widgets import AnimatedDatePickerWidget
from .models import CustomUser, Salary, Transaction

logger = logging.getLogger(__name__)


class CustomUserForm(forms.ModelForm):
    """Unified form for creating and editing users."""

    class Meta:
        model = CustomUser
        fields = (
            "first_name",
            "last_name",
            "phone_number",
            "email",
            "groups",
            "is_active",
            "address",
        )
        widgets = {
            "first_name": forms.TextInput(
                attrs={
                    "placeholder": "Enter first name",
                    "autofocus": True,
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "placeholder": "Enter last name",
                }
            ),
            "phone_number": forms.TextInput(
                attrs={
                    "type": "tel",
                    "placeholder": "Enter phone number",
                    "maxlength": "15",
                    "inputmode": "numeric",
                }
            ),
            "email": forms.EmailInput(attrs={"placeholder": "Enter email address"}),
            "groups": forms.SelectMultiple(
                attrs={
                    "class": "form-select",
                    "data-placeholder": "Select roles/groups",
                }
            ),
            "is_active": forms.CheckboxInput(attrs={}),
            "address": forms.Textarea(
                attrs={
                    "placeholder": "Enter address",
                    "rows": 3,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add required field indicators
        for _, field in self.fields.items():
            if field.required:
                field.label = f"{field.label} *"

        # Add appropriate classes to all fields based on widget type
        for visible in self.visible_fields():
            widget = visible.field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-checkbox"
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "form-select"
            elif isinstance(widget, forms.Textarea):
                widget.attrs["class"] = "form-textarea"
            else:
                widget.attrs["class"] = "form-input"

        # Override maxlength for phone_number to enforce 10 digits
        self.fields["phone_number"].widget.attrs["maxlength"] = "10"

    def clean_phone_number(self):
        """Validate that the phone number is unique."""
        phone_number = self.cleaned_data.get("phone_number")
        if not phone_number:
            raise forms.ValidationError("Phone number is required.")

        # Check for duplicate phone number, excluding current instance
        existing_user = CustomUser.objects.filter(phone_number=phone_number)
        if self.instance and self.instance.pk:
            existing_user = existing_user.exclude(pk=self.instance.pk)

        if existing_user.exists():
            raise forms.ValidationError(
                "This phone number is already in use by another user."
            )

        return phone_number

    def clean_email(self):
        """Validate that the email address is unique and valid."""
        email = self.cleaned_data.get("email")
        if email:
            # Additional validation (Django's EmailField already validates basic format)
            if "@" not in email:
                raise forms.ValidationError("Please enter a valid email address.")

            # Check for duplicate email, excluding current instance
            existing_user = CustomUser.objects.filter(email=email.lower())
            if self.instance and self.instance.pk:
                existing_user = existing_user.exclude(pk=self.instance.pk)

            if existing_user.exists():
                raise forms.ValidationError(
                    "This email address is already in use by another user."
                )
            return email.lower()
        return email or None  # Convert empty string to None


class PasswordResetForm(forms.Form):
    """Simple password reset form with minimal validation."""

    new_password = forms.CharField(
        max_length=128,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter new password",
                "autofocus": True,
            }
        ),
        label="New Password",
    )

    confirm_password = forms.CharField(
        max_length=128,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Confirm new password",
            }
        ),
        label="Confirm Password",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add required field indicators
        for _, field in self.fields.items():
            if field.required:
                field.label = f"{field.label} *"

        # Add appropriate classes to all fields based on widget type
        for visible in self.visible_fields():
            widget = visible.field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-checkbox"
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "form-select"
            elif isinstance(widget, forms.Textarea):
                widget.attrs["class"] = "form-textarea"
            else:
                widget.attrs["class"] = "form-input"

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if new_password and confirm_password:
            if new_password != confirm_password:
                raise forms.ValidationError("Passwords do not match.")

        return cleaned_data

    def clean_new_password(self):
        """Validate that the new password is provided."""
        new_password = self.cleaned_data.get("new_password")
        if not new_password:
            raise forms.ValidationError("Password is required.")
        return new_password


class SalaryForm(ThemedFormMixin, forms.ModelForm):
    """Form for creating and editing salary records."""

    class Meta:
        model = Salary
        fields = ("amount", "commission", "effective_from", "effective_to")
        widgets = {
            "amount": forms.NumberInput(
                attrs={
                    "placeholder": "Enter salary amount",
                    "autofocus": True,
                }
            ),
            "commission": forms.CheckboxInput(attrs={}),
            "effective_from": AnimatedDatePickerWidget(
                enable_time=False,
                icon_class="fa-calendar-days",
                attrs={"placeholder": "Effective from"},
            ),
            "effective_to": AnimatedDatePickerWidget(
                enable_time=False,
                icon_class="fa-calendar-check",
                attrs={"placeholder": "Effective to"},
            ),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Add required field indicators
        for _, field in self.fields.items():
            if field.required:
                field.label = f"{field.label} *"

        # Apply theme classes via mixin
        self.apply_theme_classes()

        if not self.instance.pk:
            # For new salary, set default effective_from to today
            self.fields["effective_from"].initial = timezone.now().date()
            # If there's a current salary, suggest setting its effective_to
            if self.user:
                current_salary = self.user.salaries.filter(
                    effective_to__isnull=True
                ).first()
                if current_salary:
                    self.fields["effective_to"].help_text = (
                        f"Setting this will end the current salary "
                        f"(effective from {current_salary.effective_from}). "
                        f"Leave blank to keep current salary active."
                    )

            try:
                if not self.instance.pk:
                    is_eligible = self.user.is_commission_eligible
                    if is_eligible:
                        self.fields["commission"].initial = True
                        self.fields["commission"].help_text = (
                            "User is eligible for commission."
                        )

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error setting commission field: %s", e)

    def clean_amount(self):
        """Validate that the salary amount is greater than zero."""
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount <= 0:
            raise forms.ValidationError("Amount must be greater than 0.")
        return amount

    def clean(self):
        cleaned_data = super().clean()
        effective_from = cleaned_data.get("effective_from")
        effective_to = cleaned_data.get("effective_to")

        if effective_from and effective_to:
            if effective_to < effective_from:
                raise forms.ValidationError(
                    "Effective to date cannot be before effective from date."
                )

        return cleaned_data


class TransactionForm(ThemedFormMixin, forms.ModelForm):
    """Form for creating and editing transactions."""

    class Meta:
        model = Transaction
        fields = (
            "transaction_type",
            "amount",
            "payment_method",
            "description",
            "reference_number",
            "date",
            "notes",
        )
        widgets = {
            "transaction_type": forms.Select(attrs={}),
            "amount": forms.NumberInput(
                attrs={
                    "placeholder": "Enter amount",
                    "autofocus": True,
                }
            ),
            "payment_method": forms.Select(attrs={}),
            "description": forms.Textarea(
                attrs={
                    "placeholder": "Enter transaction description",
                    "rows": 2,
                }
            ),
            "reference_number": forms.TextInput(
                attrs={
                    "placeholder": "Enter reference number (optional)",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "placeholder": "Internal notes (optional)",
                    "rows": 2,
                }
            ),
            "date": AnimatedDatePickerWidget(
                enable_time=True,
                icon_class="fa-calendar-days",
                attrs={"placeholder": "Select date & time"},
            ),
        }

    def clean_amount(self):
        """Validate that the transaction amount is not zero."""
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount == 0:
            raise forms.ValidationError("Amount cannot be 0.")
        return amount

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Add required field indicators
        for _, field in self.fields.items():
            if field.required:
                field.label = f"{field.label} *"

        # Apply theme classes via mixin
        self.apply_theme_classes()
