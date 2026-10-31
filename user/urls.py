"""
URL patterns for the user app.
"""

from django.urls import path

from . import views

app_name = "user"

urlpatterns = [
    path("", views.home, name="home"),
    path("fetch/", views.fetch_users, name="fetch"),
    path("create/", views.CreateUser.as_view(), name="create"),
    path("sessions/", views.sessions_overview, name="sessions"),
    path("dashboard/", views.user_dashboard, name="dashboard"),
    path("dashboard/fetch/", views.user_dashboard_fetch, name="dashboard_fetch"),
    path(
        "sessions/invalidate/all/",
        views.invalidate_all_sessions,
        name="invalidate_all_sessions",
    ),
    path(
        "sessions/invalidate/<str:session_key>/",
        views.invalidate_session,
        name="invalidate_session",
    ),
    path("<int:pk>/", views.user_detail, name="detail"),
    path("<int:pk>/edit/", views.EditUser.as_view(), name="edit"),
    path("<int:pk>/delete/", views.DeleteUser.as_view(), name="delete"),
    path("<int:user_id>/status/", views.change_user_status, name="change_status"),
    path(
        "<int:user_id>/reset-password/",
        views.reset_user_password,
        name="reset_password",
    ),
    # Salary CRUD
    path(
        "<int:user_id>/salary/create/",
        views.salary_create,
        name="salary_create",
    ),
    path(
        "<int:user_id>/salary/<int:salary_id>/edit/",
        views.salary_edit,
        name="salary_edit",
    ),
    path(
        "<int:user_id>/salary/<int:salary_id>/delete/",
        views.salary_delete,
        name="salary_delete",
    ),
    # Transaction CRUD
    path(
        "<int:user_id>/transaction/create/",
        views.transaction_create,
        name="transaction_create",
    ),
    path(
        "<int:user_id>/transaction/<int:transaction_id>/edit/",
        views.transaction_edit,
        name="transaction_edit",
    ),
    path(
        "<int:user_id>/transaction/<int:transaction_id>/delete/",
        views.transaction_delete,
        name="transaction_delete",
    ),
    # Commission
    path(
        "<int:user_id>/commission/",
        views.user_commission,
        name="commission",
    ),
    path(
        "<int:user_id>/commission/fetch/",
        views.fetch_user_commission,
        name="commission_fetch",
    ),
    path(
        "<int:user_id>/commission/summary/",
        views.fetch_commission_summary,
        name="commission_summary",
    ),
]
