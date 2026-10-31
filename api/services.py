"""Service layer for generating and caching PDF reports (invoices, statements)."""

import base64
import io
import logging
from datetime import datetime

import qrcode
from django.contrib.auth.views import login_not_required

from api.cloudflare import check_file_exists, BucketType
from base.utility import resolve_user
from customer.services import _build_ledger_rows, get_opening_balance
from invoice.models import InvoiceItem
from report.models import InvoicePDF, CustomerStatementPDF
from report.views import generate_pdf
from setting.models import ShopDetails, ReportConfiguration, PaymentDetails

logger = logging.getLogger(__name__)


@login_not_required
def generate_invoice_pdf(invoice, request):
    """
    Generate or retrieve cached PDF for the given invoice.

    Args:
        invoice: Invoice object to generate PDF for
        request: Django request object

    Returns:
        dict: Dictionary containing PDF information with keys:
            - url: PDF URL
            - generated_at: ISO format timestamp
            - pdf_status: 'cached' or 'newly_generated'
            - filename: PDF filename

    Raises:
        RuntimeError: If PDF generation or upload fails
    """
    # Check if valid PDF exists (not outdated)
    existing_pdf = InvoicePDF.get_valid_pdf(invoice)
    if existing_pdf and check_file_exists(existing_pdf.pdf_url):
        return {
            "url": existing_pdf.pdf_url,
            "generated_at": existing_pdf.generated_at.isoformat(),
            "pdf_status": "cached",
            "filename": existing_pdf.filename,
        }

    # PDF doesn't exist, is outdated, or URL is invalid; generate new one

    values = (
        InvoiceItem.objects.by_invoice(invoice)
        .select_related(
            "product_variant__product__category",
            "product_variant__product__uom",
            "product_variant__size",
            "product_variant__color",
        )
        .prefetch_related("return_items__return_invoice")
    )

    shop_details = ShopDetails.get_active()
    report_config = ReportConfiguration.get_default_config(
        ReportConfiguration.ReportType.INVOICE
    )
    payment_details = (
        PaymentDetails.get_active_payments(shop=shop_details)
        .order_by("display_order")
        .first()
    )

    template = "A5_pdf.html"

    context = {
        "values": values,
        "details": invoice,
        "shop_details": shop_details,
        "report_config": report_config,
        "payment_details": payment_details,
    }

    # Generate QR code if enabled

    if (
        report_config
        and report_config.show_qr_code
        and payment_details
        and payment_details.upi_id
    ):
        try:
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

    filename = f"{invoice.invoice_number}"

    pdf_response = generate_pdf(
        template, filename, context, report_type="INVOICE", upload_to_r2=True
    )

    if not pdf_response:
        logger.error("Failed to generate PDF")
        raise RuntimeError("Failed to generate PDF")

    pdf_url = pdf_response
    logger.info("PDF generated: %s", pdf_url)

    # Create new PDF record with current invoice timestamp
    pdf_record = InvoicePDF.create_pdf_record(
        invoice=invoice,
        pdf_url=pdf_url,
        filename=f"{filename}.pdf",
        generated_by=resolve_user(request),
    )

    data = {
        "url": pdf_record.pdf_url,
        "generated_at": pdf_record.generated_at.isoformat(),
        "pdf_status": "newly_generated",
        "filename": pdf_record.filename,
    }

    return data


@login_not_required
def generate_statement_pdf(customer, start_date, end_date, request):
    """
    Generate statement PDF for the given customer and date range.

    Args:
        customer: Customer object to generate statement for
        start_date: Start date for the statement period
        end_date: End date for the statement period
        request: Django request object

    Returns:
        dict: Dictionary containing PDF information with keys:
            - url: PDF URL
            - generated_at: ISO format timestamp
            - pdf_status: 'newly_generated'
            - filename: PDF filename

    Raises:
        RuntimeError: If PDF generation or upload fails
    """
    # Build ledger data
    existing_pdf = CustomerStatementPDF.get_valid_pdf(
        customer, start_date, end_date, customer.credit_summary.balance_amount
    )

    if existing_pdf and check_file_exists(
        existing_pdf.pdf_url, bucket_type=BucketType.STATEMENT
    ):
        logger.debug(
            "Using cached statement PDF for customer %s (%s - %s)",
            customer.phone_number,
            start_date,
            end_date,
        )
        return {
            "url": existing_pdf.pdf_url,
            "generated_at": existing_pdf.generated_at.isoformat(),
            "pdf_status": "cached",
            "filename": existing_pdf.filename,
        }

    ledger = _build_ledger_rows(customer, start_date, end_date)
    opening_balance = get_opening_balance(customer, start_date)

    # Sort ledger by date and type
    ledger.sort(key=lambda r: (r["date"] or datetime.min, r["type"]))

    # Calculate running balance
    balance = opening_balance
    for i in ledger:
        balance += i["credit"] - i["debit"]
        i["balance"] = balance

    # Prepare context for PDF generation
    context = {
        "customer": customer,
        "ledger": ledger,
        "start_date": start_date,
        "end_date": end_date,
        "opening_balance": opening_balance,
    }

    template = "customer_credit_ind.html"
    filename = (
        f"statement ({start_date.strftime('%d-%m-%Y')}"
        f" - {end_date.strftime('%d-%m-%Y')})"
    )

    # Generate PDF with R2 upload enabled
    pdf_response = generate_pdf(
        template,
        filename,
        context,
        report_type="STATEMENT",
        upload_to_r2=True,
    )

    if not pdf_response:
        logger.error("Failed to generate statement PDF")
        raise RuntimeError("Failed to generate PDF")

    pdf_url = pdf_response
    logger.info("Statement PDF generated: %s", pdf_url)

    # Create new PDF record with current invoice timestamp
    CustomerStatementPDF.create_pdf_record(
        customer=customer,
        pdf_url=pdf_url,
        from_date=start_date,
        to_date=end_date,
        closing_balance=customer.credit_summary.balance_amount,
        filename=f"{filename}.pdf",
        generated_by=resolve_user(request),
    )

    data = {
        "url": pdf_url,
        "generated_at": datetime.now().isoformat(),
        "pdf_status": "newly_generated",
        "filename": f"{filename}.pdf",
    }
    return data
