import datetime
from decimal import Decimal
from django.core.management import call_command
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from inventory.models import (
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
)
from inventory.services import InventoryService
from supplier.models import Supplier, SupplierInvoice

User = get_user_model()


class UnlinkedStockLinkingTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            first_name="TestUser",
            phone_number="9876543210",
            email="test@example.com",
            password="password123",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.user)

        self.hsn = GSTHsnCode.objects.create(
            code="12345678",
            gst_percentage=Decimal("5.00"),
        )
        self.category = Category.objects.create(name="Shirts")
        self.cloth_type = ClothType.objects.create(name="Cotton")
        self.uom = UOM.objects.create(name="Piece", short_code="Pcs", category="Quantity")
        self.product = Product.objects.create(
            name="Oxford Shirt",
            category=self.category,
            cloth_type=self.cloth_type,
            uom=self.uom,
            hsn_code=self.hsn,
        )
        self.size = Size.objects.create(name="M")
        self.color = Color.objects.create(name="Blue")
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=self.size,
            color=self.color,
            purchase_price=Decimal("500.00"),
            mrp=Decimal("1000.00"),
            quantity=Decimal("10.00"),
        )

        self.supplier = Supplier.objects.create(name="Acme Apparel")

        # Invoice dated 10 days ago
        self.invoice_recent = SupplierInvoice.objects.create(
            supplier=self.supplier,
            invoice_number="INV-1001",
            invoice_date=timezone.now() - datetime.timedelta(days=10),
            sub_total=Decimal("5000.00"),
        )

        # Invoice dated 90 days ago
        self.invoice_old = SupplierInvoice.objects.create(
            supplier=self.supplier,
            invoice_number="INV-0099",
            invoice_date=timezone.now() - datetime.timedelta(days=90),
            sub_total=Decimal("2000.00"),
        )

        # Initial unlinked log created today
        self.initial_log = InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.INITIAL,
            quantity_change=Decimal("10.00"),
            new_quantity=Decimal("10.00"),
            remaining_quantity=Decimal("10.00"),
            purchase_price=Decimal("500.00"),
            total_value=Decimal("5000.00"),
            supplier_invoice=None,
        )

        # Sale log allocated from initial_log
        self.sale_log = InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.SALE,
            quantity_change=Decimal("-2.00"),
            new_quantity=Decimal("8.00"),
            allocated_quantity=Decimal("2.00"),
            source_inventory_log=self.initial_log,
            supplier_invoice=None,
        )

    def test_smart_supplier_invoice_suggestions(self):
        suggestions = InventoryService.get_suggested_supplier_invoices(
            self.initial_log, limit=5
        )
        self.assertGreater(len(suggestions), 0)
        # Should prioritize recent invoice (10 days ago) over 90 days old
        self.assertEqual(suggestions[0]["id"], self.invoice_recent.id)

    def test_link_supplier_invoice_and_propagation(self):
        result = InventoryService.link_supplier_invoice_and_propagate_fifo(
            inventory_log=self.initial_log,
            supplier_invoice=self.invoice_recent,
            user=self.user,
            purchase_price=Decimal("550.00"),
        )

        self.assertTrue(result["success"])
        self.initial_log.refresh_from_db()
        self.sale_log.refresh_from_db()
        self.variant.refresh_from_db()

        # Check initial log updated
        self.assertEqual(self.initial_log.supplier_invoice, self.invoice_recent)
        self.assertEqual(self.initial_log.purchase_price, Decimal("550.00"))

        # Check variant price updated
        self.assertEqual(self.variant.purchase_price, Decimal("550.00"))

        # Check child sale log inherited supplier invoice and purchase price
        self.assertEqual(self.sale_log.supplier_invoice, self.invoice_recent)
        self.assertEqual(self.sale_log.purchase_price, Decimal("550.00"))

    # The /inventory/unlinked-stock/link/ endpoint was removed when unlinked stock log UI was removed.
    # Service logic is tested via test_link_supplier_invoice_and_propagation.


class AutoRepairUnlinkedLogsTestCase(TestCase):
    """Tests for InventoryService.auto_repair_unlinked_logs()."""

    def setUp(self):
        self.user = User.objects.create_user(
            first_name="TestUser",
            phone_number="9876543211",
            email="test2@example.com",
            password="password123",
            is_staff=True,
            is_superuser=True,
        )

        self.hsn = GSTHsnCode.objects.create(code="99999999", gst_percentage=Decimal("5.00"))
        self.category = Category.objects.create(name="Pants")
        self.cloth_type = ClothType.objects.create(name="Denim")
        self.uom = UOM.objects.create(name="Piece2", short_code="Pc2", category="Quantity")
        self.product = Product.objects.create(
            name="Jeans", category=self.category, cloth_type=self.cloth_type,
            uom=self.uom, hsn_code=self.hsn,
        )
        self.size = Size.objects.create(name="L")
        self.color = Color.objects.create(name="Black")
        self.variant = ProductVariant.objects.create(
            product=self.product, size=self.size, color=self.color,
            purchase_price=Decimal("600.00"), mrp=Decimal("1200.00"),
            quantity=Decimal("20.00"),
        )

        self.supplier = Supplier.objects.create(name="Denim Corp")
        self.invoice = SupplierInvoice.objects.create(
            supplier=self.supplier,
            invoice_number="DEN-001",
            invoice_date=timezone.now() - datetime.timedelta(days=5),
            sub_total=Decimal("12000.00"),
        )

    def test_auto_repair_from_child_sale_log(self):
        """Child SALE log with supplier_invoice should auto-link the parent INITIAL log."""
        # Create unlinked initial log
        initial_log = InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.INITIAL,
            quantity_change=Decimal("20.00"),
            new_quantity=Decimal("20.00"),
            remaining_quantity=Decimal("20.00"),
            purchase_price=Decimal("600.00"),
            total_value=Decimal("12000.00"),
            supplier_invoice=None,
        )

        # Create child sale that already has the supplier invoice (from before the link was cleared)
        InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.SALE,
            quantity_change=Decimal("-3.00"),
            new_quantity=Decimal("17.00"),
            allocated_quantity=Decimal("3.00"),
            source_inventory_log=initial_log,
            supplier_invoice=self.invoice,
            purchase_price=Decimal("600.00"),
        )

        call_command("repair_unlinked_stock", execute=True)

        initial_log.refresh_from_db()
        self.assertEqual(initial_log.supplier_invoice, self.invoice)

    def test_auto_repair_ambiguous_skipped(self):
        """Multiple different supplier invoices in children should be flagged as ambiguous."""
        # Create a second supplier/invoice
        supplier2 = Supplier.objects.create(name="Other Supplier", phone="9999888877")
        invoice2 = SupplierInvoice.objects.create(
            supplier=supplier2,
            invoice_number="OTH-001",
            invoice_date=timezone.now() - datetime.timedelta(days=3),
            sub_total=Decimal("5000.00"),
        )

        initial_log = InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.INITIAL,
            quantity_change=Decimal("20.00"),
            new_quantity=Decimal("20.00"),
            remaining_quantity=Decimal("20.00"),
            purchase_price=Decimal("600.00"),
            supplier_invoice=None,
        )

        # Two child sales with DIFFERENT supplier invoices
        InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.SALE,
            quantity_change=Decimal("-2.00"),
            new_quantity=Decimal("18.00"),
            allocated_quantity=Decimal("2.00"),
            source_inventory_log=initial_log,
            supplier_invoice=self.invoice,
        )
        InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.SALE,
            quantity_change=Decimal("-1.00"),
            new_quantity=Decimal("17.00"),
            allocated_quantity=Decimal("1.00"),
            source_inventory_log=initial_log,
            supplier_invoice=invoice2,
        )

        call_command("repair_unlinked_stock", execute=True)

        initial_log.refresh_from_db()
        self.assertIsNone(initial_log.supplier_invoice)

    def test_auto_repair_from_damaged_item_record(self):
        """DamagedItemRecord with supplier_invoice should auto-link the parent log."""
        initial_log = InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.INITIAL,
            quantity_change=Decimal("20.00"),
            new_quantity=Decimal("20.00"),
            remaining_quantity=Decimal("20.00"),
            purchase_price=Decimal("600.00"),
            supplier_invoice=None,
        )

        # Create a damage record linked to the supplier
        DamagedItemRecord.objects.create(
            variant=self.variant,
            quantity=Decimal("2.00"),
            reason=DamagedItemRecord.DamageReason.TRANSIT,
            supplier=self.supplier,
            supplier_invoice=self.invoice,
            created_by=self.user,
        )

        call_command("repair_unlinked_stock", execute=True)

        initial_log.refresh_from_db()
        self.assertEqual(initial_log.supplier_invoice, self.invoice)

    def test_auto_repair_no_match_skipped(self):
        """Logs with no traceable supplier info should be skipped."""
        initial_log = InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.INITIAL,
            quantity_change=Decimal("20.00"),
            new_quantity=Decimal("20.00"),
            remaining_quantity=Decimal("20.00"),
            purchase_price=Decimal("600.00"),
            supplier_invoice=None,
        )

        call_command("repair_unlinked_stock", execute=True)

        initial_log.refresh_from_db()
        self.assertIsNone(initial_log.supplier_invoice)



class ReconcileFifoTestCase(TestCase):
    """Tests for repair_unlinked_stock command FIFO reconciliation."""

    def setUp(self):
        self.user = User.objects.create_user(
            first_name="FifoUser",
            phone_number="9876543212",
            email="fifo@example.com",
            password="password123",
        )
        self.hsn = GSTHsnCode.objects.create(code="88888888", gst_percentage=Decimal("5.00"))
        self.category = Category.objects.create(name="Tops")
        self.cloth_type = ClothType.objects.create(name="Silk")
        self.uom = UOM.objects.create(name="Piece3", short_code="Pc3", category="Quantity")
        self.product = Product.objects.create(
            name="Silk Top", category=self.category, cloth_type=self.cloth_type,
            uom=self.uom, hsn_code=self.hsn,
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            purchase_price=Decimal("300.00"), mrp=Decimal("600.00"),
            quantity=Decimal("7.00"),
        )

    def test_reconcile_fifo_quantities(self):
        """remaining_quantity should be recalculated from allocated children."""
        initial_log = InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.INITIAL,
            quantity_change=Decimal("10.00"),
            new_quantity=Decimal("10.00"),
            remaining_quantity=Decimal("10.00"),  # Currently wrong — should be 7
            purchase_price=Decimal("300.00"),
        )

        # 3 units allocated via sales
        InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.SALE,
            quantity_change=Decimal("-3.00"),
            new_quantity=Decimal("7.00"),
            allocated_quantity=Decimal("3.00"),
            source_inventory_log=initial_log,
        )

        call_command("repair_unlinked_stock", execute=True)

        initial_log.refresh_from_db()
        self.assertEqual(initial_log.remaining_quantity, Decimal("7.000"))


class PreventionGuardrailTestCase(TestCase):
    """Tests for the EditProductVariant prevention guardrail."""

    def setUp(self):
        self.user = User.objects.create_user(
            first_name="GuardUser",
            phone_number="9876543213",
            email="guard@example.com",
            password="password123",
            is_staff=True,
            is_superuser=True,
        )
        self.hsn = GSTHsnCode.objects.create(code="77777777", gst_percentage=Decimal("5.00"))
        self.category = Category.objects.create(name="Caps")
        self.cloth_type = ClothType.objects.create(name="Poly")
        self.uom = UOM.objects.create(name="Piece4", short_code="Pc4", category="Quantity")
        self.product = Product.objects.create(
            name="Cap", category=self.category, cloth_type=self.cloth_type,
            uom=self.uom, hsn_code=self.hsn,
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            purchase_price=Decimal("100.00"), mrp=Decimal("200.00"),
            quantity=Decimal("5.00"),
        )

        self.supplier = Supplier.objects.create(name="Cap Supplier")
        self.invoice = SupplierInvoice.objects.create(
            supplier=self.supplier,
            invoice_number="CAP-001",
            invoice_date=timezone.now(),
            sub_total=Decimal("500.00"),
        )

    def test_update_initial_log_preserves_existing_link_when_no_invoice_passed(self):
        """update_initial_log should preserve existing supplier_invoice when kwarg is omitted (sentinel default)."""
        # Create initial log with supplier_invoice linked
        InventoryService.create_initial_log(
            self.variant, user=self.user, supplier_invoice=self.invoice,
        )

        # Simulate what EditProductVariant now does when user doesn't select a supplier_invoice
        # (omit the supplier_invoice kwarg entirely to use sentinel default)
        InventoryService.update_initial_log(
            self.variant, self.user, "Initial stock",
        )

        initial_log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.INITIAL,
        ).first()

        # Supplier link should be preserved
        self.assertIsNotNone(initial_log.supplier_invoice)
        self.assertEqual(initial_log.supplier_invoice, self.invoice)

    def test_update_initial_log_clears_link_when_none_explicitly_passed(self):
        """update_initial_log should clear supplier_invoice when None is explicitly passed."""
        InventoryService.create_initial_log(
            self.variant, user=self.user, supplier_invoice=self.invoice,
        )

        # Explicitly pass None — this should clear the link
        InventoryService.update_initial_log(
            self.variant, self.user, "Initial stock",
            supplier_invoice=None,
        )

        initial_log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.INITIAL,
        ).first()

        self.assertIsNone(initial_log.supplier_invoice)

    def test_initial_quantity_calculation_from_present_quantity(self):
        """Initial log quantity change should be calculated from present stock (>= 0) plus post-initial stock movements."""
        initial_log = InventoryService.create_initial_log(self.variant, user=self.user)
        # Create sale log
        InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.SALE,
            quantity_change=Decimal("-3.00"),
            new_quantity=Decimal("2.00"),
        )
        # Create damage log
        InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.DAMAGE,
            quantity_change=Decimal("-2.00"),
            new_quantity=Decimal("0.00"),
        )
        # Present quantity is 15.00
        self.variant.quantity = Decimal("15.00")
        self.variant.save()

        InventoryService.update_initial_log(self.variant, user=self.user)
        initial_log.refresh_from_db()
        # 15.00 present + 3.00 (sale) + 2.00 (damage) = 20.00 initial
        self.assertEqual(initial_log.quantity_change, Decimal("20.00"))

    def test_negative_present_quantity_does_not_adjust_initial_quantity(self):
        """Negative present quantity (< 0) should not adjust initial quantity log."""
        initial_log = InventoryService.create_initial_log(self.variant, user=self.user)
        initial_log.quantity_change = Decimal("10.00")
        initial_log.save()

        # Present quantity is -5.00
        self.variant.quantity = Decimal("-5.00")
        self.variant.save()

        InventoryService.update_initial_log(self.variant, user=self.user)
        initial_log.refresh_from_db()
        self.assertEqual(initial_log.quantity_change, Decimal("10.00"))

    def test_supplier_link_propagation_to_damage_and_adjustment_out(self):
        """Supplier link on stock batch should propagate to child DAMAGE and ADJUSTMENT_OUT logs."""
        initial_log = InventoryService.create_initial_log(
            self.variant, user=self.user, supplier_invoice=self.invoice
        )
        damage_log = InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.DAMAGE,
            quantity_change=Decimal("-1.00"),
            new_quantity=Decimal("4.00"),
            source_inventory_log=initial_log,
        )

        InventoryService.link_supplier_invoice_and_propagate_fifo(
            initial_log, self.invoice
        )
        damage_log.refresh_from_db()
        self.assertEqual(damage_log.supplier_invoice, self.invoice)

    def test_batch_link_supplier_invoices(self):
        """_batch_link_supplier_invoices should bulk update parent logs, child logs, and DamagedItemRecords in batch."""
        from inventory.management.commands.repair_unlinked_stock import Command as RepairCommand

        initial_log = InventoryService.create_initial_log(self.variant, user=self.user)
        sale_log = InventoryLog.objects.create(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.SALE,
            quantity_change=Decimal("-2.00"),
            new_quantity=Decimal("3.00"),
            source_inventory_log=initial_log,
        )

        batch_items = [
            {
                "inventory_log": initial_log,
                "supplier_invoice": self.invoice,
                "method": "child_log_tracing",
            }
        ]

        cmd = RepairCommand()
        result = cmd._batch_link_supplier_invoices(batch_items)
        self.assertEqual(result["parent_logs_linked"], 1)
        self.assertEqual(result["child_logs_updated"], 1)

        initial_log.refresh_from_db()
        sale_log.refresh_from_db()
        self.assertEqual(initial_log.supplier_invoice, self.invoice)
        self.assertEqual(sale_log.supplier_invoice, self.invoice)
