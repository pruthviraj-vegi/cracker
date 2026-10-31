import time

from django.http import JsonResponse
from django.utils import timezone

from base.decorators import get_client_ip
from .models import APIToken, APIRequestLog


class APITokenMiddleware:
    """
    Enforces Bearer token authentication for all /api/ requests.

    Every request under /api/ must include a valid Bearer token.
    Requests without a token are rejected with 403.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            from security.models import UnauthorizedAccess
            UnauthorizedAccess.objects.create(
                user=None,
                view_name="api_bearer_auth",
                required_roles="bearer_auth_header",
                ip_address=get_client_ip(request),
                url_path=request.path,
            )
            return JsonResponse({"error": "Authorization header missing or invalid"}, status=403)

        start_time = time.time()
        token_instance, error = self._authenticate(auth_header, request)

        if error:
            elapsed_ms = int((time.time() - start_time) * 1000)
            ip = get_client_ip(request)
            if token_instance:
                APIRequestLog.objects.create(
                    token=token_instance,
                    endpoint=request.path,
                    method=request.method,
                    ip_address=ip,
                    response_status=403,
                    response_time_ms=elapsed_ms,
                )
            else:
                from security.models import UnauthorizedAccess
                UnauthorizedAccess.objects.create(
                    user=None,
                    view_name="api_bearer_auth",
                    required_roles="valid_api_token",
                    ip_address=ip,
                    url_path=request.path,
                )
            return JsonResponse({"error": error}, status=403)

        request.api_token = token_instance
        request.csrf_processing_done = True
        response = self.get_response(request)

        elapsed_ms = int((time.time() - start_time) * 1000)
        ip = get_client_ip(request)

        APIRequestLog.objects.create(
            token=token_instance,
            endpoint=request.path,
            method=request.method,
            ip_address=ip,
            response_status=response.status_code,
            response_time_ms=elapsed_ms,
        )

        token_instance.last_used_at = timezone.now()
        token_instance.last_used_ip = ip
        token_instance.save(update_fields=["last_used_at", "last_used_ip"])

        return response

    def _authenticate(self, auth_header, request):
        try:
            parts = auth_header.split(" ", 1)
            if len(parts) < 2:
                return None, "Invalid authorization format"
            raw_token = parts[1].strip()
        except Exception:
            return None, "Invalid authorization format"

        token = APIToken.verify(raw_token)

        if not token:
            return None, "Invalid token"

        if not token.is_active:
            return token, "Token has been revoked"

        if token.expires_at < timezone.now():
            return token, "Token has expired"

        ip = get_client_ip(request)
        if token.allowed_ips and ip not in token.allowed_ips:
            return token, "IP address not allowed"

        return token, None
