"""Celery tasks for asynchronous customer message processing."""

import logging
from datetime import date, datetime

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from api.services import generate_invoice_pdf, generate_statement_pdf
from api.views import send_template
from customer.models import Payment
from invoice.models import Invoice
from notification.models import MessageLog, MessageStatusChoices
from notification.services import notify

logger = logging.getLogger(__name__)


def _parse_date(val):
    """Accept date object or flexible date string."""
    if isinstance(val, (datetime, timezone.datetime)):
        return val.date()
    if isinstance(val, date):
        return val
    if hasattr(val, "strftime") and not isinstance(val, str):
        return val
    from base.utility import parse_flexible_date
    res = parse_flexible_date(val)
    if res:
        return res
    return datetime.strptime(str(val), "%Y-%m-%d").date()


@shared_task(bind=True, max_retries=2)
def send_customer_message_task(self, log_id):
    """Execute customer message sending asynchronously via Celery.

    Supported message types:
      - 'statement': Generates statement PDF and sends WhatsApp template.
      - 'invoice': Generates invoice PDF and sends WhatsApp template.
      - 'balance': Sends balance details template.
      - 'payment': Sends payment receipt text template.
    """
    try:
        log = MessageLog.objects.select_related("customer", "user").get(id=log_id)
    except MessageLog.DoesNotExist:
        logger.error("MessageLog %s not found — aborting task.", log_id)
        return

    mtype = log.message_type
    customer = log.customer

    try:
        log.status = MessageStatusChoices.PROCESSING
        log.save(update_fields=["status"])

        payload = log.payload_data or {}
        response = None

        if mtype == "statement":
            start_date = _parse_date(payload["start_date"])
            end_date = _parse_date(payload["end_date"])
            pdf_data = generate_statement_pdf(customer, start_date, end_date, request=None)
            response = send_template(
                None,
                log.phone_number,
                settings.WA_STATEMENT_TEMPLATE,
                {
                    "customer_name": customer.name,
                    "from_date": start_date.strftime("%d-%m-%Y"),
                    "to_date": end_date.strftime("%d-%m-%Y"),
                },
                pdf_data["url"],
                pdf_data["filename"],
            )

        elif mtype == "invoice":
            invoice_id = payload.get("invoice_id")
            invoice = Invoice.objects.select_related("customer").get(pk=invoice_id)
            pdf_data = generate_invoice_pdf(invoice, request=None)
            response = send_template(
                None,
                log.phone_number,
                settings.WA_INVOICE_TEMPLATE,
                {
                    "customer_name": invoice.customer.name,
                    "invoice_number": invoice.invoice_number,
                },
                pdf_data["url"],
                pdf_data["filename"],
            )

        elif mtype == "balance":
            try:
                balance_amount = customer.credit_summary.balance_amount
            except Exception:
                balance_amount = 0.0

            today_str = timezone.now().strftime("%d-%m-%Y")
            response = send_template(
                None,
                log.phone_number,
                settings.WA_BALANCE_TEMPLATE,
                {
                    "customer_name": customer.name,
                    "balance": str(float(balance_amount)),
                    "date": today_str,
                },
                "",
                "",
            )

        elif mtype == "payment":
            payment_id = payload.get("payment_id")
            payment = Payment.objects.select_related("customer").get(pk=payment_id)
            response = send_template(
                None,
                log.phone_number,
                settings.WA_PAYMENT_TEMPLATE,
                {
                    "customer_name": payment.customer.name,
                    "amount": str(float(payment.amount)),
                    "date": payment.created_at.strftime("%d-%m-%Y"),
                    "payment_id": str(payment.id),
                },
                "",
                "",
            )

        else:
            raise ValueError(f"Unknown message type: {mtype}")

        if response and response.get("success") is True:
            log.status = MessageStatusChoices.SENT
            log.error_message = ""
            log.save(update_fields=["status", "error_message"])

            if log.user:
                notify(
                    user=log.user,
                    notification_type=f"{mtype}_sent",
                    title=f"{mtype.title()} Sent Successfully",
                    message=f"{mtype.title()} sent to customer {customer.name} ({log.phone_number}).",
                    linked_object=customer,
                )
            logger.info("MessageLog %s (%s) completed successfully.", log_id, mtype)
            return

        # Response indicates failure from WhatsApp CRM endpoint
        error_detail = (
            (response.get("detail") or response.get("message"))
            if response
            else "No response received"
        ) or "Failed to send message via WhatsApp CRM"
        raise RuntimeError(error_detail)

    except Exception as exc:
        logger.exception(
            "MessageLog %s failed (attempt %s): %s", log_id, self.request.retries + 1, exc
        )

        if self.request.retries < self.max_retries:
            log.status = MessageStatusChoices.PROCESSING
            log.error_message = f"Retry {self.request.retries + 1}: {str(exc)[:200]}"
            log.save(update_fields=["status", "error_message"])
            raise self.retry(exc=exc, countdown=10)

        # Final failure after retries
        log.status = MessageStatusChoices.FAILED
        log.error_message = str(exc)[:500]
        log.save(update_fields=["status", "error_message"])

        if log.user:
            notify(
                user=log.user,
                notification_type=f"{mtype}_failed",
                title=f"{mtype.title()} Delivery Failed",
                message=f"Could not send {mtype} to {customer.name}. Reason: {str(exc)[:200]}",
                linked_object=customer,
            )
