"""
Signals for cache invalidation across models.
"""

import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from base.weighted_search import (
    CUSTOMER_SEARCH_FIELDS,
    CUSTOMER_WEIGHTED_CACHE_KEY,
    INVOICE_SEARCH_FIELDS,
    INVOICE_WEIGHTED_CACHE_KEY,
    PRODUCT_SEARCH_FIELDS,
    PRODUCT_VARIANT_SEARCH_FIELDS,
    PRODUCT_VARIANT_WEIGHTED_CACHE_KEY,
    PRODUCT_WEIGHTED_CACHE_KEY,
    SUPPLIER_SEARCH_FIELDS,
    SUPPLIER_WEIGHTED_CACHE_KEY,
    get_instance_tokens,
    invalidate_cache,
)
from customer.models import Customer
from inventory.models import Product, ProductVariant
from invoice.models import Invoice
from supplier.models import Supplier

logger = logging.getLogger(__name__)


def check_and_invalidate(instance, fields, cache_key, old_tokens=None):
    """
    Helper function to check if tokens changed and invalidate cache.
    Avoids code duplication across all post_save receivers.
    """
    new_tokens = get_instance_tokens(instance, fields)

    if old_tokens is None:
        old_tokens = getattr(instance, "old_tokens", set())

    # Only invalidate if tokens actually changed
    if new_tokens != old_tokens:
        invalidate_cache(cache_key)
        logger.debug(
            "Cache invalidated for %s (%s)",
            instance.__class__.__name__,
            cache_key,
        )


# --- Customer ---
@receiver(pre_save, sender=Customer)
def capture_customer_tokens(sender, instance, **kwargs):
    """Capture tokens for Customer before saving."""
    if instance.pk:
        try:
            old_inst = Customer.objects.get(pk=instance.pk)
            setattr(
                instance,
                "old_tokens",
                get_instance_tokens(old_inst, CUSTOMER_SEARCH_FIELDS),
            )
        except Customer.DoesNotExist:
            setattr(instance, "old_tokens", set())
    else:
        setattr(instance, "old_tokens", set())


@receiver(post_save, sender=Customer)
def invalidate_customer_cache(sender, instance, **kwargs):
    """Invalidate Customer cache if search tokens have changed."""
    check_and_invalidate(
        instance,
        CUSTOMER_SEARCH_FIELDS,
        CUSTOMER_WEIGHTED_CACHE_KEY,
        getattr(instance, "old_tokens", set()),
    )


@receiver(post_delete, sender=Customer)
def delete_customer_cache(sender, instance, **kwargs):
    """Invalidate Customer cache when a Customer is deleted."""
    invalidate_cache(CUSTOMER_WEIGHTED_CACHE_KEY)


# --- Invoice ---
@receiver(pre_save, sender=Invoice)
def capture_invoice_tokens(sender, instance, **kwargs):
    """Capture tokens for Invoice before saving."""
    if instance.pk:
        try:
            old_inst = Invoice.objects.get(pk=instance.pk)
            setattr(
                instance,
                "old_tokens",
                get_instance_tokens(old_inst, INVOICE_SEARCH_FIELDS),
            )
        except Invoice.DoesNotExist:
            setattr(instance, "old_tokens", set())
    else:
        setattr(instance, "old_tokens", set())


@receiver(post_save, sender=Invoice)
def invalidate_invoice_cache(sender, instance, **kwargs):
    """Invalidate Invoice cache if search tokens have changed."""
    check_and_invalidate(
        instance,
        INVOICE_SEARCH_FIELDS,
        INVOICE_WEIGHTED_CACHE_KEY,
        getattr(instance, "old_tokens", set()),
    )


@receiver(post_delete, sender=Invoice)
def delete_invoice_cache(sender, instance, **kwargs):
    """Invalidate Invoice cache when an Invoice is deleted."""
    invalidate_cache(INVOICE_WEIGHTED_CACHE_KEY)


# --- Product ---
@receiver(pre_save, sender=Product)
def capture_product_tokens(sender, instance, **kwargs):
    """Capture tokens for Product before saving."""
    if instance.pk:
        try:
            old_inst = Product.objects.get(pk=instance.pk)
            setattr(
                instance,
                "old_tokens",
                get_instance_tokens(old_inst, PRODUCT_SEARCH_FIELDS),
            )
        except Product.DoesNotExist:
            setattr(instance, "old_tokens", set())
    else:
        setattr(instance, "old_tokens", set())


@receiver(post_save, sender=Product)
def invalidate_product_cache(sender, instance, **kwargs):
    """Invalidate Product cache if search tokens have changed."""
    new_tokens = get_instance_tokens(instance, PRODUCT_SEARCH_FIELDS)
    old_tokens = getattr(instance, "old_tokens", set())

    if new_tokens != old_tokens:
        invalidate_cache(PRODUCT_WEIGHTED_CACHE_KEY)
        invalidate_cache(PRODUCT_VARIANT_WEIGHTED_CACHE_KEY)
        logger.debug("Cache invalidated for Product (and variants)")


@receiver(post_delete, sender=Product)
def delete_product_cache(sender, instance, **kwargs):
    """Invalidate Product cache when a Product is deleted."""
    invalidate_cache(PRODUCT_WEIGHTED_CACHE_KEY)
    invalidate_cache(PRODUCT_VARIANT_WEIGHTED_CACHE_KEY)


# Fields on ProductVariant that, when changed, could affect search tokens.
_VARIANT_SEARCH_LOCAL_FIELDS = frozenset({"barcode", "product", "product_id"})


# --- Product Variant ---
@receiver(pre_save, sender=ProductVariant)
def capture_variant_tokens(sender, instance, update_fields=None, **kwargs):
    """Capture tokens for ProductVariant before saving."""
    # Skip token capture when update_fields is specified and doesn't touch search fields
    if update_fields is not None and not (_VARIANT_SEARCH_LOCAL_FIELDS & set(update_fields)):
        return

    if instance.pk:
        try:
            old_inst = ProductVariant.objects.select_related(
                "product__category"
            ).get(pk=instance.pk)
            setattr(
                instance,
                "old_tokens",
                get_instance_tokens(old_inst, PRODUCT_VARIANT_SEARCH_FIELDS),
            )
        except ProductVariant.DoesNotExist:
            setattr(instance, "old_tokens", set())
    else:
        setattr(instance, "old_tokens", set())


@receiver(post_save, sender=ProductVariant)
def invalidate_variant_cache(sender, instance, update_fields=None, **kwargs):
    """Invalidate Variant cache if search tokens have changed."""
    # Skip cache invalidation when update_fields is specified and doesn't touch search fields
    if update_fields is not None and not (_VARIANT_SEARCH_LOCAL_FIELDS & set(update_fields)):
        return

    check_and_invalidate(
        instance,
        PRODUCT_VARIANT_SEARCH_FIELDS,
        PRODUCT_VARIANT_WEIGHTED_CACHE_KEY,
        getattr(instance, "old_tokens", set()),
    )


@receiver(post_delete, sender=ProductVariant)
def delete_variant_cache(sender, instance, **kwargs):
    """Invalidate Variant cache when a ProductVariant is deleted."""
    invalidate_cache(PRODUCT_WEIGHTED_CACHE_KEY)
    invalidate_cache(PRODUCT_VARIANT_WEIGHTED_CACHE_KEY)


# --- Supplier ---
@receiver(pre_save, sender=Supplier)
def capture_supplier_tokens(sender, instance, **kwargs):
    """Capture tokens for Supplier before saving."""
    if instance.pk:
        try:
            old_inst = Supplier.objects.get(pk=instance.pk)
            setattr(
                instance,
                "old_tokens",
                get_instance_tokens(old_inst, SUPPLIER_SEARCH_FIELDS),
            )
        except Supplier.DoesNotExist:
            setattr(instance, "old_tokens", set())
    else:
        setattr(instance, "old_tokens", set())


@receiver(post_save, sender=Supplier)
def invalidate_supplier_cache(sender, instance, **kwargs):
    """Invalidate Supplier cache if search tokens have changed."""
    check_and_invalidate(
        instance,
        SUPPLIER_SEARCH_FIELDS,
        SUPPLIER_WEIGHTED_CACHE_KEY,
        getattr(instance, "old_tokens", set()),
    )


@receiver(post_delete, sender=Supplier)
def delete_supplier_cache(sender, instance, **kwargs):
    """Invalidate Supplier cache when a Supplier is deleted."""
    invalidate_cache(SUPPLIER_WEIGHTED_CACHE_KEY)
