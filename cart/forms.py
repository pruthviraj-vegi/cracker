"""
Form definitions for the cart application.

This module contains forms used to create, edit, and validate shopping carts
before proceeding to checkout. It handles inputs such as advance payments and
status changes.
"""

from django import forms
from .models import Cart


class CartForm(forms.ModelForm):
    """
    ModelForm for creating and updating Cart instances.

    This form manages fields for the cart name, status, notes, and advance
    payment. It also provides validation to ensure advance payments are
    always non-negative.
    """

    class Meta:
        model = Cart
        fields = ["name", "status", "notes", "advance_payment"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-input",
                    "placeholder": "Enter cart name (e.g., Customer Order #123)",
                    "maxlength": "255",
                    "autofocus": True,
                    "value": "Walk in",
                }
            ),
            "advance_payment": forms.TextInput(
                attrs={
                    "class": "form-input indian-number",
                    "placeholder": "Enter advance payment",
                    "maxlength": "10",
                    "value": "0",
                }
            ),
            "status": forms.Select(attrs={"class": "form-input"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-input",
                    "placeholder": "Add any special notes or instructions for this cart",
                    "rows": "4",
                }
            ),
        }

    def clean_advance_payment(self):
        """
        Validates the advance_payment field to ensure it is not negative.

        Returns:
            Decimal: The validated advance payment amount.

        Raises:
            ValidationError: If the advance payment is less than zero.
        """
        advance_payment = self.cleaned_data.get("advance_payment")
        if advance_payment is not None and advance_payment < 0:
            raise forms.ValidationError("Advance payment cannot be negative")
        return advance_payment

    def __init__(self, *args, **kwargs):
        """
        Initializes the CartForm with custom labels, placeholders, and help text.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments. May contain 'user' which is
                      popped before passing to the model form initialization.
        """
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Customize field labels and help text
        self.fields["name"].label = "Cart Name"
        self.fields["name"].help_text = (
            "Give your cart a descriptive name for easy identification"
        )

        self.fields["status"].label = "Cart Status"
        self.fields["status"].help_text = (
            "Choose whether the cart is open for editing or archived"
        )

        self.fields["notes"].label = "Notes"
        self.fields["notes"].help_text = (
            "Optional notes about this cart (e.g., customer preferences, special instructions)"
        )

        self.fields["advance_payment"].label = "Advance Payment"
        self.fields["advance_payment"].help_text = (
            "Enter the advance payment received from customer"
        )

        # Set initial status to OPEN for new carts
        if not self.instance.pk:
            self.fields["status"].initial = Cart.CartStatus.OPEN
