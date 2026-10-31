"""Custom middleware for authentication, session metadata, and inactivity logout."""

import re
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone


def _is_exempt_path(path):
    """Check if the given path matches any LOGIN_EXEMPT_URLS pattern."""
    try:
        return any(re.match(pattern, path) for pattern in settings.LOGIN_EXEMPT_URLS)
    except (AttributeError, TypeError):
        return False


class CustomLoginRequiredMiddleware:
    """Redirect unauthenticated users to the login page.

    Skips paths matching LOGIN_EXEMPT_URLS (static, media, login, API).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info.lstrip("/")

        if _is_exempt_path(path):
            return self.get_response(request)

        if not request.user.is_authenticated:
            request.session["next"] = request.path
            return redirect("base:login")

        return self.get_response(request)


class SessionMetaMiddleware:
    """Attach client metadata (IP, user agent, last activity) to the session.

    - Stores once per session: ip_address, user_agent
    - Updates last_activity on every request
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            session = request.session
            xff = request.META.get("HTTP_X_FORWARDED_FOR")
            ip_address = (
                xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
            )
            user_agent = request.META.get("HTTP_USER_AGENT", "")

            if session is not None:
                if "ip_address" not in session and ip_address:
                    session["ip_address"] = ip_address
                if "user_agent" not in session and user_agent:
                    session["user_agent"] = user_agent[:512]
                session["last_activity"] = timezone.now().isoformat()
        except (AttributeError, KeyError, TypeError):
            pass

        return self.get_response(request)


class InactivityLogoutMiddleware:
    """Log out authenticated users after a period of inactivity.

    Uses `request.session["last_activity"]` set by `SessionMetaMiddleware`.
    Must be placed BEFORE `SessionMetaMiddleware` in MIDDLEWARE so a stale
    `last_activity` value is checked prior to being refreshed.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.timeout_seconds = getattr(
            settings, "INACTIVITY_TIMEOUT_SECONDS", 3 * 60 * 60
        )

    def __call__(self, request):
        path = request.path_info.lstrip("/")

        if _is_exempt_path(path):
            return self.get_response(request)

        if request.user.is_authenticated:
            last_activity_str = request.session.get("last_activity")
            if last_activity_str:
                try:
                    last_activity_dt = datetime.fromisoformat(last_activity_str)
                except (ValueError, TypeError):
                    last_activity_dt = None

                if last_activity_dt is not None:
                    now_dt = timezone.now()
                    if (now_dt - last_activity_dt) > timedelta(
                        seconds=self.timeout_seconds
                    ):
                        logout(request)
                        request.session["next"] = request.path
                        return redirect("base:login")

        return self.get_response(request)
