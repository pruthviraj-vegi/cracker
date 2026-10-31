"""
Views for inventory management including CRUD operations for cloth types, colors,
sizes, categories, UOMs, GST HSN codes, and product variant.

Provides list/create/update/delete views for each inventory entity along with
AJAX endpoints for search suggestions, paginated fetching, and modal-based creation.
"""

# pylint: disable=too-many-lines

import logging

from django.contrib import messages
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.generic.edit import CreateView, DeleteView, UpdateView

from base.decorators import RequiredPermissionMixin, required_permission
from base.utility import render_paginated_response

from .forms import (
    CategoryForm,
    ClothTypeForm,
    ColorForm,
    GSTHsnCodeForm,
    SizeForm,
    UOMForm,
)
from .models import (
    Category,
    ClothType,
    Color,
    GSTHsnCode,
    Size,
    UOM,
)

from base.weighted_search import (
    get_category_suggestions,
    get_gst_hsn_suggestions,
    get_uom_suggestions,
)

logger = logging.getLogger(__name__)

OBJECTS_PER_PAGE = 20



@required_permission("inventory.view_clothtype")
def cloth_home(request):
    """List all cloth types with annotated product and variant counts."""
    search_query = request.GET.get("search", "").strip()
    sort_by = request.GET.get("sort", "-created_at").strip()

    cloth_types = ClothType.objects.annotate(
        products_count=Count("products", distinct=True),
        variants_count=Count("products__product_variants", distinct=True),
    )

    if search_query:
        cloth_types = cloth_types.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query)
        )

    valid_sorts = ["name", "-name", "created_at", "-created_at"]
    if sort_by in valid_sorts:
        cloth_types = cloth_types.order_by(sort_by)
    else:
        cloth_types = cloth_types.order_by("name")

    context = {
        "cloth_types": cloth_types,
        "search_query": search_query,
        "sort_by": sort_by,
    }

    return render(request, "inventory/cloth/home.html", context)


class CreateClothType(RequiredPermissionMixin, CreateView):
    """CBV to create a new cloth type record."""

    required_permission = "inventory.add_clothtype"

    model = ClothType
    form_class = ClothTypeForm
    template_name = "inventory/cloth/form.html"

    def get_success_url_name(self):  # noqa: D102
        """Return the URL name to redirect to after successful creation."""
        return "inventory:cloth_create"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Cloth Type"
        return context

    def form_valid(self, form):
        messages.success(self.request, "Cloth type created successfully")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class UpdateClothType(RequiredPermissionMixin, UpdateView):
    """CBV to update an existing cloth type record."""

    required_permission = "inventory.change_clothtype"

    model = ClothType
    form_class = ClothTypeForm
    template_name = "inventory/cloth/form.html"

    def form_valid(self, form):
        messages.success(self.request, "Cloth type updated successfully")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("inventory:cloth_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Update Cloth Type"
        return context


class DeleteClothType(RequiredPermissionMixin, DeleteView):
    """CBV to delete a cloth type record with confirmation."""

    required_permission = "inventory.delete_clothtype"

    model = ClothType
    template_name = "inventory/cloth/delete.html"

    def get_success_url(self):
        return reverse("inventory:cloth_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete Cloth Type"
        return context

    def form_valid(self, form):
        messages.success(self.request, "Cloth type deleted successfully")
        return super().form_valid(form)


@required_permission("inventory.view_color")
def color_home(request):
    """List all colors"""
    colors = Color.objects.all().order_by("name")

    context = {
        "colors": colors,
    }

    return render(request, "inventory/color/home.html", context)


class CreateColor(RequiredPermissionMixin, CreateView):
    """CBV to create a new color record."""

    required_permission = "inventory.add_color"

    model = Color
    form_class = ColorForm
    template_name = "inventory/color/form.html"

    def get_success_url_name(self):  # noqa: D102
        """Return the URL name to redirect to after successful creation."""
        return "inventory:color_create"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Color"
        return context

    def form_valid(self, form):
        messages.success(self.request, "Color created successfully")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class UpdateColor(RequiredPermissionMixin, UpdateView):
    """CBV to update an existing color record."""

    required_permission = "inventory.change_color"

    model = Color
    form_class = ColorForm
    template_name = "inventory/color/form.html"

    def form_valid(self, form):
        messages.success(self.request, "Color updated successfully")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("inventory:color_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Update Color"
        return context


class DeleteColor(RequiredPermissionMixin, DeleteView):
    """CBV to delete a color record with confirmation."""

    required_permission = "inventory.delete_color"

    model = Color
    template_name = "inventory/color/delete.html"

    def get_success_url(self):
        return reverse("inventory:color_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete Color"
        return context

    def form_valid(self, form):
        messages.success(self.request, "Color deleted successfully")
        return super().form_valid(form)


@required_permission("inventory.view_size")
def size_home(request):
    """List all sizes with annotated variant counts."""
    search_query = request.GET.get("search", "").strip()
    sort_by = request.GET.get("sort", "-created_at").strip()

    sizes = Size.objects.annotate(
        variants_count=Count("product_variants", distinct=True)
    )

    if search_query:
        sizes = sizes.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query)
        )

    valid_sorts = ["name", "-name", "created_at", "-created_at"]
    if sort_by in valid_sorts:
        sizes = sizes.order_by(sort_by)
    else:
        sizes = sizes.order_by("name")

    context = {
        "sizes": sizes,
        "search_query": search_query,
        "sort_by": sort_by,
    }

    return render(request, "inventory/size/home.html", context)


class CreateSize(RequiredPermissionMixin, CreateView):
    """CBV to create a new size record."""

    required_permission = "inventory.add_size"

    model = Size
    form_class = SizeForm
    template_name = "inventory/size/form.html"

    def get_success_url_name(self):  # noqa: D102
        """Return the URL name to redirect to after successful creation."""
        return "inventory:size_create"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Size"
        return context

    def form_valid(self, form):
        messages.success(self.request, "Size created successfully")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class UpdateSize(RequiredPermissionMixin, UpdateView):
    """CBV to update an existing size record."""

    required_permission = "inventory.change_size"

    model = Size
    form_class = SizeForm
    template_name = "inventory/size/form.html"

    def form_valid(self, form):
        messages.success(self.request, "Size updated successfully")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("inventory:size_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Update Size"
        return context


class DeleteSize(RequiredPermissionMixin, DeleteView):
    """CBV to delete a size record with confirmation."""

    required_permission = "inventory.delete_size"

    model = Size
    template_name = "inventory/size/delete.html"

    def get_success_url(self):
        return reverse("inventory:size_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete Size"
        return context

    def form_valid(self, form):
        messages.success(self.request, "Size deleted successfully")
        return super().form_valid(form)


# Constants for category management
VALID_CATEGORY_SORT_FIELDS = {
    "id",
    "-id",
    "name",
    "-name",
    "created_at",
    "-created_at",
    "updated_at",
    "-updated_at",
}



def search_suggestions(request):
    """AJAX endpoint for category search suggestions."""
    query = request.GET.get("q", "").strip()
    if not query or len(query) < 2:
        return JsonResponse({"success": True, "data": []})
    return JsonResponse({"success": True, "data": get_category_suggestions(query=query, rich=True)})


@required_permission("inventory.view_category")
def fetch_categories(request):
    """AJAX endpoint to fetch categories with search, filter, and pagination."""
    # Get search and filter parameters
    search_query = request.GET.get("search", "")
    sort_by = request.GET.get("sort", "-created_at")

    # Apply search filter
    filters = Q()
    if search_query:
        term = search_query.strip()
        for word in term.split():
            filters &= Q(name__icontains=word) | Q(description__icontains=word)

    categories = (
        Category.objects.filter(filters)
        .select_related("parent")
        .annotate(products_count=Count("products", distinct=True))
    )

    # Apply sorting
    if sort_by not in VALID_CATEGORY_SORT_FIELDS:
        sort_by = "-created_at"
    categories = categories.order_by(sort_by)

    return render_paginated_response(
        request,
        categories,
        "inventory/category/fetch.html",
    )


@required_permission("inventory.view_category")
def category_home(request):
    """Category management main page - initial load only."""
    # No need to load categories here as they'll be loaded via AJAX

    return render(request, "inventory/category/home.html")


class CreateCategory(RequiredPermissionMixin, CreateView):
    """CBV to create a new category record."""

    required_permission = "inventory.add_category"

    model = Category
    form_class = CategoryForm
    template_name = "inventory/category/form.html"

    def get_success_url(self):
        return reverse("inventory:category_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Category"
        return context

    def form_valid(self, form):
        messages.success(self.request, "Category created successfully")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Please correct the errors below.")
        logger.error("Form invalid: %s", form.errors)
        return super().form_invalid(form)


class UpdateCategory(RequiredPermissionMixin, UpdateView):
    """CBV to update an existing category record."""

    required_permission = "inventory.change_category"

    model = Category
    form_class = CategoryForm
    template_name = "inventory/category/form.html"

    def form_valid(self, form):
        messages.success(self.request, "Category updated successfully")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("inventory:category_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Update Category"
        return context


class DeleteCategory(RequiredPermissionMixin, DeleteView):
    """CBV to delete a category record with confirmation."""

    required_permission = "inventory.delete_category"

    model = Category
    template_name = "inventory/category/delete.html"

    def get_success_url(self):
        return reverse("inventory:category_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete Category"
        return context

    def form_valid(self, form):
        messages.success(self.request, "Category deleted successfully")
        return super().form_valid(form)


# ========================================
# UOM MANAGEMENT VIEWS
# ========================================


@required_permission("inventory.view_uom")
def uom_home(request):
    """UOM management main page - initial load only."""
    # No need to load UOMs here as they'll be loaded via AJAX

    return render(request, "inventory/uom/home.html")


class CreateUOM(RequiredPermissionMixin, CreateView):
    """CBV to create a new unit of measurement record."""

    required_permission = "inventory.add_uom"

    model = UOM
    form_class = UOMForm
    template_name = "inventory/uom/form.html"

    def get_success_url_name(self):  # noqa: D102
        """Return the URL name to redirect to after successful creation."""
        return "inventory:uom_create"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create UOM"
        return context

    def form_valid(self, form):
        messages.success(self.request, "UOM created successfully")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class UpdateUOM(RequiredPermissionMixin, UpdateView):
    """CBV to update an existing unit of measurement record."""

    required_permission = "inventory.change_uom"

    model = UOM
    form_class = UOMForm
    template_name = "inventory/uom/form.html"

    def form_valid(self, form):
        messages.success(self.request, "UOM updated successfully")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("inventory:uom_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Update UOM"
        return context


class DeleteUOM(RequiredPermissionMixin, DeleteView):
    """CBV to delete a unit of measurement record with confirmation."""

    required_permission = "inventory.delete_uom"

    model = UOM
    template_name = "inventory/uom/delete.html"

    def get_success_url(self):
        return reverse("inventory:uom_home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete UOM"
        return context

    def form_valid(self, form):
        messages.success(self.request, "UOM deleted successfully")
        return super().form_valid(form)


# Constants for UOM management
VALID_UOM_SORT_FIELDS = {
    "id",
    "-id",
    "name",
    "-name",
    "short_code",
    "-short_code",
    "category",
    "-category",
    "is_active",
    "-is_active",
    "created_at",
    "-created_at",
    "updated_at",
    "-updated_at",
}
UOM_OBJECTS_PER_PAGE = 10



def uom_search_suggestions(request):
    """AJAX endpoint for UOM search suggestions."""
    query = request.GET.get("q", "").strip()
    if not query or len(query) < 2:
        return JsonResponse({"success": True, "data": []})
    return JsonResponse({"success": True, "data": get_uom_suggestions(query=query, rich=True)})


@required_permission("inventory.view_uom")
def fetch_uoms(request):
    """AJAX endpoint to fetch UOMs with search, filter, and pagination."""
    # Get search and filter parameters
    search_query = request.GET.get("search", "")
    sort_by = request.GET.get("sort", "-created_at")

    # Apply search filter
    filters = Q()
    if search_query:
        term = search_query.strip()
        for word in term.split():
            filters &= (
                Q(name__icontains=word)
                | Q(short_code__icontains=word)
                | Q(category__icontains=word)
                | Q(description__icontains=word)
            )

    uoms = UOM.objects.filter(filters)

    # Apply sorting
    if sort_by not in VALID_UOM_SORT_FIELDS:
        sort_by = "-created_at"
    uoms = uoms.order_by(sort_by)

    return render_paginated_response(
        request,
        uoms,
        "inventory/uom/fetch.html",
    )


# Constants for GST HSN Code pagination and sorting
VALID_GST_HSN_SORT_FIELDS = [
    "code",
    "gst_percentage",
    "cess_rate",
    "effective_from",
    "is_active",
    "created_at",
]



def gst_hsn_search_suggestions(request):
    """AJAX endpoint for GST HSN Code search suggestions."""
    query = request.GET.get("q", "").strip()
    if not query or len(query) < 2:
        return JsonResponse({"success": True, "data": []})
    return JsonResponse({"success": True, "data": get_gst_hsn_suggestions(query=query, rich=True)})


@required_permission("inventory.view_gsthsncode")
def fetch_gst_hsn_codes(request):
    """AJAX endpoint for fetching GST HSN codes with pagination and search"""
    # Get search query
    search_query = request.GET.get("search", "")

    # Get sorting parameters
    sort_by = request.GET.get("sort", "code")
    sort_order = request.GET.get("order", "asc")

    # Validate sort field
    if sort_by not in VALID_GST_HSN_SORT_FIELDS:
        sort_by = "code"

    # Apply sorting
    if sort_order == "desc":
        sort_by = f"-{sort_by}"

    # Apply search filter
    filters = Q()
    if search_query:
        term = search_query.strip()
        for word in term.split():
            filters &= (
                Q(code__icontains=word)
                | Q(description__icontains=word)
                | Q(gst_percentage__icontains=word)
            )

    # Build queryset
    queryset = GSTHsnCode.objects.filter(filters).order_by(sort_by)

    return render_paginated_response(
        request,
        queryset,
        "inventory/gst_hsn/fetch.html",
    )


# GST HSN Code Management Views
@required_permission("inventory.view_gsthsncode")
def gst_hsn_home(request):
    """List all GST HSN Codes"""
    gst_hsn_codes = GSTHsnCode.objects.all().order_by("-created_at", "code")

    context = {
        "gst_hsn_codes": gst_hsn_codes,
    }

    return render(request, "inventory/gst_hsn/home.html", context)


class CreateGSTHsnCode(RequiredPermissionMixin, CreateView):
    """CBV to create a new GST HSN code record."""

    required_permission = "inventory.add_gsthsncode"

    model = GSTHsnCode
    form_class = GSTHsnCodeForm
    template_name = "inventory/gst_hsn/form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create GST HSN Code"
        return context

    def get_success_url(self):
        return reverse("inventory:gst_hsn_home")

    def form_valid(self, form):
        messages.success(self.request, "GST HSN code created successfully")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class UpdateGSTHsnCode(RequiredPermissionMixin, UpdateView):
    """CBV to update an existing GST HSN code record."""

    required_permission = "inventory.change_gsthsncode"

    model = GSTHsnCode
    form_class = GSTHsnCodeForm
    template_name = "inventory/gst_hsn/form.html"

    def get_success_url(self):
        return reverse("inventory:gst_hsn_home")


class DeleteGSTHsnCode(RequiredPermissionMixin, DeleteView):
    """CBV to delete a GST HSN code record with confirmation."""

    required_permission = "inventory.delete_gsthsncode"

    model = GSTHsnCode
    template_name = "inventory/gst_hsn/delete.html"

    def get_success_url(self):
        return reverse("inventory:gst_hsn_home")


@required_permission("inventory.add_category")
@require_http_methods(["POST"])
def create_category_ajax(request):
    """AJAX endpoint for creating categories via modal"""
    try:
        form = CategoryForm(request.POST)

        if form.is_valid():
            # Check if category with same name already exists
            category_name = form.cleaned_data["name"].strip()
            existing_category = Category.objects.filter(
                name__iexact=category_name
            ).first()

            if existing_category:
                # Return existing category instead of creating new one
                return JsonResponse(
                    {
                        "success": True,
                        "message": "Category already exists",
                        "data": {
                            "id": existing_category.id,
                            "name": existing_category.name,
                        },
                    }
                )
            else:
                # Create new category
                category = form.save()
                return JsonResponse(
                    {
                        "success": True,
                        "message": "Category created successfully",
                        "data": {
                            "id": category.id,
                            "name": category.name,
                        },
                    }
                )
        else:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Please correct the errors below",
                    "data": str(form.errors),
                }
            )

    except Exception as e:  # pylint: disable=broad-except
        return JsonResponse(
            {
                "success": False,
                "message": f"An error occurred: {str(e)}",
                "data": str(e),
            }
        )


@required_permission("inventory.add_clothtype")
@require_http_methods(["POST"])
def create_cloth_type_ajax(request):
    """AJAX endpoint for creating cloth types via modal"""
    try:
        form = ClothTypeForm(request.POST)

        if form.is_valid():
            # Check if cloth type with same name already exists
            cloth_type_name = form.cleaned_data["name"].strip()
            existing_cloth_type = ClothType.objects.filter(
                name__iexact=cloth_type_name
            ).first()

            if existing_cloth_type:
                # Return existing cloth type instead of creating new one
                return JsonResponse(
                    {
                        "success": True,
                        "message": "Cloth type already exists",
                        "data": {
                            "id": existing_cloth_type.id,
                            "name": existing_cloth_type.name,
                        },
                    }
                )
            else:
                # Create new cloth type
                cloth_type = form.save()
                return JsonResponse(
                    {
                        "success": True,
                        "message": "Cloth type created successfully",
                        "data": {
                            "id": cloth_type.id,
                            "name": cloth_type.name,
                        },
                    }
                )
        else:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Please correct the errors below",
                    "data": str(form.errors),
                }
            )

    except Exception as e:  # pylint: disable=broad-except
        return JsonResponse(
            {
                "success": False,
                "message": f"An error occurred: {str(e)}",
                "data": str(e),
            }
        )


@required_permission("inventory.add_uom")
@require_http_methods(["POST"])
def create_uom_ajax(request):
    """AJAX endpoint for creating UOMs via modal"""
    try:
        form = UOMForm(request.POST)

        if form.is_valid():
            # Check if UOM with same name already exists
            uom_name = form.cleaned_data["name"].strip()
            existing_uom = UOM.objects.filter(name__iexact=uom_name).first()

            if existing_uom:
                # Return existing UOM instead of creating new one
                return JsonResponse(
                    {
                        "success": True,
                        "message": "UOM already exists",
                        "data": {
                            "id": existing_uom.id,
                            "name": str(existing_uom.name),
                        },
                    }
                )
            else:
                # Create new UOM
                uom = form.save()
                return JsonResponse(
                    {
                        "success": True,
                        "message": "UOM created successfully",
                        "data": {
                            "id": uom.id,
                            "name": str(uom.name),
                        },
                    }
                )
        else:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Please correct the errors below",
                    "data": str(form.errors),
                }
            )
    except Exception as e:  # pylint: disable=broad-except
        return JsonResponse(
            {
                "success": False,
                "message": f"An error occurred: {str(e)}",
                "data": str(e),
            }
        )


@required_permission("inventory.add_gsthsncode")
@require_http_methods(["POST"])
def create_gst_hsn_code_ajax(request):
    """AJAX endpoint for creating GST HSN codes via modal"""
    try:
        form = GSTHsnCodeForm(request.POST)

        if form.is_valid():
            # Check if GST HSN code with same code already exists
            hsn_code = form.cleaned_data["code"].strip()
            existing_gst_hsn_code = GSTHsnCode.objects.filter(
                code__iexact=hsn_code
            ).first()

            if existing_gst_hsn_code:
                # Return existing GST HSN code instead of creating new one
                return JsonResponse(
                    {
                        "success": True,
                        "message": "GST HSN code already exists",
                        "data": {
                            "id": existing_gst_hsn_code.id,
                            "name": existing_gst_hsn_code.code,
                            "description": existing_gst_hsn_code.description,
                        },
                    }
                )
            else:
                # Create new GST HSN code
                gst_hsn_code = form.save()
                return JsonResponse(
                    {
                        "success": True,
                        "message": "GST HSN code created successfully",
                        "data": {
                            "id": gst_hsn_code.id,
                            "name": gst_hsn_code.code,
                            "description": gst_hsn_code.description,
                        },
                    }
                )
        else:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Please correct the errors below",
                    "data": str(form.errors),
                }
            )
    except Exception as e:  # pylint: disable=broad-except
        return JsonResponse(
            {
                "success": False,
                "message": f"An error occurred: {str(e)}",
                "data": str(e),
            }
        )


@required_permission("inventory.add_size")
@require_http_methods(["POST"])
def create_size_ajax(request):
    """AJAX endpoint for creating sizes via modal"""
    try:
        form = SizeForm(request.POST)

        if form.is_valid():
            size_name = form.cleaned_data["name"].strip()
            existing_size = Size.objects.filter(name__iexact=size_name).first()

            if existing_size:
                return JsonResponse(
                    {
                        "success": True,
                        "message": "Size already exists",
                        "data": {
                            "id": existing_size.id,
                            "name": existing_size.name,
                        },
                    }
                )
            else:
                size = form.save()
                return JsonResponse(
                    {
                        "success": True,
                        "message": "Size created successfully",
                        "data": {
                            "id": size.id,
                            "name": size.name,
                        },
                    }
                )
        else:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Please correct the errors below",
                    "data": str(form.errors),
                }
            )
    except Exception as e:  # pylint: disable=broad-except
        return JsonResponse(
            {
                "success": False,
                "message": f"An error occurred: {str(e)}",
                "data": str(e),
            }
        )


@required_permission("inventory.add_color")
@require_http_methods(["POST"])
def create_color_ajax(request):
    """AJAX endpoint for creating colors via modal"""
    try:
        form = ColorForm(request.POST)
        if form.is_valid():
            color = form.save()
            return JsonResponse(
                {
                    "success": True,
                    "message": "Color created successfully",
                    "data": {
                        "id": color.id,
                        "name": color.name,
                    },
                }
            )
        else:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Please correct the errors below",
                    "data": str(form.errors),
                }
            )
    except Exception as e:  # pylint: disable=broad-except
        return JsonResponse(
            {
                "success": False,
                "message": f"An error occurred: {str(e)}",
                "data": str(e),
            }
        )
