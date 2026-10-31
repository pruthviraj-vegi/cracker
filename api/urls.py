"""
URL configuration for the API application.
"""

from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("last_invoice/", views.get_last_invoice, name="last_invoice"),
    path("balance/", views.get_balance, name="balance"),
    path("statement/", views.get_statement, name="statement"),
]
