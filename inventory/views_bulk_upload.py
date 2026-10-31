"""Views for BulkUpload batch management."""

import csv
import json
import logging

from django.contrib import messages
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.generic.edit import CreateView, DeleteView, UpdateView

from base.decorators import RequiredPermissionMixin, required_permission
from base.utility import build_search_filter, render_paginated_response
from .forms import BulkUploadForm
from .models import (
    BulkUpload,
    BulkUploadItem,
    Category,
    ClothType,
    Color,
    GSTHsnCode,
    Product,
    ProductVariant,
    Size,
    UOM,
)
from .services import BulkUploadService

logger = logging.getLogger(__name__)

VALID_BULK_UPLOAD_SORT_FIELDS = [
    "id",
    "-id",
    "status",
    "-status",
    "supplier_invoice__invoice_number",
    "-supplier_invoice__invoice_number",
    "created_at",
    "-created_at",
    "updated_at",
    "-updated_at",
]


@required_permission("inventory.view_bulkupload")
def bulk_upload_home(request):
    return render(request, "inventory/bulk_upload/home.html")


@required_permission("inventory.view_bulkupload")
def bulk_upload_fetch(request):
    search_query = request.GET.get("search", "")
    sort_by = request.GET.get("sort", "-created_at")

    filters = build_search_filter(
        search_query,
        ["supplier_invoice__invoice_number", "status"],
    )

    batches = (
        BulkUpload.objects
        .filter(filters)
        .select_related("supplier_invoice", "created_by")
        .annotate(
            item_count=Count("items", filter=Q(items__is_deleted=False)),
            total_quantity=Sum("items__quantity", filter=Q(items__is_deleted=False)),
            total_purchase_amount=Sum(
                F("items__quantity") * F("items__purchase_price"),
                filter=Q(items__is_deleted=False),
            ),
        )
    )

    if sort_by not in VALID_BULK_UPLOAD_SORT_FIELDS:
        sort_by = "-created_at"
    batches = batches.order_by(sort_by)

    return render_paginated_response(
        request,
        batches,
        "inventory/bulk_upload/fetch.html",
    )


class CreateBulkUpload(RequiredPermissionMixin, CreateView):
    required_permission = "inventory.add_bulkupload"

    model = BulkUpload
    form_class = BulkUploadForm
    template_name = "inventory/bulk_upload/form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Bulk Upload Batch"
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Bulk upload batch created successfully")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("BulkUpload form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("inventory_bulk_upload:home")


class UpdateBulkUpload(RequiredPermissionMixin, UpdateView):
    required_permission = "inventory.change_bulkupload"

    model = BulkUpload
    form_class = BulkUploadForm
    template_name = "inventory/bulk_upload/form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Update Bulk Upload Batch"
        return context

    def form_valid(self, form):
        messages.success(self.request, "Bulk upload batch updated successfully")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("inventory_bulk_upload:home")


class DeleteBulkUpload(RequiredPermissionMixin, DeleteView):
    required_permission = "inventory.delete_bulkupload"

    model = BulkUpload
    template_name = "inventory/bulk_upload/delete.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Delete Bulk Upload Batch"
        return context

    def get_success_url(self):
        return reverse("inventory_bulk_upload:home")

    def form_valid(self, form):
        messages.success(self.request, "Bulk upload batch deleted successfully")
        return super().form_valid(form)


BULK_UPLOAD_ITEM_CSV_HEADERS = [
    "brand", "name", "category", "cloth_type", "uom", "hsn_code",
    "quantity", "purchase_price", "mrp", "discount_percentage",
    "commission_percentage", "description", "size", "color", "minimum_quantity",
]

@required_permission("inventory.view_bulkupload")
def bulk_upload_detail(request, pk):
    """Render the dual-view bulk upload workspace (Table Overview + Focus Stepper)."""
    batch = get_object_or_404(
        BulkUpload.objects.select_related("supplier_invoice", "supplier_invoice__supplier", "created_by"),
        pk=pk,
    )
    items_qs = (
        batch.items
        .select_related(
            "product", "variant", "variant__product",
            "variant__size", "variant__color",
            "category", "cloth_type", "uom", "hsn_code",
            "size", "color",
        )
        .order_by("sort_order", "created_at")
    )
    # Build lightweight item list for the client-side reactivity and stepper
    items_list = []
    for item in items_qs:
        brand_val = ""
        name_val = ""
        if item.variant:
            brand_val = item.variant.product.brand or ""
            name_val = item.variant.product.name or ""
            s_name = item.variant.size.name if item.variant.size else ""
            c_name = item.variant.color.name if item.variant.color else ""
            attr_parts = [p for p in [s_name, c_name] if p]
            attr_suffix = f" ({'/'.join(attr_parts)})" if attr_parts else ""
            label = f"{item.variant.product.name}{attr_suffix}"
        elif item.product:
            brand_val = item.product.brand or ""
            name_val = item.product.name or ""
            label = f"{item.product.brand} — {item.product.name}" if item.product.brand else item.product.name
        else:
            brand_val = item.brand or ""
            name_val = item.name or ""
            brand_p = f"{item.brand} — " if item.brand else ""
            label = f"{brand_p}{item.name or f'Item #{item.sort_order}'}"
        items_list.append({
            "id": item.id,
            "sort_order": item.sort_order,
            "is_committed": item.is_committed,
            "brand": brand_val,
            "name": name_val,
            "label": label,
        })

    aggregates = batch.items.aggregate(
        total_items=Count("id"),
        committed_items=Count("id", filter=Q(status=BulkUploadItem.ItemStatus.COMMITTED)),
        draft_items=Count("id", filter=Q(status=BulkUploadItem.ItemStatus.DRAFT)),
        total_qty=Sum("quantity"),
        total_purchase_value=Sum(F("quantity") * F("purchase_price")),
        total_selling_value=Sum(F("quantity") * F("mrp")),
    )

    total_items = aggregates["total_items"] or 0
    committed_items = aggregates["committed_items"] or 0
    draft_items = aggregates["draft_items"] or 0
    total_qty = aggregates["total_qty"] or 0
    total_purchase = aggregates["total_purchase_value"] or 0
    total_selling = aggregates["total_selling_value"] or 0
    potential_profit = total_selling - total_purchase
    margin_pct = (potential_profit / total_purchase * 100) if total_purchase > 0 else 0
    completion_pct = round((committed_items / total_items * 100)) if total_items > 0 else 0

    summary = {
        "total_items": total_items,
        "committed_items": committed_items,
        "draft_items": draft_items,
        "total_qty": total_qty,
        "total_purchase_value": total_purchase,
        "total_selling_value": total_selling,
        "potential_profit": potential_profit,
        "margin_pct": margin_pct,
        "completion_pct": completion_pct,
    }

    context = {
        "batch": batch,
        "items": items_qs,
        "items_list": items_list,
        "summary": summary,
    }
    return render(request, "inventory/bulk_upload/detail.html", context)


@required_permission("inventory.view_bulkupload")
def bulk_upload_sample_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="bulk_upload_sample.csv"'
    writer = csv.writer(response)
    writer.writerow(BULK_UPLOAD_ITEM_CSV_HEADERS)
    return response


@required_permission("inventory.view_bulkupload")
def bulk_upload_item_form(request, pk, item_id):
    """Return a single item's full editable form via AJAX for the stepper."""
    batch = get_object_or_404(BulkUpload, pk=pk)
    item = get_object_or_404(
        BulkUploadItem.objects.select_related(
            "product", "variant", "variant__product",
            "variant__size", "variant__color",
            "category", "cloth_type", "uom", "hsn_code", "size", "color",
        ),
        pk=item_id,
        bulk_upload=batch,
    )
    context = {
        "item": item,
        "batch": batch,
        "categories": Category.objects.all().order_by("name"),
        "cloth_types": ClothType.objects.all().order_by("name"),
        "uoms": UOM.objects.filter(is_active=True).order_by("name"),
        "hsn_codes": GSTHsnCode.objects.filter(is_active=True).order_by("code"),
        "sizes": Size.objects.all().order_by("name"),
        "colors": Color.objects.all().order_by("name"),
    }
    return render(request, "inventory/bulk_upload/_item_form.html", context)


@required_permission("inventory.view_bulkupload")
def product_search(request, pk):
    """AJAX product search for Select2 — returns JSON {results: [{id, text, ...}]}."""
    q = request.GET.get("q", "").strip()
    results = []
    if len(q) >= 1:
        products = (
            Product.objects
            .filter(
                is_deleted=False,
            )
            .filter(Q(name__icontains=q) | Q(brand__icontains=q))
            .only("id", "brand", "name", "category_id", "cloth_type_id", "uom_id", "hsn_code_id")
            .order_by("name")[:25]
        )
        for p in products:
            results.append({
                "id": p.id,
                "text": f"{p.brand} \u2014 {p.name} (ID: {p.id})",
                "brand": p.brand or "",
                "name": p.name or "",
                "category_id": p.category_id or "",
                "cloth_type_id": p.cloth_type_id or "",
                "uom_id": p.uom_id or "",
                "hsn_code_id": p.hsn_code_id or "",
            })
    return JsonResponse({"results": results})


@required_permission("inventory.view_bulkupload")
def variant_search(request, pk):
    """AJAX variant search for Select2 — returns JSON {results: [{id, text, ...}]}."""
    q = request.GET.get("q", "").strip()
    product_id = request.GET.get("product_id", "")
    results = []
    if len(q) >= 1 or product_id:
        qs = (
            ProductVariant.objects
            .filter(is_deleted=False)
            .select_related("product", "size", "color")
        )
        if product_id:
            qs = qs.filter(product_id=product_id)
        if q:
            qs = qs.filter(
                Q(product__name__icontains=q)
                | Q(product__brand__icontains=q)
                | Q(barcode__icontains=q)
            )
        qs = qs.only(
            "id", "barcode", "purchase_price", "mrp",
            "product_id", "size_id", "color_id",
            "product__brand", "product__name",
            "product__category_id", "product__cloth_type_id",
            "product__uom_id", "product__hsn_code_id",
            "size__name", "color__name",
        ).order_by("product__name", "barcode")[:25]
        for v in qs:
            attr_list = [p for p in [v.size.name if v.size else '', v.color.name if v.color else ''] if p]
            attr_text = f" ({'/'.join(attr_list)})" if attr_list else ""
            brand_str = f"{v.product.brand} — " if v.product.brand else ""
            results.append({
                "id": v.id,
                "text": f"{brand_str}{v.product.name}{attr_text} [#{v.barcode}]",
                "product_id": v.product_id,
                "brand": v.product.brand or "",
                "name": v.product.name or "",
                "category_id": v.product.category_id or "",
                "cloth_type_id": v.product.cloth_type_id or "",
                "uom_id": v.product.uom_id or "",
                "hsn_code_id": v.product.hsn_code_id or "",
                "size_id": v.size_id or "",
                "color_id": v.color_id or "",
                "purchase_price": str(v.purchase_price or "0"),
                "mrp": str(v.mrp or "0"),
            })
    return JsonResponse({"results": results})


@required_permission("inventory.add_bulkuploaditem")
@require_http_methods(["POST"])
def bulk_upload_csv(request, pk):
    """Upload CSV file and parse items via BulkUploadService."""
    batch = get_object_or_404(BulkUpload, pk=pk)

    if "csv_file" not in request.FILES:
        return JsonResponse({"success": False, "message": "No CSV file provided."})

    result = BulkUploadService.process_csv_import(batch, request.FILES["csv_file"])
    return JsonResponse(result)


@required_permission("inventory.change_bulkuploaditem")
@require_http_methods(["POST"])
def bulk_upload_item_update(request, pk, item_id):
    """Update a single BulkUploadItem fields via AJAX."""
    batch = get_object_or_404(BulkUpload, pk=pk)
    item = get_object_or_404(BulkUploadItem, pk=item_id, bulk_upload=batch)

    if item.is_committed:
        return JsonResponse({
            "success": False,
            "message": "This item has already been committed to inventory and cannot be updated here.",
        })

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON."})

    result = BulkUploadService.update_item(item, data)
    return JsonResponse(result)


@required_permission("inventory.delete_bulkuploaditem")
@require_http_methods(["POST"])
def bulk_upload_item_delete(request, pk, item_id):
    """Delete a single BulkUploadItem via AJAX."""
    batch = get_object_or_404(BulkUpload, pk=pk)
    item = get_object_or_404(BulkUploadItem, pk=item_id, bulk_upload=batch)

    if item.is_committed:
        return JsonResponse({
            "success": False,
            "message": "This item has already been committed to inventory and cannot be deleted from the batch.",
        })

    result = BulkUploadService.delete_item(item)
    return JsonResponse(result)


@required_permission("inventory.add_product")
@require_http_methods(["POST"])
def bulk_upload_item_commit(request, pk, item_id):
    """Commit a single BulkUploadItem: save/create real Product and ProductVariant in inventory."""
    batch = get_object_or_404(BulkUpload, pk=pk)
    item = get_object_or_404(BulkUploadItem, pk=item_id, bulk_upload=batch)

    data = None
    if request.body:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            pass

    result = BulkUploadService.commit_item(item, request.user, data)
    return JsonResponse(result)


@required_permission("inventory.add_product")
@require_http_methods(["POST"])
def bulk_upload_commit_all(request, pk):
    """Commit all uncommitted items in a batch at once."""
    batch = get_object_or_404(BulkUpload, pk=pk)
    result = BulkUploadService.commit_all_items(batch, request.user)
    return JsonResponse(result)


@required_permission("inventory.delete_bulkuploaditem")
@require_http_methods(["POST"])
def bulk_upload_delete_uncommitted(request, pk):
    """Delete all uncommitted items from a batch at once."""
    batch = get_object_or_404(BulkUpload, pk=pk)
    result = BulkUploadService.delete_uncommitted_items(batch)
    return JsonResponse(result)
