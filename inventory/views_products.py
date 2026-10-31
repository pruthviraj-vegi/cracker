"""
Views for managing products, including creation, listing, editing, and detailed viewing.
"""

import logging

from django.shortcuts import render, get_object_or_404
from django.db.models import Sum, F, Q, Count
from django.contrib import messages
from django.urls import reverse
from django.views.generic import CreateView, UpdateView

from base.decorators import RequiredPermissionMixin, required_permission
from base.utility import build_search_filter, render_paginated_response, table_sorting

from .models import Product, ProductVariant
from .forms import ProductForm, CategoryForm, ClothTypeForm, UOMForm, GSTHsnCodeForm

logger = logging.getLogger(__name__)

VALID_SORT_FIELDS = {
    "id",
    "brand",
    "name",
    "category__name",
    "status",
    "hsn_code__gst_percentage",
    "cloth_type",
    "hsn_code",
    "created_at",
}


@required_permission("inventory.view_product")
def product_home(request):
    """Product management main page - initial load only."""
    # Get filter options for the template
    from .models import Category

    categories = Category.objects.all().order_by("name")

    context = {
        "categories": categories,
        "status_choices": Product.ProductStatus.choices,
    }
    return render(request, "inventory/product/home.html", context)


def fetch_products(request):
    """AJAX endpoint to fetch products with search, filter, and pagination."""
    # Get search and filter parameters
    search_query = request.GET.get("search", "")
    category_filter = request.GET.get("category", "")

    # Apply search filter
    filters = build_search_filter(
        search_query,
        [
            "brand",
            "name",
            "description",
            "category__name",
            "hsn_code__code",
        ],
    )

    # Apply category filter
    if category_filter:
        filters &= Q(category_id=category_filter)

    # Apply sorting
    valid_sorts = table_sorting(request, VALID_SORT_FIELDS, "-id")
    products = (
        Product.objects.select_related(
            "category",
            "cloth_type",
            "hsn_code",
        )
        .annotate(variants_count=Count("product_variants", distinct=True))
        .filter(filters)
        .order_by(*valid_sorts)
    )

    return render_paginated_response(
        request,
        products,
        "inventory/product/fetch.html",
    )


@required_permission("inventory.view_product")
def product_details(request, product_id):
    """Display detailed product information with variants and statistics"""

    product = get_object_or_404(Product, id=product_id)

    # Get all variants for this product
    variants = (
        ProductVariant.objects.filter(product=product)
        .select_related("size", "color")
        .order_by("size__name", "color__name")
    )

    # Calculate statistics
    total_variants = variants.count()
    active_variants = variants.filter(
        status=ProductVariant.VariantStatus.ACTIVE
    ).count()
    out_of_stock = variants.filter(
        quantity=0, status=ProductVariant.VariantStatus.ACTIVE
    ).count()
    low_stock = variants.filter(
        quantity__lte=F("minimum_quantity"),
        status=ProductVariant.VariantStatus.ACTIVE,
    ).count()

    # Calculate inventory values
    total_quantity = variants.aggregate(total=Sum("quantity"))["total"] or 0

    total_damaged = variants.aggregate(total=Sum("damaged_quantity"))["total"] or 0

    total_inventory_value = (
        variants.aggregate(total=Sum(F("quantity") * F("purchase_price")))["total"] or 0
    )

    total_damaged_value = (
        variants.aggregate(total=Sum(F("damaged_quantity") * F("purchase_price")))[
            "total"
        ]
        or 0
    )

    context = {
        "product": product,
        "variants": variants,
        "total_variants": total_variants,
        "active_variants": active_variants,
        "out_of_stock": out_of_stock,
        "low_stock": low_stock,
        "total_quantity": total_quantity,
        "total_damaged": total_damaged,
        "total_inventory_value": total_inventory_value,
        "total_damaged_value": total_damaged_value,
    }

    return render(request, "inventory/product/details.html", context)


class CreateProduct(RequiredPermissionMixin, CreateView):
    """
    View for creating a new product.

    Handles the rendering of the product creation form and the processing
    of valid and invalid form submissions. Also provides forms for linked
    entities like categories and cloth types.
    """

    required_permission = "inventory.add_product"

    template_name = "inventory/product/form.html"
    form_class = ProductForm
    model = Product
    title = "Create Product"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["category_form"] = CategoryForm()
        context["cloth_type_form"] = ClothTypeForm()
        context["uom_form"] = UOMForm()
        context["gst_hsn_form"] = GSTHsnCodeForm()
        context["title"] = self.title
        return context

    def form_valid(self, form):
        messages.success(self.request, "Product created successfully")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse(
            "inventory_products:details", kwargs={"product_id": self.object.id}
        )


class EditProduct(RequiredPermissionMixin, UpdateView):
    """
    View for editing an existing product.

    Handles the updating of product attributes and provides additional
    forms for managing related fields such as category and units.
    """

    required_permission = "inventory.change_product"

    template_name = "inventory/product/form.html"
    form_class = ProductForm
    model = Product
    title = "Edit Product"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = self.title
        context["category_form"] = CategoryForm()
        context["cloth_type_form"] = ClothTypeForm()
        context["uom_form"] = UOMForm()
        context["gst_hsn_form"] = GSTHsnCodeForm()
        return context

    def form_valid(self, form):
        messages.success(self.request, "Product updated successfully")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse(
            "inventory_products:details", kwargs={"product_id": self.object.id}
        )
