"""
Views for handling inventory operations
such as product creation, updates, and tracking.
"""

import json
import logging
from decimal import Decimal
from typing import Optional, Union

from django.contrib import messages
from django.db import models, transaction
from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    FloatField,
    Max,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Abs, Coalesce
from django.db.utils import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.views.generic import View

from base.decorators import RequiredPermissionMixin, required_permission, query_debugger
from base.getDates import getDates
from base.utility import build_search_filter, render_paginated_response, table_sorting
from supplier.models import Supplier, SupplierInvoice

from .forms import (
    CategoryForm,
    ClothTypeForm,
    ColorForm,
    GSTHsnCodeForm,
    InventoryPriceUpdateForm,
    ProductForm,
    SizeForm,
    UOMForm,
    VariantForm,
)
from .models import BarcodeMapping, InventoryLog, Product, ProductVariant, VariantMedia
from .services import (
    InventoryService,
    get_media_gallery_data,
    get_media_gallery_stats,
)

logger = logging.getLogger(__name__)


@required_permission("inventory.view_dashboard")
def inventory_dashboard(request):
    """Enhanced inventory dashboard with comprehensive metrics"""
    active_variants = ProductVariant.objects.filter(
        is_deleted=False, status=ProductVariant.VariantStatus.ACTIVE
    )

    total_products = Product.objects.filter(is_deleted=False).count()

    variant_metrics = active_variants.aggregate(
        total_variants=Count("id"),
        low_stock_count=Count("id", filter=Q(quantity__lte=F("minimum_quantity"))),
        total_inventory_value=Coalesce(
            Sum(F("quantity") * F("purchase_price"), output_field=DecimalField()),
            Decimal("0"),
        ),
    )

    total_inventory_value = float(variant_metrics["total_inventory_value"])

    # Calculate valuation trend (month-over-month)
    from datetime import timedelta
    from django.utils import timezone

    thirty_days_ago = timezone.now() - timedelta(days=30)
    period_changes = InventoryLog.objects.filter(
        variant__is_deleted=False,
        variant__status=ProductVariant.VariantStatus.ACTIVE,
        timestamp__gte=thirty_days_ago,
    ).aggregate(
        stock_in_value=Coalesce(
            Sum(
                Abs(F("quantity_change")) * F("purchase_price"),
                filter=Q(transaction_type__in=["STOCK_IN", "INITIAL"]),
                output_field=DecimalField(),
            ),
            Decimal("0"),
        ),
        stock_out_value=Coalesce(
            Sum(
                Abs(F("quantity_change")) * F("purchase_price"),
                filter=Q(transaction_type="SALE"),
                output_field=DecimalField(),
            ),
            Decimal("0"),
        ),
    )

    stock_in_value = float(period_changes["stock_in_value"])
    stock_out_value = float(period_changes["stock_out_value"])
    valuation_change = stock_in_value - stock_out_value
    previous_valuation = total_inventory_value - valuation_change

    if previous_valuation > 0:
        trend_pct = round((valuation_change / previous_valuation) * 100, 1)
    else:
        trend_pct = 0

    total_stock_data = _calculate_total_stock_by_supplier()

    context = {
        "total_products": total_products,
        "total_variants": variant_metrics["total_variants"],
        "low_stock_variants": variant_metrics["low_stock_count"],
        "total_inventory_value": total_inventory_value,
        "valuation_trend": trend_pct,
        "date_filter": request.GET.get("date_filter", "this_month"),
        "total_stock_data_json": json.dumps(total_stock_data),
    }

    return render(request, "inventory/dashboard.html", context)


@required_permission("inventory.view_dashboard")
def inventory_dashboard_fetch(request):
    """
    AJAX endpoint to fetch dynamic dashboard data based on date filter

    OPTIMIZED: Uses conditional aggregation to get all metrics in fewer queries
    and processes percentages in a single pass instead of multiple loops.
    """
    start_date, end_date = getDates(request)
    date_filter = request.GET.get("date_filter", "this_month")

    # Base queryset for date range
    base_qs = InventoryLog.objects.filter(
        variant__is_deleted=False, timestamp__gte=start_date, timestamp__lte=end_date
    )

    # Get both stock_in and stock_out totals in a single query using conditional aggregation
    totals = base_qs.aggregate(
        stock_in_total=Coalesce(
            Sum(
                Abs(F("quantity_change")) * F("purchase_price"),
                filter=Q(transaction_type__in=["STOCK_IN", "INITIAL"]),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
            Decimal("0"),
        ),
        stock_out_total=Coalesce(
            Sum(
                Abs(F("quantity_change")) * F("purchase_price"),
                filter=Q(transaction_type="SALE"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
            Decimal("0"),
        ),
    )

    stock_in_total = float(totals["stock_in_total"])
    stock_out_total = float(totals["stock_out_total"])

    # Stock in breakdown by supplier with percentage calculation
    stock_in_breakdown_qs = (
        base_qs.filter(transaction_type__in=["STOCK_IN", "INITIAL"])
        .values(
            supplier_name=Coalesce(
                F("supplier_invoice__supplier__name"), Value("Others")
            )
        )
        .annotate(
            amount=Coalesce(
                Sum(
                    Abs(F("quantity_change")) * F("purchase_price"),
                    output_field=DecimalField(max_digits=16, decimal_places=2),
                ),
                Decimal("0"),
            )
        )
        .order_by("-amount")
    )

    # Convert to list with percentages in a single pass
    stock_in_breakdown = [
        {
            "supplier_name": item["supplier_name"],
            "amount": float(item["amount"]),
            "percentage": (
                round((float(item["amount"]) / stock_in_total * 100), 1)
                if stock_in_total > 0
                else 0
            ),
            "count": 0,  # Keeping for consistency
        }
        for item in stock_in_breakdown_qs
    ]

    # Stock out breakdown by supplier with percentage calculation
    stock_out_breakdown_qs = (
        base_qs.filter(transaction_type="SALE")
        .values(
            supplier_name=Coalesce(
                F("source_inventory_log__supplier_invoice__supplier__name"),
                Value("Others"),
            )
        )
        .annotate(
            amount=Coalesce(
                Sum(
                    Abs(F("quantity_change")) * F("purchase_price"),
                    output_field=DecimalField(max_digits=16, decimal_places=2),
                ),
                Decimal("0"),
            )
        )
        .order_by("-amount")
    )

    # Convert to list with percentages in a single pass
    stock_out_breakdown = [
        {
            "supplier_name": item["supplier_name"],
            "amount": float(item["amount"]),
            "percentage": (
                round((float(item["amount"]) / stock_out_total * 100), 1)
                if stock_out_total > 0
                else 0
            ),
            "count": 0,  # Keeping for consistency
        }
        for item in stock_out_breakdown_qs
    ]

    # Prepare stats
    stats = {
        "stock_in": round(stock_in_total, 2),
        "stock_out": round(stock_out_total, 2),
    }

    return JsonResponse(
        {
            "success": True,
            "stats": stats,
            "stock_in_breakdown": stock_in_breakdown,
            "stock_out_breakdown": stock_out_breakdown,
            "date_range": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "filter": date_filter,
            },
        }
    )


def _calculate_total_stock_by_supplier():
    """
    Calculate total stock by supplier (date-independent).

    OPTIMIZED: Uses database-level aggregation with subquery to get latest supplier
    per variant, eliminating Python-level iteration and reducing memory usage.

    Performance improvements:
    1. Single query with subquery instead of fetching all logs
    2. Database-level aggregation instead of Python loops
    3. Reduced memory footprint by not loading all variant/log data
    """

    # Subquery to get the latest supplier for each variant
    # This gets the supplier name from the most recent STOCK_IN/INITIAL log
    latest_supplier_subquery = InventoryLog.objects.filter(
        variant=models.OuterRef("pk"),
        transaction_type__in=[
            "STOCK_IN",
            "INITIAL",
        ],
        supplier_invoice__isnull=False,
    ).values("supplier_invoice__supplier__name")[:1]

    # Aggregate stock value by supplier at the database level
    stock_by_supplier = (
        ProductVariant.objects.filter(
            is_deleted=False, status=ProductVariant.VariantStatus.ACTIVE
        )
        .annotate(
            supplier_name=Coalesce(
                models.Subquery(latest_supplier_subquery),
                Value("Others"),
            ),
            stock_value=ExpressionWrapper(
                F("quantity") * F("purchase_price"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
        )
        .values("supplier_name")
        .annotate(total_value=Sum("stock_value"))
        .order_by("-total_value")
    )

    # Convert to lists
    labels = []
    values = []
    total_stock_value = Decimal("0")

    for item in stock_by_supplier:
        supplier_name = item["supplier_name"] or "Others"
        value = float(item["total_value"] or 0)

        labels.append(supplier_name)
        values.append(round(value, 2))
        total_stock_value += Decimal(str(value))

    # Calculate percentages
    total_float = float(total_stock_value)
    percentages = [
        round((val / total_float * 100), 1) if total_float > 0 else 0 for val in values
    ]

    result = {
        "labels": labels,
        "values": values,
        "percentages": percentages,
    }

    return result


@required_permission("inventory.view_low_stock")
def low_stock_page(request):
    """Display all low stock items with pagination"""

    # Get active variants that are low on stock
    low_stock_variants = (
        ProductVariant.objects.filter(
            is_deleted=False,
            status=ProductVariant.VariantStatus.ACTIVE,
            minimum_quantity__gt=0,
            quantity__lte=F("minimum_quantity"),
        )
        .select_related("product")
        .order_by("quantity")
    )

    # Pagination
    from django.core.paginator import Paginator

    paginator = Paginator(low_stock_variants, 20)  # 20 items per page
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Calculate summary stats
    total_low_stock = low_stock_variants.count()
    out_of_stock = low_stock_variants.filter(quantity=0).count()
    critical_stock = low_stock_variants.filter(
        quantity__lt=F("minimum_quantity") * 0.5
    ).count()

    # Add critical threshold to each variant for template use
    for variant in page_obj:
        variant.critical_threshold = float(variant.minimum_quantity) * 0.5

    context = {
        "page_obj": page_obj,
        "total_low_stock": total_low_stock,
        "out_of_stock": out_of_stock,
        "critical_stock": critical_stock,
        "title": "Low Stock Items",
    }

    return render(request, "inventory/low_stock.html", context)


@required_permission("inventory.view_productvariant")
def damaged_stock_page(request):
    """Shell page for Damaged Stock management with summary stat cards and filters."""
    from decimal import Decimal
    from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
    from django.db.models.functions import Coalesce
    from inventory.models import DamagedItemRecord
    from supplier.models import Supplier

    all_active = DamagedItemRecord.objects.filter(is_deleted=False)
    stats = all_active.aggregate(
        total_records=Count("id"),
        pending_count=Count("id", filter=Q(status=DamagedItemRecord.Status.PENDING)),
        returned_count=Count("id", filter=Q(status=DamagedItemRecord.Status.RETURNED)),
        repaired_count=Count("id", filter=Q(status=DamagedItemRecord.Status.REPAIRED)),
        written_off_count=Count("id", filter=Q(status=DamagedItemRecord.Status.WRITTEN_OFF)),
        total_units_damaged=Coalesce(Sum("quantity"), Decimal("0")),
        total_damaged_value=Coalesce(
            Sum(
                ExpressionWrapper(
                    F("quantity") * F("variant__purchase_price"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
                filter=Q(status=DamagedItemRecord.Status.PENDING),
            ),
            Decimal("0"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    )

    context = {
        "total_records": stats["total_records"],
        "pending_count": stats["pending_count"],
        "returned_count": stats["returned_count"],
        "repaired_count": stats["repaired_count"],
        "written_off_count": stats["written_off_count"],
        "total_units_damaged": stats["total_units_damaged"],
        "total_damaged_value": stats["total_damaged_value"],
        "title": "Damaged Stock Management",
        "status_choices": DamagedItemRecord.Status.choices,
    }

    return render(request, "inventory/damaged_stock.html", context)


@required_permission("inventory.view_productvariant")
def damaged_stock_fetch(request):
    """AJAX endpoint powering Damaged Stock table with searching, filtering, and sorting."""
    from inventory.services import DamageResolutionService

    records = DamageResolutionService.get_filtered_damaged_records(request.GET)

    sort_mapping = {
        "id": "id",
        "created_at": "created_at",
        "quantity": "quantity",
        "status": "status",
        "variant": "variant__product__name",
        "supplier": "supplier__name",
    }
    valid_sorts = table_sorting(request, sort_mapping, "-created_at")
    records = records.order_by(*valid_sorts)

    return render_paginated_response(
        request,
        records,
        "inventory/damaged_stock_fetch.html",
        per_page=20,
    )


class CreateProduct(RequiredPermissionMixin, View):
    """View to handle product creation."""

    required_permission = "inventory.add_product"

    template_name = "inventory/product_create.html"
    title = "Create Product"
    session_initial_key = "create_product_initial"
    session_barcode_key = "redirect_url"
    ACTION_CREATE_ADD = "create_add"

    def get(self, request):
        """Handle GET requests to render the product creation forms."""
        product_form, variant_form = self._get_initial_forms(request)
        return self._render_response(request, product_form, variant_form)

    def post(self, request):
        """Handle POST requests to process the product creation forms."""
        product_form = ProductForm(request.POST)
        variant_form = VariantForm(request.POST)
        action = request.POST.get("action")
        if not (product_form.is_valid() and variant_form.is_valid()):
            logger.warning(
                "Product creation form validation failed",
                extra={
                    "user_id": request.user.id,
                    "product_errors": product_form.errors,
                    "variant_errors": variant_form.errors,
                },
            )
            messages.error(request, "Please correct the errors below.")
            return self._render_response(request, product_form, variant_form)

        # Valid forms — create inside atomic block
        try:
            with transaction.atomic():
                product = product_form.save()
                variant = variant_form.save(commit=False)
                variant.product = product
                variant.created_by = request.user
                variant.save()
                InventoryService.create_initial_log(
                    variant,
                    request.user,
                    "Initial stock",
                    variant_form.cleaned_data.get("supplier_invoice"),
                )

        except IntegrityError as e:
            logger.exception(
                "Database integrity error during product creation",
                extra={"user_id": request.user.id, "error": str(e)},
            )
            messages.error(request, "A product with similar details already exists.")
            return self._render_response(request, product_form, variant_form)
        except Exception as e:  # pylint: disable=broad-except
            logger.exception(
                "Product creation failed unexpectedly",
                extra={"user_id": request.user.id, "error": str(e)},
            )
            messages.error(request, "An unexpected error occurred. Please try again.")
            return self._render_response(request, product_form, variant_form)

        messages.success(request, "Product created successfully")

        if action == self.ACTION_CREATE_ADD:
            self._persist_initial_fields(request, product_form, variant_form)
            # Store barcode URL in session for JavaScript to open
            barcode_url = reverse("report:barcode", kwargs={"pk": variant.id})
            request.session[self.session_barcode_key] = barcode_url
            request.session.modified = True
            return redirect(request.path)

        self._clear_initial_fields(request)
        return redirect("inventory_products:details", product_id=product.id)

    # ------------------ Helpers ------------------

    def _render_response(self, request, product_form, variant_form):
        return render(
            request,
            self.template_name,
            self.get_context_data(
                request, product_form=product_form, variant_form=variant_form
            ),
        )

    def get_context_data(self, request, product_form=None, variant_form=None, **kwargs):
        """Prepare context data for the product creation view."""
        context = {
            "title": self.title,
            "product_form": product_form or ProductForm(),
            "variant_form": variant_form or VariantForm(),
        }
        context.update(self._get_aux_forms())

        # Add barcode URL to context and clear it from session
        barcode_url = request.session.pop(self.session_barcode_key, None)
        if barcode_url:
            context["redirect_url"] = barcode_url

        return context

    def _get_aux_forms(self):
        return {
            "category_form": CategoryForm(),
            "cloth_type_form": ClothTypeForm(),
            "uom_form": UOMForm(),
            "gst_hsn_form": GSTHsnCodeForm(),
            "size_form": SizeForm(),
            "color_form": ColorForm(),
        }

    def _get_initial_forms(self, request):
        stored = request.session.pop(self.session_initial_key, None) or {}
        return (
            ProductForm(initial=stored.get("product", {})),
            VariantForm(initial=stored.get("variant", {})),
        )

    def _get_fields_to_persist(self):
        """Define which fields should persist in 'create and add another' workflow"""
        return {
            "product": ["cloth_type", "category", "hsn_code", "uom"],
            "variant": [
                "supplier_invoice",
                "commission_percentage",
                "discount_percentage",
            ],
        }

    def _persist_initial_fields(self, request, product_form, variant_form):
        """Persist form fields to session for 'create and add another' workflow"""
        serialize = self._serialize_value
        fields_to_persist = self._get_fields_to_persist()
        persisted_data = {}

        for form_type, field_names in fields_to_persist.items():
            form = product_form if form_type == "product" else variant_form
            persisted_data[form_type] = {
                field: serialize(form.cleaned_data.get(field)) for field in field_names
            }

        request.session[self.session_initial_key] = persisted_data
        request.session.modified = True

    def _clear_initial_fields(self, request):
        request.session.pop(self.session_initial_key, None)

    @staticmethod
    def _serialize_value(value) -> Optional[Union[int, str]]:
        """Serialize form field values for session storage"""
        if hasattr(value, "pk"):
            return value.pk
        if isinstance(value, Decimal):
            return str(value)
        return value


@required_permission("inventory.change_productvariant")
def variant_update(request, pk):
    """Update product variant details"""
    variant = get_object_or_404(ProductVariant, pk=pk)

    if request.method == "POST":
        form = VariantForm(request.POST, instance=variant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    old_purchase_price = variant.purchase_price
                    old_mrp = variant.mrp

                    # Save the updated variant
                    variant = form.save(commit=False)
                    variant.save()

                    # Create inventory log for price changes
                    if (
                        variant.purchase_price != old_purchase_price
                        or variant.mrp != old_mrp
                    ):
                        InventoryLog.objects.create(
                            variant=variant,
                            transaction_type="ADJUSTMENT_IN",
                            quantity_change=0,
                            new_quantity=variant.quantity,
                            purchase_price=variant.purchase_price,
                            mrp=variant.mrp,
                            notes=f"Price update: Purchase {old_purchase_price}→{variant.purchase_price}, "
                            f"Selling {old_mrp}→{variant.mrp}",
                            created_by=request.user,
                        )

                    messages.success(
                        request, f"Successfully updated {variant.full_name}"
                    )
                    return redirect("inventory_variant:details", variant_id=pk)
            except Exception as e:  # pylint: disable=broad-except
                logger.error("Error updating variant: %s", str(e))
                messages.error(request, f"Error updating variant: {str(e)}")
        else:
            logger.warning("Variant update form invalid: %s", form.errors)
            messages.error(request, "Please correct the errors below.")
    else:
        form = VariantForm(instance=variant)

    context = {
        "form": form,
        "variant": variant,
        "title": f"Update {variant.full_name}",
        "subtitle": "Update variant details and pricing",
    }
    return render(request, "inventory/variant_update.html", context)


@required_permission("inventory.view_supplier_invoice")
def supplier_invoice(request):
    """Render main page; data loads via AJAX fetch endpoint."""
    suppliers = (
        Supplier.objects.filter(is_deleted=False).order_by("name").values("id", "name")
    )
    invoices_count = (
        SupplierInvoice.objects.filter(is_deleted=False, inventory_logs__isnull=False)
        .distinct()
        .count()
    )
    active_suppliers_count = (
        Supplier.objects.filter(
            is_deleted=False, invoices__inventory_logs__isnull=False
        )
        .distinct()
        .count()
    )
    context = {
        "suppliers": suppliers,
        "invoices_count": invoices_count,
        "active_suppliers_count": active_suppliers_count,
    }

    return render(
        request,
        "inventory/supplier_invoice.html",
        context,
    )


def _supplier_invoice_queryset(request):
    search_query = request.GET.get("search", "").strip()
    supplier_filter = request.GET.get("supplier", "").strip()

    supplier_invoices = SupplierInvoice.objects.filter(is_deleted=False).select_related(
        "supplier"
    )

    if search_query:
        supplier_invoices = supplier_invoices.filter(
            Q(invoice_number__icontains=search_query)
            | Q(supplier__name__icontains=search_query)
        )

    if supplier_filter:
        supplier_invoices = supplier_invoices.filter(supplier_id=supplier_filter)

    supplier_invoices = supplier_invoices.annotate(
        stock_in_quantity=Coalesce(
            Sum(
                Case(
                    When(
                        inventory_logs__transaction_type__in=[
                            "STOCK_IN",
                            "INITIAL",
                            "ADJUSTMENT_IN",
                        ],
                        then=F("inventory_logs__quantity_change"),
                    ),
                    default=Decimal("0"),
                    output_field=models.DecimalField(max_digits=16, decimal_places=2),
                )
            ),
            Decimal("0"),
        ),
        sales_quantity=Coalesce(
            Sum(
                Case(
                    When(
                        inventory_logs__transaction_type="SALE",
                        then=Abs(F("inventory_logs__quantity_change")),
                    ),
                    When(
                        inventory_logs__transaction_type__in=[
                            "RETURN",
                            "CANCEL",
                        ],
                        then=-Abs(F("inventory_logs__quantity_change")),
                    ),
                    default=Decimal("0"),
                    output_field=models.DecimalField(max_digits=16, decimal_places=2),
                )
            ),
            Decimal("0"),
        ),
        damage_quantity=Coalesce(
            Sum(
                Case(
                    When(
                        inventory_logs__transaction_type__in=[
                            "DAMAGE",
                            "ADJUSTMENT_OUT",
                        ],
                        then=Abs(F("inventory_logs__quantity_change")),
                    ),
                    default=Decimal("0"),
                    output_field=models.DecimalField(max_digits=16, decimal_places=2),
                )
            ),
            Decimal("0"),
        ),
        stock_amount=Coalesce(
            Sum(
                Case(
                    When(
                        inventory_logs__transaction_type__in=[
                            "STOCK_IN",
                            "INITIAL",
                            "ADJUSTMENT_IN",
                        ],
                        then=ExpressionWrapper(
                            F("inventory_logs__quantity_change")
                            * F("inventory_logs__purchase_price"),
                            output_field=DecimalField(max_digits=16, decimal_places=2),
                        ),
                    ),
                    default=Value(0),
                    output_field=DecimalField(max_digits=16, decimal_places=2),
                )
            ),
            Value(0),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
        products_count=Count(
            "inventory_logs__variant__product",
            filter=Q(inventory_logs__transaction_type__in=["STOCK_IN", "INITIAL"]),
            distinct=True,
        ),
    )
    supplier_invoices = supplier_invoices.annotate(
        remaining_quantity=ExpressionWrapper(
            F("stock_in_quantity") - F("sales_quantity") - F("damage_quantity"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
    )

    supplier_invoices = supplier_invoices.annotate(
        sold_percentage=Case(
            When(
                stock_in_quantity__gt=0,
                then=ExpressionWrapper(
                    F("sales_quantity") * Value(100.0) / F("stock_in_quantity"),
                    output_field=FloatField(),
                ),
            ),
            default=Value(0.0),
            output_field=FloatField(),
        )
    ).filter(stock_in_quantity__gt=0)

    ordering_map = {
        "invoice_number": "invoice_number",
        "supplier_name": "supplier__name",
        "invoice_date": "invoice_date",
        "invoice_amount": "total_amount",
        "stock_in_quantity": "stock_in_quantity",
        "sales_quantity": "sales_quantity",
        "remaining_quantity": "remaining_quantity",
        "sold_percentage": "sold_percentage",
        "stock_amount": "stock_amount",
    }

    final_sorts = table_sorting(request, ordering_map, "-invoice_date")
    return supplier_invoices.order_by(*final_sorts)


def _supplier_grouped_queryset(request):
    """Return a queryset of suppliers annotated with aggregate inventory and sales stats.

    Supports search, status filter, and multi-column sorting via query params.
    """
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()

    quantity_field = models.DecimalField(max_digits=16, decimal_places=2)

    suppliers = Supplier.objects.filter(is_deleted=False)

    if search_query:
        suppliers = suppliers.filter(
            Q(name__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(contact_person__icontains=search_query)
            | Q(gstin__icontains=search_query)
        )

    suppliers = (
        suppliers.annotate(
            invoices_count=Count(
                "invoices",
                filter=Q(
                    invoices__is_deleted=False,
                    invoices__inventory_logs__isnull=False,
                ),
                distinct=True,
            ),
            total_invoiced=Coalesce(
                Sum("invoices__total_amount", filter=Q(invoices__is_deleted=False)),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            stock_in_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            invoices__inventory_logs__transaction_type__in=[
                                "STOCK_IN",
                                "INITIAL",
                                "ADJUSTMENT_IN",
                            ],
                            then=F("invoices__inventory_logs__quantity_change"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            sales_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            invoices__inventory_logs__transaction_type="SALE",
                            then=-F("invoices__inventory_logs__quantity_change"),
                        ),
                        When(
                            invoices__inventory_logs__transaction_type__in=[
                                "RETURN",
                                "CANCEL",
                            ],
                            then=-F("invoices__inventory_logs__quantity_change"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            damage_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            invoices__inventory_logs__transaction_type__in=[
                                "DAMAGE",
                                "ADJUSTMENT_OUT",
                            ],
                            then=-F("invoices__inventory_logs__quantity_change"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            sales_revenue=Coalesce(
                Sum(
                    Case(
                        When(
                            invoices__inventory_logs__transaction_type="SALE",
                            then=F("invoices__inventory_logs__total_value"),
                        ),
                        When(
                            invoices__inventory_logs__transaction_type__in=[
                                "RETURN",
                                "CANCEL",
                            ],
                            then=-F("invoices__inventory_logs__total_value"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            cogs=Coalesce(
                Sum(
                    Case(
                        When(
                            invoices__inventory_logs__transaction_type="SALE",
                            then=ExpressionWrapper(
                                -F("invoices__inventory_logs__quantity_change")
                                * Coalesce(
                                    F("invoices__inventory_logs__purchase_price"),
                                    Decimal("0"),
                                ),
                                output_field=quantity_field,
                            ),
                        ),
                        When(
                            invoices__inventory_logs__transaction_type__in=[
                                "RETURN",
                                "CANCEL",
                            ],
                            then=ExpressionWrapper(
                                -F("invoices__inventory_logs__quantity_change")
                                * Coalesce(
                                    F("invoices__inventory_logs__purchase_price"),
                                    Decimal("0"),
                                ),
                                output_field=quantity_field,
                            ),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
        )
        .annotate(
            remaining_quantity=ExpressionWrapper(
                F("stock_in_quantity") - F("sales_quantity") - F("damage_quantity"),
                output_field=quantity_field,
            ),
            profit=ExpressionWrapper(
                F("sales_revenue") - F("cogs"),
                output_field=quantity_field,
            ),
            sold_percentage=Case(
                When(
                    stock_in_quantity__gt=0,
                    then=ExpressionWrapper(
                        F("sales_quantity") * Value(100.0) / F("stock_in_quantity"),
                        output_field=FloatField(),
                    ),
                ),
                default=Value(0.0),
                output_field=FloatField(),
            ),
        )
        .filter(stock_in_quantity__gt=0)
    )

    if status_filter == "sold_out":
        suppliers = suppliers.filter(remaining_quantity__lte=0)
    elif status_filter == "in_stock":
        suppliers = suppliers.filter(remaining_quantity__gt=0)
    elif status_filter == "low_stock":
        suppliers = suppliers.filter(
            remaining_quantity__gt=0, remaining_quantity__lte=10
        )
    elif status_filter == "selling_well":
        suppliers = suppliers.filter(
            sold_percentage__gte=50.0, remaining_quantity__gt=0
        )
    elif status_filter == "slow_moving":
        suppliers = suppliers.filter(
            sold_percentage__lt=50.0, remaining_quantity__gt=0
        )
    elif status_filter == "damaged":
        suppliers = suppliers.filter(damage_quantity__gt=0)

    ordering_map = {
        "name": "name",
        "invoices_count": "invoices_count",
        "total_invoiced": "total_invoiced",
        "stock_in_quantity": "stock_in_quantity",
        "sales_quantity": "sales_quantity",
        "damage_quantity": "damage_quantity",
        "remaining_quantity": "remaining_quantity",
        "sold_percentage": "sold_percentage",
        "profit": "profit",
    }

    final_sorts = table_sorting(request, ordering_map, "-stock_in_quantity")
    return suppliers.order_by(*final_sorts)


@required_permission("inventory.view_supplier_invoice")
def supplier_invoice_fetch(request):
    """AJAX endpoint powering supplier invoice tracking table."""
    view_mode = request.GET.get("view_mode", "invoices").strip()

    if view_mode == "suppliers":
        suppliers = _supplier_grouped_queryset(request)
        return render_paginated_response(
            request,
            suppliers,
            "inventory/supplier_invoice_supplier_fetch.html",
        )

    invoices = _supplier_invoice_queryset(request)
    return render_paginated_response(
        request,
        invoices,
        "inventory/supplier_invoice_fetch.html",
    )


def _supplier_invoice_totals(invoice_id):
    """Aggregate totals for a supplier invoice (summary and KPI cards).

    Returns a dict with:
      - total_stock_in: units received
      - total_stock_in_value: total purchase value of units received
      - total_sales: net units sold (sales - returns - cancels)
      - total_sales_revenue: net revenue from sold items
      - total_cogs: cost of goods sold
      - total_profit: gross profit (sales revenue - cogs)
      - profit_margin: gross profit margin %
      - total_damage: units damaged/lost
      - total_damage_value: cost of damaged units
      - total_remaining: units remaining (stock in - sales - damage)
      - sold_percentage: overall sell-through % (total_sales / total_stock_in * 100)
    """
    quantity_field = models.DecimalField(max_digits=16, decimal_places=2)

    totals = InventoryLog.objects.filter(supplier_invoice_id=invoice_id).aggregate(
        total_stock_in=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type__in=["STOCK_IN", "INITIAL", "ADJUSTMENT_IN"],
                        then=F("quantity_change"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        total_stock_in_value=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type__in=["STOCK_IN", "INITIAL", "ADJUSTMENT_IN"],
                        then=F("total_value"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        gross_sales=Coalesce(
            Sum(
                Case(
                    When(transaction_type="SALE", then=-F("quantity_change")),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        returns_cancels=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type__in=["RETURN", "CANCEL"],
                        then=F("quantity_change"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        total_damage=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type__in=["DAMAGE", "ADJUSTMENT_OUT"],
                        then=-F("quantity_change"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        total_damage_value=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type__in=["DAMAGE", "ADJUSTMENT_OUT"],
                        then=F("total_value"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        total_sales_revenue=Coalesce(
            Sum(
                Case(
                    When(transaction_type="SALE", then=F("total_value")),
                    When(
                        transaction_type__in=["RETURN", "CANCEL"],
                        then=-F("total_value"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        total_cogs=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type="SALE",
                        then=ExpressionWrapper(
                            -F("quantity_change")
                            * Coalesce(F("purchase_price"), Decimal("0")),
                            output_field=quantity_field,
                        ),
                    ),
                    When(
                        transaction_type__in=["RETURN", "CANCEL"],
                        then=ExpressionWrapper(
                            -F("quantity_change")
                            * Coalesce(F("purchase_price"), Decimal("0")),
                            output_field=quantity_field,
                        ),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
    )

    stock_in = totals["total_stock_in"]
    net_sales = totals["gross_sales"] - totals["returns_cancels"]
    damage = totals["total_damage"]
    remaining = max(Decimal("0"), stock_in - net_sales - damage)
    revenue = totals["total_sales_revenue"]
    cogs = totals["total_cogs"]
    profit = revenue - cogs
    profit_margin = (profit / revenue * 100) if revenue > 0 else Decimal("0")
    sold_pct = (net_sales / stock_in * 100) if stock_in > 0 else Decimal("0")

    return {
        "total_stock_in": stock_in,
        "total_stock_in_value": totals["total_stock_in_value"],
        "total_sales": net_sales,
        "total_sales_revenue": revenue,
        "total_cogs": cogs,
        "total_profit": profit,
        "profit_margin": profit_margin,
        "total_damage": damage,
        "total_damage_value": totals["total_damage_value"],
        "total_remaining": remaining,
        "sold_percentage": sold_pct,
    }


def _supplier_invoice_details_products_qs(request, invoice_id):
    """Return a lazy queryset of per-product breakdown for a supplier invoice.

    Supports search, status filter, and multi-column sorting via query params.
    """
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()

    quantity_field = models.DecimalField(max_digits=16, decimal_places=2)

    products_qs = (
        InventoryLog.objects.filter(supplier_invoice_id=invoice_id)
        .values(
            "variant__product__brand",
            "variant__product__name",
            "variant__size__name",
            "variant__color__name",
            "variant__color__hex_code",
            "variant__barcode",
            "variant__id",
        )
        .annotate(
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
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            sales_quantity=Coalesce(
                Sum(
                    Case(
                        When(transaction_type="SALE", then=-F("quantity_change")),
                        When(
                            transaction_type__in=["RETURN", "CANCEL"],
                            then=-F("quantity_change"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            damage_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            transaction_type__in=["DAMAGE", "ADJUSTMENT_OUT"],
                            then=-F("quantity_change"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            purchase_price=Coalesce(
                Max(
                    Case(
                        When(
                            transaction_type__in=["STOCK_IN", "INITIAL"],
                            then=F("purchase_price"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            selling_price=Coalesce(
                Max(
                    Case(
                        When(
                            transaction_type__in=["STOCK_IN", "INITIAL"],
                            then=F("mrp"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            sales_revenue=Coalesce(
                Sum(
                    Case(
                        When(transaction_type="SALE", then=F("total_value")),
                        When(
                            transaction_type__in=["RETURN", "CANCEL"],
                            then=-F("total_value"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
        )
        .annotate(
            remaining_quantity=ExpressionWrapper(
                F("stock_in_quantity") - F("sales_quantity") - F("damage_quantity"),
                output_field=quantity_field,
            ),
            cogs=ExpressionWrapper(
                F("sales_quantity") * F("purchase_price"),
                output_field=quantity_field,
            ),
            profit=ExpressionWrapper(
                F("sales_revenue") - (F("sales_quantity") * F("purchase_price")),
                output_field=quantity_field,
            ),
            sold_percentage=Case(
                When(
                    stock_in_quantity__gt=0,
                    then=ExpressionWrapper(
                        F("sales_quantity") * Value(100.0) / F("stock_in_quantity"),
                        output_field=FloatField(),
                    ),
                ),
                default=Value(0.0),
                output_field=FloatField(),
            ),
        )
    )

    if search_query:
        products_qs = products_qs.filter(
            Q(variant__product__brand__icontains=search_query)
            | Q(variant__product__name__icontains=search_query)
            | Q(variant__barcode__icontains=search_query)
            | Q(variant__color__name__icontains=search_query)
            | Q(variant__size__name__icontains=search_query)
        )

    # Apply status filter at DB level
    if status_filter == "sold_out":
        products_qs = products_qs.filter(remaining_quantity__lte=0)
    elif status_filter == "in_stock":
        products_qs = products_qs.filter(remaining_quantity__gt=0)
    elif status_filter == "low_stock":
        products_qs = products_qs.filter(
            remaining_quantity__gt=0, remaining_quantity__lte=5
        )
    elif status_filter == "selling_well":
        products_qs = products_qs.filter(
            sold_percentage__gte=50.0, remaining_quantity__gt=0
        )
    elif status_filter == "slow_moving":
        products_qs = products_qs.filter(
            sold_percentage__lt=50.0, remaining_quantity__gt=0
        )
    elif status_filter == "damaged":
        products_qs = products_qs.filter(damage_quantity__gt=0)

    ordering_map = {
        "brand": "variant__product__brand",
        "barcode": "variant__barcode",
        "stock_in_quantity": "stock_in_quantity",
        "sales_quantity": "sales_quantity",
        "damage_quantity": "damage_quantity",
        "remaining_quantity": "remaining_quantity",
        "purchase_price": "purchase_price",
        "selling_price": "selling_price",
        "sold_percentage": "sold_percentage",
        "profit": "profit",
    }

    final_sorts = table_sorting(request, ordering_map, "-stock_in_quantity")
    return products_qs.order_by(*final_sorts)


@required_permission("inventory.view_supplier_invoice_details")
def supplier_invoice_details(request, invoice_id):
    """Shell view — products load via AJAX fetch endpoint."""
    invoice = get_object_or_404(
        SupplierInvoice.objects.select_related("supplier"),
        id=invoice_id,
        is_deleted=False,
    )
    totals = _supplier_invoice_totals(invoice_id)

    context = {
        "invoice": invoice,
        "invoice_number": invoice.invoice_number,
        "invoice_info": {
            "supplier_invoice__supplier__name": invoice.supplier.name,
            "supplier_invoice__invoice_date": invoice.invoice_date,
            "supplier_invoice__invoice_number": invoice.invoice_number,
            "supplier_invoice__total_amount": invoice.total_amount,
            "supplier_invoice__status": invoice.get_status_display(),
            "supplier_invoice__type": invoice.get_invoice_type_display(),
        },
        "title": f"Invoice - {invoice.invoice_number}",
        "invoice_id": invoice_id,
        **totals,
    }
    return render(request, "inventory/supplier_invoice_details.html", context)


@required_permission("inventory.view_supplier_invoice_details")
def supplier_invoice_details_fetch(request, invoice_id):
    """AJAX endpoint powering supplier invoice details product table."""
    # Validate invoice exists
    get_object_or_404(SupplierInvoice, id=invoice_id, is_deleted=False)

    products_qs = _supplier_invoice_details_products_qs(request, invoice_id)
    return render_paginated_response(
        request,
        products_qs,
        "inventory/supplier_invoice_details_fetch.html",
        per_page=12,
    )


def _supplier_inventory_totals(supplier_id):
    """Aggregate totals for all inventory logs associated with a supplier.

    Args:
        supplier_id (int): Primary key of the supplier.

    Returns:
        dict: Summary statistics including stock received, sales, damages,
            remaining inventory, sales revenue, COGS, profit, and margins.
    """
    quantity_field = models.DecimalField(max_digits=16, decimal_places=2)

    supplier_invoices = SupplierInvoice.objects.filter(
        supplier_id=supplier_id, is_deleted=False
    )
    all_invoices_count = supplier_invoices.count()
    total_invoice_amount = supplier_invoices.aggregate(
        total=Coalesce(
            Sum("total_amount"), Value(Decimal("0")), output_field=quantity_field
        )
    )["total"]

    totals = InventoryLog.objects.filter(
        supplier_invoice__supplier_id=supplier_id
    ).aggregate(
        total_stock_in=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type__in=["STOCK_IN", "INITIAL", "ADJUSTMENT_IN"],
                        then=F("quantity_change"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        total_stock_in_value=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type__in=["STOCK_IN", "INITIAL", "ADJUSTMENT_IN"],
                        then=F("total_value"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        gross_sales=Coalesce(
            Sum(
                Case(
                    When(transaction_type="SALE", then=-F("quantity_change")),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        returns_cancels=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type__in=["RETURN", "CANCEL"],
                        then=F("quantity_change"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        total_damage=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type__in=["DAMAGE", "ADJUSTMENT_OUT"],
                        then=-F("quantity_change"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        total_damage_value=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type__in=["DAMAGE", "ADJUSTMENT_OUT"],
                        then=F("total_value"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        total_sales_revenue=Coalesce(
            Sum(
                Case(
                    When(transaction_type="SALE", then=F("total_value")),
                    When(
                        transaction_type__in=["RETURN", "CANCEL"],
                        then=-F("total_value"),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        total_cogs=Coalesce(
            Sum(
                Case(
                    When(
                        transaction_type="SALE",
                        then=ExpressionWrapper(
                            -F("quantity_change")
                            * Coalesce(F("purchase_price"), Decimal("0")),
                            output_field=quantity_field,
                        ),
                    ),
                    When(
                        transaction_type__in=["RETURN", "CANCEL"],
                        then=ExpressionWrapper(
                            -F("quantity_change")
                            * Coalesce(F("purchase_price"), Decimal("0")),
                            output_field=quantity_field,
                        ),
                    ),
                    default=Value(Decimal("0")),
                    output_field=quantity_field,
                )
            ),
            Value(Decimal("0")),
            output_field=quantity_field,
        ),
        active_invoices_count=Count("supplier_invoice", distinct=True),
        products_count=Count("variant", distinct=True),
    )

    stock_in = totals["total_stock_in"]
    net_sales = totals["gross_sales"] - totals["returns_cancels"]
    damage = totals["total_damage"]
    remaining = max(Decimal("0"), stock_in - net_sales - damage)
    revenue = totals["total_sales_revenue"]
    cogs = totals["total_cogs"]
    profit = revenue - cogs
    profit_margin = (profit / revenue * 100) if revenue > 0 else Decimal("0")
    sold_pct = (net_sales / stock_in * 100) if stock_in > 0 else Decimal("0")
    remaining_pct = (remaining / stock_in * 100) if stock_in > 0 else Decimal("0")
    damage_pct = (damage / stock_in * 100) if stock_in > 0 else Decimal("0")

    return {
        "all_invoices_count": all_invoices_count,
        "active_invoices_count": totals["active_invoices_count"],
        "products_count": totals["products_count"],
        "total_invoice_amount": total_invoice_amount,
        "total_stock_in": stock_in,
        "total_stock_in_value": totals["total_stock_in_value"],
        "total_sales": net_sales,
        "total_sales_revenue": revenue,
        "total_cogs": cogs,
        "total_profit": profit,
        "profit_margin": profit_margin,
        "total_damage": damage,
        "total_damage_value": totals["total_damage_value"],
        "total_remaining": remaining,
        "sold_percentage": sold_pct,
        "remaining_percentage": remaining_pct,
        "damage_percentage": damage_pct,
    }


def _supplier_inventory_invoices_list(supplier_id):
    """Return annotated invoices for a specific supplier with stock and sales metrics.

    Args:
        supplier_id (int): Primary key of the supplier.

    Returns:
        QuerySet: SupplierInvoice objects with stock_in_quantity, sales_quantity,
            damage_quantity, remaining_quantity, and sold_percentage.
    """
    quantity_field = models.DecimalField(max_digits=16, decimal_places=2)

    invoices = (
        SupplierInvoice.objects.filter(supplier_id=supplier_id, is_deleted=False)
        .annotate(
            stock_in_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            inventory_logs__transaction_type__in=[
                                "STOCK_IN",
                                "INITIAL",
                                "ADJUSTMENT_IN",
                            ],
                            then=F("inventory_logs__quantity_change"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            sales_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            inventory_logs__transaction_type="SALE",
                            then=Abs(F("inventory_logs__quantity_change")),
                        ),
                        When(
                            inventory_logs__transaction_type__in=["RETURN", "CANCEL"],
                            then=-Abs(F("inventory_logs__quantity_change")),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            damage_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            inventory_logs__transaction_type__in=[
                                "DAMAGE",
                                "ADJUSTMENT_OUT",
                            ],
                            then=Abs(F("inventory_logs__quantity_change")),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            products_count=Count(
                "inventory_logs__variant",
                filter=Q(inventory_logs__transaction_type__in=["STOCK_IN", "INITIAL"]),
                distinct=True,
            ),
        )
        .annotate(
            remaining_quantity=ExpressionWrapper(
                F("stock_in_quantity") - F("sales_quantity") - F("damage_quantity"),
                output_field=quantity_field,
            ),
            sold_percentage=Case(
                When(
                    stock_in_quantity__gt=0,
                    then=ExpressionWrapper(
                        F("sales_quantity") * Value(100.0) / F("stock_in_quantity"),
                        output_field=FloatField(),
                    ),
                ),
                default=Value(0.0),
                output_field=FloatField(),
            ),
        )
        .order_by("-invoice_date")
    )
    return invoices


def _supplier_inventory_products_qs(request, supplier_id):
    """Return a lazy queryset of all product variants supplied by this vendor.

    Supports search, status filter, and multi-column sorting via query params.
    """
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()

    quantity_field = models.DecimalField(max_digits=16, decimal_places=2)

    products_qs = (
        InventoryLog.objects.filter(supplier_invoice__supplier_id=supplier_id)
        .values(
            "variant__product__brand",
            "variant__product__name",
            "variant__size__name",
            "variant__color__name",
            "variant__color__hex_code",
            "variant__barcode",
            "variant__id",
        )
        .annotate(
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
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            sales_quantity=Coalesce(
                Sum(
                    Case(
                        When(transaction_type="SALE", then=-F("quantity_change")),
                        When(
                            transaction_type__in=["RETURN", "CANCEL"],
                            then=-F("quantity_change"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            damage_quantity=Coalesce(
                Sum(
                    Case(
                        When(
                            transaction_type__in=["DAMAGE", "ADJUSTMENT_OUT"],
                            then=-F("quantity_change"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            purchase_price=Coalesce(
                Max(
                    Case(
                        When(
                            transaction_type__in=["STOCK_IN", "INITIAL"],
                            then=F("purchase_price"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            selling_price=Coalesce(
                Max(
                    Case(
                        When(
                            transaction_type__in=["STOCK_IN", "INITIAL"],
                            then=F("mrp"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            sales_revenue=Coalesce(
                Sum(
                    Case(
                        When(transaction_type="SALE", then=F("total_value")),
                        When(
                            transaction_type__in=["RETURN", "CANCEL"],
                            then=-F("total_value"),
                        ),
                        default=Value(Decimal("0")),
                        output_field=quantity_field,
                    )
                ),
                Value(Decimal("0")),
                output_field=quantity_field,
            ),
            invoices_count=Count("supplier_invoice", distinct=True),
        )
        .annotate(
            remaining_quantity=ExpressionWrapper(
                F("stock_in_quantity") - F("sales_quantity") - F("damage_quantity"),
                output_field=quantity_field,
            ),
            cogs=ExpressionWrapper(
                F("sales_quantity") * F("purchase_price"),
                output_field=quantity_field,
            ),
            profit=ExpressionWrapper(
                F("sales_revenue") - (F("sales_quantity") * F("purchase_price")),
                output_field=quantity_field,
            ),
            sold_percentage=Case(
                When(
                    stock_in_quantity__gt=0,
                    then=ExpressionWrapper(
                        F("sales_quantity") * Value(100.0) / F("stock_in_quantity"),
                        output_field=FloatField(),
                    ),
                ),
                default=Value(0.0),
                output_field=FloatField(),
            ),
        )
    )

    if search_query:
        products_qs = products_qs.filter(
            Q(variant__product__brand__icontains=search_query)
            | Q(variant__product__name__icontains=search_query)
            | Q(variant__barcode__icontains=search_query)
            | Q(variant__color__name__icontains=search_query)
            | Q(variant__size__name__icontains=search_query)
        )

    if status_filter == "sold_out":
        products_qs = products_qs.filter(remaining_quantity__lte=0)
    elif status_filter == "in_stock":
        products_qs = products_qs.filter(remaining_quantity__gt=0)
    elif status_filter == "low_stock":
        products_qs = products_qs.filter(
            remaining_quantity__gt=0, remaining_quantity__lte=5
        )
    elif status_filter == "selling_well":
        products_qs = products_qs.filter(
            sold_percentage__gte=50.0, remaining_quantity__gt=0
        )
    elif status_filter == "slow_moving":
        products_qs = products_qs.filter(
            sold_percentage__lt=50.0, remaining_quantity__gt=0
        )
    elif status_filter == "damaged":
        products_qs = products_qs.filter(damage_quantity__gt=0)

    ordering_map = {
        "brand": "variant__product__brand",
        "barcode": "variant__barcode",
        "stock_in_quantity": "stock_in_quantity",
        "sales_quantity": "sales_quantity",
        "damage_quantity": "damage_quantity",
        "remaining_quantity": "remaining_quantity",
        "purchase_price": "purchase_price",
        "selling_price": "selling_price",
        "sold_percentage": "sold_percentage",
        "profit": "profit",
    }

    final_sorts = table_sorting(request, ordering_map, "-stock_in_quantity")
    return products_qs.order_by(*final_sorts)


@required_permission("inventory.view_supplier_invoice")
def supplier_inventory_analysis(request, supplier_id):
    """Main dashboard view for full supplier-level inventory and sales analysis."""
    supplier = get_object_or_404(Supplier, id=supplier_id, is_deleted=False)
    totals = _supplier_inventory_totals(supplier_id)
    invoices = _supplier_inventory_invoices_list(supplier_id)

    context = {
        "supplier": supplier,
        "title": f"{supplier.name} - Inventory Analysis",
        "invoices": invoices,
        "supplier_id": supplier_id,
        **totals,
    }
    return render(request, "inventory/supplier_analysis.html", context)


@required_permission("inventory.view_supplier_invoice")
def supplier_inventory_analysis_fetch(request, supplier_id):
    """AJAX endpoint powering supplier products breakdown table."""
    get_object_or_404(Supplier, id=supplier_id, is_deleted=False)
    products_qs = _supplier_inventory_products_qs(request, supplier_id)
    return render_paginated_response(
        request,
        products_qs,
        "inventory/supplier_analysis_fetch.html",
        per_page=15,
    )


@required_permission("inventory.view_dashboard")
def media_gallery(request):
    """
    Media Gallery hub with live inventory visual metrics and interactive filters.

    Computes aggregate metrics across photographed garment variants, active categories,
    and stock health to power the ambient hero statistics.
    """
    context = get_media_gallery_stats()
    return render(request, "inventory/media/home.html", context)


@required_permission("inventory.view_dashboard")
def media_gallery_fetch(request):
    """
    AJAX endpoint for media gallery with real-time multi-dimensional search and filtering.
    """
    media_qs = get_media_gallery_data(request)
    return render_paginated_response(
        request,
        media_qs,
        "inventory/media/fetch.html",
        per_page=28,
    )


@required_permission("inventory.change_productvariant")
def inventory_price_update(request):
    """Render the inventory price-update page (barcode search + MRP/discount edit)."""
    return render(request, "inventory/inventory_price_update.html", {
        "title": "Inventory Price Update",
        "form": InventoryPriceUpdateForm(),
    })


@required_permission("inventory.view_productvariant")
def barcode_lookup(request):
    """AJAX endpoint: look up a product variant by barcode.

    Also checks BarcodeMapping for alternative external barcodes.
    Returns variant details as JSON for the price-update page.
    """
    barcode = request.GET.get("barcode", "").strip()
    if not barcode:
        return JsonResponse({"status": "error", "message": "Barcode is required"}, status=400)

    # Check BarcodeMapping first
    mapping = BarcodeMapping.objects.filter(barcode=barcode).select_related("variant").first()
    if mapping:
        barcode = mapping.variant.barcode

    try:
        variant = ProductVariant.objects.select_related(
            "product", "product__category", "product__hsn_code",
            "size", "color",
        ).get(barcode=barcode, is_deleted=False)
    except ProductVariant.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Product not found for this barcode"}, status=404)

    data = {
        "status": "success",
        "variant": {
            "id": variant.id,
            "barcode": variant.barcode,
            "product_name": variant.product.display_name,
            "brand": variant.product.brand,
            "name": variant.product.name or "",
            "category": variant.product.category.name if variant.product.category else "",
            "size": variant.size.name if variant.size else "",
            "color": variant.color.name if variant.color else "",
            "color_hex": variant.color.hex_code if variant.color and variant.color.hex_code else "",
            "hsn_code": variant.product.hsn_code.code if variant.product.hsn_code else "",
            "gst_percentage": str(variant.get_gst_percentage),
            "purchase_price": str(variant.purchase_price),
            "mrp": str(variant.mrp),
            "discount_percentage": str(variant.discount_percentage),
            "final_price": str(variant.final_price),
            "quantity": str(variant.quantity),
            "status": variant.get_status_display(),
            "stock_status": variant.stock_status,
            "full_name": variant.full_name,
        },
    }
    return JsonResponse(data)


@required_permission("inventory.change_productvariant")
def inventory_price_update_save(request):
    """AJAX endpoint: update MRP and discount_percentage for a variant.

    Creates an inventory log entry tracking the price change.
    """
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)

    import json as _json

    try:
        data = _json.loads(request.body)
    except _json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

    variant_id = data.get("variant_id")
    if not variant_id:
        return JsonResponse({"status": "error", "message": "variant_id is required"}, status=400)

    # Sanitize Indian currency formatted numbers (e.g. "1,000.00" -> "1000.00")
    if isinstance(data.get("mrp"), str):
        data["mrp"] = data["mrp"].replace(",", "").strip()
    if isinstance(data.get("discount_percentage"), str):
        data["discount_percentage"] = data["discount_percentage"].replace(",", "").strip()

    try:
        variant = ProductVariant.objects.get(pk=variant_id, is_deleted=False)
    except ProductVariant.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Variant not found"}, status=404)

    form = InventoryPriceUpdateForm(data, instance=variant)
    if not form.is_valid():
        errors = {field: errs[0] for field, errs in form.errors.items()}
        logger.error("Validation failed: %s", errors)
        return JsonResponse({"status": "error", "message": "Validation failed", "errors": errors}, status=400)

    try:
        with transaction.atomic():
            old_mrp = variant.mrp
            old_discount = variant.discount_percentage

            variant = form.save()

            # Log the price change
            if variant.mrp != old_mrp or variant.discount_percentage != old_discount:
                InventoryLog.objects.create(
                    variant=variant,
                    transaction_type="ADJUSTMENT_IN",
                    quantity_change=0,
                    new_quantity=variant.quantity,
                    purchase_price=variant.purchase_price,
                    mrp=variant.mrp,
                    notes=(
                        f"Price update: MRP {old_mrp}→{variant.mrp}, "
                        f"Discount {old_discount}%→{variant.discount_percentage}%"
                    ),
                    created_by=request.user,
                )

        return JsonResponse({
            "status": "success",
            "message": f"Updated {variant.full_name}",
            "variant": {
                "mrp": str(variant.mrp),
                "discount_percentage": str(variant.discount_percentage),
                "final_price": str(variant.final_price),
            },
        })
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error updating variant price: %s", e)
        return JsonResponse({"status": "error", "message": "Server error occurred"}, status=500)