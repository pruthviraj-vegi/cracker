"""
Views for the security app, handling login activity and unauthorized access logs.
"""

from django.db.models import Q
from django.shortcuts import render

from base.decorators import required_permission
from base.utility import build_search_filter, render_paginated_response, table_sorting

from .models import LoginEvent, UnauthorizedAccess


@required_permission("security.view_loginevent")
def logins_overview(request):
    """View an overview of recent login events."""
    return render(request, "security/logins/main.html")


@required_permission("security.view_loginevent")
def fetch_logins_events(request):
    """AJAX endpoint to fetch login events with search, filter, and pagination."""

    search_query = request.GET.get("search", "")

    filters = build_search_filter(
        search_query,
        [
            "user__first_name",
            "user__last_name",
            "user__phone_number",
            "user__address",
            "event_type",
            "ip_address",
            "user_agent",
        ],
    )

    sort_fields = {
        "occurred_at",
        "user",
        "event_type",
        "ip_address",
        "user_agent",
    }

    valid_sorts = table_sorting(request, sort_fields, "-occurred_at")
    events = (
        LoginEvent.objects.select_related("user").filter(filters).order_by(*valid_sorts)
    )
    return render_paginated_response(request, events, "security/logins/fetch.html", 25)


@required_permission("security.view_unauthorizedaccess")
def unauthorized_overview(request):
    """View an overview of recent unauthorized access attempts."""
    return render(request, "security/unauthorised/main.html")


@required_permission("security.view_unauthorizedaccess")
def fetch_unauthorised_events(request):
    """AJAX endpoint to fetch unauthorized access events with search, filter, and pagination."""

    search_query = request.GET.get("search", "")

    filters = build_search_filter(
        search_query,
        [
            "user__first_name",
            "user__last_name",
            "user__phone_number",
            "user__address",
            "view_name",
            "required_roles",
            "ip_address",
            "url_path",
        ],
    )

    sort_fields = {
        "timestamp",
        "user",
        "view_name",
        "required_roles",
        "ip_address",
        "url_path",
    }

    valid_sorts = table_sorting(request, sort_fields, "-timestamp")
    events = (
        UnauthorizedAccess.objects.select_related("user")
        .filter(filters)
        .order_by(*valid_sorts)
    )
    return render_paginated_response(
        request, events, "security/unauthorised/fetch.html", 25
    )
