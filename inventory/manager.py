"""Custom model managers for the Inventory app."""

from django.db import models
from django.db.models import Sum, Case, When, F, Value, DecimalField
from django.db.models.functions import Coalesce

from base.manager import SoftDeleteManager


class ProductVariantManager(SoftDeleteManager):
    """Custom manager for ProductVariant preserving soft-delete functionality."""
    pass


class InventoryLogQuerySet(models.QuerySet):
    """Custom queryset helpers for InventoryLog aggregations."""

    def with_stock_summary(self):
        """
        Annotate the queryset with stock in/sales/damage totals so callers
        can simply chain `.with_stock_summary()` after filters/values().
        """

        quantity_field = DecimalField(max_digits=16, decimal_places=3)

        return self.annotate(
            stock_in_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            transaction_type__in=[
                                "STOCK_IN",
                                "INITIAL",
                                "ADJUSTMENT_IN",
                            ],
                            then=F("quantity_change"),
                        ),
                        default=Value(0),
                        output_field=quantity_field,
                    )
                ),
                Value(0),
                output_field=quantity_field,
            ),
            sales_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            transaction_type__in=["SALE", "RETURN", "CANCEL"],
                            then=F("quantity_change"),
                        ),
                        default=Value(0),
                        output_field=quantity_field,
                    )
                ),
                Value(0),
                output_field=quantity_field,
            ),
            damage_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            transaction_type__in=["DAMAGE", "ADJUSTMENT_OUT"],
                            then=F("quantity_change"),
                        ),
                        default=Value(0),
                        output_field=quantity_field,
                    )
                ),
                Value(0),
                output_field=quantity_field,
            ),
        )


class InventoryLogManager(SoftDeleteManager.from_queryset(InventoryLogQuerySet)):
    """Manager that keeps soft-delete filtering while exposing queryset helpers."""
