"""Views for handling customer statement, invoice, payment, and balance sending via Celery broker."""

import logging

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from base.getDates import getDates
from base.utility import resolve_user
from customer.models import Customer, Payment
from invoice.models import Invoice
from notification.models import MessageLog, MessageStatusChoices
from notification.tasks import send_customer_message_task

logger = logging.getLogger(__name__)


def _dispatch_message_task(log):
    """Enqueue Celery task for the MessageLog on transaction commit, handling broker errors."""
    def _enqueue():
        try:
            send_customer_message_task.delay(log.id)
        except Exception as exc:
            logger.error("Failed to enqueue Celery task for MessageLog %s: %s", log.id, exc)
            log.status = MessageStatusChoices.FAILED
            log.error_message = f"Broker unavailable: {str(exc)[:200]}"
            log.save(update_fields=["status", "error_message"])

    transaction.on_commit(_enqueue)


def send_invoice(request, pk):
    """Queue an invoice PDF sending task asynchronously via Celery broker."""
    try:
        invoice = Invoice.objects.select_related("customer").get(pk=pk)
        customer = invoice.customer

        with transaction.atomic():
            Customer.objects.select_for_update().get(pk=customer.pk)

            if MessageLog.is_duplicate_in_flight(customer, "invoice"):
                return JsonResponse(
                    {
                        "success": False,
                        "message": "An invoice message for this customer is already in progress or was sent recently.",
                    },
                    status=200,
                )

            log = MessageLog.objects.create(
                user=resolve_user(request),
                customer=customer,
                message_type="invoice",
                phone_number=customer.phone_number,
                payload_data={"invoice_id": invoice.id},
            )

            _dispatch_message_task(log)

        return JsonResponse(
            {
                "success": True,
                "message": "Invoice sending queued in background.",
                "log_id": log.id,
            },
            status=200,
        )

    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error queueing invoice message: %s", e)
        return JsonResponse(
            {
                "success": False,
                "message": "Failed to queue invoice message",
            },
            status=500,
        )


def send_statement(request, pk):
    """Queue a statement PDF sending task asynchronously via Celery broker."""
    customer = get_object_or_404(Customer, id=pk)
    start_date, end_date = getDates(request)

    try:
        with transaction.atomic():
            Customer.objects.select_for_update().get(pk=customer.pk)

            if MessageLog.is_duplicate_in_flight(customer, "statement"):
                return JsonResponse(
                    {
                        "success": False,
                        "message": "A statement message for this customer is already in progress or was sent recently.",
                    },
                    status=200,
                )

            log = MessageLog.objects.create(
                user=resolve_user(request),
                customer=customer,
                message_type="statement",
                phone_number=customer.phone_number,
                payload_data={
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "end_date": end_date.strftime("%Y-%m-%d"),
                },
            )

            _dispatch_message_task(log)

        return JsonResponse(
            {
                "success": True,
                "message": "Statement sending queued in background.",
                "log_id": log.id,
            },
            status=200,
        )

    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error queueing statement message: %s", e)
        return JsonResponse(
            {
                "success": False,
                "message": "Failed to queue statement message",
            },
            status=500,
        )


def send_text(request, pk):
    """Queue a payment receipt message task asynchronously via Celery broker."""
    payment = get_object_or_404(Payment, id=pk)
    customer = payment.customer

    try:
        with transaction.atomic():
            Customer.objects.select_for_update().get(pk=customer.pk)

            if MessageLog.is_duplicate_in_flight(customer, "payment"):
                return JsonResponse(
                    {
                        "success": False,
                        "message": "A payment receipt for this customer is already in progress or was sent recently.",
                    },
                    status=200,
                )

            log = MessageLog.objects.create(
                user=resolve_user(request),
                customer=customer,
                message_type="payment",
                phone_number=customer.phone_number,
                payload_data={"payment_id": payment.id},
            )

            _dispatch_message_task(log)

        return JsonResponse(
            {
                "success": True,
                "message": "Payment receipt queued in background.",
                "log_id": log.id,
            },
            status=200,
        )

    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error queueing payment message: %s", e)
        return JsonResponse(
            {
                "success": False,
                "message": "Failed to queue payment receipt message",
            },
            status=500,
        )


def balance(request, pk):
    """Queue a customer balance message task asynchronously via Celery broker."""
    customer = get_object_or_404(Customer, id=pk)

    try:
        with transaction.atomic():
            Customer.objects.select_for_update().get(pk=customer.pk)

            if MessageLog.is_duplicate_in_flight(customer, "balance"):
                return JsonResponse(
                    {
                        "success": False,
                        "message": "A balance update for this customer is already in progress or was sent recently.",
                    },
                    status=200,
                )

            log = MessageLog.objects.create(
                user=resolve_user(request),
                customer=customer,
                message_type="balance",
                phone_number=customer.phone_number,
                payload_data={},
            )

            _dispatch_message_task(log)

        return JsonResponse(
            {
                "success": True,
                "message": "Balance update queued in background.",
                "log_id": log.id,
            },
            status=200,
        )

    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error queueing balance message: %s", e)
        return JsonResponse(
            {
                "success": False,
                "message": "Failed to queue balance message",
            },
            status=500,
        )

