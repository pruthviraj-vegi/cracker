"""URL patterns for the customer app."""

from django.urls import path
from . import views, views_credit


app_name = "customer"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/fetch/", views.dashboard_fetch, name="dashboard_fetch"),
    path("fetch/", views.fetch_customers, name="fetch"),
    path("create/", views.CreateCustomer.as_view(), name="create"),
    path("<int:pk>/", views.customer_detail, name="detail"),
    path(
        "<int:pk>/invoices/fetch/", views.fetch_customer_invoices, name="fetch_invoices"
    ),
    path("<int:pk>/edit/", views.EditCustomer.as_view(), name="edit"),
    path("<int:pk>/delete/", views.DeleteCustomer.as_view(), name="delete"),
    path("<int:pk>/balance/", views.get_customer_balance, name="balance"),
    ## credit details
    path("credit/", views_credit.home, name="credit_home"),
    path("create/ajax/", views.create_customer_ajax, name="create_ajax"),
    path("credit/fetch/", views_credit.fetch_credits, name="credit_fetch"),
    path("credit/<int:customer_id>/", views_credit.credit_detail, name="credit_detail"),
    path(
        "credit/<int:customer_id>/ledger/fetch/",
        views_credit.fetch_credit_ledger,
        name="fetch_credit_ledger",
    ),
    path(
        "credit/payment/create/",
        views_credit.PaymentCreateView.as_view(),
        name="payment_create",
    ),
    path(
        "credit/payment/<int:customer_id>/create/",
        views_credit.PaymentCreateView.as_view(),
        name="credit_create",
    ),
    path(
        "credit/payment/<int:pk>/edit/",
        views_credit.PaymentUpdateView.as_view(),
        name="payment_edit",
    ),
    path(
        "credit/payment/<int:pk>/delete/",
        views_credit.PaymentDeleteView.as_view(),
        name="payment_delete",
    ),
    ## Auto Reallocate (FIFO allocation)
    path(
        "credit/<int:customer_id>/auto_reallocate/",
        views_credit.auto_reallocate,
        name="credit_auto_reallocate",
    ),
]
