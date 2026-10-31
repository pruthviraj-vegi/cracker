"""
Decorators and mixins for the application.
"""

import logging
import time
from functools import wraps

from django.conf import settings
from django.db import connection
from django.shortcuts import render

from security.models import UnauthorizedAccess

logger = logging.getLogger(__name__)


def timed(fn):
    """
    Decorator to measure execution time of a function.
    Stores the last execution time in `fn._last_elapsed_time`.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = fn(*args, **kwargs)
        elapsed = time.perf_counter() - start

        logger.debug("Time taken: %.4f seconds", elapsed)

        # Store timing on the function itself
        wrapper.last_elapsed_time = elapsed
        return result

    wrapper.last_elapsed_time = None  # init attribute
    return wrapper


def query_debugger(func):
    """Decorator to count queries and execution time"""

    def wrapper(*args, **kwargs):
        # Only run in debug mode
        if not settings.DEBUG:
            return func(*args, **kwargs)

        # Reset queries
        connection.queries_log.clear()

        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()

        query_count = len(connection.queries)
        execution_time = (end_time - start_time) * 1000

        print(f"\n{'='*60}")
        print(f"Function: {func.__name__}")
        print(f"Queries: {query_count}")
        print(f"Time: {execution_time:.2f}ms")
        print(f"{'='*60}\n")

        return result

    return wrapper


def get_client_ip(request):
    """Helper function to get client's IP address"""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


def _log_unauthorized_access(request, view_name, allowed_roles):
    """Shared helper to log unauthorized access attempts."""

    UnauthorizedAccess.objects.create(
        user=request.user,
        view_name=view_name,
        required_roles=", ".join(allowed_roles),
        ip_address=get_client_ip(request),
        url_path=request.path,
    )


def required_permission(perm):
    """
    Usage:
        @required_permission('invoice.add_invoice')
        def create_invoice(request): ...
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.has_perm(perm):
                _log_unauthorized_access(request, view_func.__name__, [perm])
                return render(request, "base/403.html", status=403)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


class RequiredPermissionMixin:
    """
    Usage:
        class EditInvoiceView(RequiredPermissionMixin, UpdateView):
            required_permission = 'invoice.change_invoice'
    """

    required_permission = None

    def dispatch(self, request, *args, **kwargs):
        """checking the permission for class based"""
        if not self.required_permission:
            raise ValueError(
                f"{self.__class__.__name__} must define `required_permission`"
            )
        if not request.user.has_perm(self.required_permission):
            _log_unauthorized_access(
                request, self.__class__.__name__, [self.required_permission]
            )
            return render(request, "base/403.html", status=403)
        return super().dispatch(request, *args, **kwargs)
