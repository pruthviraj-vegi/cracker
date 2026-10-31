"""
App configuration for the invoice app.
"""

from django.apps import AppConfig


class InvoiceConfig(AppConfig):
    """Configuration class for the invoice app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "invoice"
