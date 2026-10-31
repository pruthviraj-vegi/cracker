"""
Celery application configuration for the Billing project.

This module creates the Celery app instance and configures it
to autodiscover tasks from all installed Django apps.

Usage:
    Start the worker with:
        celery -A Billing worker -l info
"""

import os

from celery import Celery

# Set the default Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Billing.settings")

app = Celery("Billing")

# Read config from Django settings, using the CELERY_ namespace
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py in every installed app
app.autodiscover_tasks()
