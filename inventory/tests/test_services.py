"""Tests for inventory/services.py covering CRUD, damage lifecycle, FIFO operations."""

from decimal import Decimal

from django.test import RequestFactory, TestCase
from django.utils import timezone

from inventory.services import (
    DamageResolutionService,
    InventoryService,
    get_media_gallery_data,
    get_media_gallery_stats,
    get_variants_data,
    total_inventory_value,
)
from inventory.models import Category, InventoryLog, DamagedItemRecord, VariantMedia
from Billing.tests.helpers import (
    create_test_user,
    create_test_product,
    create_test_variant,
    create_test_supplier,
    create_test_supplier_invoice,
)


class SuggestResolutionTests(TestCase):
    """Tests for DamageResolutionService.suggest_resolution() — pure function."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(
            purchase_price=Decimal("600.00"),
            mrp=Decimal("1000.00"),
            quantity=Decimal("40"),
            damaged_quantity=Decimal("10"),
            user=self.user,
        )

    def test_high_value_returns_return_and_repair_and_write_off(self):
        suggestions = DamageResolutionService.suggest_resolution(self.variant)
        actions = [s["action"] for s in suggestions]
        self.assertIn("return_supplier", actions)
        self.assertIn("repair", actions)
        self.assertIn("write_off", actions)

    def test_return_supplier_has_highest_priority(self):
        suggestions = DamageResolutionService.suggest_resolution(self.variant)
        self.assertEqual(suggestions[0]["action"], "return_supplier")
        self.assertEqual(suggestions[0]["priority"], 1)
        self.assertEqual(suggestions[-1]["action"], "write_off")

    def test_no_damage_returns_empty(self):
        self.variant.damaged_quantity = Decimal("0")
        suggestions = DamageResolutionService.suggest_resolution(self.variant)
        self.assertEqual(suggestions, [])

    def test_low_value_skips_return(self):
        self.variant.purchase_price = Decimal("100.00")
        self.variant.mrp = Decimal("150.00")
        self.variant.quantity = Decimal("40")
        self.variant.damaged_quantity = Decimal("10")
        suggestions = DamageResolutionService.suggest_resolution(self.variant)
        actions = [s["action"] for s in suggestions]
        self.assertNotIn("return_supplier", actions)
        self.assertIn("write_off", actions)

    def test_heavily_damaged_skips_return(self):
        self.variant.quantity = Decimal("5")
        self.variant.damaged_quantity = Decimal("45")
        suggestions = DamageResolutionService.suggest_resolution(self.variant)
        actions = [s["action"] for s in suggestions]
        self.assertNotIn("return_supplier", actions)

    def test_all_suggestions_have_required_keys(self):
        suggestions = DamageResolutionService.suggest_resolution(self.variant)
        for s in suggestions:
            self.assertIn("action", s)
            self.assertIn("priority", s)
            self.assertIn("reasoning", s)
            self.assertIn("financial_impact", s)


class ApplyDiscountTests(TestCase):
    """Tests for InventoryService.apply_discount()."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(user=self.user)

    def test_discount_applied(self):
        InventoryService.apply_discount(self.variant, 15, user=self.user)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.discount_percentage, Decimal("15"))

    def test_discount_creates_log(self):
        InventoryService.apply_discount(self.variant, 20, user=self.user)
        log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.ADJUSTMENT_IN,
        ).first()
        self.assertIsNotNone(log)
        self.assertIn("Discount applied", log.notes)

    def test_zero_discount(self):
        InventoryService.apply_discount(self.variant, 0, user=self.user)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.discount_percentage, Decimal("0"))

    def test_hundred_percent_discount(self):
        InventoryService.apply_discount(self.variant, 100, user=self.user)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.discount_percentage, Decimal("100"))


class UpdateQuantityTests(TestCase):
    """Tests for InventoryService.update_quantity()."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(
            purchase_price=Decimal("100.00"),
            mrp=Decimal("180.00"),
            quantity=Decimal("50"),
            user=self.user,
        )

    def test_positive_change(self):
        InventoryService.update_quantity(self.variant, 10, user=self.user)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.quantity, Decimal("60"))

    def test_negative_change(self):
        InventoryService.update_quantity(self.variant, -5, user=self.user)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.quantity, Decimal("45"))

    def test_creates_stock_in_log(self):
        InventoryService.update_quantity(self.variant, 10, user=self.user)
        log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.STOCK_IN,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.quantity_change, 10)
        self.assertEqual(log.new_quantity, Decimal("60"))


class AdjustQuantityTests(TestCase):
    """Tests for adjust_in_quantity() and adjust_out_quantity()."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(
            purchase_price=Decimal("100.00"), quantity=Decimal("50"), user=self.user
        )

    def test_adjust_in_raises_on_zero(self):
        with self.assertRaises(ValueError) as ctx:
            InventoryService.adjust_in_quantity(self.variant, 0, user=self.user)
        self.assertIn("zero", str(ctx.exception))

    def test_adjust_out_raises_on_zero(self):
        with self.assertRaises(ValueError) as ctx:
            InventoryService.adjust_out_quantity(self.variant, 0, user=self.user)
        self.assertIn("zero", str(ctx.exception))

    def test_adjust_in_increases_quantity(self):
        InventoryService.adjust_in_quantity(self.variant, 10, user=self.user)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.quantity, Decimal("60"))

    def test_adjust_out_decreases_quantity(self):
        InventoryService.adjust_out_quantity(self.variant, 10, user=self.user)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.quantity, Decimal("40"))

    def test_adjust_out_creates_negative_change_log(self):
        InventoryService.adjust_out_quantity(self.variant, 10, user=self.user)
        log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.ADJUSTMENT_OUT,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.quantity_change, Decimal("-10"))


class CreateInitialLogTests(TestCase):
    """Tests for InventoryService.create_initial_log()."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(
            purchase_price=Decimal("100.00"),
            mrp=Decimal("180.00"),
            quantity=Decimal("50"),
            user=self.user,
        )

    def test_creates_initial_log(self):
        log = InventoryService.create_initial_log(
            self.variant, user=self.user, notes="Fresh stock"
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.transaction_type, InventoryLog.TransactionTypes.INITIAL)
        self.assertEqual(log.quantity_change, Decimal("50"))
        self.assertEqual(log.new_quantity, Decimal("50"))
        self.assertEqual(log.remaining_quantity, Decimal("50"))

    def test_multiple_initial_logs_allowed(self):
        log1 = InventoryService.create_initial_log(self.variant, user=self.user)
        self.assertIsNotNone(log1)
        log2 = InventoryService.create_initial_log(self.variant, user=self.user)
        self.assertIsNotNone(log2)
        self.assertEqual(
            InventoryLog.objects.filter(
                variant=self.variant,
                transaction_type=InventoryLog.TransactionTypes.INITIAL,
            ).count(),
            2,
        )


class UpdateStockInLogTests(TestCase):
    """Tests for InventoryService.update_stock_in_log()."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(
            purchase_price=Decimal("100.00"),
            mrp=Decimal("180.00"),
            quantity=Decimal("50"),
            user=self.user,
        )

    def test_updates_quantity(self):
        log = InventoryService.update_stock_in_log(
            self.variant, 10, user=self.user, notes="New batch"
        )
        self.assertIsNotNone(log)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.quantity, Decimal("60"))

    def test_updates_purchase_price(self):
        InventoryService.update_stock_in_log(
            self.variant,
            10,
            user=self.user,
            purchase_price=Decimal("120.00"),
        )
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.purchase_price, Decimal("120.00"))

    def test_creates_log_with_remaining(self):
        log = InventoryService.update_stock_in_log(
            self.variant, 10, user=self.user
        )
        self.assertEqual(log.remaining_quantity, Decimal("10"))
        self.assertEqual(log.transaction_type, InventoryLog.TransactionTypes.STOCK_IN)


class ReturnSaleTests(TestCase):
    """Tests for InventoryService.return_sale()."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(
            purchase_price=Decimal("100.00"),
            mrp=Decimal("180.00"),
            quantity=Decimal("50"),
            user=self.user,
        )

    def test_raises_on_non_positive(self):
        with self.assertRaises(ValueError):
            InventoryService.return_sale(self.variant, 0, user=self.user)

    def test_increases_stock(self):
        result = InventoryService.return_sale(self.variant, 5, user=self.user)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.quantity, Decimal("55"))
        self.assertTrue(result["success"])

    def test_creates_return_log(self):
        InventoryService.return_sale(self.variant, 5, user=self.user)
        log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.RETURN,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.quantity_change, Decimal("5"))


class CancelledSaleTests(TestCase):
    """Tests for InventoryService.cancelled_sale()."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(
            purchase_price=Decimal("100.00"),
            mrp=Decimal("180.00"),
            quantity=Decimal("50"),
            user=self.user,
        )

    def test_raises_on_non_positive(self):
        with self.assertRaises(ValueError):
            InventoryService.cancelled_sale(self.variant, 0, user=self.user)

    def test_increases_stock(self):
        result = InventoryService.cancelled_sale(self.variant, 5, user=self.user)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.quantity, Decimal("55"))
        self.assertTrue(result["success"])

    def test_creates_cancel_log(self):
        InventoryService.cancelled_sale(self.variant, 5, user=self.user)
        log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.CANCEL,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.quantity_change, Decimal("5"))


class DamageLogTests(TestCase):
    """Tests for InventoryService.damage_log()."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(
            purchase_price=Decimal("100.00"),
            mrp=Decimal("180.00"),
            quantity=Decimal("50"),
            user=self.user,
        )

    def test_raises_on_non_positive(self):
        with self.assertRaises(ValueError) as ctx:
            InventoryService.damage_log(self.variant, 0, user=self.user)
        self.assertIn("positive", str(ctx.exception))

    def test_raises_on_insufficient_stock(self):
        with self.assertRaises(ValueError) as ctx:
            InventoryService.damage_log(self.variant, 100, user=self.user)
        self.assertIn("Insufficient stock", str(ctx.exception))

    def test_moves_stock_to_damaged(self):
        result = InventoryService.damage_log(self.variant, 10, user=self.user)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.quantity, Decimal("40"))
        self.assertEqual(self.variant.damaged_quantity, Decimal("10"))
        self.assertTrue(result["success"])

    def test_creates_damage_record(self):
        InventoryService.damage_log(
            self.variant, 10, user=self.user, damage_type="Water"
        )
        record = DamagedItemRecord.objects.filter(variant=self.variant).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.quantity, Decimal("10"))
        self.assertEqual(record.reason, "WATER")

    def test_creates_damage_log(self):
        InventoryService.damage_log(self.variant, 10, user=self.user)
        log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.DAMAGE,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.quantity_change, Decimal("-10"))

    def test_with_supplier_invoice(self):
        supplier = create_test_supplier(phone="7710000001")
        supplier_invoice = create_test_supplier_invoice(
            supplier=supplier,
            invoice_number="DAMAGE-TEST-001",
        )
        result = InventoryService.damage_log(
            self.variant, 5, user=self.user, supplier_invoice=supplier_invoice
        )
        record = DamagedItemRecord.objects.filter(variant=self.variant).first()
        self.assertEqual(record.supplier, supplier)
        self.assertEqual(record.supplier_invoice, supplier_invoice)


class DamageResolutionTests(TestCase):
    """Tests for DamageResolutionService methods: create, return_to_supplier, write_off, repair."""

    def setUp(self):
        self.user = create_test_user()
        self.supplier = create_test_supplier(phone="7710000002")
        self.supplier_invoice = create_test_supplier_invoice(
            supplier=self.supplier, invoice_number="RESOLVE-TEST-001"
        )
        self.variant = create_test_variant(
            purchase_price=Decimal("200.00"),
            mrp=Decimal("350.00"),
            quantity=Decimal("50"),
            user=self.user,
        )

    def test_create_damage_record(self):
        record = DamageResolutionService.create_damage_record(
            self.variant, quantity=5, user=self.user, reason="TRANSIT"
        )
        self.assertEqual(record.status, DamagedItemRecord.Status.PENDING)
        self.assertEqual(record.quantity, Decimal("5"))
        self.assertEqual(record.reason, "TRANSIT")

    def test_return_to_supplier(self):
        self.variant.damaged_quantity = Decimal("10")
        self.variant.save()
        record = DamageResolutionService.create_damage_record(
            self.variant, quantity=5, user=self.user
        )
        result = DamageResolutionService.return_to_supplier(
            record, self.supplier, self.user,
            notes="Returning to manufacturer",
            supplier_invoice=self.supplier_invoice,
        )
        self.variant.refresh_from_db()
        self.assertEqual(result.status, DamagedItemRecord.Status.RETURNED)
        self.assertEqual(self.variant.damaged_quantity, Decimal("5"))
        self.assertIsNotNone(result.resolved_at)

    def test_return_to_supplier_non_pending_raises(self):
        self.variant.damaged_quantity = Decimal("10")
        self.variant.save()
        record = DamageResolutionService.create_damage_record(
            self.variant, quantity=5, user=self.user
        )
        record.status = DamagedItemRecord.Status.RETURNED
        record.save()
        with self.assertRaises(ValueError) as ctx:
            DamageResolutionService.return_to_supplier(
                record, self.supplier, self.user
            )
        self.assertIn("Cannot return", str(ctx.exception))

    def test_return_to_supplier_insufficient_damaged_raises(self):
        self.variant.damaged_quantity = Decimal("2")
        self.variant.save()
        record = DamageResolutionService.create_damage_record(
            self.variant, quantity=5, user=self.user
        )
        with self.assertRaises(ValueError) as ctx:
            DamageResolutionService.return_to_supplier(
                record, self.supplier, self.user
            )
        self.assertIn("only", str(ctx.exception))

    def test_write_off(self):
        self.variant.damaged_quantity = Decimal("10")
        self.variant.save()
        record = DamageResolutionService.create_damage_record(
            self.variant, quantity=5, user=self.user
        )
        result = DamageResolutionService.write_off(record, self.user, notes="Total loss")
        self.variant.refresh_from_db()
        self.assertEqual(result.status, DamagedItemRecord.Status.WRITTEN_OFF)
        self.assertEqual(self.variant.damaged_quantity, Decimal("5"))

    def test_write_off_non_pending_raises(self):
        self.variant.damaged_quantity = Decimal("10")
        self.variant.save()
        record = DamageResolutionService.create_damage_record(
            self.variant, quantity=5, user=self.user
        )
        record.status = DamagedItemRecord.Status.WRITTEN_OFF
        record.save()
        with self.assertRaises(ValueError):
            DamageResolutionService.write_off(record, self.user)

    def test_repair(self):
        self.variant.damaged_quantity = Decimal("10")
        self.variant.save()
        record = DamageResolutionService.create_damage_record(
            self.variant, quantity=5, user=self.user
        )
        result = DamageResolutionService.repair(
            record, self.user, notes="Fixed at shop", repair_cost=Decimal("50.00")
        )
        self.variant.refresh_from_db()
        self.assertEqual(result.status, DamagedItemRecord.Status.REPAIRED)
        self.assertEqual(self.variant.damaged_quantity, Decimal("5"))
        self.assertEqual(self.variant.quantity, Decimal("55"))
        self.assertEqual(result.repair_cost, Decimal("50.00"))

    def test_repair_creates_restore_log(self):
        self.variant.damaged_quantity = Decimal("10")
        self.variant.save()
        record = DamageResolutionService.create_damage_record(
            self.variant, quantity=5, user=self.user
        )
        DamageResolutionService.repair(record, self.user)
        log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.ADJUSTMENT_IN,
            notes__contains="Repaired",
        ).first()
        self.assertIsNotNone(log)

    def test_repair_non_pending_raises(self):
        self.variant.damaged_quantity = Decimal("10")
        self.variant.save()
        record = DamageResolutionService.create_damage_record(
            self.variant, quantity=5, user=self.user
        )
        record.status = DamagedItemRecord.Status.REPAIRED
        record.save()
        with self.assertRaises(ValueError):
            DamageResolutionService.repair(record, self.user)

    def test_repair_insufficient_damaged_raises(self):
        self.variant.damaged_quantity = Decimal("2")
        self.variant.save()
        record = DamageResolutionService.create_damage_record(
            self.variant, quantity=5, user=self.user
        )
        with self.assertRaises(ValueError) as ctx:
            DamageResolutionService.repair(record, self.user)
        self.assertIn("only", str(ctx.exception))


class FifoSaleTests(TestCase):
    """Tests for InventoryService.sale() and _allocate_fifo()."""

    def setUp(self):
        self.user = create_test_user()
        self.variant = create_test_variant(
            purchase_price=Decimal("100.00"),
            mrp=Decimal("180.00"),
            quantity=Decimal("50"),
            user=self.user,
        )
        InventoryService.create_initial_log(self.variant, user=self.user)

    def test_sale_reduces_quantity(self):
        result = InventoryService.sale(self.variant, 10, user=self.user)
        self.variant.refresh_from_db()
        self.assertTrue(result["success"])
        self.assertEqual(self.variant.quantity, Decimal("40"))

    def test_sale_raises_on_non_positive(self):
        with self.assertRaises(ValueError):
            InventoryService.sale(self.variant, 0, user=self.user)

    def test_sale_returns_cogs(self):
        result = InventoryService.sale(self.variant, 10, user=self.user)
        self.assertEqual(result["cogs"], Decimal("1000.00"))

    def test_sale_reports_insufficient_stock(self):
        result = InventoryService.sale(self.variant, 100, user=self.user)
        self.assertTrue(result["insufficient_stock_warning"])
        self.assertEqual(result["quantity_sold"], 100)

    def test_fifo_allocates_from_initial_log(self):
        result = InventoryService.sale(self.variant, 10, user=self.user)
        self.assertEqual(len(result["allocation_logs"]), 1)
        log = result["allocation_logs"][0]
        self.assertEqual(log.transaction_type, InventoryLog.TransactionTypes.SALE)
        self.assertEqual(log.quantity_change, Decimal("-10"))

    def test_sale_handles_insufficient_stock_creates_unallocated_log(self):
        result = InventoryService.sale(self.variant, 100, user=self.user)
        self.assertGreaterEqual(len(result["allocation_logs"]), 1)
        insufficient_logs = [
            l for l in result["allocation_logs"]
            if "INSUFFICIENT STOCK" in (l.notes or "")
        ]
        self.assertEqual(len(insufficient_logs), 1)

    def test_fifo_tracks_remaining_quantity(self):
        InventoryService.sale(self.variant, 30, user=self.user)
        initial_log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.INITIAL,
        ).first()
        self.assertEqual(initial_log.remaining_quantity, Decimal("20"))


class LinkSupplierInvoiceTests(TestCase):
    """Tests for link_supplier_invoice_and_propagate_fifo()."""

    def setUp(self):
        self.user = create_test_user()
        self.supplier = create_test_supplier(phone="7710000003")
        self.supplier_invoice = create_test_supplier_invoice(
            supplier=self.supplier, invoice_number="LINK-TEST-001", total_amount=Decimal("5000.00")
        )
        self.variant = create_test_variant(
            purchase_price=Decimal("100.00"),
            mrp=Decimal("180.00"),
            quantity=Decimal("50"),
            user=self.user,
        )

    def test_link_to_initial_log(self):
        log = InventoryService.create_initial_log(self.variant, user=self.user)
        result = InventoryService.link_supplier_invoice_and_propagate_fifo(
            log, self.supplier_invoice, user=self.user, purchase_price=Decimal("120.00")
        )
        self.assertTrue(result["success"])
        log.refresh_from_db()
        self.assertEqual(log.supplier_invoice, self.supplier_invoice)
        self.assertEqual(log.purchase_price, Decimal("120.00"))

    def test_link_updates_variant_purchase_price(self):
        log = InventoryService.create_initial_log(self.variant, user=self.user)
        InventoryService.link_supplier_invoice_and_propagate_fifo(
            log, self.supplier_invoice, user=self.user, purchase_price=Decimal("120.00")
        )
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.purchase_price, Decimal("120.00"))

    def test_link_to_non_initial_raises(self):
        log = InventoryService.update_stock_in_log(
            self.variant, 10, user=self.user
        )
        log.transaction_type = InventoryLog.TransactionTypes.SALE
        log.save()
        with self.assertRaises(ValueError) as ctx:
            InventoryService.link_supplier_invoice_and_propagate_fifo(
                log, self.supplier_invoice, user=self.user
            )
        self.assertIn("Can only link", str(ctx.exception))

    def test_link_propagates_to_child_sale_logs(self):
        initial_log = InventoryService.create_initial_log(self.variant, user=self.user)
        InventoryService.sale(self.variant, 10, user=self.user)
        child_logs = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.SALE,
            source_inventory_log=initial_log,
        )
        self.assertGreater(child_logs.count(), 0)
        result = InventoryService.link_supplier_invoice_and_propagate_fifo(
            initial_log, self.supplier_invoice, user=self.user
        )
        self.assertGreater(result["child_logs_updated"], 0)


class VariantQueryServicesTests(TestCase):
    """Tests for get_variants_data and total_inventory_value service functions."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = create_test_user()
        self.product = create_test_product(brand="Nike", name="Air Max")
        self.v1 = create_test_variant(
            product=self.product,
            purchase_price=Decimal("100.00"),
            mrp=Decimal("200.00"),
            quantity=Decimal("10"),
            user=self.user,
        )
        self.v2 = create_test_variant(
            product=self.product,
            purchase_price=Decimal("150.00"),
            mrp=Decimal("250.00"),
            quantity=Decimal("4"),
            user=self.user,
        )

    def test_total_inventory_value(self):
        # 10 * 100 + 4 * 150 = 1000 + 600 = 1600.00
        val = total_inventory_value()
        self.assertEqual(val, Decimal("1600.00"))

    def test_get_variants_data_with_params(self):
        # Test params dict filtering
        results = get_variants_data(params={"search": "Nike"})
        self.assertEqual(results.count(), 2)

        results_empty = get_variants_data(params={"search": "NonExistentBrand"})
        self.assertEqual(results_empty.count(), 0)

    def test_get_variants_data_with_request(self):
        request = self.factory.get("/inventory/variants/", {"search": "Air Max", "stock": "in_stock"})
        results = get_variants_data(request)
        self.assertEqual(results.count(), 2)

    def test_get_variants_data_price_and_discount_filters(self):
        # Update v1 to have discount
        self.v1.discount_percentage = Decimal("10.00")
        self.v1.save()

        # Price range: min_price 220 should return only v2 (mrp=250)
        res_min_price = get_variants_data(params={"min_price": "220"})
        self.assertEqual(res_min_price.count(), 1)
        self.assertEqual(res_min_price.first().id, self.v2.id)

        # Price range: max_price 210 should return only v1 (mrp=200)
        res_max_price = get_variants_data(params={"max_price": "210"})
        self.assertEqual(res_max_price.count(), 1)
        self.assertEqual(res_max_price.first().id, self.v1.id)

        # Discounted only: should return only v1
        res_discount_only = get_variants_data(params={"discount_only": "true"})
        self.assertEqual(res_discount_only.count(), 1)
        self.assertEqual(res_discount_only.first().id, self.v1.id)

        # Discount percent filter
        res_discount_pct = get_variants_data(params={"min_discount": "5", "max_discount": "15"})
        self.assertEqual(res_discount_pct.count(), 1)
        self.assertEqual(res_discount_pct.first().id, self.v1.id)

        # Discount amount filter: 200 * 10% = 20.00
        res_discount_amt = get_variants_data(
            params={"discount_type": "amount", "min_discount": "15", "max_discount": "25"}
        )
        self.assertEqual(res_discount_amt.count(), 1)
        self.assertEqual(res_discount_amt.first().id, self.v1.id)


class MediaGalleryServicesTests(TestCase):
    """Tests for get_media_gallery_stats and get_media_gallery_data service functions."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = create_test_user()
        self.category = Category.objects.create(name="Shoes")
        self.category2 = Category.objects.create(name="Apparel")
        self.product1 = create_test_product(brand="Nike", name="Air Max", category=self.category)
        self.product2 = create_test_product(brand="Adidas", name="Ultraboost", category=self.category2)

        # v1: In stock (qty=10), on sale (discount=10%)
        self.v1 = create_test_variant(
            product=self.product1,
            mrp=Decimal("200.00"),
            quantity=Decimal("10"),
            user=self.user,
        )
        self.v1.discount_percentage = Decimal("10.00")
        self.v1.save(update_fields=["discount_percentage"])

        # v2: Low stock (qty=3), no discount
        self.v2 = create_test_variant(
            product=self.product2,
            mrp=Decimal("150.00"),
            quantity=Decimal("3"),
            user=self.user,
        )

        # Media files
        self.m1 = VariantMedia.objects.create(
            variant=self.v1,
            file="variant_media/test1.jpg",
            media_type=VariantMedia.MediaType.IMAGE,
        )
        self.m2 = VariantMedia.objects.create(
            variant=self.v1,
            file="variant_media/test1.mp4",
            media_type=VariantMedia.MediaType.VIDEO,
        )
        self.m3 = VariantMedia.objects.create(
            variant=self.v2,
            file="variant_media/test2.jpg",
            media_type=VariantMedia.MediaType.IMAGE,
        )

    def test_get_media_gallery_stats(self):
        result = get_media_gallery_stats()
        stats = result["stats"]
        categories = result["categories"]

        self.assertEqual(stats["total_media"], 3)
        self.assertEqual(stats["images_count"], 2)
        self.assertEqual(stats["videos_count"], 1)
        self.assertEqual(stats["variants_count"], 2)
        self.assertEqual(stats["in_stock_count"], 1)  # v1 qty > 5
        self.assertEqual(stats["low_stock_count"], 1)  # v2 qty <= 5 and > 0
        self.assertEqual(stats["on_sale_count"], 1)  # v1 discount > 0
        self.assertEqual(len(categories), 2)
        self.assertEqual(categories[0]["cat_name"], "Apparel")
        self.assertEqual(categories[0]["media_count"], 1)
        self.assertEqual(categories[1]["cat_name"], "Shoes")
        self.assertEqual(categories[1]["media_count"], 2)

    def test_get_media_gallery_data_search_multi_word(self):
        # Uses build_search_filter - multi word matching brand and product name
        results = get_media_gallery_data(params={"search": "Nike Air"})
        self.assertEqual(results.count(), 2)  # m1 and m2 belong to Nike Air Max

        results_none = get_media_gallery_data(params={"search": "Puma Runner"})
        self.assertEqual(results_none.count(), 0)

    def test_get_media_gallery_data_filters(self):
        # Filter by media_type
        videos = get_media_gallery_data(params={"media_type": "VIDEO"})
        self.assertEqual(videos.count(), 1)
        self.assertEqual(videos.first(), self.m2)

        # Filter by category
        cat_results = get_media_gallery_data(params={"category": str(self.category.id)})
        self.assertEqual(cat_results.count(), 2)

        # Filter by stock
        in_stock = get_media_gallery_data(params={"stock": "in_stock"})
        self.assertEqual(in_stock.count(), 2)  # m1, m2 from v1

        low_stock = get_media_gallery_data(params={"stock": "low_stock"})
        self.assertEqual(low_stock.count(), 1)  # m3 from v2

        # Filter by on_sale
        on_sale = get_media_gallery_data(params={"on_sale": "1"})
        self.assertEqual(on_sale.count(), 2)

    def test_get_media_gallery_data_with_request(self):
        request = self.factory.get("/inventory/media/fetch/", {"search": "Adidas", "sort": "price_asc"})
        results = get_media_gallery_data(request)
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first(), self.m3)


