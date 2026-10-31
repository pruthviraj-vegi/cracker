"""
Service layer for Cart operations: item management, price calculations, and barcode processing.
"""

from decimal import Decimal, InvalidOperation
from django.db.models import DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce

from inventory.models import BarcodeMapping, ProductVariant
from setting.models import ShopDetails
from .models import Cart, CartItem


class CartService:
    """Encapsulates core business logic for shopping carts."""

    @staticmethod
    def get_cart_summary(cart):
        """
        Retrieves cart items with optimized query, category counts, and total MRP selling price.
        """
        cart_items = list(
            CartItem.objects.filter(cart=cart)
            .select_related(
                "product_variant",
                "product_variant__product",
                "product_variant__product__category",
                "product_variant__size",
                "product_variant__color",
            )
            .order_by("-created_at")
        )

        category_map = {}
        total_selling_price = Decimal("0.00")
        for item in cart_items:
            variant = item.product_variant
            qty = item.quantity or Decimal("0")
            mrp = getattr(variant, "mrp", Decimal("0"))
            total_selling_price += qty * mrp

            product = getattr(variant, "product", None)
            category = getattr(product, "category", None) if product else None
            cat_name = category.name if category else "Other"
            category_map[cat_name] = category_map.get(cat_name, Decimal("0")) + qty

        category_counts = [
            {"category_name": cat_name, "total_qty": total_qty}
            for cat_name, total_qty in sorted(
                category_map.items(), key=lambda x: x[1], reverse=True
            )
        ]
        total_selling_price = round(total_selling_price, 2)

        frequent_prices_map = CartService.get_frequent_sold_prices(
            [item.product_variant for item in cart_items]
        )

        for item in cart_items:
            item.frequent_sold_prices = frequent_prices_map.get(
                item.product_variant.id, []
            )

        return {
            "cart_items": cart_items,
            "category_counts": category_counts,
            "total_selling_price": total_selling_price,
        }

    @staticmethod
    def get_frequent_sold_prices(variants):
        """
        Fetch the top 3 most frequently used past selling prices for given variants,
        excluding their current mrp, final_price, and purchase_price.
        """
        frequent_prices_map = {}
        if not variants:
            return frequent_prices_map

        # Create a lookup for quick exclusion
        variant_data = {
            v.id: {
                "mrp": float(v.mrp),
                "final_price": float(getattr(v, "final_price", v.mrp)),
                "purchase_price": float(v.purchase_price)
            } for v in variants
        }
        variant_ids = list(variant_data.keys())

        try:
            from invoice.models import InvoiceItem
            from django.db.models import Count

            recent_sales = (
                InvoiceItem.objects.filter(
                    product_variant_id__in=variant_ids,
                    invoice__is_cancelled=False,
                )
                .values("product_variant_id", "unit_price")
                .annotate(sale_count=Count("id"))
                .order_by("product_variant_id", "-sale_count")
            )
            for sale in recent_sales:
                v_id = sale["product_variant_id"]
                p = float(sale["unit_price"])
                
                # Exclude standard prices
                vd = variant_data[v_id]
                if p == vd["mrp"] or p == vd["final_price"] or p == vd["purchase_price"]:
                    continue
                    
                if v_id not in frequent_prices_map:
                    frequent_prices_map[v_id] = []
                if p not in frequent_prices_map[v_id] and len(frequent_prices_map[v_id]) < 3:
                    frequent_prices_map[v_id].append(p)
        except Exception:  # pylint: disable=broad-exception-caught
            pass

        return frequent_prices_map

    @staticmethod
    def add_variant_to_cart(cart, variant, quantity=1, price=None):
        """
        Adds a product variant to a cart or increments existing quantity.
        """
        if price is None:
            price = getattr(variant, "final_price", variant.mrp)

        cart_item = CartItem.objects.filter(
            cart=cart,
            product_variant=variant,
            price=price,
        ).first()

        if cart_item:
            cart_item.quantity += quantity
            cart_item.save(update_fields=["quantity"])
            created = False
        else:
            cart_item = CartItem.objects.create(
                cart=cart,
                product_variant=variant,
                price=price,
                quantity=quantity,
            )
            created = True

        return cart_item, created

    @staticmethod
    def resolve_variant_by_barcode(barcode):
        """
        Resolves a ProductVariant by direct barcode match or BarcodeMapping,
        falling back to weighted fuzzy search for misspelled names, brands, or codes.
        """
        if not barcode:
            return None
        barcode_clean = str(barcode).strip()
        variant = (
            ProductVariant.objects.filter(
                barcode__iexact=barcode_clean, is_deleted=False, status="ACTIVE"
            )
            .select_related("product", "product__category", "size", "color")
            .first()
        )
        if not variant:
            mapping = (
                BarcodeMapping.objects.filter(barcode__iexact=barcode_clean)
                .select_related(
                    "variant",
                    "variant__product",
                    "variant__product__category",
                    "variant__size",
                    "variant__color",
                )
                .first()
            )
            if (
                mapping
                and mapping.variant
                and not mapping.variant.is_deleted
                and mapping.variant.status == "ACTIVE"
            ):
                variant = mapping.variant

        if not variant and len(barcode_clean) >= 2:
            from base.weighted_search import search_variants_weighted

            fuzzy_results = search_variants_weighted(
                barcode_clean, limit=1, min_score=60.0
            )
            if fuzzy_results:
                variant = (
                    ProductVariant.objects.filter(
                        id=fuzzy_results[0]["id"],
                        is_deleted=False,
                        status="ACTIVE",
                    )
                    .select_related("product", "product__category", "size", "color")
                    .first()
                )
        return variant
