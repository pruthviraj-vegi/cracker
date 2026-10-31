"""URL patterns for BulkUpload batch management."""

from django.urls import path

from . import views_bulk_upload

app_name = "inventory_bulk_upload"

urlpatterns = [
    path("", views_bulk_upload.bulk_upload_home, name="home"),
    path("fetch/", views_bulk_upload.bulk_upload_fetch, name="fetch"),
    path("sample-csv/", views_bulk_upload.bulk_upload_sample_csv, name="sample_csv"),
    path("create/", views_bulk_upload.CreateBulkUpload.as_view(), name="create"),
    path("<int:pk>/", views_bulk_upload.bulk_upload_detail, name="detail"),
    path("<int:pk>/upload-csv/", views_bulk_upload.bulk_upload_csv, name="upload_csv"),
    path("<int:pk>/commit-all/", views_bulk_upload.bulk_upload_commit_all, name="commit_all"),
    path("<int:pk>/delete-uncommitted/", views_bulk_upload.bulk_upload_delete_uncommitted, name="delete_uncommitted"),
    path("<int:pk>/item/<int:item_id>/update/", views_bulk_upload.bulk_upload_item_update, name="item_update"),
    path("<int:pk>/item/<int:item_id>/commit/", views_bulk_upload.bulk_upload_item_commit, name="item_commit"),
    path("<int:pk>/item/<int:item_id>/delete/", views_bulk_upload.bulk_upload_item_delete, name="item_delete"),
    path("<int:pk>/item/<int:item_id>/form/", views_bulk_upload.bulk_upload_item_form, name="item_form"),
    path("<int:pk>/product-search/", views_bulk_upload.product_search, name="product_search"),
    path("<int:pk>/variant-search/", views_bulk_upload.variant_search, name="variant_search"),
    path("<int:pk>/edit/", views_bulk_upload.UpdateBulkUpload.as_view(), name="edit"),
    path("<int:pk>/delete/", views_bulk_upload.DeleteBulkUpload.as_view(), name="delete"),
]
