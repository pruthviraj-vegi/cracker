"""
Forms for the supplier app.
"""

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from base.forms import ThemedFormMixin
from base.widgets import AnimatedDatePickerWidget
from .models import Supplier, SupplierInvoice, SupplierPayment


class SupplierForm(forms.ModelForm):
    """Form to create or update a supplier."""

    class Meta:
        model = Supplier
        fields = [
            "name",
            "contact_person",
            "email",
            "phone",
            "gstin",
            "first_line",
            "second_line",
            "city",
            "state",
            "pincode",
            "country",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Supplier Name",
                    "autofocus": True,
                }
            ),
            "contact_person": forms.TextInput(attrs={"placeholder": "Contact Person"}),
            "email": forms.EmailInput(attrs={"placeholder": "Enter Email"}),
            "phone": forms.TextInput(
                attrs={
                    "type": "tel",
                    "placeholder": "Enter Phone",
                    "inputmode": "numeric",
                }
            ),
            "gstin": forms.TextInput(attrs={"placeholder": "Enter GSTIN"}),
            "first_line": forms.TextInput(attrs={"placeholder": "Enter First Line"}),
            "second_line": forms.TextInput(attrs={"placeholder": "Enter Second Line"}),
            "city": forms.TextInput(attrs={"placeholder": "Enter City"}),
            "state": forms.TextInput(attrs={"placeholder": "Enter State"}),
            "pincode": forms.TextInput(attrs={"placeholder": "Enter Pincode"}),
            "country": forms.TextInput(attrs={"placeholder": "Enter Country"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add required field indicators and form-input class
        for field in self.fields.values():
            if field.required:
                field.label = f"{field.label} *"
            field.widget.attrs["class"] = "form-input"

        # Override maxlength for phone and pincode
        self.fields["phone"].widget.attrs["maxlength"] = "10"
        self.fields["pincode"].widget.attrs["maxlength"] = "6"
        self.fields["gstin"].widget.attrs["maxlength"] = "15"
        self.fields["state"].widget.attrs["value"] = "Karnataka"
        self.fields["country"].widget.attrs["value"] = "India"

    def clean_phone(self):
        """Validate and normalize phone number"""
        phone = self.cleaned_data.get("phone")
        if phone:
            # Remove any non-digit characters
            # Check if phone number is exactly 10 digits
            if not phone.isdigit() or len(phone) != 10:
                raise forms.ValidationError(
                    "Phone number must be exactly 10 digits (e.g., 9876543210)."
                )

            # Check for duplicate phone number, excluding current instance
            existing_supplier = Supplier.objects.filter(phone=phone)
            if self.instance.pk:
                existing_supplier = existing_supplier.exclude(pk=self.instance.pk)
            if existing_supplier.exists():
                raise forms.ValidationError(
                    "A supplier with this phone number already exists."
                )
        else:
            raise forms.ValidationError("Phone number is required.")
        return phone

    def clean_gstin(self):
        """Validate GSTIN format"""
        gstin = self.cleaned_data.get("gstin")
        if gstin:
            gstin = gstin.strip().upper()
            # GSTIN should be 15 characters alphanumeric
            if len(gstin) != 15 or not gstin.isalnum():
                raise forms.ValidationError(
                    "GSTIN must be 15 characters long and alphanumeric."
                )
        return gstin


class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def to_python(self, data):
        if not data:
            return []
        
        # If it's a list, validate each item
        if isinstance(data, list):
            cleaned_data = []
            for item in data:
                cleaned_item = super().to_python(item)
                if cleaned_item:
                    cleaned_data.append(cleaned_item)
            return cleaned_data
        
        cleaned_item = super().to_python(data)
        return [cleaned_item] if cleaned_item else []


class SupplierInvoiceForm(ThemedFormMixin, forms.ModelForm):
    """Form to create or update a supplier invoice."""

    attachments = MultipleFileField(
        widget=MultipleFileInput(attrs={
            "multiple": True,
            "class": "d-none",
        }),
        required=False,
        label="Attachments"
    )

    class Meta:
        model = SupplierInvoice
        fields = [
            "invoice_number",
            "invoice_date",
            "invoice_type",
            "gst_type",
            "sub_total",
            "cgst_amount",
            "igst_amount",
            "adjustment_amount",
            "notes",
        ]
        widgets = {
            "invoice_number": forms.TextInput(
                attrs={
                    "placeholder": "Enter Invoice Number",
                    "autofocus": True,
                }
            ),
            "invoice_date": AnimatedDatePickerWidget(
                enable_time=True,
                icon_class="fa-calendar-days",
                attrs={"placeholder": "Select Invoice Date"},
            ),
            "invoice_type": forms.Select(),
            "gst_type": forms.Select(),
            "sub_total": forms.TextInput(),
            "cgst_amount": forms.TextInput(),
            "igst_amount": forms.TextInput(),
            "adjustment_amount": forms.TextInput(),
            "notes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Enter Notes (Optional)",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        supplier = kwargs.pop("supplier", None)
        super().__init__(*args, **kwargs)
        self.supplier = supplier

        # Apply theme classes via mixin
        self.apply_theme_classes()

        self.fields["invoice_type"].choices = SupplierInvoice.InvoiceType.choices
        self.fields["gst_type"].choices = SupplierInvoice.GstType.choices
        self.fields["invoice_type"].widget.attrs["class"] = "select-toggle"
        self.fields["gst_type"].widget.attrs["class"] = "select-toggle"
        self.fields["sub_total"].widget.attrs["class"] = "form-input indian-number"
        self.fields["cgst_amount"].widget.attrs["class"] = "form-input indian-number"
        self.fields["igst_amount"].widget.attrs["class"] = "form-input indian-number"
        self.fields["adjustment_amount"].widget.attrs[
            "class"
        ] = "form-input indian-number"

        # Set initial values for new invoices (skip on POST — data comes from submission)
        if not self.instance.pk and not self.is_bound:
            if self.supplier:
                last_invoice = self.supplier.invoices.filter(is_deleted=False).order_by("-invoice_date").first()
                if last_invoice:
                    self.fields["invoice_type"].initial = last_invoice.invoice_type
                    self.fields["gst_type"].initial = last_invoice.gst_type or "CGST_SGST"
                else:
                    self.fields["gst_type"].initial = "CGST_SGST"
            else:
                self.fields["gst_type"].initial = "CGST_SGST"

            # Set initial invoice date for new invoices
            self.fields["invoice_date"].initial = timezone.now().strftime("%Y-%m-%dT%H:%M")

            for field_name in [
                "sub_total",
                "cgst_amount",
                "igst_amount",
                "adjustment_amount",
            ]:
                self.fields[field_name].initial = 0

        # Add JavaScript event handlers for calculation fields
        calculation_fields = [
            "sub_total",
            "cgst_amount",
            "igst_amount",
            "adjustment_amount",
        ]
        for field_name in calculation_fields:
            self.fields[field_name].widget.attrs.update(
                {
                    "onchange": "updateTotals()",
                    "onkeyup": "updateTotals()",
                }
            )

        # Add JavaScript event handlers for form state updates
        for field_name in ["invoice_type", "gst_type"]:
            self.fields[field_name].widget.attrs["onchange"] = "updateFormState()"

    def clean_invoice_number(self):
        """Validate invoice number"""
        invoice_number = self.cleaned_data.get("invoice_number")
        if not invoice_number:
            raise forms.ValidationError("Invoice number is cannot be empty.")
        return invoice_number

    def clean_sub_total(self):
        """Validate sub total and default to 0 if empty"""
        sub_total = self.cleaned_data.get("sub_total")
        if not sub_total:
            raise forms.ValidationError("Sub total cannot be empty.")
        if sub_total <= 0:
            raise forms.ValidationError("Sub total must be greater than 0.")
        return sub_total

    def clean_cgst_amount(self):
        """Validate CGST amount and default to 0 if empty"""
        cgst_amount = self.cleaned_data.get("cgst_amount")
        if cgst_amount < 0:
            raise forms.ValidationError("CGST amount cant be negative.")
        return cgst_amount

    def clean_igst_amount(self):
        """Validate IGST amount and default to 0 if empty"""
        igst_amount = self.cleaned_data.get("igst_amount")
        if igst_amount < 0:
            raise forms.ValidationError("IGST amount cant be negative.")
        return igst_amount

    def clean_adjustment_amount(self):
        """Validate adjustment amount and default to 0 if empty"""
        adjustment_amount = self.cleaned_data.get("adjustment_amount")

        if adjustment_amount is None or adjustment_amount == "":
            raise forms.ValidationError("Adjustment amount is required.")
        return adjustment_amount or 0

    def clean(self):
        """Cross-field validation and total amount calculation"""
        cleaned_data = super().clean()
        invoice_type = cleaned_data.get("invoice_type")
        gst_type = cleaned_data.get("gst_type")
        sub_total = cleaned_data.get("sub_total") or Decimal("0")
        cgst_amount = cleaned_data.get("cgst_amount") or Decimal("0")
        igst_amount = cleaned_data.get("igst_amount") or Decimal("0")
        adjustment_amount = cleaned_data.get("adjustment_amount") or Decimal("0")

        # Validate GST type is required for GST applicable invoices
        if invoice_type == "GST_APPLICABLE" and not gst_type:
            raise forms.ValidationError(
                {"gst_type": "GST type is required for GST applicable invoices."}
            )

        # Calculate total amount
        total_amount = sub_total + adjustment_amount

        if invoice_type == "GST_APPLICABLE":
            if gst_type == "CGST_SGST":
                total_amount += cgst_amount * 2  # CGST + SGST (both same amount)
            elif gst_type == "IGST":
                total_amount += igst_amount

        cleaned_data["total_amount"] = total_amount
        return cleaned_data

    def clean_attachments(self):
        """Validate and sanitize uploaded attachment files."""
        files = self.cleaned_data.get("attachments") or []
        from .models import validate_media_file
        for f in files:
            try:
                validate_media_file(f)
            except ValidationError as e:
                raise ValidationError(e.message)
        return files


class SupplierPaymentForm(ThemedFormMixin, forms.ModelForm):
    """Form to record a payment made to a supplier."""

    attachments = MultipleFileField(
        widget=MultipleFileInput(attrs={
            "multiple": True,
            "class": "d-none",
        }),
        required=False,
        label="Attachments"
    )

    class Meta:
        model = SupplierPayment
        fields = [
            "amount",
            "method",
            "transaction_id",
            "payment_date",
        ]
        widgets = {
            "amount": forms.TextInput(
                attrs={
                    "placeholder": "0.00",
                    "value": "",
                    "autofocus": True,
                }
            ),
            "method": forms.Select(),
            "transaction_id": forms.TextInput(
                attrs={"placeholder": "Transaction reference (optional)"}
            ),
            "payment_date": AnimatedDatePickerWidget(
                enable_time=True,
                icon_class="fa-calendar-days",
                attrs={"placeholder": "Select Payment Date"},
            ),
        }

    def __init__(self, *args, **kwargs):
        supplier = kwargs.pop("supplier", None)
        super().__init__(*args, **kwargs)
        self.supplier = supplier

        # Add required field indicators and appropriate classes
        for field in self.fields.values():
            if field.required:
                field.label = f"{field.label} *"

        # Apply theme classes via mixin
        self.apply_theme_classes()

        # Set initial payment date to current time
        if not self.instance.pk:
            from django.utils import timezone

            self.fields["payment_date"].initial = timezone.now().strftime(
                "%Y-%m-%dT%H:%M"
            )

        # Make transaction_id optional
        self.fields["transaction_id"].required = False
        self.fields["method"].initial = SupplierPayment.PaymentMethod.CASH
        self.fields["method"].widget.attrs["class"] = "select-toggle"
        self.fields["amount"].widget.attrs["class"] = "form-input indian-number"

    def clean_amount(self):
        """Validate amount"""
        amount = self.cleaned_data.get("amount")
        if amount is None or amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount

    def clean_transaction_id(self):
        """Validate transaction ID"""
        cleaned_data = super().clean()
        method = cleaned_data.get("method")
        transaction_id = cleaned_data.get("transaction_id")

        # Require transaction ID for non-cash payments
        if method in ["BANK_TRANSFER", "UPI"] and not transaction_id:
            raise ValidationError(
                f"Transaction ID is required for {method.replace('_', ' ').title()} payments."
            )

        return transaction_id

    def clean(self):
        cleaned_data = super().clean()

        return cleaned_data

    def clean_attachments(self):
        """Validate and sanitize uploaded attachment files."""
        files = self.cleaned_data.get("attachments") or []
        from .models import validate_media_file
        for f in files:
            try:
                validate_media_file(f)
            except ValidationError as e:
                raise ValidationError(e.message)
        return files
