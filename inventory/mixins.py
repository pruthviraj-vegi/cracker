"""Inventory mixins for product variants."""

import logging
from decimal import Decimal

from django.db.models import Sum


logger = logging.getLogger(__name__)


class ProductVariantNamingMixin:
    """Provides naming and display properties for a ProductVariant."""

    @property
    def simple_name(self):
        """Simple name without barcode for display purposes"""
        product_name = getattr(self.product, "name", "Unknown Product")
        if hasattr(self, "size") and self.size:
            product_name += f" - {self.size.name}"
        if hasattr(self, "color") and self.color:
            product_name += f" - {self.color.name}"
        return product_name

    def _build_name(self, include_barcode=True, include_variants=True, use_slash=False):
        """
        Build a clean, formatted name for the product variant.

        Args:
            include_barcode (bool): Whether to include barcode in the name
            include_variants (bool): Whether to include size/color info
            use_slash (bool): Use ` / ` separator for display-friendly headings

        Returns:
            str: Formatted product name
        """
        try:
            sep = " / " if use_slash else " - "
            dot = " / " if use_slash else ", "

            product_name = getattr(self.product, "brand", "Unknown Product")

            if hasattr(self.product, "name") and self.product.name:
                product_name = f"{product_name}{sep}{self.product.name}"

            if include_variants:
                variant_parts = []

                if self.size and hasattr(self.size, "name"):
                    variant_parts.append(self.size.name)

                if self.color and hasattr(self.color, "name"):
                    variant_parts.append(self.color.name)

                if variant_parts:
                    product_name = f"{product_name}{dot}{', '.join(variant_parts)}"

            if include_barcode and hasattr(self, "barcode") and self.barcode:
                product_name = f"{product_name}{sep}{self.barcode}"

            return product_name

        except (AttributeError, TypeError):
            return f"Product Variant #{self.id}"

    @property
    def full_name(self):
        """Full name with all details, cleaned for display."""
        return self._build_name(include_barcode=True, include_variants=True)

    @property
    def full_name_slash(self):
        """Display-friendly name using ` / ` separators."""
        return self._build_name(include_barcode=True, include_variants=True, use_slash=True)

    @property
    def price_name(self):
        """Short name without barcode for display purposes"""
        return self.product.brand + " - " + self.simple_name

    @property
    def barcode_with_name(self):
        """Short name without barcode for display purposes"""
        name = ""
        if hasattr(self, "size") and self.size:
            name += f"{self.size.name}"
        if hasattr(self, "color") and self.color:
            name += f" - {self.color.name}"
        return name if name else None

    def get_name(self, include_barcode=True, include_variants=True):
        """
        Get a clean, formatted name for the product variant

        Args:
            include_barcode (bool): Whether to include barcode in the name
            include_variants (bool): Whether to include size/color info

        Returns:
            str: Formatted product name
        """
        return self._build_name(include_barcode, include_variants)


class ProductVariantStockMixin:
    """Provides stock and quantity-related properties for a ProductVariant."""

    @property
    def is_low_stock(self):
        """Check if the stock is low"""
        if self.minimum_quantity == 0:
            return False
        return self.quantity <= self.minimum_quantity

    @property
    def total_quantity(self):
        """Total quantity including damaged items"""
        return self.quantity + self.damaged_quantity

    @property
    def available_quantity(self):
        """Quantity available for sale (excluding damaged)"""
        return self.quantity

    @property
    def damage_percentage(self):
        """Percentage of total stock that is damaged"""
        if self.total_quantity > 0:
            return (self.damaged_quantity / self.total_quantity) * 100
        return 0

    @property
    def stock_status(self):
        """Return a human-readable stock status label."""
        if self.quantity == 0:
            return "Out of Stock"
        elif self.is_low_stock:
            return "Low Stock"
        return "In Stock"

    @property
    def stock_health(self):
        """Get stock health status"""
        if self.quantity == 0:
            return "critical"
        elif self.quantity <= self.minimum_quantity:
            return "low"
        return "healthy"

    @property
    def get_barcode_qty(self):
        """
        Get the minimum of:
        1. Current quantity (self.quantity)
        2. Quantity change from first INITIAL transaction
        3. Quantity change from first STOCK_IN transaction
        """
        quantities = [self.quantity]

        from .models import InventoryLog

        # Get the first transaction (INITIAL or STOCK_IN) by timestamp
        first_log = (
            self.inventory_logs.filter(
                transaction_type__in=[
                    InventoryLog.TransactionTypes.INITIAL,
                    InventoryLog.TransactionTypes.STOCK_IN,
                ]
            )
            .order_by("-updated_at")
            .first()
        )

        if first_log:
            quantities.append(first_log.quantity_change)

        qty = min(quantities) if quantities else 0
        return max(1, int(qty + 1) // 2) if qty > 0 else 1

    @property
    def cart_qty(self):
        """Get the cart quantity for the variant in open carts"""
        return (
            self.cart_items.filter(cart__status="OPEN").aggregate(
                total_quantity=Sum("quantity")
            )["total_quantity"]
            or 0
        )

    @property
    def billing_stock(self):
        """Get the billing stock for the variant"""
        return max(0, self.quantity - self.cart_qty)


class ProductVariantPricingMixin:
    """Provides pricing and financial properties for a ProductVariant."""

    @property
    def final_price(self):
        """Calculate final price after discount"""
        if self.discount_percentage > 0:
            return round(self.mrp * (1 - self.discount_percentage / 100), 2)
        return self.mrp

    @property
    def profit_margin(self):
        """Calculate profit margin percentage"""
        if self.mrp > 0:
            return ((self.mrp - self.purchase_price) / self.mrp) * 100
        return 0

    @property
    def total_value(self):
        """Calculate total inventory value"""
        return round(self.quantity * self.purchase_price, 2)

    @property
    def damaged_value(self):
        """Calculate value of damaged inventory"""
        return self.damaged_quantity * self.purchase_price

    @property
    def get_gst_percentage(self):
        """Get GST percentage"""
        if self.product.hsn_code:
            return self.product.hsn_code.gst_percentage
        return Decimal("0")

    @property
    def actual_purchased_price(self):
        """Calculate actual purchased price"""
        return self.purchase_price * (1 + (self.get_gst_percentage / 100))

    @property
    def get_amount(self):
        """Calculate amount"""
        if self.discount_percentage > 0:
            return round(
                self.mrp * (1 - self.discount_percentage / 100) * self.quantity,
                2,
            )
        return round(self.mrp * self.quantity, 2)
