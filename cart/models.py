"""
Cart models for managing temporary item collections and estimates.

Imported fields from:
- decimal.Decimal
- django.conf.settings
- django.core.validators
- django.db.models
"""

from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce

from base.utility import StringProcessor
from inventory.models import ProductVariant

User = settings.AUTH_USER_MODEL


class CartQuerySet(models.QuerySet):
    """Custom queryset for Cart providing precomputed totals to eliminate N+1 queries."""

    def with_totals(self):
        """Precomputes total amount, total quantity, and item count in a single query."""
        return self.annotate(
            annotated_total_amount=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F("cart_items__quantity") * F("cart_items__price"),
                        output_field=DecimalField(max_digits=10, decimal_places=2),
                    )
                ),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=10, decimal_places=2),
            ),
            annotated_total_quantity=Coalesce(
                Sum("cart_items__quantity"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=10, decimal_places=2),
            ),
            annotated_total_profit=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F("cart_items__quantity")
                        * (
                            F("cart_items__price")
                            - F("cart_items__product_variant__purchase_price")
                        ),
                        output_field=DecimalField(max_digits=10, decimal_places=2),
                    )
                ),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=10, decimal_places=2),
            ),
            annotated_item_count=Count("cart_items", distinct=True),
        )


class Cart(models.Model):
    """Model for managing temporary item collections and estimates."""

    class CartStatus(models.TextChoices):
        """Status choices for a cart."""

        OPEN = "OPEN", "Open"
        ARCHIVED = "ARCHIVED", "Archived"

    name = models.CharField(max_length=255, help_text="Cart name")
    status = models.CharField(
        max_length=20,
        choices=CartStatus.choices,
        default=CartStatus.OPEN,
    )
    advance_payment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Advance payment received from customer",
    )
    notes = models.TextField(blank=True, null=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="carts"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CartQuerySet.as_manager()

    class Meta:
        """Meta options for Cart model."""
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["name"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        if self.advance_payment > 0:
            return f"Cart #{self.id} - {self.name} - ({self.advance_payment})" 
        else:
            return f"Cart #{self.id} - {self.name}"

    def save(self, *args, **kwargs):
        self.name = StringProcessor(self.name).toTitle()
        super().save(*args, **kwargs)

    @property
    def total_amount(self):
        """Calculate total amount using annotated value if available, in-memory if prefetched, otherwise DB aggregation."""
        if hasattr(self, "annotated_total_amount"):
            return round(self.annotated_total_amount or Decimal(0), 2)

        if hasattr(self, "_prefetched_objects_cache") and "cart_items" in self._prefetched_objects_cache:
            total = sum(
                (item.quantity * item.price for item in self.cart_items.all()),
                Decimal(0),
            )
            return round(total, 2)

        total = self.cart_items.aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("quantity") * F("price"),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            )
        )["total"] or Decimal(0)

        return round(total, 2)

    @property
    def total_quantity(self):
        """Calculate total quantity using annotated value if available, in-memory if prefetched, otherwise DB aggregation."""
        if hasattr(self, "annotated_total_quantity"):
            return round(self.annotated_total_quantity or Decimal(0), 2)

        if hasattr(self, "_prefetched_objects_cache") and "cart_items" in self._prefetched_objects_cache:
            total = sum((item.quantity for item in self.cart_items.all()), Decimal(0))
            return round(total, 2)

        total = self.cart_items.aggregate(total=Sum("quantity"))["total"] or Decimal(0)

        return round(total, 2)

    def get_item_count(self):
        """Get item count using annotated value if available, in-memory if prefetched, otherwise DB count."""
        if hasattr(self, "annotated_item_count"):
            return self.annotated_item_count

        if hasattr(self, "_prefetched_objects_cache") and "cart_items" in self._prefetched_objects_cache:
            return len(self.cart_items.all())

        return self.cart_items.count()

    def get_cart_summary(self):
        """Get cart summary in a single query"""
        summary = self.cart_items.aggregate(
            total_items=Count("id"), total_amount=Sum("price")
        )

        return {
            "item_count": summary["total_items"] or 0,
            "total_amount": summary["total_amount"] or 0,
        }

    @property
    def net_amount(self):
        """Calculate net amount using database aggregation for better performance"""
        return self.total_amount - self.advance_payment

    @property
    def total_profit(self):
        """Calculate total profit using annotated value if available, in-memory if prefetched, otherwise DB aggregation."""
        if hasattr(self, "annotated_total_profit"):
            return round(self.annotated_total_profit or Decimal(0), 2)

        if hasattr(self, "_prefetched_objects_cache") and "cart_items" in self._prefetched_objects_cache:
            total = Decimal(0)
            for item in self.cart_items.all():
                purchase_price = getattr(item.product_variant, "purchase_price", Decimal(0))
                total += item.quantity * (item.price - purchase_price)
            return round(total, 2)

        profit = self.cart_items.aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("quantity") * (F("price") - F("product_variant__purchase_price")),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            )
        )["total"] or Decimal(0)

        return round(profit, 2)


class CartItem(models.Model):
    """Model for storing individual items within a cart."""

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="cart_items")
    product_variant = models.ForeignKey(
        ProductVariant, on_delete=models.PROTECT, related_name="cart_items"
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["cart"]),
            models.Index(fields=["product_variant"]),
        ]

    def __str__(self):
        return f"{self.cart.name} - {self.product_variant.full_name}"

    def amount(self):
        """Calculate the total for this item with caching"""
        if not hasattr(self, "_amount_cache"):
            self._amount_cache = round(self.quantity * self.price, 2)  # pylint: disable=attribute-defined-outside-init
        return self._amount_cache

    @property
    def amount_property(self):
        """Property to access amount for templates"""
        return self.amount()

    @property
    def product_name(self):
        """Get product name with caching"""
        if not hasattr(self, "_product_name_cache"):
            self._product_name_cache = self.product_variant.full_name  # pylint: disable=attribute-defined-outside-init
        return self._product_name_cache

    @property
    def discount_percentage(self):
        """Calculate discount percentage with caching"""
        if not hasattr(self, "_discount_cache"):
            if not self.product_variant.mrp or self.product_variant.mrp <= 0:
                self._discount_cache = 0  # pylint: disable=attribute-defined-outside-init
            else:
                discount = (
                    (self.product_variant.mrp - self.price) / self.product_variant.mrp
                ) * 100
                self._discount_cache = round(max(0, discount), 2)  # pylint: disable=attribute-defined-outside-init
        return self._discount_cache

    def save(self, *args, **kwargs):
        """Clear cache on save"""
        if hasattr(self, "_amount_cache"):
            delattr(self, "_amount_cache")
        if hasattr(self, "_product_name_cache"):
            delattr(self, "_product_name_cache")
        if hasattr(self, "_discount_cache"):
            delattr(self, "_discount_cache")
        super().save(*args, **kwargs)
