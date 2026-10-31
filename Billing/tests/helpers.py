"""
Shared test factory helpers to reduce setUp() boilerplate across all test files.
"""

from decimal import Decimal
from django.utils import timezone
from user.models import CustomUser
from customer.models import Customer
from inventory.models import Category, GSTHsnCode, Product, ProductVariant


_sequence_counter = 0


def _next_seq():
    global _sequence_counter
    _sequence_counter += 1
    return _sequence_counter


def create_test_user(phone_number=None, first_name="Test", is_staff=False, is_superuser=False):
    seq = _next_seq()
    if phone_number is None:
        phone_number = f"9999999{seq:04d}"[-10:]
    user = CustomUser.objects.create_user(
        phone_number=phone_number,
        first_name=first_name,
        password="testpass123",
    )
    if is_staff:
        user.is_staff = True
    if is_superuser:
        user.is_superuser = True
    if is_staff or is_superuser:
        user.save()
    return user


def create_test_customer(name=None, phone=None, created_by=None):
    seq = _next_seq()
    return Customer.objects.create(
        name=name or f"Test Customer {seq}",
        phone_number=phone or f"8888888{seq:04d}"[-10:],
        created_by=created_by,
    )


def create_test_category(name=None):
    seq = _next_seq()
    return Category.objects.create(name=name or f"Test Category {seq}")


def create_test_hsn_code(code=None, gst_percentage=Decimal("5.00")):
    seq = _next_seq()
    return GSTHsnCode.objects.create(
        code=code or f"HSN{seq:04d}",
        gst_percentage=gst_percentage,
    )


def create_test_product(brand=None, name=None, category=None, hsn_code=None, user=None):
    seq = _next_seq()
    if hsn_code is None:
        hsn_code = create_test_hsn_code()
    return Product.objects.create(
        brand=brand or f"Brand {seq}",
        name=name or f"Product {seq}",
        hsn_code=hsn_code,
        category=category or create_test_category(),
    )


def create_test_variant(product=None, barcode=None, purchase_price=Decimal("100.00"),
                        mrp=Decimal("180.00"), quantity=Decimal("50"), damaged_quantity=Decimal("0"),
                        user=None):
    seq = _next_seq()
    if product is None:
        product = create_test_product()
    return ProductVariant.objects.create(
        product=product,
        barcode=barcode or f"BAR{seq:06d}",
        purchase_price=purchase_price,
        mrp=mrp,
        quantity=quantity,
        damaged_quantity=damaged_quantity,
        created_by=user,
    )


def create_test_invoice(customer=None, sold_by=None, created_by=None,
                         amount=Decimal("1000.00"), payment_type="CASH",
                         payment_status="PAID"):
    from invoice.models import Invoice, get_next_sequence
    from invoice.choices import (
        PaymentTypeChoices, PaymentStatusChoices,
        InvoiceTypeChoices, GstTypeChoices,
    )
    seq = _next_seq()

    seq_type = Invoice.Invoice_type.CASH if payment_type == "CASH" else Invoice.Invoice_type.GST
    sequence_no, invoice_number = get_next_sequence(seq_type, "24-25")

    return Invoice.objects.create(
        customer=customer,
        sold_by=sold_by or created_by,
        created_by=created_by,
        sequence_no=sequence_no,
        invoice_number=invoice_number,
        amount=amount,
        invoice_type=InvoiceTypeChoices.GST,
        payment_type=getattr(PaymentTypeChoices, payment_type, PaymentTypeChoices.CASH),
        payment_status=getattr(PaymentStatusChoices, payment_status, PaymentStatusChoices.PAID),
        gst_type=GstTypeChoices.CGST_SGST,
        paid_amount=amount if payment_status == "PAID" else Decimal("0"),
    )


def create_test_invoice_item(invoice=None, product_variant=None, quantity=Decimal("5"),
                              unit_price=Decimal("180.00"), mrp=Decimal("180.00")):
    from invoice.models import InvoiceItem
    return InvoiceItem.objects.create(
        invoice=invoice,
        product_variant=product_variant,
        quantity=quantity,
        unit_price=unit_price,
        mrp=mrp,
        purchase_price=product_variant.purchase_price if product_variant else Decimal("100.00"),
    )


def create_test_payment(customer=None, amount=Decimal("500.00"), payment_type="PAID",
                         created_by=None, method="CASH"):
    from customer.models import Payment
    if created_by is None:
        created_by = create_test_user()
    return Payment.objects.create(
        customer=customer,
        amount=amount,
        payment_type=payment_type,
        created_by=created_by,
        method=method,
        unallocated_amount=amount,
    )


def create_test_supplier(name=None, phone=None, user=None):
    from supplier.models import Supplier
    seq = _next_seq()
    return Supplier.objects.create(
        name=name or f"Test Supplier {seq}",
        phone=phone or f"7777777{seq:04d}"[-10:],
        created_by=user,
    )


def create_test_supplier_invoice(supplier=None, invoice_number=None, total_amount=Decimal("5000.00")):
    from supplier.models import SupplierInvoice
    seq = _next_seq()
    return SupplierInvoice.objects.create(
        supplier=supplier,
        invoice_number=invoice_number or f"SUP-INV-{seq:04d}",
        total_amount=total_amount,
        sub_total=total_amount,
    )


def create_test_cart(name=None, user=None):
    from cart.models import Cart
    seq = _next_seq()
    return Cart.objects.create(
        name=name or f"Test Cart {seq}",
        created_by=user,
    )
