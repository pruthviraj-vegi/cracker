"""
Django management command to auto-repair unlinked INITIAL/STOCK_IN inventory logs
and reconcile FIFO remaining quantities.

Uses 3 bottom-up inference strategies:
1. Child Log Tracing — check SALE/DAMAGE children via source_inventory_log
2. DamagedItemRecord Tracing — check DamagedItemRecord for same variant (±7 days)
3. Single Supplier Match — if variant has exactly one supplier invoice across all logs

Usage:
    python manage.py repair_unlinked_stock --dry-run
    python manage.py repair_unlinked_stock --execute
    python manage.py repair_unlinked_stock --execute --variant-id 42
"""

import datetime
import logging
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from inventory.models import DamagedItemRecord, InventoryLog
from inventory.services import InventoryService
from supplier.models import SupplierInvoice

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Management command to auto-repair unlinked stock logs and reconcile FIFO quantities.
    """

    help = "Auto-repair unlinked INITIAL/STOCK_IN logs using supplier inference and reconcile FIFO quantities"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview auto-repairs and reconciliation without saving changes",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Execute auto-repairs and apply changes to database",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=200,
            help="Number of items to process per bulk database batch (default: 200)",
        )
        parser.add_argument(
            "--variant-id",
            type=int,
            default=None,
            help="Process only a specific variant ID",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        execute = options["execute"]
        batch_size = options["batch_size"]
        variant_id = options["variant_id"]

        if not dry_run and not execute:
            self.stdout.write(
                self.style.ERROR("Please specify either --dry-run or --execute")
            )
            return

        mode = "DRY RUN" if dry_run else "EXECUTE"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'=' * 60}\n"
                f"Auto-Repair Unlinked Stock & FIFO Reconciliation - {mode} (Batch Size: {batch_size})\n"
                f"{'=' * 60}\n"
            )
        )

        # -------------------------------------------------------------
        # STEP 1: Auto-Repair Unlinked Logs (Batch Processing)
        # -------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n[1/2] Auto-Repairing Unlinked Stock Logs (Batch Mode)..."))

        unlinked_query = InventoryLog.objects.filter(
            transaction_type__in=[
                InventoryLog.TransactionTypes.INITIAL,
                InventoryLog.TransactionTypes.STOCK_IN,
            ],
            supplier_invoice__isnull=True,
        ).select_related("variant", "variant__product").order_by("timestamp")

        if variant_id:
            unlinked_query = unlinked_query.filter(variant_id=variant_id)

        unlinked_logs = list(unlinked_query)
        self.stdout.write(f"Found {len(unlinked_logs)} unlinked stock logs to process.")

        auto_linked_count = 0
        ambiguous_count = 0
        skipped_count = 0
        details = []

        pending_batch = []

        def _flush_batch(batch_items):
            nonlocal auto_linked_count, skipped_count
            if not batch_items or not execute:
                return
            try:
                result = self._batch_link_supplier_invoices(batch_items)
                auto_linked_count += result.get("parent_logs_linked", 0)
            except Exception as e:
                skipped_count += len(batch_items)
                self.stdout.write(
                    self.style.ERROR(f"  [BATCH ERROR] Error during batch link: {e}")
                )

        for log in unlinked_logs:
            inferred_invoice = None
            method_used = ""

            # --- Strategy 1: Child Log Tracing ---
            child_invoices = (
                InventoryLog.objects.filter(
                    source_inventory_log=log,
                    supplier_invoice__isnull=False,
                )
                .values_list("supplier_invoice_id", flat=True)
                .distinct()
            )
            child_invoice_ids = set(child_invoices)

            if len(child_invoice_ids) == 1:
                inferred_invoice_id = child_invoice_ids.pop()
                try:
                    inferred_invoice = SupplierInvoice.objects.get(
                        id=inferred_invoice_id, is_deleted=False
                    )
                    method_used = "child_log_tracing"
                except SupplierInvoice.DoesNotExist:
                    pass
            elif len(child_invoice_ids) > 1:
                ambiguous_count += 1
                msg = f"Log #{log.id} ({log.variant.full_name}): Multiple supplier invoices found in child logs ({len(child_invoice_ids)})"
                details.append(msg)
                self.stdout.write(self.style.WARNING(f"  [AMBIGUOUS] {msg}"))
                continue

            # --- Strategy 2: DamagedItemRecord Tracing ---
            if inferred_invoice is None:
                log_time = log.timestamp or log.created_at
                min_date = log_time - datetime.timedelta(days=7)
                max_date = log_time + datetime.timedelta(days=7)

                damage_invoices = (
                    DamagedItemRecord.objects.filter(
                        variant=log.variant,
                        supplier_invoice__isnull=False,
                        created_at__range=(min_date, max_date),
                    )
                    .values_list("supplier_invoice_id", flat=True)
                    .distinct()
                )
                damage_invoice_ids = set(damage_invoices)

                if len(damage_invoice_ids) == 1:
                    damage_inv_id = damage_invoice_ids.pop()
                    try:
                        inferred_invoice = SupplierInvoice.objects.get(
                            id=damage_inv_id, is_deleted=False
                        )
                        method_used = "damaged_item_tracing"
                    except SupplierInvoice.DoesNotExist:
                        pass
                elif len(damage_invoice_ids) > 1:
                    ambiguous_count += 1
                    msg = f"Log #{log.id} ({log.variant.full_name}): Multiple supplier invoices found in damage records ({len(damage_invoice_ids)})"
                    details.append(msg)
                    self.stdout.write(self.style.WARNING(f"  [AMBIGUOUS] {msg}"))
                    continue

            # --- Strategy 3: Single Supplier Match ---
            if inferred_invoice is None:
                variant_invoices = (
                    InventoryLog.objects.filter(
                        variant=log.variant,
                        supplier_invoice__isnull=False,
                    )
                    .values_list("supplier_invoice_id", flat=True)
                    .distinct()
                )
                variant_invoice_ids = set(variant_invoices)

                if len(variant_invoice_ids) == 1:
                    single_inv_id = variant_invoice_ids.pop()
                    try:
                        inferred_invoice = SupplierInvoice.objects.get(
                            id=single_inv_id, is_deleted=False
                        )
                        method_used = "single_supplier_match"
                    except SupplierInvoice.DoesNotExist:
                        pass

            # --- Apply or Skip ---
            if inferred_invoice is not None:
                if execute:
                    pending_batch.append(
                        {
                            "inventory_log": log,
                            "supplier_invoice": inferred_invoice,
                            "method": method_used,
                        }
                    )
                    msg = f"Log #{log.id} ({log.variant.full_name}) -> Invoice #{inferred_invoice.invoice_number} via {method_used}"
                    details.append(msg)
                    self.stdout.write(self.style.SUCCESS(f"  [LINKED] {msg}"))

                    if len(pending_batch) >= batch_size:
                        _flush_batch(pending_batch)
                        pending_batch = []
                else:
                    auto_linked_count += 1
                    msg = f"Log #{log.id} ({log.variant.full_name}) would link to Invoice #{inferred_invoice.invoice_number} via {method_used}"
                    details.append(msg)
                    self.stdout.write(self.style.SUCCESS(f"  [WOULD LINK] {msg}"))
            else:
                skipped_count += 1
                msg = f"Log #{log.id} ({log.variant.full_name}): No supplier invoice could be inferred"
                details.append(msg)
                self.stdout.write(f"  [SKIPPED] {msg}")

        if pending_batch:
            _flush_batch(pending_batch)
            pending_batch = []

        # -------------------------------------------------------------
        # STEP 2: Reconcile FIFO Quantities
        # -------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n[2/2] Reconciling FIFO Remaining Quantities..."))

        stock_log_filter = {
            "transaction_type__in": [
                InventoryLog.TransactionTypes.STOCK_IN,
                InventoryLog.TransactionTypes.INITIAL,
                InventoryLog.TransactionTypes.RETURN,
            ],
        }
        if variant_id:
            stock_log_filter["variant_id"] = variant_id

        stock_logs = InventoryLog.objects.filter(**stock_log_filter)

        reconciled_count = 0
        corrected_count = 0
        logs_to_update = []

        for stock_log in stock_logs:
            # For INITIAL log, if present quantity >= 0, ensure initial quantity_change reflects present stock + net stock movements
            if (
                stock_log.transaction_type == InventoryLog.TransactionTypes.INITIAL
                and stock_log.variant.quantity >= 0
            ):
                other_logs = InventoryLog.objects.filter(variant=stock_log.variant).exclude(
                    id=stock_log.id
                )
                if other_logs.exists():
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

                    calc_initial = stock_log.variant.quantity + stock_out_total - stock_in_total
                    if calc_initial >= 0 and stock_log.quantity_change != calc_initial:
                        if execute:
                            stock_log.quantity_change = calc_initial
                            stock_log.total_value = calc_initial * (
                                stock_log.purchase_price or Decimal("0")
                            )

            total_allocated = (
                InventoryLog.objects.filter(
                    source_inventory_log=stock_log,
                ).aggregate(
                    total=Sum("allocated_quantity")
                )["total"]
                or Decimal("0")
            )

            expected_remaining = max(abs(stock_log.quantity_change) - total_allocated, Decimal("0"))

            if stock_log.remaining_quantity != expected_remaining:
                if execute:
                    stock_log.remaining_quantity = expected_remaining
                    logs_to_update.append(stock_log)
                corrected_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  Log #{stock_log.id}: remaining_qty was {stock_log.remaining_quantity}, corrected to {expected_remaining}"
                    )
                )

            reconciled_count += 1

        if execute and logs_to_update:
            InventoryLog.objects.bulk_update(
                logs_to_update, ["quantity_change", "remaining_quantity", "total_value"]
            )

        # -------------------------------------------------------------
        # SUMMARY
        # -------------------------------------------------------------
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("SUMMARY REPORT")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"Unlinked Logs Processed:    {len(unlinked_logs)}")
        self.stdout.write(self.style.SUCCESS(f"  Auto-Linked:              {auto_linked_count}"))
        self.stdout.write(self.style.WARNING(f"  Ambiguous:                {ambiguous_count}"))
        self.stdout.write(f"  Skipped:                  {skipped_count}")
        self.stdout.write(f"FIFO Sources Reconciled:    {reconciled_count}")
        self.stdout.write(self.style.SUCCESS(f"  Quantities Corrected:     {corrected_count}"))
        self.stdout.write(f"{'=' * 60}\n")

        if dry_run:
            self.stdout.write(self.style.WARNING("[!] DRY RUN — No changes were made to the database"))
        else:
            self.stdout.write(self.style.SUCCESS("[OK] All repairs & reconciliations applied to database"))

    def _batch_link_supplier_invoices(self, link_items):
        """Perform bulk supplier invoice linking and propagation across a batch of logs."""
        if not link_items:
            return {"parent_logs_linked": 0, "child_logs_updated": 0}

        parent_logs_to_update = []
        parent_log_ids = []
        supplier_invoice_map = {}

        for item in link_items:
            log = item["inventory_log"]
            invoice = item["supplier_invoice"]
            method = item.get("method", "batch_repair")

            log.supplier_invoice = invoice
            clean_notes = log.notes or ""
            log.notes = f"{clean_notes} | Linked Invoice #{invoice.invoice_number} ({method})".strip(" |")

            parent_logs_to_update.append(log)
            parent_log_ids.append(log.id)
            supplier_invoice_map[log.id] = invoice

        with transaction.atomic():
            # 1. Bulk update parent INITIAL / STOCK_IN logs
            InventoryLog.objects.bulk_update(
                parent_logs_to_update,
                ["supplier_invoice", "notes"],
                batch_size=500,
            )

            # 2. Bulk update child logs assigned to these parent logs
            child_logs = InventoryLog.objects.filter(
                source_inventory_log_id__in=parent_log_ids
            )
            child_logs_to_update = []
            for child in child_logs:
                inv = supplier_invoice_map.get(child.source_inventory_log_id)
                if inv:
                    child.supplier_invoice = inv
                    child_logs_to_update.append(child)

            if child_logs_to_update:
                InventoryLog.objects.bulk_update(
                    child_logs_to_update,
                    ["supplier_invoice"],
                    batch_size=500,
                )

            # 3. Update DamagedItemRecords for affected variants where supplier_invoice is null
            for item in link_items:
                log = item["inventory_log"]
                invoice = item["supplier_invoice"]
                DamagedItemRecord.objects.filter(
                    variant_id=log.variant_id, supplier_invoice__isnull=True
                ).update(
                    supplier_invoice=invoice,
                    supplier=invoice.supplier,
                )

        return {
            "parent_logs_linked": len(parent_logs_to_update),
            "child_logs_updated": len(child_logs_to_update),
        }
