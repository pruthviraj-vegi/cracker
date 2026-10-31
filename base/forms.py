"""
Authentication and user management forms.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import authenticate

from base.widgets import AnimatedDatePickerWidget


class ThemedFormMixin:
    """
    Mixin that auto-applies project CSS classes to form widgets.

    Call ``self.apply_theme_classes()`` inside ``__init__`` to assign
    the correct CSS class to each field widget based on its type:

    * ``AnimatedDatePickerWidget`` → skipped (handles its own classes)
    * ``CheckboxInput``           → ``form-checkbox``
    * ``SelectMultiple / Select`` → ``form-select``
    * ``Textarea``                → ``form-textarea``
    * everything else             → ``form-input``
    """

    def apply_theme_classes(self):
        """Apply theme-appropriate CSS classes to all form field widgets."""
        for _name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, AnimatedDatePickerWidget):
                continue  # Widget handles its own classes and wrapper
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-checkbox")
            elif isinstance(widget, (forms.SelectMultiple, forms.Select)):
                widget.attrs.setdefault("class", "form-select")
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", "form-textarea")
            else:
                widget.attrs.setdefault("class", "form-input")


class CustomLoginForm(AuthenticationForm):
    """
    Custom login form that uses phone number instead of a username for authentication.
    """

    username = forms.CharField(
        max_length=15,
        widget=forms.TextInput(
            attrs={
                "class": "form-input",
                "placeholder": "Enter your phone number",
                "type": "tel",
            }
        ),
        label="Phone Number",
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-input", "placeholder": "Enter your password"}
        ),
        label="Password",
    )
    remember = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "checkbox-input"}),
        label="Remember me",
    )

    def clean(self):
        # Get the phone number from the username field (which is actually phone_number)
        phone_number = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if phone_number and password:
            # Try to authenticate with phone number
            user = authenticate(username=phone_number, password=password)
            if user is None:
                raise forms.ValidationError(
                    "Invalid phone number or password. Please try again."
                )
            if not user.is_active:
                raise forms.ValidationError(
                    "This account is inactive. Please contact administrator."
                )
            self.user_cache = user
        return self.cleaned_data
