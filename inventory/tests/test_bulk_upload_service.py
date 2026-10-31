"""Tests for BulkUploadService and CSV import."""

import io
from decimal import Decimal
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from Billing.tests.helpers import (
    create_test_user,
    create_test_supplier,
    create_test_supplier_invoice,
    create_test_category,
)
from inventory.models import BulkUpload, BulkUploadItem, Category, ClothType, GSTHsnCode
from inventory.services import BulkUploadService


class BulkUploadServiceCsvImportTests(TestCase):
    def setUp(self):
        self.user = create_test_user()
        self.supplier = create_test_supplier(user=self.user)
        self.invoice = create_test_supplier_invoice(supplier=self.supplier)
        self.batch = BulkUpload.objects.create(
            supplier_invoice=self.invoice,
            created_by=self.user,
        )
        self.category = create_test_category(name="Shirts")
        self.cloth_type = ClothType.objects.create(name="Cotton")
        self.hsn = GSTHsnCode.objects.create(code="6205", gst_percentage=Decimal("5.00"))

    def test_process_csv_import_success(self):
        csv_content = (
            "brand,name,category,cloth_type,uom,hsn_code,quantity,purchase_price,mrp,size,color,minimum_quantity\n"
            "Raymond,Classic White Shirt,Shirts,Cotton,,6205,10,500.00,899.00,L,White,2\n"
            "Peter England,Blue Casual Shirt,Shirts,Cotton,,6205,5,400.00,699.00,M,Blue,1\n"
        )
        uploaded = SimpleUploadedFile("items.csv", csv_content.encode("utf-8"), content_type="text/csv")
        result = BulkUploadService.process_csv_import(self.batch, uploaded)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_created"], 2)
        self.assertEqual(result["total_rows"], 2)
        self.assertEqual(len(result["errors"]), 0)
        self.assertEqual(BulkUploadItem.objects.filter(bulk_upload=self.batch).count(), 2)

        item = BulkUploadItem.objects.filter(bulk_upload=self.batch, brand="Raymond").first()
        self.assertIsNotNone(item)
        self.assertEqual(item.name, "Classic White Shirt")
        self.assertEqual(item.category, self.category)
        self.assertEqual(item.cloth_type, self.cloth_type)
        self.assertEqual(item.hsn_code, self.hsn)
        self.assertEqual(item.quantity, Decimal("10"))
        self.assertEqual(item.purchase_price, Decimal("500.00"))
        self.assertEqual(item.mrp, Decimal("899.00"))

    def test_process_csv_import_cp1252_encoding(self):
        raw_csv = (
            b"brand,name,category,cloth_type,uom,hsn_code,quantity,purchase_price,mrp,size,color,minimum_quantity\n"
            b"Raymond,Special Shirt \x96 Edition,Shirts,Cotton,,6205,2,450.00,750.00,,,0\n"
        )
        uploaded = SimpleUploadedFile("items.csv", raw_csv, content_type="text/csv")
        result = BulkUploadService.process_csv_import(self.batch, uploaded)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_created"], 1)

    def test_process_csv_import_missing_required_headers(self):
        csv_content = (
            "category,quantity,purchase_price\n"
            "Shirts,10,500.00\n"
        )
        uploaded = SimpleUploadedFile("items.csv", csv_content.encode("utf-8"), content_type="text/csv")
        result = BulkUploadService.process_csv_import(self.batch, uploaded)

        self.assertFalse(result["success"])
        self.assertIn("Missing required columns", result["message"])

    def test_process_csv_import_row_level_errors(self):
        csv_content = (
            "brand,name,quantity,purchase_price,mrp\n"
            ",Missing Brand,5,100,200\n"
            "BrandOnly,,5,100,200\n"
            "ValidBrand,ValidProduct,10,300,500\n"
        )
        uploaded = SimpleUploadedFile("items.csv", csv_content.encode("utf-8"), content_type="text/csv")
        result = BulkUploadService.process_csv_import(self.batch, uploaded)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_created"], 1)
        self.assertEqual(result["total_rows"], 3)
        self.assertEqual(len(result["errors"]), 2)

    def test_process_csv_import_empty_file(self):
        uploaded = SimpleUploadedFile("empty.csv", b"", content_type="text/csv")
        result = BulkUploadService.process_csv_import(self.batch, uploaded)

        self.assertFalse(result["success"])

    def test_process_csv_import_comma_and_formatted_numbers(self):
        csv_content = (
            "brand,name,quantity,purchase_price,mrp\n"
            "FormattedBrand,FormattedProduct,\"1,250\",\"1,500.50\",\"2,999.00\"\n"
        )
        uploaded = SimpleUploadedFile("formatted.csv", csv_content.encode("utf-8"), content_type="text/csv")
        result = BulkUploadService.process_csv_import(self.batch, uploaded)

        self.assertTrue(result["success"])
        self.assertEqual(result["rows_created"], 1)
        item = BulkUploadItem.objects.filter(bulk_upload=self.batch, brand="FormattedBrand").first()
        self.assertIsNotNone(item)
        self.assertEqual(item.quantity, Decimal("1250"))
        self.assertEqual(item.purchase_price, Decimal("1500.50"))
        self.assertEqual(item.mrp, Decimal("2999.00"))

    def test_detail_view_renders_successfully(self):
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        response = self.client.get(f"/inventory/bulk-upload/{self.batch.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Batch #{self.batch.id}")
        self.assertContains(response, "search-filter-section")
