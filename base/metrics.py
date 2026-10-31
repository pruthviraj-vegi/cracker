"""
Performance metrics middleware and function profiling utilities.

Captures per-request performance data into a structured JSON log
(``logs/metrics.jsonl``), consumed by the ``metrics_report`` management
command.

Middleware order: place **first** in ``MIDDLEWARE`` so it wraps everything
else and measures total request duration.

Settings
--------
``METRICS_ENABLED``       bool, default True.
``METRICS_CAPTURE_SQL``   bool, default ``settings.DEBUG``.  Forces query
                          capture even when DEBUG is False.  Costs a little
                          per query; safe to leave on for a small site, worth
                          sampling on a busy one.
``METRICS_SAMPLE_RATE``   float 0..1, default 1.0.  Log only this fraction of
                          requests.  Errors and slow requests are always
                          logged regardless of the sample rate.
``METRICS_SLOW_MS``       float, default 200.0.  Above this, a request is
                          always logged and its duplicate queries recorded.

Changes from the previous version
---------------------------------
* Timestamps are timezone-aware.  Naive ``datetime.now()`` silently broke
  ordering across DST boundaries and across machines.
* Query capture no longer depends on DEBUG.  ``connection.queries`` is empty
  when DEBUG is False, so the old version reported 0 queries and 0 DB time in
  production without saying so.
* Requests that raise are still logged (``try/finally``), with ``exc`` set.
* ``route`` is recorded, so the report can group ``/cart/2127/`` and
  ``/cart/2151/`` as one endpoint instead of two.
* Class-based views resolve to their real class name rather than
  ``app.views.View.as_view.<locals>.view``.
* ``db_dupes`` counts repeated identical SQL in one request -- the direct
  signal for an N+1 query, which a bare query count only hints at.
* All connections are measured, not just ``default``.
* Function profiling writes events to the log instead of an in-process dict.
  The management command runs in a different process from the server, so the
  old registry was always empty by the time the report was generated.
"""

import atexit
import functools
import json
import logging
import random
import re
import threading
import time
from typing import Optional

from django.conf import settings
from django.db import connections
from django.utils import timezone

logger = logging.getLogger(__name__)
metrics_logger = logging.getLogger("performance")

_SKIP_PATH_RE = re.compile(r"^/(static|media|favicon\.ico|__debug__|__reload__)")

# Strip literals so that "... WHERE id = 42" and "... WHERE id = 43" are
# recognised as the same query shape when counting duplicates.
_SQL_LITERAL_RE = re.compile(r"('[^']*'|\b\d+\b)")


def _get_client_ip(request) -> str:
    """Extract client IP, respecting X-Forwarded-For from reverse proxies.

    Only trust this if your proxy overwrites the header. If it appends, or if
    the app is reachable directly, a client can set any value it likes.
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _sql_shape(sql: str) -> str:
    return _SQL_LITERAL_RE.sub("?", sql or "")[:400]


class _QueryCapture:
    """Count queries and SQL time across every configured connection.

    Uses Django's execute_wrapper API, which works whether or not DEBUG is on
    and does not accumulate an ever-growing connection.queries list.
    """

    def __init__(self):
        self.count = 0
        self.total_s = 0.0
        self.shapes = {}
        self._conns = []

    def __call__(self, execute, sql, params, many, context):
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            elapsed = time.perf_counter() - start
            self.count += 1
            self.total_s += elapsed
            shape = _sql_shape(sql)
            self.shapes[shape] = self.shapes.get(shape, 0) + 1

    def __enter__(self):
        for alias in connections:
            ctx = connections[alias].execute_wrapper(self)
            ctx.__enter__()
            self._conns.append(ctx)
        return self

    def __exit__(self, *exc):
        for ctx in reversed(self._conns):
            try:
                ctx.__exit__(*exc)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        return False

    @property
    def duplicates(self) -> int:
        """Total redundant executions: 3 identical queries count as 2."""
        return sum(n - 1 for n in self.shapes.values() if n > 1)

    def worst_repeat(self):
        """The most-repeated query shape, for slow-request diagnostics."""
        if not self.shapes:
            return None, 0
        shape, n = max(self.shapes.items(), key=lambda kv: kv[1])
        return (shape, n) if n > 1 else (None, 0)


class PerformanceMetricsMiddleware:
    """Log one JSON line per non-static request.

    Fields: ``ts`` (ISO-8601, timezone-aware), ``method``, ``path``, ``route``
    (URL pattern), ``view``, ``status``, ``duration_ms``, ``db_queries``,
    ``db_time_ms``, ``db_dupes``, ``size`` (response bytes), ``ip``, ``user``,
    ``is_ajax``, and ``exc`` when the request raised.

    A ``Server-Timing`` header is also set so Chrome DevTools shows the
    server-side breakdown on the Network panel.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = getattr(settings, "METRICS_ENABLED", True)
        self.capture_sql = getattr(settings, "METRICS_CAPTURE_SQL", settings.DEBUG)
        self.sample_rate = float(getattr(settings, "METRICS_SAMPLE_RATE", 1.0))
        self.slow_ms = float(getattr(settings, "METRICS_SLOW_MS", 200.0))

    def __call__(self, request):
        if not self.enabled or _SKIP_PATH_RE.match(request.path):
            return self.get_response(request)

        start = time.perf_counter()
        capture = _QueryCapture() if self.capture_sql else None
        response = None
        exc_name = None

        try:
            if capture is not None:
                with capture:
                    response = self.get_response(request)
            else:
                response = self.get_response(request)
            return response
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Re-raised below; recorded so failures do not vanish from the log.
            exc_name = type(exc).__name__
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            try:
                self._record(request, response, duration_ms, capture, exc_name)
            except Exception:  # pylint: disable=broad-exception-caught
                pass  # metrics must never break a request
            if response is not None and capture is not None:
                db_ms = capture.total_s * 1000.0
                response["Server-Timing"] = (
                    f'total;dur={duration_ms:.1f};desc="Total", '
                    f'db;dur={db_ms:.1f};desc="DB ({capture.count} queries)"'
                )

    def _record(self, request, response, duration_ms, capture, exc_name):
        status = getattr(response, "status_code", 500 if exc_name else 0)
        slow = duration_ms > self.slow_ms
        failed = status >= 400 or exc_name is not None

        # Always keep slow and failed requests; sample the rest.
        if not (slow or failed) and self.sample_rate < 1.0:
            if random.random() > self.sample_rate:
                return

        record = {
            "ts": timezone.now().isoformat(timespec="milliseconds"),
            "method": request.method,
            "path": request.path,
            "route": self._resolve_route(request),
            "view": self._resolve_view_name(request),
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "db_queries": capture.count if capture else None,
            "db_time_ms": round(capture.total_s * 1000.0, 2) if capture else None,
            "db_dupes": capture.duplicates if capture else None,
            "size": self._response_size(response),
            "ip": _get_client_ip(request),
            "user": self._get_username(request),
            "is_ajax": self._is_ajax(request),
        }
        if exc_name:
            record["exc"] = exc_name

        # On a slow request, the repeated query is usually the whole story,
        # so keep it. Normal requests stay one compact line.
        if slow and capture:
            shape, n = capture.worst_repeat()
            if shape:
                record["repeat_sql"] = shape
                record["repeat_n"] = n

        record = {k: v for k, v in record.items() if v is not None}
        metrics_logger.info(json.dumps(record, separators=(",", ":")))

    @staticmethod
    def _resolve_route(request) -> str:
        """Return the URL pattern, e.g. 'cart/<int:pk>/'."""
        match = getattr(request, "resolver_match", None)
        return getattr(match, "route", "") if match else ""

    @staticmethod
    def _resolve_view_name(request) -> str:
        """Return a readable dotted view name.

        Django wraps class-based views in a closure, so ``func.__qualname__``
        is ``View.as_view.<locals>.view``. The real class hangs off
        ``func.view_class``.
        """
        match = getattr(request, "resolver_match", None)
        if match is None:
            return "unknown"
        try:
            func = match.func
            cls = getattr(func, "view_class", None)
            if cls is not None:
                return f"{cls.__module__}.{cls.__qualname__}"
            module = getattr(func, "__module__", "")
            qual = getattr(func, "__qualname__", getattr(func, "__name__", "unknown"))
            return f"{module}.{qual}" if module else qual
        except Exception:  # pylint: disable=broad-exception-caught
            return "unknown"

    @staticmethod
    def _response_size(response) -> Optional[int]:
        if response is None:
            return None
        try:
            if response.has_header("Content-Length"):
                return int(response["Content-Length"])
            if hasattr(response, "content"):
                return len(response.content)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return None

    @staticmethod
    def _get_username(request) -> str:
        try:
            if hasattr(request, "user") and request.user.is_authenticated:
                return request.user.get_username()
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return "anonymous"

    @staticmethod
    def _is_ajax(request) -> bool:
        """Detect a background request.

        X-Requested-With alone misses ``fetch()``, which sends no such header.
        Same endpoint, two different answers, depending on the caller.
        """
        if request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest":
            return True
        if request.headers.get("Sec-Fetch-Dest", "") == "empty":
            return True
        accept = request.headers.get("Accept", "")
        return "application/json" in accept and "text/html" not in accept


# ---------------------------------------------------------------------------
# Function-level profiler
# ---------------------------------------------------------------------------

_registry_lock = threading.Lock()
_profile_registry: dict = {}


def profile_func(threshold_ms: float = 50.0, name: Optional[str] = None):
    """Profile a function and log calls that exceed *threshold_ms*.

    Aggregates are written to the metrics log when the process exits, tagged
    ``"t":"fn"``, so the report command can read them. Keeping them only in
    memory meant they were never visible to a separate management-command
    process.
    """

    def decorator(func):
        func_name = name or f"{func.__module__}.{func.__qualname__}"
        with _registry_lock:
            _profile_registry.setdefault(func_name, {
                "calls": 0, "total_ms": 0.0, "min_ms": None, "max_ms": 0.0,
                "threshold_ms": threshold_ms, "slow_calls": 0, "errors": 0,
            })

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            failed = False
            try:
                return func(*args, **kwargs)
            except Exception:  # pylint: disable=broad-exception-caught
                failed = True
                raise
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                with _registry_lock:
                    e = _profile_registry[func_name]
                    e["calls"] += 1
                    e["total_ms"] += elapsed_ms
                    e["max_ms"] = max(e["max_ms"], elapsed_ms)
                    e["min_ms"] = elapsed_ms if e["min_ms"] is None else min(e["min_ms"], elapsed_ms)
                    if failed:
                        e["errors"] += 1
                    if elapsed_ms > threshold_ms:
                        e["slow_calls"] += 1
                if elapsed_ms > threshold_ms:
                    logger.warning(
                        "[slow function] %s took %.2fms (threshold %.0fms)",
                        func_name, elapsed_ms, threshold_ms,
                    )

        wrapper._profile_name = func_name
        return wrapper

    return decorator


def get_profile_registry() -> dict:
    """Snapshot of the function profiling registry for this process."""
    with _registry_lock:
        return {k: dict(v) for k, v in _profile_registry.items()}


def flush_profile_registry() -> None:
    """Write function aggregates to the metrics log as ``t=fn`` events."""
    for fname, e in get_profile_registry().items():
        if not e["calls"]:
            continue
        metrics_logger.info(json.dumps({
            "t": "fn",
            "ts": timezone.now().isoformat(timespec="milliseconds"),
            "fn": fname,
            "calls": e["calls"],
            "total_ms": round(e["total_ms"], 2),
            "avg_ms": round(e["total_ms"] / e["calls"], 2),
            "min_ms": round(e["min_ms"] or 0.0, 2),
            "max_ms": round(e["max_ms"], 2),
            "slow_calls": e["slow_calls"],
            "errors": e["errors"],
        }, separators=(",", ":")))


atexit.register(flush_profile_registry)
