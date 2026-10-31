from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from base.decorators import required_permission
from base.utility import render_paginated_response, table_sorting
from .models import APIToken


VALID_SORTS = {
    "name": "name",
    "prefix": "prefix",
    "expires_at": "expires_at",
    "last_used_at": "last_used_at",
    "created_at": "created_at",
}


@required_permission("api.view_apitoken")
def home(request):
    return render(request, "api/tokens/home.html")


@required_permission("api.view_apitoken")
def fetch_tokens(request):
    tokens = APIToken.objects.all()

    search = request.GET.get("search", "").strip()
    if search:
        tokens = tokens.filter(name__icontains=search)

    sort_params = table_sorting(request, VALID_SORTS, "-created_at")
    tokens = tokens.order_by(*sort_params)

    return render_paginated_response(
        request,
        tokens,
        "api/tokens/fetch.html",
        per_page=20,
    )


@required_permission("api.add_apitoken")
@require_http_methods(["POST"])
def create_token(request):
    name = request.POST.get("name", "").strip()
    purpose = request.POST.get("purpose", "").strip()
    expires_in = request.POST.get("expires_in", "365")

    if not name:
        return JsonResponse({"success": False, "error": "Name is required"}, status=400)

    days = int(expires_in) if expires_in.isdigit() else 365
    if days < 1 or days > 3650:
        days = 365
    expires_at = timezone.now() + timedelta(days=days)

    instance, raw_token = APIToken.generate(
        name=name,
        purpose=purpose,
        expires_at=expires_at,
        created_by=request.user,
        allowed_ips=[],
    )

    return JsonResponse(
        {
            "success": True,
            "raw_token": raw_token,
            "token": {
                "id": str(instance.id),
                "name": instance.name,
                "prefix": instance.prefix,
                "expires_at": instance.expires_at.strftime("%b %d, %Y"),
                "created_at": instance.created_at.strftime("%b %d, %Y %H:%M"),
            },
        }
    )


@required_permission("api.view_apitoken")
def token_detail(request, pk):
    token = get_object_or_404(APIToken, pk=pk)
    logs = token.request_logs.order_by("-requested_at")[:50]

    all_logs = token.request_logs.all()
    stats = all_logs.aggregate(
        total_requests=Count("id"),
        avg_response_ms=Avg("response_time_ms"),
        success_count=Count("id", filter=Q(response_status__gte=200, response_status__lt=300)),
        error_count=Count("id", filter=Q(response_status__gte=400)),
    )

    total = stats["total_requests"] or 0
    success = stats["success_count"] or 0
    errors = stats["error_count"] or 0
    success_rate = round((success / total) * 100) if total > 0 else 0
    error_rate = round((errors / total) * 100) if total > 0 else 0
    avg_ms = round(stats["avg_response_ms"]) if stats["avg_response_ms"] else 0

    return render(
        request,
        "api/tokens/detail.html",
        {
            "token": token,
            "logs": logs,
            "total_requests": total,
            "success_rate": success_rate,
            "error_rate": error_rate,
            "avg_response_ms": avg_ms,
        },
    )


@required_permission("api.change_apitoken")
@require_http_methods(["POST"])
def revoke_token(request, pk):
    token = get_object_or_404(APIToken, pk=pk)

    if not token.is_active:
        return JsonResponse({"success": False, "error": "Token is already revoked"})

    token.is_active = False
    token.revoked_at = timezone.now()
    token.revoked_by = request.user
    token.save(update_fields=["is_active", "revoked_at", "revoked_by"])

    return JsonResponse({"success": True})
