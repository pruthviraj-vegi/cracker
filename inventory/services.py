import csv
import io
import logging
import re
from decimal import Decimal, InvalidOperation

from django.db import models, transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Q, Sum
from django.urls import reverse
from django.utils import timezone

from base.utility import build_search_filter, table_sorting

from .models import (
    BulkUpload,
    BulkUploadItem,
    Category,
    ClothType,
    Color,
    DamagedItemRecord,
    GSTHsnCode,
    InventoryLog,
    Product,
    ProductVariant,
    Size,
    UOM,
    VariantMedia,
)
from supplier.models import SupplierInvoice

try:
    from rapidfuzz import process, fuzz
except ImportError:
    try:
        from fuzzywuzzy import process, fuzz
    except ImportError:
        process = None
        fuzz = None

logger = logging.getLogger(__name__)


class InventoryService:
    """Service class for inventory operations"""

    @staticmethod
    def apply_discount(variant, percentage, user=None):
        """Apply discount and log the change"""
        if 0 <= percentage <= 100:
            with transaction.atomic():
                variant.discount_percentage = percentage
                variant.save()

                InventoryLog.objects.create(
                    variant=variant,
                    created_by=user,
                    quantity_change=0,
                    new_quantity=variant.quantity,
                    transaction_type=InventoryLog.TransactionTypes.ADJUSTMENT_IN,
                    notes=f"Discount applied: {percentage}%",
                )

    @staticmethod
    def update_quantity(variant, change, user=None, notes="", supplier_invoice=None):
        """Safely update quantity and create log entry"""
        with transaction.atomic():
            new_quantity = variant.quantity + change
            variant.quantity = new_quantity
            variant.save()

            InventoryLog.objects.create(
                variant=variant,
                created_by=user,
                quantity_change=change,
                new_quantity=new_quantity,
                transaction_type=InventoryLog.TransactionTypes.STOCK_IN,
                total_value=change * variant.purchase_price,
                notes=notes or f"Stock In: {change} units",
                supplier_invoice=supplier_invoice,
            )

    @staticmethod
    def adjust_in_quantity(variant, change, user=None, notes="", supplier_invoice=None):
        """Adjust quantity and create log entry"""
        with transaction.atomic():
            if change == 0:
                raise ValueError("Quantity change cannot be zero")

            new_quantity = variant.quantity + change
            variant.quantity = new_quantity
            variant.save()

            InventoryLog.objects.create(
                variant=variant,
                created_by=user,
                quantity_change=change,
                new_quantity=new_quantity,
                transaction_type=InventoryLog.TransactionTypes.ADJUSTMENT_IN,
                total_value=change * variant.purchase_price,
                notes=notes or f"Adjustment In: {change} units",
                supplier_invoice=supplier_invoice,
            )

    @staticmethod
    def adjust_out_quantity(variant, change, user=None, notes="", supplier_invoice=None):
        """Adjust quantity and create log entry"""
        with transaction.atomic():
            if change == 0:
                raise ValueError("Quantity change cannot be zero")

            if change > variant.quantity:
                raise ValueError(
                    f"Insufficient stock to adjust out. Available stock: {variant.quantity}"
                )

            new_quantity = variant.quantity - change
            variant.quantity = new_quantity
            variant.save()

            InventoryLog.objects.create(
                variant=variant,
                created_by=user,
                quantity_change=-change,
                new_quantity=new_quantity,
                transaction_type=InventoryLog.TransactionTypes.ADJUSTMENT_OUT,
                total_value=change * variant.purchase_price,
                notes=notes or f"Adjustment Out: {change} units",
                supplier_invoice=supplier_invoice,
            )

    @staticmethod
    def create_initial_log(variant, user=None, notes="", supplier_invoice=None):
        """Create initial log entry for a new variant"""
        try:
            with transaction.atomic():
                inventory_log = InventoryLog.objects.create(
                    variant=variant,
                    created_by=user,
                    quantity_change=variant.quantity,
                    new_quantity=variant.quantity,
                    purchase_price=variant.purchase_price,
                    remaining_quantity=variant.quantity,
                    mrp=variant.mrp,
                    total_value=variant.quantity * variant.purchase_price,
                    transaction_type=InventoryLog.TransactionTypes.INITIAL,
                    notes=notes or f"Initial Stock: {variant.quantity} units",
                    supplier_invoice=supplier_invoice,
                )
                return inventory_log

        except Exception as e:  # pylint: disable=broad-except
            logger.error("Failed to create initial log: %s", e)
            return None

    _SENTINEL = object()

    @staticmethod
    def update_initial_log(variant, user=None, notes="", supplier_invoice=_SENTINEL):
        """Update the initial inventory log entry for a variant"""
        log_data = InventoryLog.objects.filter(
            variant=variant,
            transaction_type=InventoryLog.TransactionTypes.INITIAL,
        ).first()
        if log_data:
            has_other_transactions = InventoryLog.objects.filter(
                variant=variant
            ).exclude(id=log_data.id).exists()

            if not has_other_transactions:
                if variant.quantity >= 0:
                    log_data.quantity_change = variant.quantity
                    log_data.new_quantity = variant.quantity
                    log_data.remaining_quantity = variant.quantity
                    log_data.total_value = variant.quantity * variant.purchase_price
                    log_data.notes = notes or f"Initial Stock: {variant.quantity} units"
                else:
                    # Negative quantity: preserve existing initial log quantity_change
                    if notes:
                        log_data.notes = notes
            else:
                # Stock movements have occurred — if present quantity >= 0, adjust initial quantity calculation
                if variant.quantity >= 0:
                    other_logs = InventoryLog.objects.filter(variant=variant).exclude(id=log_data.id)
                    stock_out_total = Decimal("0")
                    stock_in_total = Decimal("0")
                    for l in other_logs:
                        if l.transaction_type in [
                            InventoryLog.TransactionTypes.SALE,
                            InventoryLog.TransactionTypes.DAMAGE,
                            InventoryLog.TransactionTypes.ADJUSTMENT_OUT,
                        ]:
                            stock_out_total += abs(l.quantity_change)
                        elif l.transaction_type in [
                            InventoryLog.TransactionTypes.STOCK_IN,
                            InventoryLog.TransactionTypes.ADJUSTMENT_IN,
                            InventoryLog.TransactionTypes.RETURN,
                            InventoryLog.TransactionTypes.CANCEL,
                        ]:
                            stock_in_total += abs(l.quantity_change)

                    calculated_initial = variant.quantity + stock_out_total - stock_in_total
                    if calculated_initial >= 0:
                        log_data.quantity_change = calculated_initial
                        allocated = (
                            InventoryLog.objects.filter(source_inventory_log=log_data)
                            .aggregate(total=Sum("allocated_quantity"))["total"]
                            or Decimal("0")
                        )
                        log_data.remaining_quantity = max(calculated_initial - allocated, Decimal("0"))

                log_data.total_value = log_data.quantity_change * variant.purchase_price
                if notes:
                    log_data.notes = notes

            log_data.purchase_price = variant.purchase_price
            log_data.mrp = variant.mrp
            if supplier_invoice is not InventoryService._SENTINEL:
                log_data.supplier_invoice = supplier_invoice
            log_data.created_by = user
            log_data.save()

    @staticmethod
    def update_stock_in_log(
        variant,
        quantity_change,
        user=None,
        notes="",
        supplier_invoice=None,
        purchase_price=None,
        mrp=None,
    ):
        """Update stock in log for a variant"""
        try:
            with transaction.atomic():
                new_quantity = variant.quantity + quantity_change
                variant.quantity = new_quantity

                if purchase_price is not None and purchase_price != variant.purchase_price:
                    variant.purchase_price = purchase_price

                if mrp is not None and mrp != variant.mrp:
                    variant.mrp = mrp

                variant.save()

                inventory_log = InventoryLog.objects.create(
                    variant=variant,
                    supplier_invoice=supplier_invoice,
                    transaction_type=InventoryLog.TransactionTypes.STOCK_IN,
                    created_by=user,
                    quantity_change=quantity_change,
                    remaining_quantity=quantity_change,
                    new_quantity=variant.quantity,
                    total_value=quantity_change
                    * (purchase_price or variant.purchase_price),
                    purchase_price=purchase_price or variant.purchase_price,
                    mrp=mrp or variant.mrp,
                    notes=notes or f"Stock In: {quantity_change} units",
                )

                return inventory_log

        except Exception as e:  # pylint: disable=broad-except
            logger.error("Error updating stock in log: %s", e)
            return None

    @staticmethod
    def sale(variant, quantity_sold, user=None, invoice_item=None, notes=""):
        """Process a sale and automatically update inventory

        Args:
            variant: The variant being sold
            quantity_sold: Amount sold
            user: User performing sale
            invoice_item: Associated invoice item
            notes: Sale notes

        Returns:
            dict: Result of sale process
        """
        with transaction.atomic():
            if quantity_sold <= 0:
                raise ValueError("Sale quantity must be positive")

            # Use selling price from invoice_item if available, otherwise variant's final_price
            unit_price = (
                invoice_item.unit_price if invoice_item else variant.final_price
            )

            # Perform FIFO allocation FIRST
            allocation_result = InventoryService._allocate_fifo(
                variant=variant,
                quantity_to_allocate=quantity_sold,
                invoice_item=invoice_item,
                unit_price=unit_price,
                user=user,
                notes=notes,
            )

            # Update variant quantity AFTER FIFO allocation
            new_quantity = variant.quantity - quantity_sold
            variant.quantity = new_quantity
            variant.save(update_fields=["quantity", "updated_at"])

            return {
                "success": True,
                "quantity_sold": quantity_sold,
                "remaining_stock": new_quantity,
                "total_amount": quantity_sold * unit_price,
                "cogs": allocation_result["total_cogs"],
                "gross_profit": (quantity_sold * unit_price)
                - allocation_result["total_cogs"],
                "allocation_logs": allocation_result["logs"],
                "insufficient_stock_warning": allocation_result.get(
                    "insufficient_stock", False
                ),
            }

    @staticmethod
    def _allocate_fifo(
        variant,
        quantity_to_allocate,
        invoice_item=None,
        unit_price=None,
        user=None,
        notes="",
    ):
        """Internal method to perform FIFO allocation

        Args:
            variant: The product variant to allocate stock from
            quantity_to_allocate: Amount of stock to allocate
            invoice_item: The associated invoice item (optional)
            unit_price: Selling price per unit (optional)
            user: The user performing the action (optional)
            notes: Additional notes for the log (optional)

        Returns:
            dict: Allocation results including logs, COGS, and insufficient stock flag
        """
        remaining_to_allocate = Decimal(str(quantity_to_allocate))
        allocation_logs = []
        total_cogs = Decimal("0")
        insufficient_stock = False

        # Get available stock logs in FIFO order (oldest first)
        available_logs = InventoryLog.objects.filter(
            variant=variant,
            transaction_type__in=[
                InventoryLog.TransactionTypes.STOCK_IN,
                InventoryLog.TransactionTypes.INITIAL,
                InventoryLog.TransactionTypes.RETURN,
            ],
            remaining_quantity__gt=0,
        ).order_by("timestamp")

        # Allocate from available stock logs
        current_variant_quantity = variant.quantity
        updated_logs = []  # Track logs for batch update

        for stock_log in available_logs:
            if remaining_to_allocate <= 0:
                break

            allocatable = min(stock_log.remaining_quantity, remaining_to_allocate)

            new_quantity_after_allocation = current_variant_quantity - allocatable

            sale_log = InventoryLog.objects.create(
                variant=variant,
                transaction_type=InventoryLog.TransactionTypes.SALE,
                quantity_change=-allocatable,
                new_quantity=new_quantity_after_allocation,
                invoice_item=invoice_item,
                selling_price=unit_price,
                source_inventory_log=stock_log,
                allocated_quantity=allocatable,
                purchase_price=stock_log.purchase_price,
                total_value=allocatable * unit_price if unit_price else None,
                supplier_invoice=stock_log.supplier_invoice,
                created_by=user,
                notes=notes
                or f"FIFO Sale: {allocatable} from {stock_log.timestamp.date()}",
            )

            # Track remaining quantity locally instead of F() + refresh_from_db()
            new_remaining = stock_log.remaining_quantity - allocatable
            stock_log.remaining_quantity = new_remaining
            updated_logs.append(stock_log)

            if stock_log.purchase_price:
                total_cogs += allocatable * stock_log.purchase_price

            allocation_logs.append(sale_log)
            remaining_to_allocate -= allocatable
            current_variant_quantity -= allocatable

        # Batch update remaining quantities
        if updated_logs:
            InventoryLog.objects.bulk_update(updated_logs, ["remaining_quantity"])

        # Handle insufficient stock (negative inventory)
        if remaining_to_allocate > 0:
            insufficient_stock = True

            # Create sale log for the unallocated quantity
            sale_log = InventoryLog.objects.create(
                variant=variant,
                transaction_type=InventoryLog.TransactionTypes.SALE,
                quantity_change=-remaining_to_allocate,
                new_quantity=current_variant_quantity
                - remaining_to_allocate,  # Correct final quantity
                invoice_item=invoice_item,
                selling_price=unit_price,
                total_value=remaining_to_allocate * unit_price if unit_price else None,
                created_by=user,
                notes=(
                    f"INSUFFICIENT STOCK: {remaining_to_allocate} units - {notes}"
                    if notes
                    else f"INSUFFICIENT STOCK: {remaining_to_allocate} units"
                ),
            )
            allocation_logs.append(sale_log)

        return {
            "logs": allocation_logs,
            "total_cogs": total_cogs,
            "insufficient_stock": insufficient_stock,
        }

    @staticmethod
    def return_sale(
        variant,
        quantity_returned,
        user=None,
        invoice_item=None,
        notes="",
    ):
        """Process a customer return and restore inventory

        Args:
            variant: The returned variant
            quantity_returned: Amount returned
            user: User processing return
            invoice_item: Associated invoice item
            notes: Return notes

        Returns:
            dict: Return processing results
        """
        with transaction.atomic():
            if quantity_returned <= 0:
                raise ValueError("Return quantity must be positive")

            selling_price = invoice_item.unit_price if invoice_item else variant.final_price

            new_quantity = variant.quantity + quantity_returned
            variant.quantity = new_quantity
            variant.save()

            inventory_log = InventoryLog.objects.filter(
                variant=variant,
                transaction_type=InventoryLog.TransactionTypes.SALE,
                quantity_change__lt=quantity_returned,
                invoice_item=invoice_item,
            ).first()

            supplier_invoice = None
            if inventory_log:
                supplier_invoice = inventory_log.supplier_invoice

            InventoryLog.objects.create(
                variant=variant,
                transaction_type=InventoryLog.TransactionTypes.RETURN,
                quantity_change=quantity_returned,
                invoice_item=invoice_item,
                remaining_quantity=quantity_returned,
                created_by=user,
                new_quantity=new_quantity,
                supplier_invoice=supplier_invoice,
                selling_price=selling_price,
                total_value=quantity_returned * selling_price,
                purchase_price=variant.purchase_price,
                notes=notes
                or f"Customer return: {quantity_returned} units{f' for {invoice_item}' if invoice_item else ''}",
            )

            return {
                "success": True,
                "quantity_returned": quantity_returned,
                "new_stock": new_quantity,
                "refund_amount": quantity_returned * variant.final_price,
            }

    @staticmethod
    def cancelled_sale(
        variant,
        quantity_cancelled,
        user=None,
        invoice_item=None,
        notes="",
    ):
        """Process a customer cancellation and restore inventory

        Args:
            variant: The cancelled variant
            quantity_cancelled: Amount cancelled
            user: User processing cancellation
            invoice_item: Associated invoice item
            notes: Cancellation notes

        Returns:
            dict: Cancellation processing results
        """
        with transaction.atomic():
            if quantity_cancelled <= 0:
                raise ValueError("Return quantity must be positive")

            selling_price = invoice_item.unit_price if invoice_item else variant.final_price

            new_quantity = variant.quantity + quantity_cancelled
            variant.quantity = new_quantity
            variant.save()

            inventory_log = InventoryLog.objects.filter(
                variant=variant,
                transaction_type=InventoryLog.TransactionTypes.SALE,
                quantity_change__lt=quantity_cancelled,
                invoice_item=invoice_item,
            ).first()

            supplier_invoice = None
            if inventory_log:
                supplier_invoice = inventory_log.supplier_invoice

            InventoryLog.objects.create(
                variant=variant,
                transaction_type=InventoryLog.TransactionTypes.CANCEL,
                quantity_change=quantity_cancelled,  # Positive for returns
                invoice_item=invoice_item,
                remaining_quantity=quantity_cancelled,
                created_by=user,
                new_quantity=new_quantity,
                supplier_invoice=supplier_invoice,
                selling_price=selling_price,
                total_value=quantity_cancelled * selling_price,
                purchase_price=variant.purchase_price,
                notes=notes
                or f"Customer cancel: {quantity_cancelled} units{f' for {invoice_item}' if invoice_item else ''}",
            )

            return {
                "success": True,
                "quantity_cancelled": quantity_cancelled,
                "new_stock": new_quantity,
                "refund_amount": quantity_cancelled * variant.final_price,
            }

    @staticmethod
    def damage_log(
        variant,
        quantity_damaged,
        user=None,
        notes="",
        damage_type="General",
        supplier_invoice=None,
    ):
        """Mark items as damaged and move them to damaged inventory"""
        with transaction.atomic():
            if quantity_damaged <= 0:
                raise ValueError("Damaged quantity must be positive")

            if quantity_damaged > variant.quantity:
                raise ValueError(
                    f"Insufficient stock to mark as damaged. Available stock: {variant.quantity}"
                )

            # Move from available to damaged
            variant.quantity -= quantity_damaged
            variant.damaged_quantity += quantity_damaged
            variant.save()

            formatted_notes = f"Marked as damaged: {quantity_damaged} units - {damage_type}. {notes}".strip()

            # Create inventory log
            InventoryLog.objects.create(
                variant=variant,
                created_by=user,
                quantity_change=-quantity_damaged,  # Negative for available stock
                new_quantity=variant.quantity,
                total_value=quantity_damaged * variant.purchase_price,
                transaction_type=InventoryLog.TransactionTypes.DAMAGE,
                supplier_invoice=supplier_invoice,
                notes=formatted_notes,
            )

            # Create pending damage record for lifecycle tracking
            supplier = (
                supplier_invoice.supplier if supplier_invoice else None
            )
            reason = (
                "TRANSIT" if damage_type == "Transit" else
                "WATER" if damage_type == "Water" else
                "GENERAL"
            )
            DamageResolutionService.create_damage_record(
                variant=variant,
                quantity=quantity_damaged,
                user=user,
                reason=reason,
                notes=notes,
                supplier=supplier,
                supplier_invoice=supplier_invoice,
            )

            return {
                "success": True,
                "quantity_damaged": quantity_damaged,
                "remaining_available": variant.quantity,
                "total_damaged": variant.damaged_quantity,
                "damage_type": damage_type,
            }

    @staticmethod
    def get_suggested_supplier_invoices(inventory_log, limit=5):
        """Get suggested supplier invoices for an inventory log scored by weighted probability signals.

        Weights & Signals:
        1. Exact Variant Match (40 pts) / Product Match (25 pts) in candidate Supplier Invoice
        2. Adjacent Log Context (Neighboring Cluster Match: 30 pts for immediate neighbors, 20 pts for +/-5 cluster)
        3. Date Proximity (20 pts for 0-7 days before log, scaling down to 5 pts)
        4. Purchase Price Match (10 pts for matching price)

        Returns list of dicts with score, confidence level, and match reasons.
        """
        import datetime
        from supplier.models import SupplierInvoice

        log_time = inventory_log.timestamp or inventory_log.created_at
        variant = inventory_log.variant
        product = variant.product if variant else None

        min_date = log_time - datetime.timedelta(days=60)
        max_date = log_time + datetime.timedelta(days=7)

        candidates = list(
            SupplierInvoice.objects.filter(
                is_deleted=False,
                invoice_date__range=(min_date, max_date),
            ).select_related("supplier")
        )

        if len(candidates) < limit:
            existing_ids = {inv.id for inv in candidates}
            fallback = list(
                SupplierInvoice.objects.filter(is_deleted=False)
                .exclude(id__in=existing_ids)
                .select_related("supplier")
                .order_by("-invoice_date")[: limit - len(candidates)]
            )
            candidates.extend(fallback)

        # 1. Variant & Product linked invoices map
        variant_linked_invoice_ids = set()
        product_linked_invoice_ids = set()
        if variant:
            from inventory.models import InventoryLog

            variant_linked_invoice_ids = set(
                InventoryLog.objects.filter(
                    variant=variant,
                    supplier_invoice__isnull=False,
                    is_deleted=False,
                ).values_list("supplier_invoice_id", flat=True)
            )
            if product:
                product_linked_invoice_ids = set(
                    InventoryLog.objects.filter(
                        variant__product=product,
                        supplier_invoice__isnull=False,
                        is_deleted=False,
                    ).values_list("supplier_invoice_id", flat=True)
                )

        # 2. Adjacent Log Context (Neighboring cluster)
        from inventory.models import InventoryLog

        adjacent_before = list(
            InventoryLog.objects.filter(
                created_at__lt=log_time,
                is_deleted=False,
            )
            .order_by("-created_at")[:5]
        )
        adjacent_after = list(
            InventoryLog.objects.filter(
                created_at__gt=log_time,
                is_deleted=False,
            )
            .order_by("created_at")[:5]
        )

        adjacent_invoice_dist = {}
        for idx, adj in enumerate(adjacent_before):
            if adj.supplier_invoice_id:
                dist = idx + 1
                if (
                    adj.supplier_invoice_id not in adjacent_invoice_dist
                    or dist < adjacent_invoice_dist[adj.supplier_invoice_id]
                ):
                    adjacent_invoice_dist[adj.supplier_invoice_id] = dist

        for idx, adj in enumerate(adjacent_after):
            if adj.supplier_invoice_id:
                dist = idx + 1
                if (
                    adj.supplier_invoice_id not in adjacent_invoice_dist
                    or dist < adjacent_invoice_dist[adj.supplier_invoice_id]
                ):
                    adjacent_invoice_dist[adj.supplier_invoice_id] = dist

        # Score candidates
        scored_results = []
        for inv in candidates:
            score = 0
            reasons = []

            # 1. Variant / Product score
            if inv.id in variant_linked_invoice_ids:
                score += 40
                reasons.append("Exact product variant exists in invoice")
            elif inv.id in product_linked_invoice_ids:
                score += 25
                if product:
                    reasons.append(f"Product '{product.name}' items exist in invoice")
                else:
                    reasons.append("Product items exist in invoice")

            # 2. Adjacent log score
            if inv.id in adjacent_invoice_dist:
                dist = adjacent_invoice_dist[inv.id]
                if dist == 1:
                    score += 30
                    reasons.append("Immediately adjacent stock log linked to this invoice")
                else:
                    score += 20
                    reasons.append(f"Nearby stock log (distance {dist}) linked to this invoice")

            # 3. Date proximity
            days_diff = (log_time - inv.invoice_date).total_seconds() / 86400.0
            if 0 <= days_diff <= 7:
                score += 20
                reasons.append(f"Invoice dated {int(days_diff)} days before stock log")
            elif 7 < days_diff <= 14:
                score += 15
                reasons.append(f"Invoice dated {int(days_diff)} days before stock log")
            elif 14 < days_diff <= 30:
                score += 10
                reasons.append(f"Invoice dated {int(days_diff)} days before stock log")
            elif 30 < days_diff <= 60 or -7 <= days_diff < 0:
                score += 5
                reasons.append("Invoice dated within 60-day stock log window")
            else:
                score += 2
                reasons.append("Active supplier invoice")

            # 4. Purchase price match
            if inventory_log.purchase_price and inventory_log.purchase_price > 0:
                if variant and variant.purchase_price == inventory_log.purchase_price:
                    score += 10
                    reasons.append(f"Purchase price match ({inventory_log.purchase_price:.2f})")

            confidence_score = min(99 if score < 100 else 100, max(15, score))

            if confidence_score >= 75:
                confidence_level = "HIGH"
            elif confidence_score >= 45:
                confidence_level = "MEDIUM"
            else:
                confidence_level = "LOW"

            scored_results.append({
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "invoice_date": inv.invoice_date.strftime("%d %b %Y"),
                "supplier_name": inv.supplier.name if inv.supplier else "N/A",
                "supplier_contact": inv.supplier.contact_person if inv.supplier and inv.supplier.contact_person else "",
                "supplier_phone": inv.supplier.phone if inv.supplier and inv.supplier.phone else "",
                "supplier_gstin": inv.supplier.gstin if inv.supplier and inv.supplier.gstin else "",
                "sub_total": float(inv.sub_total),
                "total_amount": float(inv.total_amount),
                "confidence_score": int(confidence_score),
                "confidence_level": confidence_level,
                "match_reasons": reasons,
            })

        scored_results.sort(key=lambda x: (x["confidence_score"], x["id"]), reverse=True)
        return scored_results[:limit]

    @staticmethod
    def link_supplier_invoice_and_propagate_fifo(
        inventory_log, supplier_invoice, user=None, purchase_price=None, notes=""
    ):
        """Link supplier invoice to initial/stock-in inventory log and propagate to child logs."""
        with transaction.atomic():
            if inventory_log.transaction_type not in [
                InventoryLog.TransactionTypes.INITIAL,
                InventoryLog.TransactionTypes.STOCK_IN,
            ]:
                raise ValueError(
                    "Can only link supplier invoice to Initial or Stock In logs."
                )

            inventory_log.supplier_invoice = supplier_invoice
            if purchase_price is not None and purchase_price >= 0:
                inventory_log.purchase_price = Decimal(str(purchase_price))
                inventory_log.total_value = (
                    inventory_log.quantity_change * inventory_log.purchase_price
                )

            if notes:
                clean_notes = inventory_log.notes or ""
                inventory_log.notes = (
                    f"{clean_notes} | Linked Invoice #{supplier_invoice.invoice_number}".strip(
                        " |"
                    )
                )

            inventory_log.save()

            # Update purchase price on variant if log is initial or stock-in and price changed
            variant = inventory_log.variant
            if purchase_price is not None and purchase_price > 0:
                variant.purchase_price = Decimal(str(purchase_price))
                variant.save()

            # Propagate supplier invoice & purchase price to directly allocated child SALE and DAMAGE logs
            child_logs = InventoryLog.objects.filter(source_inventory_log=inventory_log)
            child_count = 0
            for child in child_logs:
                child.supplier_invoice = supplier_invoice
                if purchase_price is not None and purchase_price > 0:
                    child.purchase_price = Decimal(str(purchase_price))
                child.save()
                child_count += 1

            # Update DamagedItemRecord if unlinked
            DamagedItemRecord.objects.filter(
                variant=variant, supplier_invoice__isnull=True
            ).update(
                supplier_invoice=supplier_invoice,
                supplier=supplier_invoice.supplier,
            )

            # Re-run FIFO allocation for any unallocated stock-out logs (SALE, DAMAGE, ADJUSTMENT_OUT) of this variant
            unallocated_stock_outs = InventoryLog.objects.filter(
                variant=variant,
                transaction_type__in=[
                    InventoryLog.TransactionTypes.SALE,
                    InventoryLog.TransactionTypes.DAMAGE,
                    InventoryLog.TransactionTypes.ADJUSTMENT_OUT,
                ],
                source_inventory_log__isnull=True,
            )

            reallocated_count = 0
            if unallocated_stock_outs.exists():
                available_logs = InventoryLog.objects.filter(
                    variant=variant,
                    transaction_type__in=[
                        InventoryLog.TransactionTypes.STOCK_IN,
                        InventoryLog.TransactionTypes.INITIAL,
                        InventoryLog.TransactionTypes.RETURN,
                    ],
                    remaining_quantity__gt=0,
                ).order_by("timestamp")

                for stock_out in unallocated_stock_outs:
                    needed = abs(stock_out.quantity_change)
                    for stock_log in available_logs:
                        if needed <= 0 or stock_log.remaining_quantity <= 0:
                            continue
                        allocatable = min(stock_log.remaining_quantity, needed)
                        stock_out.source_inventory_log = stock_log
                        stock_out.supplier_invoice = stock_log.supplier_invoice
                        stock_out.purchase_price = stock_log.purchase_price
                        stock_out.allocated_quantity = allocatable
                        stock_out.save()

                        stock_log.remaining_quantity -= allocatable
                        stock_log.save()
                        reallocated_count += 1
                        needed -= allocatable

            return {
                "success": True,
                "log_id": inventory_log.id,
                "variant_name": variant.full_name,
                "supplier_invoice_number": supplier_invoice.invoice_number,
                "child_logs_updated": child_count,
                "reallocated_sales_count": reallocated_count,
            }


class DamageResolutionService:
    """Service for managing the lifecycle of damaged items."""

    @staticmethod
    def create_damage_record(variant, quantity, user, reason="GENERAL",
                              notes="", supplier=None, supplier_invoice=None):
        with transaction.atomic():
            record = DamagedItemRecord.objects.create(
                variant=variant,
                quantity=quantity,
                reason=reason,
                notes=notes,
                supplier=supplier,
                supplier_invoice=supplier_invoice,
                created_by=user if (user and getattr(user, "is_authenticated", True)) else None,
                status=DamagedItemRecord.Status.PENDING,
            )
            return record

    @staticmethod
    def return_to_supplier(record, supplier, user, notes="",
                            supplier_invoice=None):
        """Return damaged items to supplier by linking supplier/invoice and reducing damaged stock."""
        with transaction.atomic():
            if record.status != DamagedItemRecord.Status.PENDING:
                raise ValueError(f"Cannot return — record is {record.get_status_display()}")

            variant = record.variant
            if record.quantity > variant.damaged_quantity:
                raise ValueError(
                    f"Cannot return {record.quantity} units — only {variant.damaged_quantity} damaged units currently available."
                )

            variant.damaged_quantity -= record.quantity
            variant.save()

            resolved_user = user if (user and getattr(user, "is_authenticated", True)) else None
            record.supplier = supplier or (supplier_invoice.supplier if supplier_invoice else None)
            if supplier_invoice:
                record.supplier_invoice = supplier_invoice
            record.status = DamagedItemRecord.Status.RETURNED
            record.resolved_at = timezone.now()
            record.resolved_by = resolved_user
            record.resolution_notes = notes
            record.save()

            return record

    @staticmethod
    def write_off(record, user, notes=""):
        """Write off damaged items as a loss."""
        with transaction.atomic():
            if record.status != DamagedItemRecord.Status.PENDING:
                raise ValueError(f"Cannot write off — record is {record.get_status_display()}")

            variant = record.variant
            if record.quantity > variant.damaged_quantity:
                raise ValueError(
                    f"Cannot write off {record.quantity} units — only {variant.damaged_quantity} damaged units currently available."
                )

            variant.damaged_quantity -= record.quantity
            variant.save()

            resolved_user = user if (user and getattr(user, "is_authenticated", True)) else None
            record.status = DamagedItemRecord.Status.WRITTEN_OFF
            record.resolved_at = timezone.now()
            record.resolved_by = resolved_user
            record.resolution_notes = notes
            record.save()

            if resolved_user:
                try:
                    from user.models import Transaction as UserTransaction
                    loss = record.quantity * (variant.purchase_price or Decimal("0.01"))
                    UserTransaction.objects.create(
                        user=resolved_user,
                        transaction_type=UserTransaction.TransactionType.EXPENSE,
                        amount=loss,
                        payment_method=UserTransaction.PaymentMethod.OTHER,
                        description=(
                            f"Write-off: {variant.full_name} x{record.quantity}"
                        ),
                    )
                except Exception as e:
                    logger.error("Failed to create expense transaction for write-off: %s", e)

            return record

    @staticmethod
    def repair(record, user, notes="", repair_cost=None):
        """Repair damaged items and restore them to sellable stock with an InventoryLog audit entry."""
        with transaction.atomic():
            if record.status != DamagedItemRecord.Status.PENDING:
                raise ValueError(f"Cannot repair — record is {record.get_status_display()}")

            variant = record.variant
            if record.quantity > variant.damaged_quantity:
                raise ValueError(
                    f"Cannot repair {record.quantity} units — only {variant.damaged_quantity} damaged units currently available."
                )

            variant.damaged_quantity -= record.quantity
            variant.quantity += record.quantity
            variant.save()

            resolved_user = user if (user and getattr(user, "is_authenticated", True)) else None

            # Create inventory log for restored sellable stock
            InventoryLog.objects.create(
                variant=variant,
                created_by=resolved_user,
                quantity_change=record.quantity,
                new_quantity=variant.quantity,
                purchase_price=variant.purchase_price,
                total_value=record.quantity * variant.purchase_price,
                transaction_type=InventoryLog.TransactionTypes.ADJUSTMENT_IN,
                notes=f"Repaired & restored from damaged stock (Record #{record.id}). {notes}".strip(),
            )

            record.status = DamagedItemRecord.Status.REPAIRED
            record.resolved_at = timezone.now()
            record.resolved_by = resolved_user
            record.resolution_notes = notes
            if repair_cost is not None:
                record.repair_cost = repair_cost
            record.save()

            if repair_cost and repair_cost > 0 and resolved_user:
                try:
                    from user.models import Transaction as UserTransaction
                    UserTransaction.objects.create(
                        user=resolved_user,
                        transaction_type=UserTransaction.TransactionType.EXPENSE,
                        amount=repair_cost,
                        payment_method=UserTransaction.PaymentMethod.OTHER,
                        description=(
                            f"Repair cost: {variant.full_name} x{record.quantity}"
                        ),
                    )
                except Exception as e:
                    logger.error("Failed to create expense transaction for repair cost: %s", e)

            return record

    @staticmethod
    def suggest_resolution(variant):
        if variant.damaged_quantity <= 0:
            return []

        price = variant.purchase_price or variant.mrp or Decimal("0")
        total_qty = variant.quantity + variant.damaged_quantity
        damage_pct = (variant.damaged_quantity / total_qty * 100) if total_qty > 0 else 0

        suggestions = []

        if price > 500 and damage_pct < 50:
            suggestions.append({
                "action": "return_supplier",
                "priority": 1,
                "reasoning": (
                    f"High value item ({price:,.0f}) with "
                    f"{damage_pct:.0f}% damage — "
                    "supplier may accept return for credit."
                ),
                "financial_impact": (
                    f"Potential credit: "
                    f"{variant.damaged_quantity * price:,.0f}"
                ),
            })

        if price > 200 and damage_pct < 70:
            suggestions.append({
                "action": "repair",
                "priority": 2,
                "reasoning": (
                    f"Item at {price:,.0f} with {damage_pct:.0f}% damage — "
                    "repair may be cost-effective."
                ),
                "financial_impact": (
                    f"Restore {variant.damaged_quantity} units to sellable stock."
                ),
            })

        suggestions.append({
            "action": "write_off",
            "priority": 3,
            "reasoning": (
                "Low value or heavily damaged — most practical to "
                "write off as loss."
            ),
            "financial_impact": (
                f"Loss: "
                f"{variant.damaged_quantity * (price or Decimal('0.01')):,.0f}"
            ),
        })

        return sorted(suggestions, key=lambda s: s["priority"])

    @staticmethod
    def get_filtered_damaged_records(params):
        """Filter DamagedItemRecord queryset based on query parameters.

        Args:
            params: dict-like object (e.g. request.GET, request.POST, or dict)
                Supported keys:
                    - status: PENDING, RETURNED, REPAIRED, WRITTEN_OFF, ALL (default: PENDING)
                    - search: string to search across variant, brand, barcode, supplier, area, invoice
                    - supplier: supplier ID
                    - area: supplier city / area name

        Returns:
            QuerySet of DamagedItemRecord.
        """
        from base.utility import build_search_filter
        from inventory.models import DamagedItemRecord

        status_filter = str(params.get("status", "PENDING") or "").strip()
        search_query = str(params.get("search", "") or "").strip()
        supplier_filter = str(params.get("supplier", "") or "").strip()
        area_filter = str(params.get("area", "") or "").strip()

        records = (
            DamagedItemRecord.objects.filter(is_deleted=False)
            .select_related(
                "variant",
                "variant__product",
                "variant__product__category",
                "variant__size",
                "variant__color",
                "supplier",
                "supplier_invoice",
            )
        )

        if status_filter and status_filter != "ALL":
            records = records.filter(status=status_filter)

        if search_query:
            filters = build_search_filter(
                search_query,
                [
                    "variant__product__brand",
                    "variant__product__name",
                    "variant__barcode",
                    "supplier__name",
                    "supplier__city",
                    "supplier_invoice__invoice_number",
                ],
            )
            records = records.filter(filters)

        if supplier_filter and supplier_filter.isdigit():
            records = records.filter(supplier_id=int(supplier_filter))

        if area_filter:
            records = records.filter(supplier__city__iexact=area_filter)

        return records

    @staticmethod
    def get_grouped_damaged_stock(params):
        """Prepare grouped damaged stock data structured by shop name (supplier).

        Organizes records by Shop Name (Supplier), invoice number, date,
        and computes line amounts, shop subtotals, and grand totals.

        Args:
            params: dict-like object with filter criteria.

        Returns:
            dict containing:
                - groups: list of shop group dictionaries
                - overall_total_units: Decimal
                - overall_total_amount: Decimal
                - total_shops: int
                - total_records: int
                - active_filters: dict
        """
        from collections import OrderedDict

        records = DamageResolutionService.get_filtered_damaged_records(params)
        records = records.order_by(
            "supplier__name",
            "supplier_invoice__invoice_number",
            "-created_at",
        )

        groups_map = OrderedDict()
        overall_total_units = Decimal("0")
        overall_total_amount = Decimal("0.00")
        total_records = 0

        for record in records:
            total_records += 1
            supplier = record.supplier
            shop_key = supplier.id if supplier else None

            if shop_key not in groups_map:
                groups_map[shop_key] = {
                    "supplier": supplier,
                    "shop_name": supplier.name if supplier else "Unassigned / Direct",
                    "area": supplier.city if supplier and supplier.city else "—",
                    "phone": supplier.phone if supplier and supplier.phone else "—",
                    "items": [],
                    "subtotal_quantity": Decimal("0"),
                    "subtotal_amount": Decimal("0.00"),
                }

            qty = record.quantity or Decimal("0")
            price = (
                record.variant.purchase_price
                if (record.variant and record.variant.purchase_price)
                else Decimal("0.00")
            )
            item_amount = (qty * price).quantize(Decimal("0.01"))

            invoice_num = (
                record.supplier_invoice.invoice_number
                if record.supplier_invoice
                else "—"
            )
            invoice_dt = (
                record.supplier_invoice.invoice_date
                if record.supplier_invoice
                else record.created_at
            )

            item_data = {
                "record": record,
                "invoice_number": invoice_num,
                "invoice_date": invoice_dt,
                "variant_name": record.variant.full_name if record.variant else "Unknown",
                "barcode": record.variant.barcode if record.variant else "—",
                "quantity": qty,
                "purchase_price": price,
                "amount": item_amount,
                "reason": record.get_reason_display(),
                "status": record.get_status_display(),
                "notes": record.notes or "",
            }

            groups_map[shop_key]["items"].append(item_data)
            groups_map[shop_key]["subtotal_quantity"] += qty
            groups_map[shop_key]["subtotal_amount"] += item_amount

            overall_total_units += qty
            overall_total_amount += item_amount

        active_filters = {
            "status": str(params.get("status", "PENDING") or "").strip(),
            "search": str(params.get("search", "") or "").strip(),
            "supplier": str(params.get("supplier", "") or "").strip(),
            "area": str(params.get("area", "") or "").strip(),
        }

        return {
            "groups": list(groups_map.values()),
            "overall_total_units": overall_total_units,
            "overall_total_amount": overall_total_amount,
            "total_shops": len(groups_map),
            "total_records": total_records,
            "active_filters": active_filters,
        }


class BulkUploadService:
    """Service class for BulkUpload batch and item operations."""

    REQUIRED_CSV_FIELDS = ["brand", "name"]

    @staticmethod
    def fuzzy_match(value, model, field="name", threshold=80, cache=None):
        """Find the best fuzzy match for a value against a model field.

        Returns (matched_instance, confidence, nearby_candidates).
        """
        if not value or not value.strip():
            return None, 0, []

        value = value.strip()
        query_key = (model, field, "query", value.lower())
        if cache is not None and query_key in cache:
            return cache[query_key]

        cache_key = (model, field)
        exact_cache_key = (model, field, "exact_map")
        choices_cache_key = (model, field, "choices_list")

        if cache is not None and cache_key in cache:
            instances = cache[cache_key]
            exact_map = cache[exact_cache_key]
            choices_list = cache.get(choices_cache_key)
        else:
            instances = list(model.objects.filter(**{f"{field}__isnull": False}))
            exact_map = {getattr(inst, field, "").strip().lower(): inst for inst in instances if getattr(inst, field, None)}
            choices_list = [getattr(inst, field, "") for inst in instances if getattr(inst, field, None)]
            if cache is not None:
                cache[cache_key] = instances
                cache[exact_cache_key] = exact_map
                cache[choices_cache_key] = choices_list

        # Fast O(1) exact match check
        exact_inst = exact_map.get(value.lower())
        if exact_inst:
            res = (exact_inst, 100, [])
            if cache is not None:
                cache[query_key] = res
            return res

        # Fuzzy match check
        if process is None or not instances:
            res = (None, 0, [])
            if cache is not None:
                cache[query_key] = res
            return res

        if choices_list is None:
            choices_list = [getattr(inst, field, "") for inst in instances if getattr(inst, field, None)]

        matches = process.extract(value, choices_list, limit=5, scorer=fuzz.token_sort_ratio)
        nearby = [{"name": m[0], "score": m[1]} for m in matches if m[1] >= 60]

        best_match = matches[0] if matches else None
        if best_match and best_match[1] >= threshold:
            for inst in instances:
                if getattr(inst, field, "") == best_match[0]:
                    res = (inst, best_match[1], nearby)
                    if cache is not None:
                        cache[query_key] = res
                    return res

        res = (None, 0, nearby)
        if cache is not None:
            cache[query_key] = res
        return res

    @classmethod
    def process_csv_import(cls, batch, csv_file):
        """Parse CSV file, create BulkUploadItem records with fuzzy-matched FK lookups."""
        try:
            if hasattr(csv_file, "seek"):
                try:
                    csv_file.seek(0)
                except Exception:
                    pass

            raw_content = csv_file.read()
            if not raw_content:
                return {
                    "success": False,
                    "total_rows": 0,
                    "rows_created": 0,
                    "errors": ["The uploaded file is empty."],
                    "matches": [],
                    "message": "The uploaded CSV file is empty.",
                }

            decoded = None
            for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                try:
                    decoded = raw_content.decode(encoding)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue

            if decoded is None:
                decoded = raw_content.decode("latin-1", errors="replace")

        except Exception as e:
            return {
                "success": False,
                "total_rows": 0,
                "rows_created": 0,
                "errors": [f"Could not read CSV file: {str(e)}"],
                "matches": [],
                "message": f"Could not read CSV file: {str(e)}",
            }

        reader = csv.DictReader(io.StringIO(decoded))
        if not reader.fieldnames:
            return {
                "success": False,
                "total_rows": 0,
                "rows_created": 0,
                "errors": ["CSV file has no headers or is empty."],
                "matches": [],
                "message": "CSV file has no headers.",
            }

        headers_lower = [h.strip().lower() for h in reader.fieldnames if h and isinstance(h, str)]
        missing = [f for f in cls.REQUIRED_CSV_FIELDS if f not in headers_lower]
        if missing:
            return {
                "success": False,
                "total_rows": 0,
                "rows_created": 0,
                "errors": [f"Missing required columns in CSV header: {', '.join(missing)}"],
                "matches": [],
                "message": f"Missing required columns: {', '.join(missing)}",
            }

        rows_created = 0
        total_rows = 0
        errors = []
        matches_log = []
        max_order = batch.items.aggregate(models.Max("sort_order"))["sort_order__max"]
        sort_order = max_order if max_order is not None else 0
        fuzzy_cache = {}
        items_to_create = []

        with transaction.atomic():
            for row_num, row in enumerate(reader, start=2):
                try:
                    normalized = {
                        key.strip().lower(): str(val or "").strip()
                        for key, val in row.items()
                        if key and isinstance(key, str)
                    }

                    # Skip empty rows (e.g. blank lines at bottom of CSV)
                    if not any(val for val in normalized.values()):
                        continue

                    total_rows += 1

                    brand = normalized.get("brand", "")
                    name = normalized.get("name", "")
                    if not brand or not name:
                        errors.append(f"Row {row_num}: 'brand' and 'name' are required fields.")
                        continue

                    category, _, _ = cls.fuzzy_match(
                        normalized.get("category", ""), Category, "name", threshold=80, cache=fuzzy_cache
                    )
                    cloth_type, _, _ = cls.fuzzy_match(
                        normalized.get("cloth_type", ""), ClothType, "name", threshold=80, cache=fuzzy_cache
                    )
                    uom, _, _ = cls.fuzzy_match(
                        normalized.get("uom", ""), UOM, "name", threshold=80, cache=fuzzy_cache
                    )
                    hsn_code, _, _ = cls.fuzzy_match(
                        normalized.get("hsn_code", ""), GSTHsnCode, "code", threshold=90, cache=fuzzy_cache
                    )
                    size, _, _ = cls.fuzzy_match(
                        normalized.get("size", ""), Size, "name", threshold=80, cache=fuzzy_cache
                    )
                    color, _, _ = cls.fuzzy_match(
                        normalized.get("color", ""), Color, "name", threshold=80, cache=fuzzy_cache
                    )

                    if category and normalized.get("category"):
                        matches_log.append(f"Row {row_num}: auto-matched Category '{normalized.get('category')}' → '{category.name}'")
                    if cloth_type and normalized.get("cloth_type"):
                        matches_log.append(f"Row {row_num}: auto-matched Cloth Type '{normalized.get('cloth_type')}' → '{cloth_type.name}'")
                    if uom and normalized.get("uom"):
                        matches_log.append(f"Row {row_num}: auto-matched UOM '{normalized.get('uom')}' → '{uom.name}'")
                    if hsn_code and normalized.get("hsn_code"):
                        matches_log.append(f"Row {row_num}: auto-matched HSN '{normalized.get('hsn_code')}' → '{hsn_code.code}'")
                    if size and normalized.get("size"):
                        matches_log.append(f"Row {row_num}: auto-matched Size '{normalized.get('size')}' → '{size.name}'")
                    if color and normalized.get("color"):
                        matches_log.append(f"Row {row_num}: auto-matched Color '{normalized.get('color')}' → '{color.name}'")

                    def parse_decimal(val, default="0"):
                        if val is None or val == "":
                            return Decimal(default)
                        cleaned = re.sub(r"[^\d.-]", "", str(val))
                        if not cleaned or cleaned in (".", "-"):
                            return Decimal(default)
                        try:
                            return Decimal(cleaned)
                        except (InvalidOperation, TypeError, ValueError):
                            return Decimal(default)

                    sort_order += 1
                    items_to_create.append(
                        BulkUploadItem(
                            bulk_upload=batch,
                            brand=brand,
                            name=name,
                            description=normalized.get("description", ""),
                            category=category,
                            cloth_type=cloth_type,
                            uom=uom,
                            hsn_code=hsn_code,
                            size=size,
                            color=color,
                            quantity=parse_decimal(normalized.get("quantity"), "1"),
                            minimum_quantity=parse_decimal(normalized.get("minimum_quantity"), "0"),
                            purchase_price=parse_decimal(normalized.get("purchase_price"), "0"),
                            mrp=parse_decimal(normalized.get("mrp"), "0"),
                            discount_percentage=parse_decimal(normalized.get("discount_percentage"), "0"),
                            commission_percentage=parse_decimal(normalized.get("commission_percentage"), "0"),
                            sort_order=sort_order,
                        )
                    )
                    rows_created += 1

                except Exception as e:
                    logger.exception("Error processing row %d", row_num)
                    errors.append(f"Row {row_num}: {str(e)}")

            if items_to_create:
                BulkUploadItem.objects.bulk_create(items_to_create, batch_size=500)

        if total_rows == 0:
            return {
                "success": False,
                "total_rows": 0,
                "rows_created": 0,
                "errors": ["CSV file contains no data rows."],
                "matches": [],
                "message": "CSV file contains no data rows.",
            }

        total_errors_count = len(errors)
        total_matches_count = len(matches_log)

        # Cap detailed log lists to prevent DOM memory exhaustion on large CSVs
        MAX_LOG_ITEMS = 250
        capped_errors = list(errors[:MAX_LOG_ITEMS])
        if total_errors_count > MAX_LOG_ITEMS:
            capped_errors.append(f"... and {total_errors_count - MAX_LOG_ITEMS} more error(s).")

        capped_matches = list(matches_log[:MAX_LOG_ITEMS])
        if total_matches_count > MAX_LOG_ITEMS:
            capped_matches.append(f"... and {total_matches_count - MAX_LOG_ITEMS} more auto-match(es).")

        if rows_created == 0 and errors:
            return {
                "success": False,
                "total_rows": total_rows,
                "rows_created": 0,
                "errors": capped_errors,
                "matches": capped_matches,
                "errors_count": total_errors_count,
                "matches_count": total_matches_count,
                "message": f"Failed to import items. All {total_rows} row(s) had errors.",
            }

        return {
            "success": True,
            "total_rows": total_rows,
            "rows_created": rows_created,
            "errors": capped_errors,
            "matches": capped_matches,
            "errors_count": total_errors_count,
            "matches_count": total_matches_count,
            "message": f"Imported {rows_created} of {total_rows} items from CSV." + (
                f" ({total_errors_count} error{'s' if total_errors_count > 1 else ''})" if total_errors_count else ""
            ),
        }

    @staticmethod
    def update_item(item, data):
        """Update fields and FK lookups on a BulkUploadItem."""
        updatable_fields = {
            "brand": str, "name": str, "quantity": Decimal,
            "minimum_quantity": Decimal, "purchase_price": Decimal,
            "mrp": Decimal, "discount_percentage": Decimal,
            "commission_percentage": Decimal, "description": str,
        }

        for field, converter in updatable_fields.items():
            if field in data:
                try:
                    val = data[field]
                    if val is not None and val != "":
                        if converter is Decimal:
                            cleaned = re.sub(r"[^\d.-]", "", str(val))
                            if cleaned and cleaned not in (".", "-"):
                                setattr(item, field, Decimal(cleaned))
                        else:
                            setattr(item, field, converter(val))
                except (ValueError, InvalidOperation, TypeError):
                    pass

        fk_map = {
            "product": Product,
            "variant": ProductVariant,
            "category": Category,
            "cloth_type": ClothType,
            "uom": UOM,
            "hsn_code": GSTHsnCode,
            "size": Size,
            "color": Color,
        }
        for field, model_cls in fk_map.items():
            if field in data:
                val = data[field]
                if val:
                    try:
                        instance = model_cls.objects.get(pk=int(val))
                        setattr(item, field, instance)
                    except (ValueError, model_cls.DoesNotExist):
                        setattr(item, field, None)
                else:
                    setattr(item, field, None)

        item.save()
        return {
            "success": True,
            "message": "Item updated.",
            "line_total": str(item.line_total),
        }

    @classmethod
    def delete_item(cls, item):
        """Delete a BulkUploadItem and recalculate parent batch completion status."""
        batch = item.bulk_upload
        item.delete()
        all_committed = cls.recalculate_batch_status(batch)

        return {
            "success": True,
            "message": "Item deleted.",
            "batch_completed": all_committed,
            "batch_status": batch.get_status_display(),
        }

    @staticmethod
    def recalculate_batch_status(batch):
        """Recalculate parent batch status based on remaining items."""
        all_items = batch.items.filter(is_deleted=False)
        all_committed = all_items.exists() and not all_items.filter(status=BulkUploadItem.ItemStatus.DRAFT).exists()

        if all_committed and batch.status != BulkUpload.BatchStatus.COMMITTED:
            batch.status = BulkUpload.BatchStatus.COMMITTED
            batch.save()
        elif not all_committed and batch.status == BulkUpload.BatchStatus.COMMITTED:
            batch.status = BulkUpload.BatchStatus.DRAFT
            batch.save()

        return all_committed

    @classmethod
    def commit_item(cls, item, user, data=None):
        """Commit a single BulkUploadItem to inventory (Product & ProductVariant)."""
        batch = item.bulk_upload

        if data and isinstance(data, dict):
            updatable = ["brand", "name", "description"]
            for f in updatable:
                if f in data and data[f] is not None:
                    setattr(item, f, str(data[f]).strip())
            for f in ["quantity", "minimum_quantity", "purchase_price", "mrp", "discount_percentage", "commission_percentage"]:
                if f in data and data[f] is not None and data[f] != "":
                    try:
                        cleaned = re.sub(r"[^\d.-]", "", str(data[f]))
                        if cleaned and cleaned not in (".", "-"):
                            setattr(item, f, Decimal(cleaned))
                    except (InvalidOperation, TypeError, ValueError):
                        pass
            fk_map = {
                "product": Product, "variant": ProductVariant, "category": Category,
                "cloth_type": ClothType, "uom": UOM, "hsn_code": GSTHsnCode,
                "size": Size, "color": Color,
            }
            for field, model_cls in fk_map.items():
                if field in data:
                    val = data[field]
                    if val:
                        try:
                            setattr(item, field, model_cls.objects.get(pk=int(val)))
                        except (ValueError, model_cls.DoesNotExist):
                            pass
            item.save()

        try:
            with transaction.atomic():
                # 1. Product creation or lookup
                product = item.product
                if not product and item.brand and item.name:
                    product = Product.objects.filter(
                        brand__iexact=item.brand.strip(),
                        name__iexact=item.name.strip(),
                        is_deleted=False,
                    ).first()

                if not product:
                    if not item.brand or not item.name:
                        return {
                            "success": False,
                            "message": "Brand and Product Name are required to create a Product.",
                        }
                    if not item.hsn_code:
                        return {
                            "success": False,
                            "message": "HSN Code is required to create a Product.",
                        }

                    product = Product.objects.create(
                        brand=item.brand.strip(),
                        name=item.name.strip(),
                        description=item.description,
                        category=item.category,
                        cloth_type=item.cloth_type,
                        uom=item.uom,
                        hsn_code=item.hsn_code,
                    )
                else:
                    updated = False
                    if item.category and not product.category:
                        product.category = item.category
                        updated = True
                    if item.cloth_type and not product.cloth_type:
                        product.cloth_type = item.cloth_type
                        updated = True
                    if item.uom and not product.uom:
                        product.uom = item.uom
                        updated = True
                    if item.hsn_code and not product.hsn_code:
                        product.hsn_code = item.hsn_code
                        updated = True
                    if updated:
                        product.save()

                # 2. ProductVariant creation or lookup
                variant = item.variant
                if not variant:
                    variant = ProductVariant.objects.filter(
                        product=product,
                        size=item.size,
                        color=item.color,
                        is_deleted=False,
                    ).first()

                if not variant:
                    variant = ProductVariant.objects.create(
                        product=product,
                        size=item.size,
                        color=item.color,
                        quantity=item.quantity,
                        minimum_quantity=item.minimum_quantity,
                        purchase_price=item.purchase_price,
                        mrp=item.mrp,
                        discount_percentage=item.discount_percentage,
                        commission_percentage=item.commission_percentage or Decimal("0"),
                        created_by=user,
                    )
                    variant.create_barcode(save=True)
                    InventoryService.create_initial_log(
                        variant,
                        user,
                        f"Bulk upload batch #{batch.id}",
                        batch.supplier_invoice,
                    )
                else:
                    if item.quantity > 0:
                        InventoryService.update_stock_in_log(
                            variant=variant,
                            quantity_change=item.quantity,
                            user=user,
                            notes=f"Bulk upload batch #{batch.id}",
                            supplier_invoice=batch.supplier_invoice,
                            purchase_price=item.purchase_price,
                            mrp=item.mrp,
                        )
                    else:
                        variant.purchase_price = item.purchase_price
                        variant.mrp = item.mrp
                        variant.discount_percentage = item.discount_percentage
                        if item.commission_percentage:
                            variant.commission_percentage = item.commission_percentage
                        variant.save()

                # Link back to item and mark status as COMMITTED
                item.product = product
                item.variant = variant
                item.status = BulkUploadItem.ItemStatus.COMMITTED
                item.save()

                all_committed = cls.recalculate_batch_status(batch)

            variant_url = reverse("inventory_variant:details", kwargs={"variant_id": variant.id})
            barcode_url = reverse("report:barcode", kwargs={"pk": variant.id})
            return {
                "success": True,
                "message": f"Saved to Product '{product.display_name}' and Variant ({variant.barcode})!",
                "product_id": product.id,
                "product_name": product.display_name,
                "variant_id": variant.id,
                "variant_url": variant_url,
                "barcode": variant.barcode,
                "barcode_url": barcode_url,
                "batch_completed": all_committed,
                "batch_status": batch.get_status_display(),
            }

        except Exception as e:
            logger.exception("Error committing BulkUploadItem %s", item.id)
            return {"success": False, "message": f"Error saving to Product/Variant: {str(e)}"}

    @classmethod
    def commit_all_items(cls, batch, user):
        """Commit all uncommitted items in a batch to inventory in a single transaction."""
        uncommitted_items = list(batch.items.filter(is_deleted=False, status=BulkUploadItem.ItemStatus.DRAFT))
        if not uncommitted_items:
            return {
                "success": False,
                "message": "No uncommitted items found in this batch.",
                "committed_count": 0,
            }

        committed_count = 0
        errors = []
        with transaction.atomic():
            for item in uncommitted_items:
                res = cls.commit_item(item, user)
                if res.get("success"):
                    committed_count += 1
                else:
                    errors.append(f"Item #{item.id}: {res.get('message')}")

            all_committed = cls.recalculate_batch_status(batch)

        return {
            "success": True,
            "message": f"Successfully committed {committed_count} items to inventory." + (
                f" {len(errors)} items had errors." if errors else ""
            ),
            "committed_count": committed_count,
            "errors": errors,
            "batch_completed": all_committed,
            "batch_status": batch.get_status_display(),
        }

    @classmethod
    def delete_uncommitted_items(cls, batch):
        """Delete all uncommitted items from a batch."""
        uncommitted_items = batch.items.filter(is_deleted=False, status=BulkUploadItem.ItemStatus.DRAFT)
        count = uncommitted_items.count()
        if count == 0:
            return {
                "success": False,
                "message": "No uncommitted items found to delete.",
                "deleted_count": 0,
            }

        with transaction.atomic():
            uncommitted_items.delete()
            all_committed = cls.recalculate_batch_status(batch)

        return {
            "success": True,
            "message": f"Deleted {count} uncommitted items from batch.",
            "deleted_count": count,
            "batch_completed": all_committed,
            "batch_status": batch.get_status_display(),
        }


VALID_SORT_FIELDS = {
    "id",
    "barcode",
    "product__brand",
    "product__name",
    "product__category__name",
    "size__name",
    "color__name",
    "quantity",
    "mrp",
    "purchase_price",
    "commission_percentage",
    "discount_percentage",
    "status",
    "created_at",
}


def total_inventory_value(request=None) -> Decimal:
    """Calculate total inventory value across all active variants."""
    total_value = ProductVariant.objects.aggregate(
        total_value=Sum(
            F("quantity") * F("purchase_price"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
    )
    return total_value["total_value"]


def get_variants_data(request=None, params=None):
    """Retrieve and filter variants based on request or parameter dictionary."""
    if params is None:
        if hasattr(request, "GET"):
            params = request.GET
        elif isinstance(request, dict):
            params = request
            request = None
        else:
            params = {}

    # Get search and filter parameters
    search_query = params.get("search", "")
    category_filter = params.get("category", "")
    color_filter = params.get("color", "")
    size_filter = params.get("size", "")
    status_filter = params.get("status", "")
    stock_filter = params.get("stock", "")
    min_price = params.get("min_price", "")
    max_price = params.get("max_price", "")
    discount_type = params.get("discount_type", "percent")
    min_discount = params.get("min_discount", "")
    max_discount = params.get("max_discount", "")
    discount_only = params.get("discount_only", "")

    # Apply search filter
    filters = build_search_filter(
        search_query,
        [
            "product__brand",
            "product__name",
            "barcode",
            "product__description",
            "product__category__name",
            "size__name",
            "color__name",
            "mrp",
            "purchase_price",
        ],
    )

    # Apply category filter (supports both ID and name search)
    if category_filter:
        try:
            category_id = int(category_filter)
            filters &= Q(product__category_id=category_id)
        except ValueError:
            filters &= Q(product__category__name__icontains=category_filter)

    # Apply color filter (supports both ID and name search)
    if color_filter:
        try:
            color_id = int(color_filter)
            filters &= Q(color_id=color_id)
        except ValueError:
            filters &= Q(color__name__icontains=color_filter)

    # Apply size filter (supports both ID and name search)
    if size_filter:
        try:
            size_id = int(size_filter)
            filters &= Q(size_id=size_id)
        except ValueError:
            filters &= Q(size__name__icontains=size_filter)

    # Apply status filter
    if status_filter:
        filters &= Q(status=status_filter)

    # Apply stock filter
    if stock_filter == "in_stock":
        filters &= Q(quantity__gt=0)
    elif stock_filter == "out_of_stock":
        filters &= Q(quantity=0)
    elif stock_filter == "low_stock":
        filters &= Q(quantity__lte=F("minimum_quantity"), quantity__gt=0)

    # Apply price range filters (MRP)
    if min_price:
        try:
            filters &= Q(mrp__gte=Decimal(str(min_price).strip()))
        except (InvalidOperation, ValueError):
            pass

    if max_price:
        try:
            filters &= Q(mrp__lte=Decimal(str(max_price).strip()))
        except (InvalidOperation, ValueError):
            pass

    # Apply discounted only filter
    if discount_only in ("true", "1", "on", True):
        filters &= Q(discount_percentage__gt=0)

    # Apply discount filters (percent or amount)
    needs_discount_amount = False
    if discount_type == "amount":
        if min_discount:
            try:
                filters &= Q(discount_amount__gte=Decimal(str(min_discount).strip()))
                needs_discount_amount = True
            except (InvalidOperation, ValueError):
                pass
        if max_discount:
            try:
                filters &= Q(discount_amount__lte=Decimal(str(max_discount).strip()))
                needs_discount_amount = True
            except (InvalidOperation, ValueError):
                pass
    else:
        if min_discount:
            try:
                filters &= Q(discount_percentage__gte=Decimal(str(min_discount).strip()))
            except (InvalidOperation, ValueError):
                pass
        if max_discount:
            try:
                filters &= Q(discount_percentage__lte=Decimal(str(max_discount).strip()))
            except (InvalidOperation, ValueError):
                pass

    variants = ProductVariant.objects.select_related(
        "product", "product__category", "size", "color"
    )
    if needs_discount_amount:
        variants = variants.annotate(
            discount_amount=ExpressionWrapper(
                F("mrp") * F("discount_percentage") / Decimal("100"),
                output_field=DecimalField(max_digits=10, decimal_places=2),
            )
        )
    variants = variants.filter(filters)

    # Apply sorting
    if request is not None and hasattr(request, "GET"):
        valid_sorts = table_sorting(request, VALID_SORT_FIELDS, "-created_at")
        variants = variants.order_by(*valid_sorts)
    else:
        sort_param = params.get("sort", "")
        if sort_param:
            sort_fields = [f.strip() for f in sort_param.split(",") if f.strip()]
            final_sorts = [f for f in sort_fields if f.lstrip("-") in VALID_SORT_FIELDS]
            variants = variants.order_by(*(final_sorts or ["-created_at"]))
        else:
            variants = variants.order_by("-created_at")

    return variants


MEDIA_GALLERY_SEARCH_FIELDS = [
    "variant__product__brand",
    "variant__product__name",
    "variant__color__name",
    "variant__size__name",
    "variant__product__cloth_type__name",
    "variant__barcode",
    "variant__extra_attributes",
]


def get_media_gallery_stats() -> dict:
    """
    Compute aggregate metrics across photographed garment variants, active categories,
    and stock health for the media gallery hub.
    """
    active_media = VariantMedia.objects.filter(
        variant__is_deleted=False,
        variant__status=ProductVariant.VariantStatus.ACTIVE,
    )

    total_media = active_media.count()
    images_count = active_media.filter(media_type=VariantMedia.MediaType.IMAGE).count()
    videos_count = active_media.filter(media_type=VariantMedia.MediaType.VIDEO).count()
    variants_count = active_media.values("variant_id").distinct().count()

    low_stock_count = active_media.filter(
        variant__quantity__lte=5, variant__quantity__gt=0
    ).values("variant_id").distinct().count()
    out_of_stock_count = active_media.filter(
        variant__quantity=0
    ).values("variant_id").distinct().count()
    in_stock_count = active_media.filter(
        variant__quantity__gt=5
    ).values("variant_id").distinct().count()

    on_sale_count = active_media.filter(
        variant__discount_percentage__gt=0
    ).values("variant_id").distinct().count()

    in_stock_pct = round((in_stock_count / variants_count * 100)) if variants_count else 0

    categories = list(
        active_media.filter(variant__product__category__isnull=False)
        .values(
            cat_id=F("variant__product__category__id"),
            cat_name=F("variant__product__category__name"),
        )
        .annotate(media_count=Count("id"))
        .order_by("cat_name")
    )

    stats = {
        "total_media": total_media,
        "images_count": images_count,
        "videos_count": videos_count,
        "variants_count": variants_count,
        "in_stock_count": in_stock_count,
        "in_stock_pct": in_stock_pct,
        "low_stock_count": low_stock_count,
        "out_of_stock_count": out_of_stock_count,
        "on_sale_count": on_sale_count,
    }

    return {
        "stats": stats,
        "categories": categories,
    }


def get_media_gallery_data(request=None, params=None):
    """
    Retrieve and filter VariantMedia based on request or parameter dictionary.

    Supports:
        - search: text query across brand, name, color, size, cloth_type, barcode, extra_attributes
        - category: category id or 'all'
        - stock: 'in_stock', 'low_stock', 'out_of_stock', or 'all'
        - media_type: 'IMAGE', 'VIDEO', or 'all'
        - on_sale: '1' or 'true' for discounted items
        - sort: 'newest', 'price_asc', 'price_desc', 'discount_desc', 'stock_desc', 'name_asc'
    """
    if params is None:
        if hasattr(request, "GET"):
            params = request.GET
        elif isinstance(request, dict):
            params = request
            request = None
        else:
            params = {}

    search_query = params.get("search", "").strip()
    category_id = params.get("category", "").strip()
    stock_filter = params.get("stock", "").strip()
    media_type = params.get("media_type", "").strip()
    on_sale = params.get("on_sale", "").strip()
    sort_key = params.get("sort", "newest").strip()

    media_qs = VariantMedia.objects.filter(
        variant__is_deleted=False,
        variant__status=ProductVariant.VariantStatus.ACTIVE,
    ).select_related(
        "variant__product__category",
        "variant__product__cloth_type",
        "variant__color",
        "variant__size",
    )

    if search_query:
        search_filter = build_search_filter(
            search_query,
            MEDIA_GALLERY_SEARCH_FIELDS,
        )
        media_qs = media_qs.filter(search_filter)

    if category_id and category_id.lower() != "all":
        try:
            media_qs = media_qs.filter(variant__product__category_id=int(category_id))
        except (ValueError, TypeError):
            pass

    if stock_filter == "in_stock":
        media_qs = media_qs.filter(variant__quantity__gt=5)
    elif stock_filter == "low_stock":
        media_qs = media_qs.filter(variant__quantity__gt=0, variant__quantity__lte=5)
    elif stock_filter == "out_of_stock":
        media_qs = media_qs.filter(variant__quantity=0)

    if media_type in [VariantMedia.MediaType.IMAGE, VariantMedia.MediaType.VIDEO]:
        media_qs = media_qs.filter(media_type=media_type)

    if on_sale in ["1", "true", "True"]:
        media_qs = media_qs.filter(variant__discount_percentage__gt=0)

    sort_mapping = {
        "newest": ["-created_at", "-id"],
        "price_asc": ["variant__mrp", "variant__product__name"],
        "price_desc": ["-variant__mrp", "variant__product__name"],
        "discount_desc": ["-variant__discount_percentage", "-variant__mrp"],
        "stock_desc": ["-variant__quantity", "-id"],
        "name_asc": ["variant__product__brand", "variant__product__name"],
    }
    ordering = sort_mapping.get(sort_key, ["-created_at", "-id"])
    media_qs = media_qs.order_by(*ordering)

    return media_qs



