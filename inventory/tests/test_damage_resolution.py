from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from inventory.models import (
    Category,
    ClothType,
    DamagedItemRecord,
    GSTHsnCode,
    InventoryLog,
    Product,
    ProductVariant,
    UOM,
)
from inventory.services import DamageResolutionService, InventoryService
from supplier.models import Supplier, SupplierInvoice

User = get_user_model()


class DamageResolutionServiceTestCase(TestCase):
    """Unit tests for InventoryService.damage_log and DamageResolutionService."""

    def setUp(self):
        self.user = User.objects.create_user(
            first_name="TestUser",
            phone_number="9876543210",
            password="password123",
        )
        self.hsn = GSTHsnCode.objects.create(
            code="12345678",
            gst_percentage=Decimal("5.00"),
        )
        self.category = Category.objects.create(name="Clothing")
        self.cloth_type = ClothType.objects.create(name="Cotton")
        self.uom = UOM.objects.create(name="Piece", short_code="PCS", category="Quantity")

        self.product = Product.objects.create(
            brand="BrandA",
            name="Shirt",
            category=self.category,
            cloth_type=self.cloth_type,
            uom=self.uom,
            hsn_code=self.hsn,
        )

        self.variant = ProductVariant.objects.create(
            product=self.product,
            purchase_price=Decimal("100.00"),
            mrp=Decimal("200.00"),
            quantity=Decimal("50.00"),
            damaged_quantity=Decimal("0.00"),
        )

        self.supplier = Supplier.objects.create(
            name="Main Supplier",
            phone="9876543210",
        )
        self.invoice = SupplierInvoice.objects.create(
            supplier=self.supplier,
            invoice_number="INV-001",
            invoice_date="2026-01-01",
            sub_total=Decimal("1000.00"),
            total_amount=Decimal("1000.00"),
        )

    def test_damage_log_success(self):
        """Test marking items as damaged moves stock to damaged_quantity and creates DamagedItemRecord."""
        res = InventoryService.damage_log(
            variant=self.variant,
            quantity_damaged=Decimal("5.00"),
            user=self.user,
            notes="Torn packaging",
            damage_type="General",
            supplier_invoice=self.invoice,
        )

        self.assertTrue(res["success"])
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.quantity, Decimal("45.00"))
        self.assertEqual(self.variant.damaged_quantity, Decimal("5.00"))

        # Verify InventoryLog
        log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.DAMAGE,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.quantity_change, Decimal("-5.00"))

        # Verify DamagedItemRecord
        record = DamagedItemRecord.objects.filter(variant=self.variant).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.quantity, Decimal("5.00"))
        self.assertEqual(record.status, DamagedItemRecord.Status.PENDING)
        self.assertEqual(record.supplier, self.supplier)
        self.assertEqual(record.supplier_invoice, self.invoice)

    def test_damage_log_insufficient_stock(self):
        """Test that marking more than available stock raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            InventoryService.damage_log(
                variant=self.variant,
                quantity_damaged=Decimal("60.00"),
                user=self.user,
            )
        self.assertIn("Insufficient stock", str(ctx.exception))

    def test_return_to_supplier_without_money_modification(self):
        """Test returning damaged items links supplier & invoice without altering invoice totals."""
        InventoryService.damage_log(
            variant=self.variant,
            quantity_damaged=Decimal("10.00"),
            user=self.user,
            supplier_invoice=self.invoice,
        )
        record = DamagedItemRecord.objects.get(variant=self.variant)
        initial_invoice_total = self.invoice.total_amount

        # Return to supplier
        resolved_record = DamageResolutionService.return_to_supplier(
            record=record,
            supplier=self.supplier,
            user=self.user,
            notes="Returned to vendor",
            supplier_invoice=self.invoice,
        )

        self.assertEqual(resolved_record.status, DamagedItemRecord.Status.RETURNED)
        self.assertEqual(resolved_record.supplier, self.supplier)
        self.assertEqual(resolved_record.supplier_invoice, self.invoice)

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.damaged_quantity, Decimal("0.00"))

        # Invoice totals must NOT be altered
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.total_amount, initial_invoice_total)

    def test_repair_restores_available_stock_and_creates_inventory_log(self):
        """Test repairing damaged items restores sellable stock and creates an audit InventoryLog."""
        InventoryService.damage_log(
            variant=self.variant,
            quantity_damaged=Decimal("8.00"),
            user=self.user,
        )
        record = DamagedItemRecord.objects.get(variant=self.variant)

        # Perform repair
        resolved_record = DamageResolutionService.repair(
            record=record,
            user=self.user,
            notes="Restitched button",
            repair_cost=Decimal("15.00"),
        )

        self.assertEqual(resolved_record.status, DamagedItemRecord.Status.REPAIRED)
        self.assertEqual(resolved_record.repair_cost, Decimal("15.00"))

        self.variant.refresh_from_db()
        self.assertEqual(self.variant.quantity, Decimal("50.00"))  # Restored 42 + 8
        self.assertEqual(self.variant.damaged_quantity, Decimal("0.00"))

        # Verify audit InventoryLog created for restored stock
        repair_log = InventoryLog.objects.filter(
            variant=self.variant,
            transaction_type=InventoryLog.TransactionTypes.ADJUSTMENT_IN,
            quantity_change=Decimal("8.00"),
        ).first()
        self.assertIsNotNone(repair_log)
        self.assertIn("Repaired & restored", repair_log.notes)

    def test_write_off(self):
        """Test writing off damaged items reduces damaged_quantity and marks status as WRITTEN_OFF."""
        InventoryService.damage_log(
            variant=self.variant,
            quantity_damaged=Decimal("4.00"),
            user=self.user,
        )
        record = DamagedItemRecord.objects.get(variant=self.variant)

        resolved_record = DamageResolutionService.write_off(
            record=record,
            user=self.user,
            notes="Beyond repair",
        )

        self.assertEqual(resolved_record.status, DamagedItemRecord.Status.WRITTEN_OFF)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.damaged_quantity, Decimal("0.00"))

    def test_cannot_resolve_already_resolved_record(self):
        """Test that resolving an already resolved record raises ValueError."""
        InventoryService.damage_log(
            variant=self.variant,
            quantity_damaged=Decimal("3.00"),
            user=self.user,
        )
        record = DamagedItemRecord.objects.get(variant=self.variant)
        DamageResolutionService.write_off(record=record, user=self.user)

        # Attempt to repair or return again
        with self.assertRaises(ValueError):
            DamageResolutionService.repair(record=record, user=self.user)

    def test_filtered_and_grouped_damaged_stock(self):
        """Test filtering by area/supplier and grouping by shop name, invoice no, and amount."""
        self.supplier.city = "Secunderabad"
        self.supplier.save()

        supplier_b = Supplier.objects.create(
            name="Agarwal Sarees",
            phone="9876543211",
            city="Rikabgunj",
        )
        invoice_b = SupplierInvoice.objects.create(
            supplier=supplier_b,
            invoice_number="INV-002",
            invoice_date="2026-02-01",
            sub_total=Decimal("500.00"),
            total_amount=Decimal("500.00"),
        )

        # Create damage record for supplier A
        InventoryService.damage_log(
            variant=self.variant,
            quantity_damaged=Decimal("2.00"),
            user=self.user,
            supplier_invoice=self.invoice,
        )
        # Create damage record for supplier B
        InventoryService.damage_log(
            variant=self.variant,
            quantity_damaged=Decimal("3.00"),
            user=self.user,
            supplier_invoice=invoice_b,
        )

        # 1. Filter by Area
        area_records = DamageResolutionService.get_filtered_damaged_records({"area": "Secunderabad", "status": "ALL"})
        self.assertEqual(area_records.count(), 1)
        self.assertEqual(area_records.first().supplier.city, "Secunderabad")

        # 2. Filter by Supplier
        supplier_records = DamageResolutionService.get_filtered_damaged_records({"supplier": str(supplier_b.id), "status": "ALL"})
        self.assertEqual(supplier_records.count(), 1)
        self.assertEqual(supplier_records.first().supplier.name, "Agarwal Sarees")

        # 3. Grouped Damaged Stock
        grouped = DamageResolutionService.get_grouped_damaged_stock({"status": "ALL"})
        self.assertEqual(grouped["total_shops"], 2)
        self.assertEqual(grouped["total_records"], 2)
        self.assertEqual(grouped["overall_total_units"], Decimal("5.00"))
        # 5 units * 100 purchase_price = 500.00
        self.assertEqual(grouped["overall_total_amount"], Decimal("500.00"))

        # Verify shop groups structure
        shop_names = [g["shop_name"] for g in grouped["groups"]]
        self.assertIn("Main Supplier", shop_names)
        self.assertIn("Agarwal Sarees", shop_names)

        sec_group = next(g for g in grouped["groups"] if g["shop_name"] == "Main Supplier")
        self.assertEqual(sec_group["area"], "Secunderabad")
        self.assertEqual(sec_group["subtotal_quantity"], Decimal("2.00"))
        self.assertEqual(sec_group["subtotal_amount"], Decimal("200.00"))
        self.assertEqual(sec_group["items"][0]["invoice_number"], "INV-001")

    def test_damaged_stock_download_pdf(self):
        """Test downloading damaged stock via PDF endpoint in report app."""
        from django.contrib.auth.models import Permission
        from django.urls import reverse

        self.supplier.city = "Secunderabad"
        self.supplier.save()

        # Add view permission to user
        perm = Permission.objects.get(codename="view_productvariant")
        self.user.user_permissions.add(perm)

        InventoryService.damage_log(
            variant=self.variant,
            quantity_damaged=Decimal("2.00"),
            user=self.user,
            supplier_invoice=self.invoice,
        )

        self.client.force_login(self.user)

        # Test PDF download (report app)
        rep_pdf_url = reverse("report:damaged_stock_pdf")
        rep_pdf_resp = self.client.get(rep_pdf_url, {"area": "Secunderabad", "status": "ALL"})
        self.assertEqual(rep_pdf_resp.status_code, 200)
        self.assertEqual(rep_pdf_resp["Content-Type"], "application/pdf")

