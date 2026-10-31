"""
Forms for managing shop details and report configurations.
"""

from django import forms

from base.manager import phone_regex
from .models import (
    BarcodeConfiguration,
    PaymentDetails,
    ReportConfiguration,
    ShopDetails,
)


class ShopDetailsForm(forms.ModelForm):
    """Form for managing shop details."""

    class Meta:
        model = ShopDetails
        fields = [
            "shop_name",
            "first_line",
            "second_line",
            "city",
            "state",
            "pincode",
            "country",
            "gst_no",
            "phone_number",
            "phone_two",
            "email",
            "website",
            "logo",
            "is_active",
        ]
        widgets = {
            "shop_name": forms.TextInput(
                attrs={"placeholder": "Enter shop/business name", "autofocus": True}
            ),
            "first_line": forms.TextInput(
                attrs={"placeholder": "Building name, Street"}
            ),
            "second_line": forms.TextInput(
                attrs={"placeholder": "Area, Locality (optional)"}
            ),
            "city": forms.TextInput(attrs={"placeholder": "City name"}),
            "state": forms.TextInput(
                attrs={"placeholder": "State name", "value": "Karnataka"}
            ),
            "pincode": forms.TextInput(attrs={"placeholder": "PIN/ZIP code"}),
            "country": forms.TextInput(attrs={"placeholder": "Country name"}),
            "gst_no": forms.TextInput(
                attrs={"placeholder": "GST Registration Number (optional)"}
            ),
            "phone_number": forms.TextInput(
                attrs={"placeholder": "Primary phone number"}
            ),
            "phone_two": forms.TextInput(
                attrs={"placeholder": "Secondary phone number (optional)"}
            ),
            "email": forms.EmailInput(
                attrs={"placeholder": "Business email (optional)"}
            ),
            "website": forms.URLInput(attrs={"placeholder": "Website URL (optional)"}),
            "logo": forms.FileInput(attrs={"accept": "image/*"}),
            "is_active": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add appropriate classes based on widget type
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-checkbox"
            elif isinstance(widget, forms.FileInput):
                widget.attrs["class"] = "form-input"
            else:
                widget.attrs["class"] = "form-input"

        # Override maxlength for phone_number to enforce 10 digits
        self.fields["phone_number"].widget.attrs["maxlength"] = "10"
        self.fields["phone_two"].widget.attrs["maxlength"] = "10"
        self.fields["pincode"].widget.attrs["maxlength"] = "6"

        # Add form labels
        labels = {
            "shop_name": "Shop/Business Name",
            "first_line": "Address Line 1",
            "second_line": "Address Line 2",
            "city": "City",
            "state": "State",
            "pincode": "PIN Code",
            "country": "Country",
            "gst_no": "GST Number",
            "phone_number": "Primary Phone",
            "phone_two": "Secondary Phone",
            "email": "Email Address",
            "website": "Website",
            "logo": "Logo Image",
            "is_active": "Active",
        }
        for field_name, label in labels.items():
            if field_name in self.fields:
                self.fields[field_name].label = label

        # Add help text
        help_texts = {
            "shop_name": "The name of your shop or business",
            "first_line": "Building name, street address",
            "second_line": "Area, locality, landmark (optional)",
            "gst_no": "GST registration number (optional)",
            "phone_number": "Primary contact number",
            "phone_two": "Secondary contact number (optional)",
            "logo": "Upload your shop logo (optional)",
        }
        for field_name, help_text in help_texts.items():
            if field_name in self.fields:
                self.fields[field_name].help_text = help_text

    def _validate_phone(self, phone):
        """Helper method to validate phone number format"""
        if phone:
            if not phone_regex.regex.match(phone):
                raise forms.ValidationError("Phone number must be exactly 10 digits.")
        return phone

    def clean_phone_number(self):
        """Validate primary phone number"""
        return self._validate_phone(self.cleaned_data.get("phone_number"))

    def clean_phone_two(self):
        """Validate secondary phone number"""
        return self._validate_phone(self.cleaned_data.get("phone_two"))

    def clean_gst_no(self):
        """Validate GST number format"""
        gst = self.cleaned_data.get("gst_no")
        if gst:
            gst = gst.strip().upper()
            # Basic GST validation (15 characters, alphanumeric)
            if len(gst) != 15 or not gst.replace(" ", "").isalnum():
                raise forms.ValidationError(
                    {
                        "gst_no": "GST number must be 15 characters long and alphanumeric."
                    }
                )
        return gst


class ReportConfigurationForm(forms.ModelForm):
    """Form for managing report configuration settings."""

    class Meta:
        model = ReportConfiguration
        fields = [
            "report_type",
            "paper_size",
            "currency",
            "is_direct_print_enabled",
            "printer_ip",
            "printer_port",
            "show_logo",
            "show_shop_name",
            "show_address",
            "show_contact",
            "show_gst",
            "show_invoice_number",
            "show_date",
            "show_due_date",
            "show_payment_method",
            "show_customer_details",
            "show_item_description",
            "show_quantity",
            "show_unit_price",
            "show_discount",
            "show_tax_breakdown",
            "show_total",
            "show_terms_conditions",
            "show_qr_code",
            "show_thank_you",
            "show_signature",
            "terms_conditions",
            "thank_you_message",
            "footer_note",
            "is_default",
            "is_active",
        ]
        widgets = {
            "report_type": forms.Select(),
            "paper_size": forms.Select(),
            "currency": forms.Select(),
            "is_direct_print_enabled": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
            "printer_ip": forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g., 192.168.1.192"}),
            "printer_port": forms.NumberInput(attrs={"class": "form-input", "placeholder": "9100"}),
            "terms_conditions": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Enter custom terms and conditions...",
                }
            ),
            "thank_you_message": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Enter custom thank you message...",
                }
            ),
            "footer_note": forms.Textarea(
                attrs={
                    "rows": 2,
                    "placeholder": "Enter additional footer note...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add appropriate classes based on widget type
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.Select):
                widget.attrs["class"] = "form-select"
            elif isinstance(widget, forms.Textarea):
                widget.attrs["class"] = "form-textarea"
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-checkbox"
            else:
                widget.attrs["class"] = "form-input"

        # Add form labels
        labels = {
            "report_type": "Report Type",
            "paper_size": "Paper Size",
            "currency": "Currency",
            "show_logo": "Show Logo",
            "show_shop_name": "Show Shop Name",
            "show_address": "Show Address",
            "show_contact": "Show Contact Info",
            "show_gst": "Show GST Number",
            "show_invoice_number": "Show Invoice Number",
            "show_date": "Show Date",
            "show_due_date": "Show Due Date",
            "show_payment_method": "Show Payment Method",
            "show_customer_details": "Show Customer Details",
            "show_item_description": "Show Item Description",
            "show_quantity": "Show Quantity",
            "show_unit_price": "Show Unit Price",
            "show_discount": "Show Discount",
            "show_tax_breakdown": "Show Tax Breakdown",
            "show_total": "Show Total",
            "show_terms_conditions": "Show Terms & Conditions",
            "show_qr_code": "Show QR Code",
            "show_thank_you": "Show Thank You Message",
            "show_signature": "Show Signature Line",
            "terms_conditions": "Custom Terms & Conditions",
            "thank_you_message": "Custom Thank You Message",
            "footer_note": "Footer Note",
            "is_default": "Set as Default",
            "is_active": "Active",
        }
        for field_name, label in labels.items():
            if field_name in self.fields:
                self.fields[field_name].label = label

        # Add help text
        help_texts = {
            "report_type": "Type of report this configuration applies to",
            "paper_size": "Paper size for report generation",
            "currency": "Currency symbol to display",
            "is_default": "Use this as the default configuration for this report type",
            "terms_conditions": "Leave blank to use default terms and conditions",
            "thank_you_message": "Leave blank to use default thank you message",
        }
        for field_name, help_text in help_texts.items():
            if field_name in self.fields:
                self.fields[field_name].help_text = help_text

    def clean(self):
        """Custom validation to ensure only one default config per report type"""
        cleaned_data = super().clean()

        # If setting as default, ensure no other config of same type is default
        if cleaned_data.get("is_default") and cleaned_data.get("report_type"):
            existing_default = ReportConfiguration.objects.filter(
                report_type=cleaned_data["report_type"], is_default=True
            ).exclude(pk=self.instance.pk if self.instance.pk else None)

            if existing_default.exists():
                raise forms.ValidationError(
                    f'Another {cleaned_data["report_type"]} configuration is already set as default. '
                    "Please uncheck the default setting for that configuration first."
                )

        return cleaned_data


class PaymentDetailsForm(forms.ModelForm):
    """Form for managing payment details."""

    class Meta:
        model = PaymentDetails
        fields = [
            "payment_name",
            "payment_type",
            "upi_id",
            "account_holder_name",
            "bank_name",
            "account_number",
            "ifsc_code",
            "branch_name",
            "qr_code_image",
            "qr_code_url",
            "description",
            "counter_name",
            "is_active",
            "is_default",
            "display_order",
            "shop",
        ]
        widgets = {
            "payment_name": forms.TextInput(
                attrs={"placeholder": "e.g., Main Counter UPI"}
            ),
            "payment_type": forms.Select(),
            "upi_id": forms.TextInput(attrs={"placeholder": "e.g., shopname@paytm"}),
            "account_holder_name": forms.TextInput(
                attrs={"placeholder": "Account Holder Name"}
            ),
            "bank_name": forms.TextInput(attrs={"placeholder": "Bank Name"}),
            "account_number": forms.TextInput(attrs={"placeholder": "Account Number"}),
            "ifsc_code": forms.TextInput(attrs={"placeholder": "IFSC Code"}),
            "branch_name": forms.TextInput(attrs={"placeholder": "Branch Name"}),
            "qr_code_image": forms.FileInput(attrs={"accept": "image/*"}),
            "qr_code_url": forms.URLInput(
                attrs={"placeholder": "https://example.com/qr"}
            ),
            "description": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Additional notes..."}
            ),
            "counter_name": forms.TextInput(attrs={"placeholder": "e.g., Counter 1"}),
            "is_active": forms.CheckboxInput(),
            "is_default": forms.CheckboxInput(),
            "display_order": forms.NumberInput(attrs={"min": 0}),
            "shop": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add appropriate classes based on widget type
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-checkbox"
            elif isinstance(widget, forms.FileInput):
                widget.attrs["class"] = "form-input"
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "form-select"
            elif isinstance(widget, forms.Textarea):
                widget.attrs["class"] = "form-textarea"
            else:
                widget.attrs["class"] = "form-input"

        # Add help text
        help_texts = {
            "payment_name": "Name/Label for this payment method",
            "upi_id": "Required for UPI payment type",
            "account_number": "Required for Bank Account",
            "ifsc_code": "Required for Bank Account",
            "is_default": "Use as default payment method on invoices",
        }
        for field_name, help_text in help_texts.items():
            if field_name in self.fields:
                self.fields[field_name].help_text = help_text


class BarcodeConfigurationForm(forms.ModelForm):
    """Form for managing barcode configuration settings."""

    class Meta:
        model = BarcodeConfiguration
        fields = [
            "config_name",
            "barcode_type",
            "label_size",
            "paper_size",
            "show_heading",
            "heading_text",
            "custom_label_width",
            "custom_label_height",
            "labels_per_row",
            "show_product_name",
            "show_product_code",
            "show_mrp",
            "show_price",
            "show_discount",
            "show_shop_logo",
            "shop",
            "is_default",
            "is_active",
        ]
        widgets = {
            "config_name": forms.TextInput(
                attrs={"placeholder": "e.g., Default Barcode Config"}
            ),
            "barcode_type": forms.Select(),
            "label_size": forms.Select(),
            "paper_size": forms.Select(),
            "heading_text": forms.TextInput(
                attrs={"placeholder": "Custom heading text (optional)"}
            ),
            "custom_label_width": forms.NumberInput(
                attrs={"placeholder": "Width (mm)", "step": "0.01"}
            ),
            "custom_label_height": forms.NumberInput(
                attrs={"placeholder": "Height (mm)", "step": "0.01"}
            ),
            "labels_per_row": forms.NumberInput(attrs={"min": 1}),
            "shop": forms.Select(),
            "show_heading": forms.CheckboxInput(),
            "show_product_name": forms.CheckboxInput(),
            "show_product_code": forms.CheckboxInput(),
            "show_mrp": forms.CheckboxInput(),
            "show_price": forms.CheckboxInput(),
            "show_discount": forms.CheckboxInput(),
            "show_shop_logo": forms.CheckboxInput(),
            "is_default": forms.CheckboxInput(),
            "is_active": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add appropriate classes based on widget type
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-checkbox"
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "form-select"
            elif isinstance(widget, forms.NumberInput):
                widget.attrs["class"] = "form-input"
            else:
                widget.attrs["class"] = "form-input"

        # Add help text
        help_texts = {
            "config_name": "Name for this configuration",
            "heading_text": "Text to display at the top of the label",
            "custom_label_width": "Width in mm (only for Custom Size)",
            "custom_label_height": "Height in mm (only for Custom Size)",
            "is_default": "Use this as the default barcode configuration",
        }
        for field_name, help_text in help_texts.items():
            if field_name in self.fields:
                self.fields[field_name].help_text = help_text

    def clean(self):
        """Custom validation."""
        cleaned_data = super().clean()

        # Validate custom size if selected
        label_size = cleaned_data.get("label_size")
        custom_width = cleaned_data.get("custom_label_width")
        custom_height = cleaned_data.get("custom_label_height")

        if label_size == "CUSTOM":
            if not custom_width or not custom_height:
                raise forms.ValidationError(
                    "Custom width and height are required when 'Custom Size' is selected."
                )

        # If setting as default, ensure no other config for same shop is default
        if cleaned_data.get("is_default") and cleaned_data.get("shop"):
            existing_default = BarcodeConfiguration.objects.filter(
                shop=cleaned_data["shop"], is_default=True
            ).exclude(pk=self.instance.pk if self.instance.pk else None)

            if existing_default.exists():
                raise forms.ValidationError(
                    "Another barcode configuration is already set as default for this shop. "
                    "Please uncheck the default setting for that configuration first."
                )

        return cleaned_data
