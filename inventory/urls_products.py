"""URL patterns for product-related views."""

from django.urls import path
from . import views_products

app_name = "inventory_products"

urlpatterns = [
    path("", views_products.product_home, name="home"),
    path("fetch/", views_products.fetch_products, name="fetch"),
    path("<int:product_id>/", views_products.product_details, name="details"),
    path("create/", views_products.CreateProduct.as_view(), name="create"),
    path("<int:pk>/edit/", views_products.EditProduct.as_view(), name="edit"),
]
