"""Unit tests for the setting app (models and views)."""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from Billing.tests.helpers import create_test_user
from setting.models import (
    BarcodeConfiguration,
    PaymentDetails,
    ReportConfiguration,
    ShopDetails,
)


class ShopDetailsModelTestCase(TestCase):
    """Test ShopDetails model methods, string processing, and properties."""

    def setUp(self):
        self.user = create_test_user(is_staff=True, is_superuser=True)
        self.shop = ShopDetails.objects.create(
            shop_name="my test boutique",
            first_line="123 main street",
            second_line="suite 4",
            city="shahapur",
            state="karnataka",
            pincode="585223",
            country="india",
            gst_no="29abcde1234f1z5",
            phone_number="9876543210",
            phone_two="9123456789",
            email="SHOP@EXAMPLE.COM",
            created_by=self.user,
        )

    def test_shop_details_save_formatting(self):
        """Verify save() formats title-case, lowercase email, and uppercase GST."""
        self.assertEqual(self.shop.shop_name, "My Test Boutique")
        self.assertEqual(self.shop.first_line, "123 Main Street")
        self.assertEqual(self.shop.second_line, "Suite 4")
        self.assertEqual(self.shop.city, "Shahapur")
        self.assertEqual(self.shop.state, "Karnataka")
        self.assertEqual(self.shop.email, "shop@example.com")
        self.assertEqual(self.shop.gst_no, "29ABCDE1234F1Z5")

    def test_shop_details_address_and_contact_properties(self):
        """Verify address and contact properties."""
        self.assertIn("123 Main Street", self.shop.full_address)
        self.assertIn("Shahapur", self.shop.full_address)
        self.assertEqual(
            self.shop.address_line_one, "123 Main Street, Suite 4"
        )
        self.assertEqual(
            self.shop.address_line_two, "Shahapur, Karnataka - 585223"
        )
        self.assertEqual(self.shop.short_address, "Shahapur, Karnataka - 585223")
        self.assertIn("9876543210", self.shop.contact_info)
        self.assertIn("9123456789", self.shop.contact_info)


class ReportConfigurationModelTestCase(TestCase):
    """Test ReportConfiguration model methods, default handling, and single default rule."""

    def setUp(self):
        self.user = create_test_user(is_staff=True, is_superuser=True)
        self.config1 = ReportConfiguration.objects.create(
            report_type=ReportConfiguration.ReportType.INVOICE,
            paper_size=ReportConfiguration.PaperSize.A5,
            is_default=True,
            created_by=self.user,
        )

    def test_default_config_creation(self):
        """Test getting and creating default report config."""
        default_cfg = ReportConfiguration.get_default_config(
            ReportConfiguration.ReportType.INVOICE
        )
        self.assertEqual(default_cfg.pk, self.config1.pk)

        # Non-existing report type creates default
        estimate_cfg = ReportConfiguration.get_default_config(
            ReportConfiguration.ReportType.ESTIMATE
        )
        self.assertTrue(estimate_cfg.is_default)
        self.assertEqual(estimate_cfg.report_type, ReportConfiguration.ReportType.ESTIMATE)

    def test_single_default_config_enforcement(self):
        """Creating a new default config resets existing default config for same report type."""
        config2 = ReportConfiguration.objects.create(
            report_type=ReportConfiguration.ReportType.INVOICE,
            paper_size=ReportConfiguration.PaperSize.A4,
            is_default=True,
            created_by=self.user,
        )
        self.config1.refresh_from_db()
        self.assertFalse(self.config1.is_default)
        self.assertTrue(config2.is_default)

    def test_default_text_properties(self):
        """Test default terms and conditions and thank you messages."""
        self.assertIn("Goods Once Sold", self.config1.default_terms_conditions)
        self.assertEqual(self.config1.default_thank_you_message, "Thank You Please Visit Again")

        self.config1.terms_conditions = "Custom Terms"
        self.config1.thank_you_message = "Custom Thanks"
        self.assertEqual(self.config1.default_terms_conditions, "Custom Terms")
        self.assertEqual(self.config1.default_thank_you_message, "Custom Thanks")


class PaymentDetailsModelTestCase(TestCase):
    """Test PaymentDetails model clean validation, formatting, and defaults."""

    def setUp(self):
        self.user = create_test_user(is_staff=True, is_superuser=True)
        self.shop = ShopDetails.objects.create(
            shop_name="Payment Test Shop",
            first_line="Line 1",
            city="City",
            state="State",
            pincode="123456",
            phone_number="9876543210",
        )

    def test_upi_validation(self):
        """UPI payment type requires upi_id."""
        payment = PaymentDetails(
            shop=self.shop,
            payment_name="UPI Counter",
            payment_type=PaymentDetails.PaymentType.UPI,
            upi_id="",
        )
        with self.assertRaises(ValidationError):
            payment.clean()

    def test_bank_account_validation(self):
        """Bank Account payment type requires account_number and ifsc_code."""
        payment = PaymentDetails(
            shop=self.shop,
            payment_name="Bank Account",
            payment_type=PaymentDetails.PaymentType.BANK_ACCOUNT,
            account_number="",
            ifsc_code="",
        )
        with self.assertRaises(ValidationError):
            payment.clean()

    def test_single_default_payment_per_shop(self):
        """Only one default payment per shop."""
        p1 = PaymentDetails.objects.create(
            shop=self.shop,
            payment_name="UPI 1",
            payment_type=PaymentDetails.PaymentType.UPI,
            upi_id="shop@upi",
            is_default=True,
        )
        p2 = PaymentDetails.objects.create(
            shop=self.shop,
            payment_name="UPI 2",
            payment_type=PaymentDetails.PaymentType.UPI,
            upi_id="shop2@upi",
            is_default=True,
        )
        p1.refresh_from_db()
        self.assertFalse(p1.is_default)
        self.assertTrue(p2.is_default)

    def test_payment_info_formatting(self):
        """Test payment_info and bank_details_formatted properties."""
        p = PaymentDetails.objects.create(
            shop=self.shop,
            payment_name="Main Bank",
            payment_type=PaymentDetails.PaymentType.BANK_ACCOUNT,
            account_holder_name="test holder",
            bank_name="sbi",
            account_number="1234567890",
            ifsc_code="sbin0001234",
            branch_name="main branch",
        )
        self.assertEqual(p.account_holder_name, "Test Holder")
        self.assertEqual(p.bank_name, "Sbi")
        self.assertEqual(p.ifsc_code, "SBIN0001234")
        self.assertIn("A/C No: 1234567890", p.bank_details_formatted)
        self.assertIn("A/C: 1234567890", p.payment_info)


class BarcodeConfigurationModelTestCase(TestCase):
    """Test BarcodeConfiguration dimensions and heading properties."""

    def setUp(self):
        self.shop = ShopDetails.objects.create(
            shop_name="Barcode Shop",
            first_line="Street 1",
            city="City",
            state="State",
            pincode="123456",
            phone_number="9876543210",
        )
        self.config = BarcodeConfiguration.objects.create(
            shop=self.shop,
            config_name="Medium Label",
            label_size=BarcodeConfiguration.LabelSize.MEDIUM,
            is_default=True,
        )

    def test_actual_label_dimensions(self):
        """Verify width and height parsing for label sizes."""
        self.assertEqual(self.config.actual_label_width, 38.0)
        self.assertEqual(self.config.actual_label_height, 25.0)

        custom_config = BarcodeConfiguration.objects.create(
            shop=self.shop,
            config_name="Custom Label",
            label_size=BarcodeConfiguration.LabelSize.CUSTOM,
            custom_label_width=Decimal("60.50"),
            custom_label_height=Decimal("30.25"),
        )
        self.assertEqual(custom_config.actual_label_width, 60.50)
        self.assertEqual(custom_config.actual_label_height, 30.25)

    def test_display_heading(self):
        """Verify heading text or fallback to shop name."""
        self.assertEqual(self.config.display_heading, "Barcode Shop")
        self.config.heading_text = "Custom Heading"
        self.assertEqual(self.config.display_heading, "Custom Heading")


class SettingViewsTestCase(TestCase):
    """Test views in setting app."""

    def setUp(self):
        self.user = create_test_user(is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.shop = ShopDetails.objects.create(
            shop_name="Dashboard Shop",
            first_line="Line 1",
            city="City",
            state="State",
            pincode="123456",
            phone_number="9876543210",
        )

    def test_shop_settings_dashboard(self):
        """Test shop settings dashboard renders successfully."""
        response = self.client.get(reverse("setting:shop_settings_dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_shop_details_crud_views(self):
        """Test listing, creating, editing shop details."""
        res_list = self.client.get(reverse("setting:shop_details_list"))
        self.assertEqual(res_list.status_code, 200)

        res_detail = self.client.get(
            reverse("setting:shop_details_detail", kwargs={"pk": self.shop.pk})
        )
        self.assertEqual(res_detail.status_code, 200)

        res_create_get = self.client.get(reverse("setting:shop_details_create"))
        self.assertEqual(res_create_get.status_code, 200)

    def test_report_config_views(self):
        """Test report config listing and setting default via AJAX and standard POST."""
        config1 = ReportConfiguration.objects.create(
            report_type=ReportConfiguration.ReportType.INVOICE,
            paper_size=ReportConfiguration.PaperSize.A4,
            is_default=False,
        )
        res_list = self.client.get(reverse("setting:report_config_list"))
        self.assertEqual(res_list.status_code, 200)

        # Test AJAX request
        res_default_ajax = self.client.post(
            reverse("setting:set_default_config", kwargs={"pk": config1.pk}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(res_default_ajax.status_code, 200)
        self.assertTrue(res_default_ajax.json()["success"])
        config1.refresh_from_db()
        self.assertTrue(config1.is_default)

        # Test standard form POST request
        config2 = ReportConfiguration.objects.create(
            report_type=ReportConfiguration.ReportType.INVOICE,
            paper_size=ReportConfiguration.PaperSize.A5,
            is_default=False,
        )
        res_default_form = self.client.post(
            reverse("setting:set_default_config", kwargs={"pk": config2.pk})
        )
        self.assertEqual(res_default_form.status_code, 302)
        config2.refresh_from_db()
        self.assertTrue(config2.is_default)

