"""URL patterns for product variant-related views."""

from django.urls import path
from . import views_variant

app_name = "inventory_variant"

urlpatterns = [
    path("", views_variant.variant_home, name="home"),
    path("fetch/", views_variant.fetch_variants, name="fetch"),
    path("<int:variant_id>/", views_variant.variant_details, name="details"),
    path(
        "<int:variant_id>/recent-logs/",
        views_variant.recent_variants_logs,
        name="recent_logs",
    ),
    path(
        "create/<int:product_id>/",
        views_variant.CreateProductVariant.as_view(),
        name="create",
    ),
    path(
        "edit/<int:pk>/",
        views_variant.EditProductVariant.as_view(),
        name="edit",
    ),
    # Inventory Operations
    path(
        "operations/stock-in/<int:variant_id>/",
        views_variant.StockInCreate.as_view(),
        name="stock_in",
    ),
    path(
        "operations/adjustment-in/<int:variant_id>/",
        views_variant.AdjustmentInCreate.as_view(),
        name="adjustment_in",
    ),
    path(
        "operations/adjustment-out/<int:variant_id>/",
        views_variant.AdjustmentOutCreate.as_view(),
        name="adjustment_out",
    ),
    path(
        "operations/damage/<int:variant_id>/",
        views_variant.DamageCreate.as_view(),
        name="damage_create",
    ),
    path(
        "operations/damage/resolve/<int:record_id>/",
        views_variant.DamageResolveView.as_view(),
        name="damage_resolve",
    ),
    # Media Management
    path(
        "<int:variant_id>/media/upload/",
        views_variant.variant_media_upload,
        name="media_upload",
    ),
    path(
        "media/<int:media_id>/delete/",
        views_variant.variant_media_delete,
        name="media_delete",
    ),
    path(
        "media/<int:media_id>/featured/",
        views_variant.variant_media_set_featured,
        name="media_set_featured",
    ),
]
