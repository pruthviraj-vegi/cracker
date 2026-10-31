"""Notification URL Configuration."""

from django.urls import path
from . import views

app_name = "notification"

urlpatterns = [
    path("count/", views.notification_count, name="count"),
    path("", views.notification_list, name="list"),
    path("<int:notification_id>/read/", views.mark_read, name="mark_read"),
    path("mark-all-read/", views.mark_all_read, name="mark_all_read"),
]
