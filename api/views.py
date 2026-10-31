import json
import logging
from datetime import datetime

import requests
from decouple import config
from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from api.services import generate_invoice_pdf, generate_statement_pdf
from base.getDates import getDates
from customer.models import Customer
from invoice.models import Invoice

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phone number utilities
# ---------------------------------------------------------------------------

def clean_phone_digits(phone):
    """Strip a phone number to its bare 10-digit Indian form.

    Removes all non-digit characters and strips the leading '91' country
    code when present.

    Args:
        phone (str | int): Raw phone number in any common format.

    Returns:
        str: Digits-only string (ideally 10 characters for a valid Indian number).
    """
    cleaned = "".join(c for c in str(phone) if c.isdigit())
    if len(cleaned) == 12 and cleaned.startswith("91"):
        cleaned = cleaned[2:]
    return cleaned


def number_format(phone_number):
    """Validate and normalize a phone number to 10 digits.

    Args:
        phone_number: Raw phone number string.

    Returns:
        str: Normalized 10-digit phone number.

    Raises:
        ValueError: If the phone number is invalid.
    """
    if not str(phone_number).replace("+", "").replace(" ", "").replace("-", "").isdigit():
        raise ValueError("Phone number must contain only digits")
    cleaned = clean_phone_digits(phone_number)
    if len(cleaned) != 10:
        raise ValueError("Issue With Phone No, Provide a Valid Phone No")
    return cleaned


def format_crm_phone(phone):
    """Format a phone number to standard +91XXXXXXXXXX structure.

    Args:
        phone (str | int): Raw phone number.

    Returns:
        str: Formatted phone number starting with +91.
    """
    return f"+91{clean_phone_digits(phone)}"


# ---------------------------------------------------------------------------
# Webhook request parsing helper
# ---------------------------------------------------------------------------

def _parse_request_and_get_customer(request):
    """Parse POST body, validate phone, and look up the customer.

    Centralises the boilerplate shared by every public webhook view:
    POST-method check ➜ JSON/form parsing ➜ phone extraction ➜ validation
    ➜ customer lookup.

    Args:
        request: The Django HTTP request object.

    Returns:
        tuple:
            (customer, phone_number, data, None) on success.
            (None, None, None, JsonResponse) when an error is detected.
    """
    if request.method != "POST":
        return None, None, None, JsonResponse(
            {"error": "Only POST method is allowed"}, status=405
        )

    data = {}
    if request.body:
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            pass

    phone_number = (
        data.get("phone_number")
        or data.get("phone")
        or request.POST.get("phone_number")
        or request.POST.get("phone")
    )

    if not phone_number:
        return None, None, None, JsonResponse(
            {"error": "Phone number is required"}, status=400
        )

    phone_number = str(phone_number)

    try:
        phone_number = number_format(phone_number)
    except ValueError as exc:
        return None, None, None, JsonResponse({"error": str(exc)}, status=400)

    customer = Customer.objects.filter(phone_number=phone_number).first()
    if not customer:
        return None, None, None, JsonResponse(
            {"error": "Customer not found"}, status=404
        )

    return customer, phone_number, data, None


# ---------------------------------------------------------------------------
# Public webhook views
# ---------------------------------------------------------------------------

@csrf_exempt
@login_not_required
def get_balance(request):
    """Return the current credit balance for a customer via POST request.

    Args:
        request: The HTTP request object containing the customer's phone number.

    Returns:
        JsonResponse: A JSON response containing the recipient details, event metadata, and payload.
    """
    customer, phone_number, _data, error = _parse_request_and_get_customer(request)
    if error:
        return error

    balance = customer.credit_summary.balance_amount
    return JsonResponse(
        {
            "recipient": {
                "name": customer.name,
                "phone": f"+91{phone_number}",
            },
            "event": {
                "type": "credit_balance_checked",
                "language": "en",
                "preferred_channels": ["whatsapp"],
            },
            "payload": {
                "attributes": {
                    "customer_name": customer.name,
                    "balance": balance,
                    "date": datetime.now().strftime("%d-%m-%Y"),
                },
            },
        },
        status=200,
    )


@csrf_exempt
@login_not_required
def get_last_invoice(request):
    """Return the last invoice PDF for a customer via POST request."""
    customer, phone_number, _data, error = _parse_request_and_get_customer(request)
    if error:
        return error

    invoice = Invoice.objects.filter(customer=customer).order_by("-created_at").first()

    if not invoice:
        return JsonResponse({"error": "No invoice found"}, status=404)

    try:
        # Use the helper function to generate or retrieve PDF
        pdf_data = generate_invoice_pdf(invoice, request)

        return JsonResponse(
            {
                "recipient": {
                    "name": customer.name,
                    "phone": f"+91{phone_number}",
                },
                "event": {
                    "type": "last_invoice_generated",
                    "language": "en",
                    "preferred_channels": ["whatsapp"],
                },
                "payload": {
                    "attributes": {
                        "customer_name": customer.name,
                        "invoice_number": invoice.invoice_number,
                        "amount": invoice.net_amount_due,
                    },
                    "attachments": [
                        {
                            "type": "document",
                            "url": pdf_data.get("url"),
                            "filename": pdf_data.get("filename"),
                            "status": pdf_data.get("pdf_status"),
                            "generated_at": pdf_data.get("generated_at"),
                        }
                    ],
                },
            },
            status=200,
        )
    except RuntimeError:
        logger.error("Error generating invoice PDF for invoice %s", invoice.pk)
        return JsonResponse(
            {"error": "Failed to generate or retrieve invoice PDF"}, status=500
        )


@csrf_exempt
@login_not_required
def get_statement(request):
    """Return a credit statement PDF for a customer via POST request.

    Args:
        request: The HTTP request object containing customer credentials and filters.

    Returns:
        JsonResponse: A JSON response containing the generated statement PDF URL and details.
    """
    customer, phone_number, _data, error = _parse_request_and_get_customer(request)
    if error:
        return error

    start_date, end_date = getDates(request)

    try:
        # Use the service function to generate statement PDF
        pdf_data = generate_statement_pdf(customer, start_date, end_date, request)

        return JsonResponse(
            {
                "recipient": {
                    "name": customer.name,
                    "phone": f"+91{phone_number}",
                },
                "event": {
                    "type": "monthly_statement_generated",
                    "language": "en",
                    "preferred_channels": ["whatsapp"],
                },
                "payload": {
                    "attributes": {
                        "customer_name": customer.name,
                        "from_date": start_date.strftime("%d-%m-%Y"),
                        "to_date": end_date.strftime("%d-%m-%Y"),
                    },
                    "attachments": [
                        {
                            "type": "document",
                            "url": pdf_data.get("url"),
                            "filename": pdf_data.get("filename"),
                            "status": pdf_data.get("pdf_status"),
                            "generated_at": pdf_data.get("generated_at"),
                        }
                    ],
                },
            },
            status=200,
        )
    except RuntimeError:
        logger.error("Error generating statement PDF for customer %s", customer.pk)
        return JsonResponse(
            {"error": "Failed to generate or retrieve statement PDF"}, status=500
        )


# ---------------------------------------------------------------------------
# WhatsApp CRM integration helpers
# ---------------------------------------------------------------------------

def get_whatsapp_api_key():
    """Retrieve the WhatsApp API key from the environment configuration.

    Reads WHATSAPP_API_KEY from the environment via ``decouple.config``.
    Falls back to parsing the project ``.env`` file if the env var is unset.

    Returns:
        str: The API key.

    Raises:
        RuntimeError: If no API key can be resolved from any source.
    """
    api_key = config("WHATSAPP_API_KEY", default=None)
    if api_key:
        return api_key

    # Fallback: parse the .env file relative to BASE_DIR
    env_path = getattr(settings, "BASE_DIR", None)
    if env_path:
        try:
            env_file = env_path / ".env"
            with open(env_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    if "WHATSAPP_URL =" in line and not line.strip().endswith("api/v1"):
                        parts = line.split("=")
                        if len(parts) > 1:
                            val = parts[1].strip()
                            if len(val) >= 32:
                                return val
        except IOError:
            pass

    raise RuntimeError(
        "WHATSAPP_API_KEY is not configured. "
        "Set it in your .env file or environment variables."
    )


def _get_customer_name_from_db(phone):
    """Attempt to retrieve a customer name from the database by phone number.

    Args:
        phone (str): Raw phone number.

    Returns:
        str: Customer name if found, otherwise 'Customer'.
    """
    try:
        cleaned_phone = clean_phone_digits(phone)
        customer = Customer.objects.filter(phone_number=cleaned_phone).first()
        if customer:
            return customer.name
    except Exception:  # pylint: disable=broad-except
        pass
    return "Customer"


# pylint: disable=too-many-branches,too-many-locals
def format_whatsapp_payload(phone, template_name, params, url, file_name):
    """Format the WhatsApp/CRM message payload dynamically based on parameters.

    Supports both legacy positional parameter lists and modern key-value dictionary attributes.

    Args:
        phone (str): Recipient phone number.
        template_name (str): Template / event type to use.
        params (list | dict): List of variables or dictionary of named attributes.
        url (str): Attachment document URL.
        file_name (str): Attachment document filename.

    Returns:
        dict: The structured payload compliant with the CRM API.
    """
    formatted_phone = format_crm_phone(phone)

    # Dictionary representation maps directly to CRM attributes
    if isinstance(params, dict):
        attributes = params.copy()
    else:
        # Fallback for list/sequence: convert to param_1, param_2, etc.
        attributes = {}
        for idx, param in enumerate(params):
            attributes[f"param_{idx + 1}"] = param

    # Resolve customer name from attributes or DB
    customer_name = attributes.get("customer_name") or attributes.get("name")
    if not customer_name:
        customer_name = _get_customer_name_from_db(phone)
    else:
        customer_name = str(customer_name)

    # Ensure customer_name is set in attributes
    attributes["customer_name"] = customer_name

    # Build attachments
    attachments = []
    if url:
        attachments.append({
            "type": "document",
            "url": url,
            "filename": file_name or "document.pdf",
        })

    return {
        "recipient": {
            "name": customer_name,
            "phone": formatted_phone,
        },
        "event": {
            "type": template_name,
            "message_type": "template",
        },
        "payload": {
            "attributes": attributes,
            "attachments": attachments,
        },
    }


# pylint: disable=too-many-arguments,too-many-positional-arguments
def send_template(request, phone, template_name, params, url, file_name):
    """Send a formatted WhatsApp template message to the CRM endpoint.

    Uses `get_whatsapp_api_key` and `format_whatsapp_payload` to assemble
    the payload and authorization headers, then posts it.

    Args:
        request: The Django HTTP request (unused but kept for API consistency).
        phone (str): Recipient phone number.
        template_name (str): WhatsApp template name / CRM event type.
        params (list | dict): Variables / attributes for template formatting.
        url (str): PDF/document attachment URL.
        file_name (str): PDF/document filename.

    Returns:
        dict: Response from CRM API containing success status.
    """
    api_key = get_whatsapp_api_key()
    payload = format_whatsapp_payload(phone, template_name, params, url, file_name)

    post_url = config("WHATSAPP_SEND_DIRECT_URL", default=None)
    if not post_url:
        base_url = config("WHATSAPP_URL", default="https://your-app.com/api").rstrip("/")
        if not base_url.endswith("/api"):
            post_url = f"{base_url}/api/whatsapp/send-direct"
        else:
            post_url = f"{base_url}/whatsapp/send-direct"

    headers = {
        "x-api-key": api_key,
    }

    try:
        response = requests.post(
            post_url,
            headers=headers,
            json=payload,
            timeout=30,
        )
        try:
            return response.json()
        except ValueError:
            logger.error("Non-JSON response from CRM API: %s", response.text)
            return {
                "success": response.status_code in [200, 201],
                "detail": "Invalid JSON response",
            }
    except requests.RequestException as exc:
        logger.error("Request to WhatsApp CRM API failed: %s", exc)
        return {
            "success": False,
            "detail": str(exc),
        }
