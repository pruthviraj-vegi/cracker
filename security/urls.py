"""
URL patterns for the security app.
"""

from django.urls import path

from . import views

app_name = "security"

urlpatterns = [
    path("logins/", views.logins_overview, name="logins"),
    path("logins/fetch/", views.fetch_logins_events, name="fetch_logins"),
    path("unauthorized/", views.unauthorized_overview, name="unauthorized"),
    path(
        "unauthorized/fetch/",
        views.fetch_unauthorised_events,
        name="fetch_unauthorised",
    ),
]
