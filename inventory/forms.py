"""Forms for the Inventory app."""

import logging
from decimal import Decimal

from django import forms

from base.forms import ThemedFormMixin
from base.widgets import AnimatedDatePickerWidget

from .models import (
    BulkUpload,
    Category,
    ClothType,
    Color,
    DamagedItemRecord,
    GSTHsnCode,
    InventoryLog,
    Product,
    ProductVariant,
    Size,
    SupplierInvoice,
    UOM,
    VariantMedia,
)
from supplier.models import Supplier

logger = logging.getLogger(__name__)


class GSTHsnCodeSelect(forms.Select):
    """Custom Select widget to inject GST percentage data attributes on options"""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            instance = getattr(value, "instance", None)
            if instance and hasattr(instance, "gst_percentage"):
                option["attrs"]["data-gst-percentage"] = str(instance.gst_percentage)
            else:
                val_id = value.value if hasattr(value, "value") else value
                if val_id:
                    try:
                        from inventory.models import GSTHsnCode
                        hsn = GSTHsnCode.objects.only("gst_percentage").get(pk=val_id)
                        option["attrs"]["data-gst-percentage"] = str(hsn.gst_percentage)
                    except Exception:
                        pass
        return option


class ProductForm(forms.ModelForm):
    """Form for creating a product"""

    class Meta:
        model = Product
        fields = [
            "brand",
            "name",
            "description",
            "category",
            "cloth_type",
            "uom",
            "hsn_code",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Enter product name",
                }
            ),
            "brand": forms.TextInput(
                attrs={
                    "placeholder": "Enter brand name",
                    "autofocus": True,
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "placeholder": "Enter product description",
                    "rows": 3,
                }
            ),
            "category": forms.Select(attrs={"placeholder": "Select category"}),
            "cloth_type": forms.Select(attrs={"placeholder": "Select cloth type"}),
            "uom": forms.Select(attrs={"placeholder": "Select UOM"}),
            "hsn_code": GSTHsnCodeSelect(attrs={"placeholder": "Select HSN Code"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add required field indicators and form-control class
        for field in self.fields.values():
            if field.required:
                field.label = f"{field.label} *"
            field.widget.attrs["class"] = "form-input"

        # Restrict to active querysets
        self._set_active_queryset("hsn_code", GSTHsnCode)
        self._set_active_queryset("uom", UOM)
        self.fields["category"].queryset = Category.objects.select_related("parent").all()

    def _set_active_queryset(self, field_name, model):
        """Helper method to set active queryset for a field"""
        try:
            active_qs = model.objects.filter(is_active=True)
            self.fields[field_name].queryset = active_qs

            first_active = active_qs.first()
            if first_active is not None:
                if not self.is_bound and not self.instance.pk:
                    self.fields[field_name].initial = first_active
            else:
                model_name = model._meta.verbose_name or model.__name__
                self.fields[field_name].help_text = (
                    f"Add an active {model_name} before assigning it to a product."
                )
        except Exception:  # pylint: disable=broad-except
            pass

    def clean_brand(self):
        """Validate brand name length"""
        brand = self.cleaned_data.get("brand")
        if brand and len(brand) > 255:
            raise forms.ValidationError(
                "Brand name must be less than 255 characters long"
            )
        return brand

    def clean_name(self):
        """Validate product name length"""
        name = self.cleaned_data.get("name")
        if name and len(name) > 255:
            raise forms.ValidationError(
                "Product name must be less than 255 characters long"
            )
        return name

class SupplierInvoiceSelect(forms.Select):
    """Custom Select widget to inject invoice type data attributes on options"""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            instance = getattr(value, "instance", None)
            if instance and hasattr(instance, "invoice_type"):
                option["attrs"]["data-invoice-type"] = instance.invoice_type
            else:
                val_id = value.value if hasattr(value, "value") else value
                if val_id:
                    try:
                        from supplier.models import SupplierInvoice
                        invoice = SupplierInvoice.objects.only("invoice_type").get(pk=val_id)
                        option["attrs"]["data-invoice-type"] = invoice.invoice_type
                    except Exception:
                        pass
        return option


class VariantForm(forms.ModelForm):
    """Form for creating a variant"""

    supplier_invoice = forms.ModelChoiceField(
        queryset=SupplierInvoice.objects.filter(supplier__is_deleted=False).select_related(
            "supplier"
        ).order_by("-created_at"),
        required=False,
        widget=SupplierInvoiceSelect(attrs={"class": "form-input"}),
        help_text="Select the supplier invoice for this variant (optional)",
    )

    class Meta:
        model = ProductVariant
        fields = [
            "size",
            "color",
            "quantity",
            "minimum_quantity",
            "purchase_price",
            "mrp",
            "discount_percentage",
            "commission_percentage",
        ]
        widgets = {
            "supplier": forms.Select(attrs={"placeholder": "Select supplier"}),
            "quantity": forms.NumberInput(
                attrs={"placeholder": "Enter quantity", "step": "1"}
            ),
            "minimum_quantity": forms.NumberInput(
                attrs={"placeholder": "Enter minimum quantity", "step": "1"}
            ),
            "discount_percentage": forms.NumberInput(
                attrs={"placeholder": "Enter discount percentage", "step": "1"}
            ),
            "commission_percentage": forms.NumberInput(
                attrs={"placeholder": "Enter commission percentage", "step": "1"}
            ),
            "purchase_price": forms.TextInput(
                attrs={"placeholder": "Enter purchase price", "step": "1"}
            ),
            "mrp": forms.TextInput(
                attrs={"placeholder": "Enter selling price", "step": "1"}
            ),
            "size": forms.Select(attrs={"placeholder": "Select size"}),
            "color": forms.Select(attrs={"placeholder": "Select color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add required field indicators and form-control class
        for field in self.fields.values():
            if field.required:
                field.label = f"{field.label} *"
            field.widget.attrs["class"] = "form-input"

        self.fields["purchase_price"].widget.attrs["class"] = "form-input indian-number"
        self.fields["mrp"].widget.attrs["class"] = "form-input indian-number"

        try:
            if not self.instance.pk:
                self.fields["commission_percentage"].initial = 1
            else:
                from inventory.models import InventoryLog
                # Check if transactions exist for this variant
                has_other_transactions = InventoryLog.objects.filter(
                    variant=self.instance
                ).exclude(
                    transaction_type=InventoryLog.TransactionTypes.INITIAL
                ).exists()

                if has_other_transactions and "quantity" in self.fields:
                    self.fields["quantity"].disabled = True
                    self.fields["quantity"].help_text = (
                        "Current available stock (cannot be edited directly when stock movements exist; "
                        "use Stock In, Damage, or Adjustment operations)."
                    )

                # When editing an existing variant, initialize supplier_invoice from the initial InventoryLog
                if "supplier_invoice" in self.fields and not self.initial.get("supplier_invoice"):
                    initial_log = InventoryLog.objects.filter(
                        variant=self.instance,
                        transaction_type=InventoryLog.TransactionTypes.INITIAL,
                    ).first()
                    if initial_log and initial_log.supplier_invoice_id:
                        self.fields["supplier_invoice"].initial = initial_log.supplier_invoice_id
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Failed to set initial values in VariantForm: %s", e)

    def _validate_positive_number(self, value, _field_name, error_message):
        """Helper method to validate positive numbers"""
        if value is not None and value <= 0:
            raise forms.ValidationError(error_message)
        return value

    def clean_quantity(self):
        """Validate quantity is greater than 0, preserving existing quantity if transactions exist"""
        if self.instance and self.instance.pk:
            from inventory.models import InventoryLog
            has_other_transactions = InventoryLog.objects.filter(
                variant=self.instance
            ).exclude(
                transaction_type=InventoryLog.TransactionTypes.INITIAL
            ).exists()
            if has_other_transactions:
                return self.instance.quantity

        return self._validate_positive_number(
            self.cleaned_data.get("quantity"),
            "quantity",
            "Quantity must be greater than 0",
        )

    def clean_purchase_price(self):
        """Validate purchase price is greater than 0"""
        return self._validate_positive_number(
            self.cleaned_data.get("purchase_price"),
            "purchase_price",
            "Purchase price must be greater than 0",
        )

    def clean_mrp(self):
        """Validate selling price (MRP) is greater than 0"""
        return self._validate_positive_number(
            self.cleaned_data.get("mrp"),
            "mrp",
            "Selling price must be greater than 0",
        )


class CategoryForm(forms.ModelForm):
    """Form for creating and editing categories"""

    class Meta:
        model = Category
        fields = ["name", "parent", "description"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Enter category name",
                    "autofocus": True,
                }
            ),
            "parent": forms.Select(
                attrs={
                    "placeholder": "Select parent category (optional)",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Enter category description",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add form-input class to all fields
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-input"

        # When editing, exclude self and all descendants from parent choices
        # to prevent circular references (e.g. A → B → A)
        if self.instance.pk:
            excluded_ids = {self.instance.pk}
            excluded_ids.update(d.pk for d in self.instance.get_descendants())
            self.fields["parent"].queryset = Category.objects.select_related(
                "parent"
            ).exclude(pk__in=excluded_ids)
        else:
            self.fields["parent"].queryset = Category.objects.select_related(
                "parent"
            ).all()

    def clean_parent(self):
        """Prevent circular parent references (server-side backup validation)."""
        parent = self.cleaned_data.get("parent")
        if parent and self.instance.pk:
            # Cannot set self as parent
            if parent.pk == self.instance.pk:
                raise forms.ValidationError("A category cannot be its own parent.")
            # Cannot set a descendant as parent
            if parent in self.instance.get_descendants():
                raise forms.ValidationError(
                    f'"{parent.name}" is a subcategory of "{self.instance.name}". '
                    "Setting it as parent would create a circular reference."
                )
        return parent

    def clean_name(self):
        """Strip whitespace from category name."""
        name = self.cleaned_data.get("name")
        if name:
            name = name.strip()
        return name

    def clean(self):
        """Ensure category name is unique within the same parent (case-insensitive).

        Allows duplicate names under different parents, e.g.:
        Women → Inners, Men → Inners, Kids → Inners
        """
        cleaned_data = super().clean()
        name = cleaned_data.get("name")
        parent = cleaned_data.get("parent")

        if name:
            # Check for duplicate name under the same parent
            qs = Category.objects.filter(name__iexact=name, parent=parent)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                parent_label = f'under "{parent.name}"' if parent else "at root level"
                raise forms.ValidationError(
                    f'A category named "{name}" already exists {parent_label}.'
                )
        return cleaned_data


class ColorForm(forms.ModelForm):
    """Form for creating and editing colors"""

    class Meta:
        model = Color
        fields = ["name", "hex_code"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Enter color name",
                    "autofocus": True,
                }
            ),
            "hex_code": forms.TextInput(
                attrs={
                    "placeholder": "#FF0000",
                    "pattern": "#[0-9A-Fa-f]{6}",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add form-input class to all fields
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-input"

        # Override maxlength for hex_code to enforce 6 digits
        self.fields["hex_code"].widget.attrs["maxlength"] = "6"

    def clean_name(self):
        """Ensure color name is unique (case-insensitive)"""
        name = self.cleaned_data.get("name")
        if name:
            name = name.strip()
            # Check for duplicate (case-insensitive), excluding current instance
            qs = Color.objects.filter(name__iexact=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError("A color with this name already exists.")
        return name

    def clean_hex_code(self):
        """Validate and normalize hex color code"""
        hex_code = self.cleaned_data.get("hex_code")
        if hex_code:
            hex_code = hex_code.strip().upper()
            if not hex_code.startswith("#"):
                hex_code = "#" + hex_code
            if len(hex_code) != 7 or not all(
                c in "0123456789ABCDEF" for c in hex_code[1:]
            ):
                raise forms.ValidationError(
                    "Please enter a valid hex color code (e.g., #FF0000)"
                )
        return hex_code


class SizeForm(forms.ModelForm):
    """Form for creating and editing sizes"""

    class Meta:
        model = Size
        fields = ["name", "description"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Enter size name",
                    "autofocus": True,
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Enter size description",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add form-input class to all fields
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-input"

    def clean_name(self):
        """Ensure size name is unique (case-insensitive)"""
        name = self.cleaned_data.get("name")
        if name:
            name = name.strip()
            # Check for duplicate (case-insensitive), excluding current instance
            qs = Size.objects.filter(name__iexact=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError("A size with this name already exists.")
        return name


class ClothTypeForm(forms.ModelForm):
    """Form for creating and editing cloth types"""

    class Meta:
        model = ClothType
        fields = ["name", "description"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Enter cloth type name",
                    "autofocus": True,
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Enter cloth type description",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add form-input class to all fields
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-input"

    def clean_name(self):
        """Ensure cloth type name is unique (case-insensitive)"""
        name = self.cleaned_data.get("name")
        if name:
            name = name.strip()
            # Check for duplicate (case-insensitive), excluding current instance
            qs = ClothType.objects.filter(name__iexact=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError(
                    "A cloth type with this name already exists."
                )
        return name


class UOMForm(forms.ModelForm):
    """Form for creating and editing UOM (Unit of Measurement)"""

    class Meta:
        model = UOM
        fields = [
            "name",
            "short_code",
            "category",
            "base_unit",
            "conversion_factor",
            "description",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Enter UOM name (e.g., Piece, Dozen, Meter)",
                    "autofocus": True,
                }
            ),
            "short_code": forms.TextInput(
                attrs={
                    "placeholder": "Enter short code (e.g., pcs, doz, m)",
                    "maxlength": "10",
                }
            ),
            "category": forms.TextInput(
                attrs={
                    "placeholder": "Enter category (e.g., Quantity, Weight, Length)",
                }
            ),
            "base_unit": forms.CheckboxInput(),
            "conversion_factor": forms.NumberInput(
                attrs={
                    "placeholder": "Enter conversion factor (e.g., 12 for dozen)",
                    "step": "0.0001",
                    "min": "0.0001",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Enter UOM description (optional)",
                }
            ),
            "is_active": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add form-input class to text/number fields, form-check-input to checkboxes
        for _field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                widget.attrs["class"] = "form-input"

    def clean_short_code(self):
        """Validate and normalize short code, ensure uniqueness"""
        short_code = self.cleaned_data.get("short_code")
        if short_code:
            short_code = short_code.strip().upper()
            # Check for duplicate, excluding current instance
            qs = UOM.objects.filter(short_code=short_code)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError(
                    "A UOM with this short code already exists."
                )
        return short_code

    def clean_conversion_factor(self):
        """Validate conversion factor is greater than 0"""
        conversion_factor = self.cleaned_data.get("conversion_factor")
        if conversion_factor is not None and conversion_factor <= 0:
            raise forms.ValidationError("Conversion factor must be greater than 0")
        return conversion_factor


class GSTHsnCodeForm(ThemedFormMixin, forms.ModelForm):
    """Form for creating and editing GST HSN Code"""

    class Meta:
        model = GSTHsnCode
        fields = [
            "code",
            "gst_percentage",
            "cess_rate",
            "effective_from",
            "description",
            "is_active",
        ]
        widgets = {
            "code": forms.TextInput(
                attrs={
                    "placeholder": "Enter HSN Code (e.g., 61091000)",
                    "autofocus": True,
                    "maxlength": "10",
                }
            ),
            "gst_percentage": forms.NumberInput(
                attrs={
                    "placeholder": "Enter GST percentage (e.g., 12.00)",
                    "step": "0.01",
                    "min": "0.00",
                    "max": "40.00",
                }
            ),
            "cess_rate": forms.NumberInput(
                attrs={
                    "placeholder": "Enter Cess rate (e.g., 0.00)",
                    "step": "0.01",
                    "min": "0.00",
                    "max": "25.00",
                }
            ),
            "effective_from": AnimatedDatePickerWidget(
                enable_time=False,
                icon_class="fa-calendar-days",
                attrs={"placeholder": "Select effective date"},
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Enter HSN code description (optional)",
                }
            ),
            "is_active": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Apply theme classes via mixin (handles datepicker, select, textarea, etc.)
        self.apply_theme_classes()
        # Checkboxes need explicit class since mixin uses setdefault
        if isinstance(self.fields['is_active'].widget, forms.CheckboxInput):
            self.fields['is_active'].widget.attrs['class'] = 'form-check-input'

    def clean_code(self):
        """Validate HSN code format and ensure uniqueness"""
        code = self.cleaned_data.get("code")
        if code:
            code = code.strip()
            # Ensure code is numeric
            if not code.isdigit():
                raise forms.ValidationError("HSN Code must contain only numbers")
            # Validate length
            if len(code) < 4 or len(code) > 10:
                raise forms.ValidationError("HSN Code must be 4-10 digits long")
            # Check for duplicate, excluding current instance
            qs = GSTHsnCode.objects.filter(code=code)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError(
                    "A GST HSN Code with this code already exists."
                )
        return code

    def clean_gst_percentage(self):
        """Validate GST percentage is between 0.00 and 40.00"""
        gst_percentage = self.cleaned_data.get("gst_percentage")
        if gst_percentage is not None and (gst_percentage < 0 or gst_percentage > 40):
            raise forms.ValidationError("GST percentage must be between 0.00 and 40.00")
        return gst_percentage

    def clean_cess_rate(self):
        """Validate Cess rate is between 0.00 and 25.00"""
        cess_rate = self.cleaned_data.get("cess_rate")
        if cess_rate is not None and (cess_rate < 0 or cess_rate > 25):
            raise forms.ValidationError("Cess rate must be between 0.00 and 25.00")
        return cess_rate


class StockInForm(forms.ModelForm):
    """Optimized form for stock-in operations."""

    class Meta:
        model = InventoryLog
        fields = [
            "variant",
            "quantity_change",
            "purchase_price",
            "mrp",
            "supplier_invoice",
            "notes",
        ]
        widgets = {
            "variant": forms.Select(),
            "quantity_change": forms.NumberInput(
                attrs={
                    "autofocus": True,
                    "placeholder": "Enter quantity",
                }
            ),
            "purchase_price": forms.NumberInput(attrs={}),
            "mrp": forms.NumberInput(attrs={}),
            "supplier_invoice": SupplierInvoiceSelect(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        variant = kwargs.pop("variant", None)
        super().__init__(*args, **kwargs)

        # Standardize widget styling using a CSS class (see main.css theming)
        for _name, field in self.fields.items():
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-input multiline")
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-input")
            elif isinstance(field.widget, forms.NumberInput):
                field.widget.attrs.setdefault("class", "form-input number")
                field.widget.attrs.setdefault("min", "0")
            else:
                field.widget.attrs.setdefault("class", "form-input")

        self.variant = variant

        if self.variant:
            self.fields["variant"].widget = forms.HiddenInput()
            self.fields["variant"].initial = self.variant
            self.fields["variant"].required = False
        else:
            self.fields["variant"].queryset = ProductVariant.objects.filter(
                is_deleted=False
            )

        # Stock In can be from any active supplier
        self.fields["supplier_invoice"].queryset = SupplierInvoice.objects.filter(
            supplier__is_deleted=False
        ).select_related("supplier")
        self.fields["supplier_invoice"].required = False
        self.fields["purchase_price"].required = True

    def clean_quantity_change(self):
        """Validate quantity change is greater than 0"""
        quantity_change = self.cleaned_data.get("quantity_change")
        if quantity_change is not None and quantity_change <= 0:
            raise forms.ValidationError("Stock in quantity must be greater than zero.")
        return quantity_change

    def clean_purchase_price(self):
        """Validate purchase price is non-negative"""
        purchase_price = self.cleaned_data.get("purchase_price")
        if purchase_price is not None and purchase_price < 0:
            raise forms.ValidationError("Purchase price cannot be negative.")
        return purchase_price

    def clean_mrp(self):
        """Validate MRP is greater than 0"""
        mrp = self.cleaned_data.get("mrp")
        if mrp is not None and mrp <= 0:
            raise forms.ValidationError("MRP cannot be negative.")
        return mrp

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.variant and not instance.variant:
            instance.variant = self.variant
        instance.transaction_type = InventoryLog.TransactionTypes.STOCK_IN
        if commit:
            instance.save()
        return instance


class InventoryAdjustmentForm(forms.ModelForm):
    """Unified form for inventory adjustments (in, out, damage)"""

    class Meta:
        model = InventoryLog
        fields = [
            "variant",
            "supplier_invoice",
            "quantity_change",
            "notes",
        ]
        widgets = {
            "variant": forms.Select(attrs={"class": "form-input"}),
            "quantity_change": forms.NumberInput(
                attrs={"class": "form-input", "step": "0.01", "autofocus": True}
            ),
            "supplier_invoice": SupplierInvoiceSelect(attrs={"class": "form-input"}),
            "notes": forms.Textarea(attrs={"class": "form-input", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.adjustment_type = kwargs.pop("adjustment_type", "adjustment_in")
        self.variant = kwargs.pop("variant", None)  # Get variant from kwargs
        super().__init__(*args, **kwargs)

        # If variant is provided, hide the variant field and set it
        if self.variant:
            self.fields["variant"].widget = forms.HiddenInput()
            self.fields["variant"].initial = self.variant
            self.fields["variant"].required = False
        else:
            # Only show variant dropdown if no variant provided
            self.fields["variant"].queryset = ProductVariant.objects.filter(
                is_deleted=False
            )

        # Filter supplier invoices based on variant and operation type
        if self.variant:
            # For variant operations (damage, adjustment in, adjustment out),
            # only show supplier invoices that supplied stock (INITIAL or STOCK_IN) for this variant
            self.fields["supplier_invoice"].queryset = (
                SupplierInvoice.objects.filter(
                    supplier__is_deleted=False,
                    inventory_logs__variant=self.variant,
                    inventory_logs__transaction_type__in=[
                        InventoryLog.TransactionTypes.INITIAL,
                        InventoryLog.TransactionTypes.STOCK_IN,
                    ],
                )
                .select_related("supplier")
                .distinct()
            )
        else:
            # If no variant provided, show all active supplier invoices
            self.fields["supplier_invoice"].queryset = SupplierInvoice.objects.filter(
                supplier__is_deleted=False
            ).select_related("supplier")

        # Make supplier_invoice optional
        self.fields["supplier_invoice"].required = False

        # Set labels based on adjustment type
        labels = {
            "adjustment_in": {
                "quantity_change": "Quantity to Add",
                "notes": "Reason for Adjustment",
            },
            "adjustment_out": {
                "quantity_change": "Quantity to Remove",
                "notes": "Reason for Adjustment",
            },
            "damage": {
                "quantity_change": "Quantity to Mark as Damaged",
                "notes": "Damage Details",
            },
        }

        # Apply appropriate labels
        if self.adjustment_type in labels:
            for field_name, label in labels[self.adjustment_type].items():
                if field_name in self.fields:
                    self.fields[field_name].label = label

    def clean(self):
        cleaned_data = super().clean()
        quantity_change = cleaned_data.get("quantity_change")
        supplier_invoice = cleaned_data.get("supplier_invoice")
        variant = (
            cleaned_data.get("variant") or self.variant
        )  # Use passed variant if available

        # Validate variant is available (either from form or passed)
        if not variant:
            raise forms.ValidationError("Please select a product variant.")

        # Validate supplier invoice contains this variant (if supplier invoice is selected)
        if supplier_invoice and variant:
            has_supplied_stock = supplier_invoice.inventory_logs.filter(
                variant=variant,
                transaction_type__in=[
                    InventoryLog.TransactionTypes.INITIAL,
                    InventoryLog.TransactionTypes.STOCK_IN,
                ],
            ).exists()
            if not has_supplied_stock:
                self.add_error(
                    "supplier_invoice",
                    f"The selected supplier invoice does not have stock supplied for the variant '{variant.full_name}'. "
                    "Please select a supplier invoice that supplied stock for this variant.",
                )

        # Validate quantity based on adjustment type
        if quantity_change is not None:
            if quantity_change <= 0:
                error_messages = {
                    "adjustment_in": "Adjustment in quantity must be positive.",
                    "adjustment_out": "Adjustment out quantity must be positive.",
                    "damage": "Damage quantity must be positive.",
                }
                raise forms.ValidationError(
                    error_messages.get(
                        self.adjustment_type, "Quantity must be positive."
                    )
                )

            # For adjustment_out and damage, check if sufficient stock exists
            if self.adjustment_type in ["adjustment_out", "damage"]:
                if variant.quantity < quantity_change:
                    raise forms.ValidationError(
                        f"Insufficient stock. Available: {variant.quantity}, "
                        f"Requested: {quantity_change}"
                    )

        return cleaned_data

    def save(self, commit=True):
        """Override save to set transaction_type based on adjustment_type"""
        instance = super().save(commit=False)

        # Set variant if passed from view
        if self.variant and not instance.variant:
            instance.variant = self.variant

        # Map adjustment_type to transaction_type
        transaction_type_mapping = {
            "adjustment_in": InventoryLog.TransactionTypes.ADJUSTMENT_IN,
            "adjustment_out": InventoryLog.TransactionTypes.ADJUSTMENT_OUT,
            "damage": InventoryLog.TransactionTypes.DAMAGE,
        }

        instance.transaction_type = transaction_type_mapping.get(
            self.adjustment_type, InventoryLog.TransactionTypes.ADJUSTMENT_IN
        )

        if commit:
            instance.save()
        return instance


# Convenience classes for backward compatibility
class AdjustmentInForm(InventoryAdjustmentForm):
    """Form for adjustment in operations"""

    def __init__(self, *args, **kwargs):
        kwargs["adjustment_type"] = "adjustment_in"
        super().__init__(*args, **kwargs)


class AdjustmentOutForm(InventoryAdjustmentForm):
    """Form for adjustment out operations"""

    def __init__(self, *args, **kwargs):
        kwargs["adjustment_type"] = "adjustment_out"
        super().__init__(*args, **kwargs)


class DamageForm(InventoryAdjustmentForm):
    """Form for damage operations"""

    def __init__(self, *args, **kwargs):
        kwargs["adjustment_type"] = "damage"
        super().__init__(*args, **kwargs)


class DamageResolveForm(forms.Form):
    """Unified form for resolving a pending damaged record.

    Supports three resolution types via a dropdown:
    - RETURNED: Return to supplier (requires supplier, optional invoice)
    - WRITTEN_OFF: Write off as loss (notes only)
    - REPAIRED: Repair & restore to stock (optional repair cost)
    """

    RESOLUTION_CHOICES = [
        ("", "— Select Resolution Type —"),
        ("RETURNED", "Return to Supplier"),
        ("WRITTEN_OFF", "Write Off (Loss)"),
        ("REPAIRED", "Repair & Restore"),
    ]

    resolution_type = forms.ChoiceField(
        choices=RESOLUTION_CHOICES,
        required=True,
        label="Resolution Type",
        widget=forms.Select(attrs={"class": "form-input", "id": "id_resolution_type"}),
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(is_deleted=False),
        required=False,
        label="Supplier",
    )
    supplier_invoice = forms.ModelChoiceField(
        queryset=SupplierInvoice.objects.none(),
        required=False,
        label="Supplier Invoice",
        help_text="Optional: link to the original purchase invoice",
    )
    repair_cost = forms.DecimalField(
        min_value=Decimal("0"),
        max_digits=10,
        decimal_places=2,
        required=False,
        initial=0,
        label="Repair Cost",
        help_text="Optional: total cost of repair",
    )
    notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-input"}),
        required=False,
        label="Resolution Notes",
    )

    def __init__(self, *args, record=None, **kwargs):
        self.damage_record = record
        super().__init__(*args, **kwargs)

        # Style widgets
        self.fields["supplier"].widget.attrs["class"] = "form-input"
        self.fields["supplier_invoice"].widget.attrs["class"] = "form-input"
        self.fields["repair_cost"].widget.attrs["class"] = "form-input"

        if record and record.variant:
            variant = record.variant
            from inventory.models import InventoryLog

            # 1. Identify suppliers who have supplied this variant (via InventoryLog or DamagedItemRecord)
            supplier_ids = list(
                InventoryLog.objects.filter(
                    variant=variant,
                    supplier_invoice__supplier__isnull=False,
                )
                .values_list("supplier_invoice__supplier_id", flat=True)
                .distinct()
            )

            if record.supplier_id and record.supplier_id not in supplier_ids:
                supplier_ids.append(record.supplier_id)
            if (
                record.supplier_invoice
                and record.supplier_invoice.supplier_id
                and record.supplier_invoice.supplier_id not in supplier_ids
            ):
                supplier_ids.append(record.supplier_invoice.supplier_id)

            if supplier_ids:
                supplier_qs = Supplier.objects.filter(
                    id__in=supplier_ids, is_deleted=False
                )
            else:
                supplier_qs = Supplier.objects.filter(is_deleted=False)

            self.fields["supplier"].queryset = supplier_qs

            # 2. Determine target supplier and filter supplier_invoice queryset
            target_supplier = record.supplier or (
                record.supplier_invoice.supplier if record.supplier_invoice else None
            )

            if not target_supplier and supplier_qs.count() == 1:
                target_supplier = supplier_qs.first()

            if target_supplier:
                self.fields["supplier"].initial = target_supplier
                inv_qs = SupplierInvoice.objects.filter(
                    supplier=target_supplier, is_deleted=False
                ).select_related("supplier")
                variant_inv_qs = inv_qs.filter(
                    inventory_logs__variant=variant
                ).distinct()
                self.fields["supplier_invoice"].queryset = (
                    variant_inv_qs if variant_inv_qs.exists() else inv_qs
                )
            else:
                variant_inv_qs = SupplierInvoice.objects.filter(
                    is_deleted=False, inventory_logs__variant=variant
                ).select_related("supplier").distinct()
                self.fields["supplier_invoice"].queryset = (
                    variant_inv_qs
                    if variant_inv_qs.exists()
                    else SupplierInvoice.objects.filter(is_deleted=False).select_related(
                        "supplier"
                    )
                )

            if record.supplier_invoice:
                self.fields["supplier_invoice"].initial = record.supplier_invoice

    def clean(self):
        cleaned_data = super().clean()
        resolution_type = cleaned_data.get("resolution_type")
        supplier = cleaned_data.get("supplier")
        supplier_invoice = cleaned_data.get("supplier_invoice")

        if not resolution_type:
            raise forms.ValidationError("Please select a resolution type.")

        if resolution_type == "RETURNED":
            if not supplier:
                self.add_error("supplier", "Supplier is required when returning items to a supplier.")

            if supplier_invoice:
                # Backend validation: Invoice must belong to the selected supplier
                if supplier_invoice.supplier != supplier:
                    self.add_error(
                        "supplier_invoice",
                        f"The selected invoice '{supplier_invoice.invoice_number}' does not belong to supplier '{supplier.name}'."
                    )
                # Backend validation: Invoice must contain the variant being resolved
                if self.damage_record and self.damage_record.variant:
                    variant = self.damage_record.variant
                    has_supplied = supplier_invoice.inventory_logs.filter(variant=variant).exists()
                    if not has_supplied:
                        self.add_error(
                            "supplier_invoice",
                            f"The selected invoice does not contain stock for variant '{variant.full_name}'."
                        )

        elif resolution_type == "WRITTEN_OFF":
            # Sanitize data on backend: ignore supplier / invoice / repair_cost for write offs
            cleaned_data["supplier"] = None
            cleaned_data["supplier_invoice"] = None
            cleaned_data["repair_cost"] = None

        elif resolution_type == "REPAIRED":
            # Sanitize data on backend: ignore supplier / invoice for repairs
            cleaned_data["supplier"] = None
            cleaned_data["supplier_invoice"] = None

        return cleaned_data


class VariantMediaForm(forms.ModelForm):
    """Form for uploading media (images/videos) to a product variant."""

    ALLOWED_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "gif"]
    ALLOWED_VIDEO_EXTENSIONS = ["mp4", "webm", "mov"]
    MAX_IMAGE_SIZE = 50 * 1024 * 1024  # 50 MB — originals kept, thumbnails generated
    MAX_VIDEO_SIZE = 200 * 1024 * 1024  # 200 MB

    class Meta:
        model = VariantMedia
        fields = ["file", "alt_text", "is_featured"]
        widgets = {
            "file": forms.ClearableFileInput(
                attrs={
                    "accept": "image/*,video/mp4,video/webm,video/quicktime",
                }
            ),
            "alt_text": forms.TextInput(
                attrs={"placeholder": "Describe this media (optional)"}
            ),
            "is_featured": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-input"

    def clean_file(self):
        """Validate file extension and size."""
        uploaded_file = self.cleaned_data.get("file")
        if not uploaded_file:
            return uploaded_file

        # Get extension
        name = uploaded_file.name
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

        all_allowed = self.ALLOWED_IMAGE_EXTENSIONS + self.ALLOWED_VIDEO_EXTENSIONS
        if ext not in all_allowed:
            raise forms.ValidationError(
                f"Unsupported file type '.{ext}'. " f"Allowed: {', '.join(all_allowed)}"
            )

        # Size validation
        if ext in self.ALLOWED_VIDEO_EXTENSIONS:
            if uploaded_file.size > self.MAX_VIDEO_SIZE:
                raise forms.ValidationError(
                    f"Video file too large ({uploaded_file.size // (1024 * 1024)} MB). "
                    f"Maximum is {self.MAX_VIDEO_SIZE // (1024 * 1024)} MB."
                )
        else:
            if uploaded_file.size > self.MAX_IMAGE_SIZE:
                raise forms.ValidationError(
                    f"Image file too large ({uploaded_file.size // (1024 * 1024)} MB). "
                    f"Maximum is {self.MAX_IMAGE_SIZE // (1024 * 1024)} MB."
                )

        return uploaded_file


class InventoryPriceUpdateForm(forms.ModelForm):
    """Minimal form for updating only MRP and discount percentage on a variant."""

    class Meta:
        model = ProductVariant
        fields = ["mrp", "discount_percentage"]
        widgets = {
            "mrp": forms.TextInput(
                attrs={
                    "placeholder": "Enter selling price",
                    "step": "1",
                }
            ),
            "discount_percentage": forms.NumberInput(
                attrs={
                    "placeholder": "Enter discount %",
                    "step": "1",
                    "min": "0",
                    "max": "100",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-input"
        self.fields["mrp"].widget.attrs["class"] = "form-input indian-number"

    def clean_mrp(self):
        """Validate selling price (MRP) is greater than 0."""
        mrp = self.cleaned_data.get("mrp")
        if mrp is not None and mrp <= 0:
            raise forms.ValidationError("Selling price must be greater than 0")
        return mrp


class BulkUploadForm(forms.ModelForm):
    """Form for creating and editing BulkUpload batches."""

    class Meta:
        model = BulkUpload
        fields = ["supplier_invoice", "status"]
        widgets = {
            "supplier_invoice": SupplierInvoiceSelect(
                attrs={"autofocus": True, "placeholder": "Select supplier invoice"}
            ),
            "status": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-input"

        self.fields["supplier_invoice"].queryset = SupplierInvoice.objects.filter(
            supplier__is_deleted=False
        ).select_related("supplier").order_by("-created_at")
