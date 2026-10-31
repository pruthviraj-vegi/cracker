"""Report views for generating PDFs, invoices, barcodes, and reports."""

# pylint: disable=too-many-locals
import base64
import io
import logging
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import qrcode
from django.conf import settings
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.template.loader import get_template
from weasyprint import HTML

from barcode import Code128
from barcode.base import Barcode
from barcode.writer import SVGWriter

from base.getDates import getDates

from cart.models import Cart, CartItem
from customer.models import Customer
from customer.views import get_data as get_customers_data
from customer.services import (
    _build_ledger_rows as build_ledger_rows,
    get_opening_balance,
)
from customer.views_credit import (
    credit_customers_data as get_credit_customers_data,
    total_credit_customers_data as get_total_credit_outstanding,
)

from inventory.models import ProductVariant
from inventory.services import get_variants_data, total_inventory_value

from invoice.models import Invoice, InvoiceItem
from setting.models import (
    ShopDetails,
    ReportConfiguration,
    PaymentDetails,
    BarcodeConfiguration,
)
from supplier.models import Supplier, SupplierInvoice
from supplier.views import get_suppliers_data, get_total_outstanding_balance, get_supplier_report_data

from .helper import build_invoice_report_context

logger = logging.getLogger(__name__)

Barcode.default_writer_options["write_text"] = False

try:
    from api.cloudflare import upload_pdf_to_r2, BucketType, R2StorageError
except Exception:  # pylint: disable=broad-exception-caught
    logger.error("Failed to import R2 modules")
    raise


def _render_pdf_html(template_name, context, report_type="INVOICE"):
    """Prepare HTML string ready for WeasyPrint.

    Shared pipeline: injects shop details, report config, renders the
    template, and replaces the QR-code placeholder if present.

    Args:
        template_name: Template filename inside ``report/``.
        context: Template context dict (mutated in-place).
        report_type: ``INVOICE``, ``STATEMENT``, or ``ESTIMATE``.

    Returns:
        Rendered HTML string.
    """
    context["shop_details"] = ShopDetails.get_active()
    context["report_config"] = ReportConfiguration.get_default_config(report_type)

    html = get_template(f"report/{template_name}").render(context)

    if "qrcode" in context:
        html = html.replace(
            "{{ qrcode }}",
            f'<img src="data:image/png;base64, {context["qrcode"]}"/>',
        )
    return html


def generate_pdf(
    template_name,
    _file_name,
    context,
    report_type="INVOICE",
    upload_to_r2=False,
):
    """Generate PDF and optionally upload to R2 storage.

    Args:
        template_name: Name of the template to render.
        _file_name: Reserved for future use (filename hint).
        context: Template context dictionary.
        report_type: Type of report (INVOICE or STATEMENT).
        upload_to_r2: Set to True when you want to upload this specific PDF.
    """
    html = _render_pdf_html(template_name, context, report_type)

    pdf_file = HTML(string=html, base_url=str(settings.STATIC_ROOT)).write_pdf(
        presentational_hints=True
    )

    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    # Upload to R2 only if requested
    if upload_to_r2:
        try:
            pdf_buffer = BytesIO(pdf_file)
            bucket_type = (
                BucketType.INVOICE if report_type == "INVOICE" else BucketType.STATEMENT
            )

            r2_url = upload_pdf_to_r2(
                file_obj=pdf_buffer,
                filename=filename,
                bucket_type=bucket_type,
            )

            logger.debug("PDF uploaded to R2: %s", r2_url)
            return r2_url

        except R2StorageError as exc:
            logger.error("Failed to upload PDF to R2: %s", exc)
            return None

    # Return HTTP response
    response = HttpResponse(pdf_file, content_type="application/pdf")
    response["Content-Disposition"] = f'filename="{filename}"'
    response["pdfkit-dpi"] = "800"
    return response


def generate_pdf_bytes(template_name, context, base_url=None):
    """Return raw PDF bytes — used by Celery tasks (no HttpResponse, no R2)."""
    report_type = context.get("report_type", "INVOICE")
    html = _render_pdf_html(template_name, context, report_type)

    return HTML(string=html, base_url=base_url or str(settings.STATIC_ROOT)).write_pdf(
        presentational_hints=True
    )


def create_invoice(request, pk):
    """Create and render an invoice page for the given invoice ID."""
    template = None

    invoice = Invoice.objects.select_related("customer", "created_by").get(id=pk)
    values = (
        InvoiceItem.objects.filter(invoice__id=pk)
        .select_related(
            "product_variant__product__category",
            "product_variant__product__uom",
            "product_variant__size",
            "product_variant__color",
        )
        .prefetch_related("return_items__return_invoice")
    )

    # Get shop details and report configuration
    shop_details = ShopDetails.get_active()
    report_config = ReportConfiguration.get_default_config(
        ReportConfiguration.ReportType.INVOICE
    )
    payment_details = (
        PaymentDetails.get_active_payments(shop=shop_details)
        .order_by("display_order")
        .first()
    )

    if report_config.paper_size == "58mm":
        template = "report/58mm.html"
    elif report_config.paper_size == "80mm":
        template = "report/80mm.html"
    else:
        template = "report/A5.html"

    context = {
        "values": values,
        "details": invoice,
        "shop_details": shop_details,
        "report_config": report_config,
        "payment_details": payment_details,
    }

    # Generate QR code if enabled in config
    if (
        report_config
        and report_config.show_qr_code
        and payment_details
        and payment_details.upi_id
    ):
        try:
            # Create UPI payment QR code
            qr_data = (
                f"upi://pay?pa={payment_details.upi_id}"
                f"&pn={shop_details.shop_name}"
                f"&am={invoice.net_amount_due}"
                f"&tn=for bill no {invoice.invoice_number}"
                f"&cu=INR"
            )
            qr_code = qrcode.make(qr_data)
            image_bytes = io.BytesIO()
            qr_code.save(image_bytes, format="PNG")
            context["qrcode"] = base64.b64encode(image_bytes.getvalue()).decode()
        except (ValueError, OSError) as exc:
            logger.error("Error generating QR code: %s", exc)

    return render(request, template, context)


def estimate_invoice(request, pk):
    """Render an estimate invoice page for the given estimate ID."""
    template = "report/estimate.html"
    estimate = Cart.objects.get(id=pk)
    values = CartItem.objects.filter(cart__id=pk).select_related(
        "product_variant__product"
    )
    shop_details = ShopDetails.get_active()
    report_config = ReportConfiguration.get_default_config(
        ReportConfiguration.ReportType.ESTIMATE
    )
    context = {
        "values": values,
        "details": estimate,
        "shop_details": shop_details,
        "report_config": report_config,
    }
    return render(request, template, context)


def generate_barcode(request, pk):
    """Generate and render a barcode page for the given product variant."""
    template = "report/barcode.html"
    variant = ProductVariant.objects.get(id=pk)
    shop_details = ShopDetails.get_active()
    code128 = Code128(variant.barcode, writer=SVGWriter())
    buffer = io.BytesIO()
    code128.write(buffer)
    buffer.seek(0)
    barcode_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

    barcode_config = BarcodeConfiguration.get_active_barcodes(shop_details).first()

    # Add the barcode image to the context dictionary
    context = {
        "values": variant,
        "print_count": variant.get_barcode_qty,
        "barcode_svg": barcode_image,
        "shop_details": shop_details,
        "barcode_config": barcode_config,
    }
    return render(request, template, context)


def generate_customers_pdf(request):
    """Generate PDF for customers list with search and sort parameters."""

    # Reuse the same query logic as the customer list view
    customers = get_customers_data(request)

    # Prepare context
    context = {
        "customers": customers,
        "total_count": customers.count(),
    }

    # Render template
    template = "customer_pdf.html"

    filename = "customers"

    return generate_pdf(template, filename, context)


def generate_credit_pdf(request):
    """Generate PDF for credit customers list with search and sort parameters."""
    customers = get_credit_customers_data(request)
    total_outstanding = get_total_credit_outstanding(request)

    if isinstance(customers, list):
        count = len(customers)
    else:
        count = customers.count()

    # Prepare context
    context = {
        "customers": customers,
        "total_count": count,
        "total_outstanding": total_outstanding,
    }

    # Render template
    template = "customer_credit.html"
    filename = "credit_customers"

    return generate_pdf(template, filename, context)


def generate_credit_ind_pdf(request, pk):
    """Generate PDF for credit individual customer with search and sort parameters."""
    customer = get_object_or_404(Customer, pk=pk)
    start_date, end_date = getDates(request)
    ledger = build_ledger_rows(customer, start_date, end_date)
    opening_balance = get_opening_balance(customer, start_date)

    ledger.sort(key=lambda r: (r["date"] or datetime.min, r["type"]))

    balance = opening_balance
    for i in ledger:
        balance += i["credit"] - i["debit"]
        i["balance"] = balance

    context = {
        "customer": customer,
        "ledger": ledger,
        "start_date": start_date,
        "end_date": end_date,
        "opening_balance": opening_balance,
    }
    template = "customer_credit_ind.html"
    filename = "credit_individual_customer"
    return generate_pdf(template, filename, context)


def generate_suppliers_pdf(request):
    """Generate PDF for suppliers list with search and sort parameters."""
    suppliers = get_suppliers_data(request)

    if isinstance(suppliers, list):
        count = len(suppliers)
        total_outstanding = sum(
            (s.annotated_balance_due for s in suppliers), Decimal("0.00")
        )
    else:
        count = suppliers.count()
        total_outstanding = suppliers.aggregate(
            total=Coalesce(Sum("annotated_balance_due"), Value(Decimal("0.00")))
        )["total"]

    # Prepare context
    context = {
        "suppliers": suppliers,
        "total_count": count,
        "total_outstanding": total_outstanding,
    }

    # Render template
    template = "suppliers_pdf.html"
    filename = "suppliers"

    return generate_pdf(template, filename, context)


def generate_variants_pdf(request):
    """Generate PDF for variants list with search and sort parameters."""
    variants = get_variants_data(request)
    total_outstanding = total_inventory_value()
    total_count = variants.count()

    # Prepare context
    context = {
        "variants": variants,
        "total_outstanding": total_outstanding,
        "total_count": total_count,
    }

    # Render template
    template = "variants_pdf.html"
    filename = "variants"

    return generate_pdf(template, filename, context)


def build_variants_context(params):
    """Pure function — no request needed.

    Builds the full context dict for the variants PDF template using
    filter/sort parameters stored in PdfJob.parameters.

    Args:
        params: dict with optional keys: search, category, color,
                size, status, stock, sort.
    """
    variants = get_variants_data(params=params)
    return {
        "variants": variants,
        "total_outstanding": total_inventory_value(),
        "total_count": variants.count(),
    }


def generate_purchase_orders_pdf(request):
    """Generate PDF for purchase order list with search and sort parameters."""

    start_date, end_date = getDates(request)

    purchase_orders = SupplierInvoice.objects.filter(
        is_deleted=False,
        invoice_type=SupplierInvoice.InvoiceType.GST_APPLICABLE,
        invoice_date__range=(start_date, end_date),
    ).select_related("supplier")

    total_count = purchase_orders.count()

    # Use Coalesce to handle NULL values properly
    aggregates = purchase_orders.aggregate(
        total_subtotal=Coalesce(Sum("sub_total"), Decimal("0.00")),
        total_cgst=Coalesce(Sum("cgst_amount"), Decimal("0.00")),
        total_igst=Coalesce(Sum("igst_amount"), Decimal("0.00")),
        total_amount=Coalesce(Sum("total_amount"), Decimal("0.00")),
        total_adjustment=Coalesce(Sum("adjustment_amount"), Decimal("0.00")),
    )

    context = {
        "data": purchase_orders,
        "total_count": total_count,
        "total_subtotal": aggregates["total_subtotal"],
        "total_cgst": aggregates["total_cgst"] * 2,  # CGST + SGST
        "total_igst": aggregates["total_igst"],
        "total_amount": aggregates["total_amount"],
        "total_adjustment": aggregates["total_adjustment"],
        "start_date": start_date,
        "end_date": end_date,
    }

    template = "supplier_purchased_pdf.html"
    filename = "purchase_orders"
    return generate_pdf(template, filename, context)


def generate_supplier_ind_pdf(request, pk):
    """Generate PDF for individual supplier purchase order with search and sort parameters."""
    supplier = get_object_or_404(Supplier, pk=pk)
    start_date, end_date = getDates(request)
    date_range = [start_date, end_date]
    report_data = get_supplier_report_data(supplier, date_range)

    context = {
        "supplier": supplier,
        "transactions": report_data["transactions"],
        "total_invoiced": report_data["total_invoiced"],
        "total_paid": report_data["total_paid"],
        "outstanding_balance": report_data["outstanding_balance"],
        "opening_balance": report_data["opening_balance"],
        "start_date": start_date,
        "end_date": end_date,
    }
    template = "supplier_ind_report_pdf.html"
    filename = "supplier_individual_report"

    return generate_pdf(template, filename, context)


def generate_invoice_report_pdf(request):
    """Generate a comprehensive invoice report PDF including cancelled and returned invoices."""
    start_date, end_date = getDates(request)
    context = build_invoice_report_context(start_date, end_date)

    template = "invoice_report_pdf.html"
    filename = (
        f"invoice_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
    )
    return generate_pdf(template, filename, context)


from django.http import JsonResponse
from .printing import (
    send_to_network_printer,
    format_invoice_for_direct_print,
    format_estimate_for_direct_print,
)

def direct_print_invoice(request, pk):
    """Directly print invoice to configured network printer."""
    invoice = get_object_or_404(Invoice, id=pk)

    # Get active shop details and configuration
    shop_details = ShopDetails.get_active()
    report_config = ReportConfiguration.get_default_config(
        ReportConfiguration.ReportType.INVOICE
    )

    # Determine printer configuration (prefer ReportConfiguration, fallback to ShopDetails)
    is_enabled = bool(report_config.is_direct_print_enabled) or bool(
        shop_details and getattr(shop_details, 'is_direct_print_enabled', False)
    )
    printer_ip = (
        report_config.printer_ip
        or (shop_details and getattr(shop_details, 'printer_ip', None))
    )
    printer_port = (
        report_config.printer_port
        or (shop_details and getattr(shop_details, 'printer_port', 9100))
        or 9100
    )

    if not is_enabled or not printer_ip:
        return JsonResponse({
            "success": False,
            "error": "Direct printing is not enabled or printer IP is not configured in Settings."
        }, status=400)

    # Check paper size/width
    width = 32 if report_config.paper_size == "58mm" else 48

    try:
        print_data = format_invoice_for_direct_print(invoice, shop_details, report_config, width=width)
    except Exception as e:
        logger.exception("Error formatting invoice for direct print")
        return JsonResponse({
            "success": False,
            "error": f"Error formatting invoice: {str(e)}"
        }, status=500)

    # Send to printer
    success, err_msg = send_to_network_printer(
        printer_ip,
        printer_port,
        print_data
    )
    
    if success:
        return JsonResponse({"success": True, "message": "Invoice sent to printer successfully."})
    else:
        return JsonResponse({"success": False, "error": err_msg}, status=500)


def direct_print_estimate(request, pk):
    """Directly print estimate (cart) to configured network printer."""
    cart = get_object_or_404(Cart, id=pk)
    
    # Get active shop details and configuration
    shop_details = ShopDetails.get_active()
    report_config = ReportConfiguration.get_default_config(
        ReportConfiguration.ReportType.ESTIMATE
    )

    # Determine printer configuration (prefer ReportConfiguration, fallback to ShopDetails)
    printer_ip = (
        report_config.printer_ip
        or (shop_details and getattr(shop_details, 'printer_ip', None))
    )
    printer_port = (
        report_config.printer_port
        or (shop_details and getattr(shop_details, 'printer_port', 9100))
        or 9100
    )

    is_enabled = bool(report_config.is_direct_print_enabled) or bool(
        shop_details and getattr(shop_details, 'is_direct_print_enabled', False)
    )
    if not is_enabled or not printer_ip:
        return JsonResponse({
            "success": False,
            "error": "Direct printing is not enabled or printer IP is not configured in Settings."
        }, status=400)

    # Check paper size/width
    width = 32 if report_config.paper_size == "58mm" else 48

    try:
        print_data = format_estimate_for_direct_print(cart, shop_details, report_config, width=width)
    except Exception as e:
        logger.exception("Error formatting estimate for direct print")
        return JsonResponse({
            "success": False,
            "error": f"Error formatting estimate: {str(e)}"
        }, status=500)

    # Send to printer
    success, err_msg = send_to_network_printer(
        printer_ip,
        printer_port,
        print_data
    )
    
    if success:
        return JsonResponse({"success": True, "message": "Estimate sent to printer successfully."})
    else:
        return JsonResponse({"success": False, "error": err_msg}, status=500)


def generate_damaged_stock_pdf(request):
    """Generate PDF for damaged stock grouped by shop name (supplier), invoice no, and date."""
    from inventory.services import DamageResolutionService

    data = DamageResolutionService.get_grouped_damaged_stock(request.GET)
    shop_details = (
        ShopDetails.objects.filter(is_active=True).first()
        or ShopDetails.objects.first()
    )

    context = {
        "shop_details": shop_details,
        "groups": data["groups"],
        "overall_total_units": data["overall_total_units"],
        "overall_total_amount": data["overall_total_amount"],
        "total_shops": data["total_shops"],
        "total_records": data["total_records"],
        "active_filters": data["active_filters"],
    }

    template = "damaged_stock_pdf.html"
    filename = "damaged_stock"
    return generate_pdf(template, filename, context)
