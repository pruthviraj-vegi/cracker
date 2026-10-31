"""
Django management command to recalculate FIFO allocations for all inventory logs.

After a database migration broke the linkage between invoices and inventory stock,
this command replays all inventory movements per variant in chronological order to:
- Reset and re-link SALE logs to their source STOCK_IN/INITIAL batches (FIFO)
- Recalculate remaining_quantity on STOCK_IN/INITIAL/RETURN logs
- Fix new_quantity running totals on all logs
- Correct variant.quantity to match the replayed value

Usage:
    python manage.py recalculate_fifo --dry-run
    python manage.py recalculate_fifo --execute
    python manage.py recalculate_fifo --execute --variant-id 42
"""

import logging
from collections import deque
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import InventoryLog, ProductVariant

logger = logging.getLogger(__name__)

# Transaction types that feed into the FIFO queue
STOCK_IN_TYPES = {
    InventoryLog.TransactionTypes.STOCK_IN,
    InventoryLog.TransactionTypes.INITIAL,
    InventoryLog.TransactionTypes.RETURN,
}

# Transaction types that consume from the FIFO queue
STOCK_OUT_TYPES = {
    InventoryLog.TransactionTypes.SALE,
    InventoryLog.TransactionTypes.DAMAGE,
    InventoryLog.TransactionTypes.ADJUSTMENT_OUT,
}

# Transaction types where cancellation reverses a previous sale
CANCEL_TYPES = {
    InventoryLog.TransactionTypes.CANCEL,
}


class Command(BaseCommand):
    """
    Recalculate FIFO allocations and fix inventory log linkages
    """

    help = "Recalculate FIFO allocations and fix inventory log linkages"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without applying them",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Execute the recalculation",
        )
        parser.add_argument(
            "--variant-id",
            type=int,
            default=None,
            help="Process only a specific variant ID (for debugging)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        execute = options["execute"]
        variant_id = options["variant_id"]

        if not dry_run and not execute:
            self.stdout.write(
                self.style.ERROR("Please specify either --dry-run or --execute")
            )
            return

        mode = "DRY RUN" if dry_run else "EXECUTE"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'=' * 60}\n" f"FIFO Recalculation - {mode}\n" f"{'=' * 60}\n"
            )
        )

        # Get variants to process
        if variant_id:
            variants = ProductVariant.objects.filter(id=variant_id)
            if not variants.exists():
                self.stdout.write(
                    self.style.ERROR(f"Variant ID {variant_id} not found.")
                )
                return
        else:
            # All variants that have at least one inventory log
            variants = ProductVariant.objects.filter(
                inventory_logs__isnull=False
            ).distinct()

        total_variants = variants.count()
        self.stdout.write(f"Variants to process: {total_variants}\n")

        if total_variants == 0:
            self.stdout.write(self.style.SUCCESS("No variants to process."))
            return

        # Statistics
        stats = {
            "variants_processed": 0,
            "variants_fixed": 0,
            "variants_quantity_mismatch": 0,
            "sale_logs_linked": 0,
            "cancel_logs_reversed": 0,
            "logs_updated": 0,
            "insufficient_stock_variants": 0,
            "errors": 0,
        }

        # Detailed report data
        report_entries = []
        errors = []

        for variant in variants.select_related("product").iterator(chunk_size=100):
            stats["variants_processed"] += 1

            try:
                result = self._process_variant(variant, dry_run)

                if result["was_fixed"]:
                    stats["variants_fixed"] += 1
                if result["quantity_mismatch"]:
                    stats["variants_quantity_mismatch"] += 1
                if result["insufficient_stock"]:
                    stats["insufficient_stock_variants"] += 1

                stats["sale_logs_linked"] += result["sale_logs_linked"]
                stats["cancel_logs_reversed"] += result["cancel_logs_reversed"]
                stats["logs_updated"] += result["logs_updated"]

                if result["was_fixed"] or result["quantity_mismatch"]:
                    report_entries.append(result)

            except Exception as e:
                stats["errors"] += 1
                error_msg = f"Error processing variant {variant.id} ({variant}): {e}"
                errors.append(error_msg)
                logger.error(error_msg, exc_info=True)

            # Progress indicator
            if stats["variants_processed"] % 100 == 0:
                self.stdout.write(
                    f"  Processed {stats['variants_processed']}/{total_variants}..."
                )

        # Print summary
        self._print_summary(stats, dry_run)

    def _process_variant(self, variant, dry_run):
        """
        Process a single variant: replay all logs chronologically and fix FIFO links.

        Returns a dict with processing results.
        """
        result = {
            "variant_id": variant.id,
            "variant_name": str(variant),
            "was_fixed": False,
            "quantity_mismatch": False,
            "old_quantity": variant.quantity,
            "new_quantity": variant.quantity,
            "sale_logs_linked": 0,
            "cancel_logs_reversed": 0,
            "logs_updated": 0,
            "insufficient_stock": False,
            "details": [],
        }

        # Get ALL logs for this variant, ordered chronologically
        all_logs = list(
            InventoryLog.objects.filter(variant=variant)
            .select_related("supplier_invoice", "invoice_item")
            .order_by("timestamp", "id")
        )

        if not all_logs:
            return result

        # --- PHASE 1: Reset FIFO fields ---
        logs_to_save = []
        for log in all_logs:
            changed = False

            if log.transaction_type in STOCK_IN_TYPES:
                # Reset remaining_quantity to original quantity_change
                original_remaining = abs(log.quantity_change)
                if log.remaining_quantity != original_remaining:
                    log.remaining_quantity = original_remaining
                    changed = True

            elif log.transaction_type in STOCK_OUT_TYPES:
                # Clear FIFO linkage and supplier_invoice (will be re-set from source)
                if log.source_inventory_log is not None:
                    log.source_inventory_log = None
                    changed = True
                if log.allocated_quantity is not None:
                    log.allocated_quantity = None
                    changed = True
                if log.supplier_invoice is not None:
                    log.supplier_invoice = None
                    changed = True

            if changed:
                logs_to_save.append(log)

        # --- PHASE 2: Replay chronologically ---
        fifo_queue = deque()  # deque of [log_obj, remaining_decimal]
        running_quantity = Decimal("0")
        new_logs_to_create = []  # New logs for multi-batch FIFO splits
        sales_by_invoice_item = {}  # invoice_item_id -> list of allocated sale logs

        # Pre-calculate totals for INITIAL log check
        total_stock_out = Decimal("0")
        total_stock_in_except_initial = Decimal("0")
        for l in all_logs:
            if l.transaction_type in STOCK_OUT_TYPES:
                total_stock_out += abs(l.quantity_change)
            elif l.transaction_type in STOCK_IN_TYPES:
                if l.transaction_type != InventoryLog.TransactionTypes.INITIAL:
                    total_stock_in_except_initial += abs(l.quantity_change)
            elif (
                l.transaction_type in CANCEL_TYPES
                or l.transaction_type == InventoryLog.TransactionTypes.ADJUSTMENT_IN
            ):
                total_stock_in_except_initial += abs(l.quantity_change)

        for log in all_logs:
            tx_type = log.transaction_type
            qty_change = log.quantity_change  # positive for in, negative for out

            if tx_type in STOCK_IN_TYPES:
                if tx_type == InventoryLog.TransactionTypes.INITIAL and variant.quantity >= 0:
                    calc_initial = variant.quantity + total_stock_out - total_stock_in_except_initial
                    if calc_initial >= 0:
                        qty_change = calc_initial
                        if log.quantity_change != calc_initial:
                            log.quantity_change = calc_initial
                            log.total_value = calc_initial * (log.purchase_price or Decimal("0"))
                            if log not in logs_to_save:
                                logs_to_save.append(log)

                stock_qty = abs(qty_change)
                running_quantity += stock_qty

                # RETURN with invoice_item → restore to original source batch
                if tx_type == InventoryLog.TransactionTypes.RETURN and log.invoice_item_id:
                    reversed_to_source = False
                    # Find original SALE logs for this invoice_item using O(1) map
                    original_sales = sales_by_invoice_item.get(log.invoice_item_id, [])
                    if original_sales:
                        # Restore remaining_quantity on the original source batches
                        qty_to_restore = stock_qty
                        for sale in original_sales:
                            if qty_to_restore <= 0:
                                break
                            restore_amt = min(
                                abs(sale.allocated_quantity or 0), qty_to_restore
                            )
                            source = sale.source_inventory_log
                            if not source:
                                continue
                            # Set supplier_invoice on the RETURN log from source
                            if source.supplier_invoice and not log.supplier_invoice:
                                log.supplier_invoice = source.supplier_invoice
                            # Find in FIFO queue or re-add
                            found_in_queue = False
                            for entry in fifo_queue:
                                if entry[0].id == source.id:
                                    entry[1] += restore_amt
                                    found_in_queue = True
                                    break
                            if not found_in_queue:
                                fifo_queue.append([source, restore_amt])
                            qty_to_restore -= restore_amt
                        reversed_to_source = True
                        result["cancel_logs_reversed"] += 1
                        if log not in logs_to_save:
                            logs_to_save.append(log)

                    if not reversed_to_source:
                        # No linked sale found — add as new FIFO entry
                        fifo_queue.append([log, stock_qty])
                else:
                    # STOCK_IN / INITIAL / RETURN without invoice_item
                    fifo_queue.append([log, stock_qty])

            elif tx_type in STOCK_OUT_TYPES:
                # Consume from FIFO queue (oldest first)
                to_allocate = abs(qty_change)
                running_quantity -= to_allocate

                is_first_allocation = True
                while to_allocate > 0 and fifo_queue:
                    source_log, source_remaining = fifo_queue[0]
                    allocatable = min(source_remaining, to_allocate)

                    if is_first_allocation:
                        # First batch — update the original log
                        log.source_inventory_log = source_log
                        log.allocated_quantity = allocatable
                        log.quantity_change = -allocatable
                        if source_log.supplier_invoice:
                            log.supplier_invoice = source_log.supplier_invoice
                        if source_log.purchase_price:
                            log.purchase_price = source_log.purchase_price
                        # Recalculate total_value for reduced quantity
                        if log.selling_price:
                            log.total_value = allocatable * log.selling_price
                        is_first_allocation = False

                        if log.invoice_item_id:
                            sales_by_invoice_item.setdefault(log.invoice_item_id, []).append(log)

                        if log not in logs_to_save:
                            logs_to_save.append(log)
                    else:
                        # Subsequent batches — create a NEW sale log
                        new_log = InventoryLog(
                            variant=variant,
                            transaction_type=log.transaction_type,
                            quantity_change=-allocatable,
                            new_quantity=Decimal("0"),  # Will be set in Phase 3b
                            invoice_item=log.invoice_item,
                            selling_price=log.selling_price,
                            source_inventory_log=source_log,
                            allocated_quantity=allocatable,
                            purchase_price=source_log.purchase_price
                            or log.purchase_price,
                            total_value=(
                                (allocatable * log.selling_price)
                                if log.selling_price
                                else None
                            ),
                            supplier_invoice=source_log.supplier_invoice,
                            created_by=log.created_by,
                            notes=f"FIFO split: {allocatable} units from {source_log.timestamp.date()}",
                        )
                        new_logs_to_create.append(new_log)
                        if new_log.invoice_item_id:
                            sales_by_invoice_item.setdefault(new_log.invoice_item_id, []).append(new_log)

                    # Decrement source remaining
                    fifo_queue[0][1] -= allocatable
                    if fifo_queue[0][1] <= 0:
                        fifo_queue.popleft()

                    to_allocate -= allocatable
                    result["sale_logs_linked"] += 1

                if to_allocate > 0:
                    # Insufficient stock — sale log has no full source
                    result["insufficient_stock"] = True
                    result["details"].append(
                        f"  INSUFFICIENT: Log #{log.id} needs {to_allocate} more units"
                    )

            elif tx_type in CANCEL_TYPES:
                # Cancellation restores stock — find the original SALE via invoice_item
                cancel_qty = abs(qty_change)
                running_quantity += cancel_qty

                # Try to reverse the FIFO by finding the source of the original sale
                reversed_to_source = False
                if log.invoice_item_id:
                    # Find the sale log(s) for this invoice_item using O(1) map
                    original_sales = sales_by_invoice_item.get(log.invoice_item_id, [])
                    if original_sales:
                        # Restore remaining_quantity on the original source
                        for sale in original_sales:
                            source = sale.source_inventory_log
                            if not source:
                                continue
                            # Set supplier_invoice on the CANCEL log from source
                            if source.supplier_invoice and not log.supplier_invoice:
                                log.supplier_invoice = source.supplier_invoice
                            # Find it in the fifo_queue or re-add
                            found_in_queue = False
                            for entry in fifo_queue:
                                if entry[0].id == source.id:
                                    entry[1] += abs(sale.allocated_quantity or 0)
                                    found_in_queue = True
                                    break
                            if not found_in_queue:
                                fifo_queue.append(
                                    [source, abs(sale.allocated_quantity or cancel_qty)]
                                )
                        reversed_to_source = True
                        result["cancel_logs_reversed"] += 1
                        if log not in logs_to_save:
                            logs_to_save.append(log)

                if not reversed_to_source:
                    # Generic stock restore — add as new FIFO entry (like RETURN)
                    fifo_queue.append([log, cancel_qty])

            elif tx_type == InventoryLog.TransactionTypes.ADJUSTMENT_IN:
                running_quantity += abs(qty_change)

            # Update new_quantity on every log
            old_new_qty = log.new_quantity
            if old_new_qty != running_quantity:
                log.new_quantity = running_quantity
                if log not in logs_to_save:
                    logs_to_save.append(log)

        # --- PHASE 3: Finalize remaining_quantity on source logs ---
        # After replay, the fifo_queue tells us the true remaining per source
        remaining_map = {}
        for entry in fifo_queue:
            remaining_map[entry[0].id] = entry[1]

        for log in all_logs:
            if log.transaction_type in STOCK_IN_TYPES:
                true_remaining = remaining_map.get(log.id, Decimal("0"))
                if log.remaining_quantity != true_remaining:
                    log.remaining_quantity = true_remaining
                    if log not in logs_to_save:
                        logs_to_save.append(log)

        # --- PHASE 4: Check variant quantity ---
        if running_quantity != variant.quantity:
            result["quantity_mismatch"] = True
            result["new_quantity"] = running_quantity
            result["details"].append(
                f"  QUANTITY MISMATCH: DB has {variant.quantity}, "
                f"replay calculated {running_quantity}"
            )

        # Determine if anything was fixed
        result["logs_updated"] = len(logs_to_save) + len(new_logs_to_create)
        result["was_fixed"] = (
            len(logs_to_save) > 0
            or len(new_logs_to_create) > 0
            or result["quantity_mismatch"]
        )

        # --- PHASE 5: Apply changes ---
        if not dry_run and result["was_fixed"]:
            with transaction.atomic():
                # Bulk update existing logs
                if logs_to_save:
                    InventoryLog.objects.bulk_update(
                        logs_to_save,
                        [
                            "remaining_quantity",
                            "source_inventory_log",
                            "allocated_quantity",
                            "new_quantity",
                            "supplier_invoice",
                            "quantity_change",
                            "purchase_price",
                            "total_value",
                        ],
                        batch_size=500,
                    )

                # Create new split logs (multi-batch FIFO)
                if new_logs_to_create:
                    InventoryLog.objects.bulk_create(new_logs_to_create, batch_size=500)

                # Update variant quantity
                if result["quantity_mismatch"]:
                    variant.quantity = running_quantity
                    variant.save(update_fields=["quantity"])

        return result

    def _print_summary(self, stats, dry_run):
        """Print summary statistics to console."""
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("SUMMARY")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(
            f"Variants processed:           {stats['variants_processed']}"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Variants fixed:               {stats['variants_fixed']}"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                f"Variants with qty mismatch:   {stats['variants_quantity_mismatch']}"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                f"Insufficient stock variants:  {stats['insufficient_stock_variants']}"
            )
        )
        self.stdout.write(f"SALE logs linked (FIFO):      {stats['sale_logs_linked']}")
        self.stdout.write(
            f"CANCEL logs reversed:         {stats['cancel_logs_reversed']}"
        )
        self.stdout.write(f"Total logs updated:           {stats['logs_updated']}")
        self.stdout.write(
            self.style.ERROR(f"Errors:                       {stats['errors']}")
            if stats["errors"] > 0
            else f"Errors:                       0"
        )
        self.stdout.write(f"{'=' * 60}\n")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\n[!] DRY RUN — No changes were made to the database"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("\n[OK] Changes have been applied to the database")
            )
