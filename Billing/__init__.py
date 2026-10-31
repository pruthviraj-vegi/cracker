"""Billing project package initialization — ensures Celery app loads on startup."""

from .celery import app as celery_app

__all__ = ("celery_app",)
