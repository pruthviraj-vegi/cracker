"""
URL patterns for the base app.
"""

from django.urls import path
from . import views


app_name = "base"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("login/", views.CustomLoginView.as_view(), name="login"),
    path(
        "login/forget-account/",
        views.forget_remembered_account,
        name="forget_account",
    ),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard-stats/", views.dashboard_stats, name="dashboard_stats"),
    path("calendar/", views.CalendarView.as_view(), name="calendar"),
    path("calendar-stats/", views.calendar_stats_api, name="calendar_stats_api"),
    path("calendar/details/", views.calendar_details_page, name="calendar_details"),
    path("calendar/details-api/", views.calendar_details_api, name="calendar_details_api"),
]
