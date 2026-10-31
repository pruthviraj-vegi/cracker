"""
Views for handling cart creation, updates, and checkout processes.

This module provides the necessary views and APIs to manage user shopping carts,
including adding items via barcode, manually updating quantities, and clearing
cart contents.
"""

import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.generic import CreateView, TemplateView, UpdateView

from base.decorators import required_permission, RequiredPermissionMixin
from base.weighted_search import search_variants_weighted

from inventory.models import BarcodeMapping, ProductVariant
from inventory.services import get_variants_data

from .forms import CartForm
from .models import Cart, CartItem
from .services import CartService
from setting.models import ShopDetails

logger = logging.getLogger(__name__)


def get_cart_category_counts(cart):
    """Return category-wise total quantity for items in a cart."""
    qs = CartItem.objects.filter(cart=cart).values(
        category_name=Coalesce(
            "product_variant__product__category__name", Value("Other")
        )
    ).annotate(total_qty=Sum("quantity")).order_by("-total_qty")
    return list(qs)


class CartMainPageView(RequiredPermissionMixin, TemplateView):
    """Template view to render the main cart management page"""

    template_name = "cart/main_page.html"
    required_permission = "cart.view_cart"

    def get_context_data(self, **kwargs):
        """
        Add open carts to template context with optimized queries.

        Retrieves all carts with 'OPEN' status and prepopulates creator
        and associated items through select_related and prefetch_related
        to eliminate N+1 query redundancy.
        """
        context = super().get_context_data(**kwargs)
        # Use with_totals() to precompute amounts in a single query
        context["carts"] = (
            Cart.objects.filter(status="OPEN", created_by=self.request.user)
            .with_totals()
            .select_related("created_by")
            .order_by("-created_at")
        )
        context["shop_details"] = ShopDetails.get_active()
        return context


@required_permission("cart.view_cart")
def get_cart_data(request, pk):
    """
    Retrieve and display data for a specific cart along with other open carts.
    """
    template_name = "cart/main_page.html"

    try:
        cart = Cart.objects.with_totals().get(id=pk)
        summary = CartService.get_cart_summary(cart)
        carts = (
            Cart.objects.filter(status="OPEN", created_by=request.user)
            .with_totals()
            .order_by("-created_at")
        )
        shop_details = ShopDetails.get_active()

        context = {
            "cart_list": summary["cart_items"],
            "cart": cart,
            "carts": carts,
            "total_selling_price": summary["total_selling_price"],
            "category_counts": summary["category_counts"],
            "shop_details": shop_details,
        }
    except Cart.DoesNotExist as e:
        logger.info("Cart not found: %s", e)
        return redirect("cart:auto_cart_create")

    return render(request, template_name, context)


class CreateCart(RequiredPermissionMixin, CreateView):
    """
    View for creating a new Cart instance.

    Provides a form for users to create carts and automatically assigns the
    created cart to the currently authenticated user making the request.
    """

    model = Cart
    template_name = "cart/form.html"
    form_class = CartForm
    required_permission = "cart.add_cart"

    def get_context_data(self, **kwargs):
        """
        Populate the context dictionary with the necessary page title.

        Args:
            **kwargs: Arbitrary keyword arguments extending context data.

        Returns:
            dict: The context dictionary containing "title": "Create Cart".
        """
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Cart"
        return context

    def form_valid(self, form):
        """
        Handle valid form submissions by dictating cart creator assigning.

        Args:
            form (CartForm): The successfully validated form instance.

        Returns:
            HttpResponseRedirect: Overridden form validation response routing.
        """
        form.instance.created_by = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        """
        Resolve the target URL to redirect towards post successful cart creation.

        Returns:
            str: Resolved URL string navigating to cart management data page.
        """
        return reverse("cart:get_cart_data", kwargs={"pk": self.object.id})


class EditCart(RequiredPermissionMixin, UpdateView):
    """
    View for editing an existing Cart instance.

    Allows users to update the details of a cart using the provided CartForm.
    """

    model = Cart
    template_name = "cart/form.html"
    form_class = CartForm
    required_permission = "cart.change_cart"

    def get_context_data(self, **kwargs):
        """
        Populate the view context dict comprising the cart targeted for editing.

        Args:
            **kwargs: Arbitrary keyword arguments to populate data.

        Returns:
            dict: Render context loaded with the object map corresponding to cart.
        """
        context = super().get_context_data(**kwargs)
        context["title"] = "Edit Cart"
        context["cart"] = self.get_object()
        return context

    def get_success_url(self):
        """
        Compute target post-editing URL to direct users toward their cart listing.

        Returns:
            str: Routing path bridging user straight into cart view endpoints.
        """
        return reverse("cart:get_cart_data", kwargs={"pk": self.object.id})


@required_permission("cart.view_cart")
def auto_cart_create(request):
    """
    Automatically create a new cart or redirect to an existing empty open cart.

    Checks the user's open carts and redirects to the first empty one found.
    If none are empty, it creates a new "Walk in" cart and redirects to it.
    """

    carts = (
        Cart.objects.filter(status="OPEN", created_by=request.user)
        .with_totals()
        .order_by("-created_at")
    )

    for cart in carts:
        if cart.get_item_count() == 0:
            messages.success(request, "Open cart existed, redirecting to it")
            return redirect("cart:get_cart_data", pk=cart.id)

    cart = Cart.objects.create(name="Walk in", created_by=request.user)
    messages.success(request, "Cart created successfully")
    return redirect("cart:get_cart_data", pk=cart.id)


def barcode_suggestions(request):
    """
    Return JSON list of product variants matching the query string.
    Used for live barcode suggestion dropdown in cart page.
    Supports exact/substring matching and fuzzy typo tolerance for misspelled words.
    Prioritizes exact and prefix barcode matches at the top.
    """
    search = request.GET.get("search", "").strip()
    if len(search) < 2:
        return JsonResponse([], safe=False)

    search_lower = search.lower()

    # 1. Query exact and prefix barcode matches first to guarantee they are included
    barcode_matches = list(
        ProductVariant.objects.filter(
            Q(barcode__iexact=search) | Q(barcode__istartswith=search),
            is_deleted=False,
            status="ACTIVE",
        ).select_related("product", "product__category", "size", "color")[:10]
    )

    combined_variants = list(barcode_matches)
    seen_ids = {v.id for v in barcode_matches}

    # 2. Substring matches via get_variants_data (only if needed and no exact barcode match)
    has_exact_barcode = any((v.barcode or "").lower() == search_lower for v in barcode_matches)
    if not has_exact_barcode and len(combined_variants) < 10:
        needed = 10 - len(combined_variants)
        general_variants = list(get_variants_data(request)[: needed + 5])
        for v in general_variants:
            if v.id not in seen_ids:
                seen_ids.add(v.id)
                combined_variants.append(v)
                if len(combined_variants) >= 10:
                    break

    # 3. Fuzzy weighted search fallback/supplement if fewer than 10 (only if no exact barcode match)
    if not has_exact_barcode and len(combined_variants) < 10:
        needed = 10 - len(combined_variants)
        fuzzy_results = search_variants_weighted(search, limit=needed + 5, min_score=45.0)
        fuzzy_ids = [r["id"] for r in fuzzy_results if r.get("id") not in seen_ids][:needed]
        if fuzzy_ids:
            fuzzy_variants_dict = {
                v.id: v
                for v in ProductVariant.objects.filter(
                    id__in=fuzzy_ids,
                    is_deleted=False,
                    status="ACTIVE",
                ).select_related("product", "product__category", "size", "color")
            }
            for fid in fuzzy_ids:
                if fid in fuzzy_variants_dict and len(combined_variants) < 10:
                    combined_variants.append(fuzzy_variants_dict[fid])
                    seen_ids.add(fid)

    if not combined_variants:
        return JsonResponse([], safe=False)

    # 4. Sort combined variants by relevance: exact barcode match > prefix barcode > substring barcode > exact name/brand > prefix name/brand > rest
    def relevance_key(v):
        bc = (v.barcode or "").lower()
        p_name = (v.product.name or "").lower() if v.product else ""
        p_brand = (v.product.brand or "").lower() if v.product else ""

        if bc == search_lower:
            return (0, 0, bc)
        if bc.startswith(search_lower):
            return (1, len(bc), bc)
        if search_lower in bc:
            return (2, len(bc), bc)
        if p_name == search_lower or p_brand == search_lower:
            return (3, 0, p_name)
        if p_name.startswith(search_lower) or p_brand.startswith(search_lower):
            return (4, len(p_name), p_name)
        if search_lower in p_name or search_lower in p_brand:
            return (5, len(p_name), p_name)
        return (6, 0, "")

    combined_variants.sort(key=relevance_key)
    variants = combined_variants[:10]

    # Batch compute cart quantities for all returned variants to eliminate N+1 queries
    # Filter for OPEN carts only to avoid reserving stock for ARCHIVED carts
    variant_ids = [v.id for v in variants]
    cart_qty_map = dict(
        CartItem.objects.filter(
            product_variant_id__in=variant_ids,
            cart__status=Cart.CartStatus.OPEN,
        )
        .values("product_variant_id")
        .annotate(total=Sum("quantity"))
        .values_list("product_variant_id", "total")
    )

    data = [
        {
            "barcode": v.barcode,
            "product": v.product.name,
            "brand": v.product.brand or "",
            "color": v.color.name if v.color else "",
            "size": v.size.name if v.size else "",
            "mrp": str(v.mrp),
            "final_price": str(v.final_price),
            "discount_percentage": str(v.discount_percentage or 0),
            "stock": str(max(0, v.quantity - (cart_qty_map.get(v.id) or 0))),
        }
        for v in variants
    ]
    return JsonResponse(data, safe=False)


# API Views for Cart Operations


@required_permission("cart.add_cartitem")
@require_http_methods(["POST"])
def scan_barcode(request):
    """
    Scan a barcode and add the corresponding product variant to the cart.

    Accepts JSON containing a barcode, cart ID, and optional quantity. Checks
    alternative barcode mappings, fetches the variant, updates cart item quantities,
    and returns a JSON response with the updated cart totals and product details.
    """
    action_type = "Create"
    try:
        data = json.loads(request.body.decode("utf-8"))

        # Validate required fields
        barcode = data.get("barcode")
        cart_id = data.get("cart_id")
        quantity = data.get("quantity", 1)

        if not barcode:
            return JsonResponse(
                {"status": "error", "message": "Barcode is required"}, status=400
            )
        if not cart_id:
            return JsonResponse(
                {"status": "error", "message": "Cart ID is required"}, status=400
            )

        # Convert quantity to Decimal
        try:
            quantity = Decimal(str(quantity))
            if quantity <= 0:
                return JsonResponse(
                    {"status": "error", "message": "Quantity must be greater than 0"},
                    status=400,
                )
        except (ValueError, TypeError, InvalidOperation):
            return JsonResponse(
                {"status": "error", "message": "Invalid quantity"}, status=400
            )

        try:
            cart = Cart.objects.get(id=cart_id, status="OPEN")
            product_variant = CartService.resolve_variant_by_barcode(barcode)
            if not product_variant or product_variant.status != "ACTIVE":
                return JsonResponse(
                    {"status": "error", "message": "Product variant not found or inactive"},
                    status=404,
                )

            cart_item, created = CartService.add_variant_to_cart(
                cart=cart,
                variant=product_variant,
                quantity=quantity,
                price=product_variant.final_price,
            )
            action_type = "Add" if created else "Update"

            # Fetch frequent sold prices for the variant
            frequent_prices_map = CartService.get_frequent_sold_prices([product_variant])
            frequent_sold_prices = frequent_prices_map.get(product_variant.id, [])

            # Build cart item data for response
            cart_item_data = {
                "id": cart_item.id,
                "quantity": float(cart_item.quantity),
                "price": float(cart_item.price),
                "amount": float(cart_item.amount_property),
                "discount_percentage": (
                    float(cart_item.discount_percentage)
                    if cart_item.discount_percentage
                    else 0
                ),
                "product_variant": {
                    "id": product_variant.id,
                    "barcode": product_variant.barcode,
                    "full_name": product_variant.full_name,
                    "mrp": float(product_variant.mrp),
                    "final_price": float(product_variant.final_price),
                    "discount_percentage": float(product_variant.discount_percentage or 0),
                    "simple_name": product_variant.simple_name,
                    "purchase_price": float(product_variant.purchase_price),
                    "product_name": product_variant.product.brand,
                    "frequent_sold_prices": frequent_sold_prices,
                },
            }

            return JsonResponse(
                {
                    "status": "success",
                    "message": f"Product {product_variant.full_name} added to cart",
                    "cart_item": cart_item_data,
                    "cart_total": float(cart.total_amount),
                    "remaining_stock": float(product_variant.billing_stock),
                    "type": action_type,
                    "category_counts": get_cart_category_counts(cart),
                }
            )

        except Cart.DoesNotExist:
            logger.error("Cart not found or not open: %s", cart_id)
            return JsonResponse(
                {"status": "error", "message": "Cart not found or not open"}, status=404
            )
        except ProductVariant.DoesNotExist:
            logger.error("Product not found or inactive: %s", barcode)
            return JsonResponse(
                {"status": "error", "message": "Product not found or inactive"},
                status=404,
            )

    except json.JSONDecodeError:
        logger.error("Invalid JSON data")
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON data"}, status=400
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Server error: %s", e)
        return JsonResponse(
            {"status": "error", "message": "Server error occurred"}, status=500
        )


@require_http_methods(["PUT", "DELETE"])
def manage_cart_item(request, item_id):
    """
    Update the quantity or price of a cart item, or remove it completely.

    Handles PUT requests to update an item's quantity or price, returning
    the new totals. Handles DELETE requests to remove the item from its cart.
    """
    try:
        cart_item = CartItem.objects.get(id=item_id)

        if request.method == "PUT":
            data = json.loads(request.body.decode("utf-8"))

            # Update quantity if provided
            if "quantity" in data:
                try:
                    quantity = Decimal(str(data["quantity"]))
                    if quantity <= 0:
                        return JsonResponse(
                            {
                                "status": "error",
                                "message": "Quantity must be greater than 0",
                            },
                            status=400,
                        )
                    cart_item.quantity = quantity
                except (ValueError, TypeError, InvalidOperation):
                    return JsonResponse(
                        {"status": "error", "message": "Invalid quantity"}, status=400
                    )

            # Update price if provided
            if "price" in data:
                try:
                    price = Decimal(str(data["price"]))
                    if price < 0:
                        return JsonResponse(
                            {"status": "error", "message": "Price cannot be negative"},
                            status=400,
                        )
                    cart_item.price = price
                except (ValueError, TypeError, InvalidOperation):
                    return JsonResponse(
                        {"status": "error", "message": "Invalid price"}, status=400
                    )

            cart_item.save()
            cart_item.refresh_from_db()

            cart_item_data = {
                "id": cart_item.id,
                "quantity": float(cart_item.quantity),
                "price": float(cart_item.price),
                "amount": float(cart_item.amount_property),
                "discount_percentage": (
                    float(cart_item.discount_percentage)
                    if cart_item.discount_percentage
                    else 0
                ),
            }

            return JsonResponse(
                {
                    "status": "success",
                    "message": "Cart item updated successfully",
                    "cart_item": cart_item_data,
                    "cart_total": float(cart_item.cart.total_amount),
                    "remaining_stock": float(cart_item.product_variant.billing_stock),
                    "category_counts": get_cart_category_counts(cart_item.cart),
                }
            )

        elif request.method == "DELETE":
            cart = cart_item.cart
            cart_item.delete()
            return JsonResponse(
                {
                    "status": "success",
                    "message": "Cart item removed successfully",
                    "cart_total": float(cart.total_amount),
                    "category_counts": get_cart_category_counts(cart),
                }
            )

    except CartItem.DoesNotExist:
        logger.error("Cart item not found: %s", item_id)
        return JsonResponse(
            {"status": "error", "message": "Cart item not found"}, status=404
        )
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON data"}, status=400
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Server error: %s", e)
        return JsonResponse(
            {"status": "error", "message": f"Server error: {str(e)}"}, status=500
        )


@required_permission("cart.change_cart")
@require_http_methods(["POST"])
def archive_cart(request, cart_id):
    """
    Archive a specific open cart.

    Changes the status of an open cart to 'ARCHIVED' so it no longer appears in
    the active cart lists. Allows cart state preservation for owners.
    """
    try:
        cart = Cart.objects.get(id=cart_id, status="OPEN")
        cart.status = "ARCHIVED"
        cart.save()
        return JsonResponse(
            {"status": "success", "message": "Cart archived successfully"}
        )

    except Cart.DoesNotExist:
        logger.error("Cart not found: %s", cart_id)
        return JsonResponse(
            {"status": "error", "message": "Cart not found"}, status=404
        )


@required_permission("cart.delete_cartitem")
@require_http_methods(["POST"])
def clear_cart(request, cart_id):
    """
    Clear all items from a given open cart.

    Removes all associated cart items while keeping the cart object intact.
    Useful for resetting a cart without having to create a new one.
    """
    try:
        cart = Cart.objects.get(id=cart_id, status="OPEN")
        cart.cart_items.all().delete()
        return JsonResponse(
            {
                "status": "success",
                "message": "Cart cleared successfully",
                "category_counts": [],
            }
        )

    except Cart.DoesNotExist:
        logger.error("Cart not found: %s", cart_id)
        return JsonResponse(
            {"status": "error", "message": "Cart not found"}, status=404
        )
