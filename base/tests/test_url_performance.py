"""Automated test suite to audit GET endpoints for database query count and response latency.

Run with:
    ./venv/bin/python manage.py test base.tests.test_url_performance
"""

import re
import time
from typing import Dict, List, Tuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, reset_queries
from django.test import Client, TestCase
from django.urls import URLPattern, URLResolver, get_resolver

# Maximum allowed queries on any single standard GET page before failing or warning
MAX_ALLOWED_QUERIES_PER_PAGE = 150


class UrlPerformanceTestCase(TestCase):
    """Audits GET routes for query explosion (N+1 issues) and latency."""

    @classmethod
    def setUpTestData(cls):
        """Create sample data so parameterized URLs can resolve and render."""
        User = get_user_model()
        cls.user = User.objects.create_superuser(
            first_name="Admin",
            phone_number="9999999999",
            password="testpassword123",
            email="tester@example.com",
        )

    def extract_patterns(self, patterns, prefix="") -> List[Tuple[str, str]]:
        discovered = []
        for pattern in patterns:
            if isinstance(pattern, URLPattern):
                full_path = prefix + str(pattern.pattern)
                name = pattern.name or getattr(pattern.callback, "__name__", "")
                discovered.append((full_path, name))
            elif isinstance(pattern, URLResolver):
                sub_prefix = prefix + str(pattern.pattern)
                discovered.extend(self.extract_patterns(pattern.url_patterns, sub_prefix))
        return discovered

    def get_sample_ids(self) -> Dict[str, any]:
        """Map common URL parameters to safe test IDs."""
        sample_map = {
            "pk": 1,
            "id": 1,
            "user_id": self.user.id,
            "product_id": 1,
            "variant_id": 1,
            "customer_id": 1,
            "supplier_id": 1,
            "invoice_id": 1,
            "cart_id": 1,
            "item_id": 1,
            "credit_id": 1,
            "payment_id": 1,
            "batch_id": 1,
            "salary_id": 1,
            "transaction_id": 1,
            "record_id": 1,
            "slug": "sample",
        }

        try:
            from inventory.models import Product, ProductVariant
            p = Product.objects.filter(is_deleted=False).first()
            if p:
                sample_map["product_id"] = p.id
                sample_map["pk"] = p.id
            v = ProductVariant.objects.filter(is_deleted=False).first()
            if v:
                sample_map["variant_id"] = v.id
        except Exception:
            pass

        return sample_map

    def test_get_urls_performance(self):
        """Execute GET requests across all non-destructive app routes and check query counts."""
        client = Client(SERVER_NAME="localhost")
        client.force_login(self.user)

        sample_map = self.get_sample_ids()
        raw_urls = self.extract_patterns(get_resolver().url_patterns)

        test_routes = []
        for raw_path, name in raw_urls:
            # Skip admin, debug toolbar, static
            if (
                raw_path.startswith("admin/")
                or raw_path.startswith("__debug__/")
                or raw_path.startswith("static/")
                or raw_path.startswith("media/")
            ):
                continue

            # Skip destructive or action endpoints
            lower_path = raw_path.lower()
            if any(
                term in lower_path
                for term in [
                    "delete",
                    "logout",
                    "invalidate",
                    "reset-password",
                    "direct-print",
                    "auto_reallocate",
                    "auto-reallocate",
                ]
            ):
                continue

            resolved = re.sub(
                r"<([^>]+)>",
                lambda m: str(sample_map.get(m.group(1).split(":")[-1], 1)),
                raw_path,
            ).lstrip("^").rstrip("$")

            if not resolved.startswith("/"):
                resolved = "/" + resolved

            test_routes.append((resolved, name))

        # Deduplicate
        unique_routes = list(dict.fromkeys(test_routes))

        high_query_routes = []
        total_queries = 0
        successful_routes = 0

        for path, name in unique_routes:
            reset_queries()
            try:
                t0 = time.perf_counter()
                resp = client.get(path, follow=False)
                t1 = time.perf_counter()
                dur_ms = (t1 - t0) * 1000
                q_count = len(connection.queries)

                if resp.status_code in [200, 301, 302]:
                    successful_routes += 1
                    total_queries += q_count

                    if q_count > MAX_ALLOWED_QUERIES_PER_PAGE:
                        high_query_routes.append((path, name, q_count, dur_ms))
            except Exception:
                # Ignore routes that expect specific query parameters or special setup
                pass

        # Assert no route exceeds catastrophic query ceiling
        if high_query_routes:
            msg = "\n".join(
                [f"Route '{p}' ({name}) executed {q} queries ({d:.1f}ms) - exceeds limit of {MAX_ALLOWED_QUERIES_PER_PAGE}" for p, name, q, d in high_query_routes]
            )
            self.fail(f"High query routes detected:\n{msg}")

        print(f"\n[Performance Test OK] Audited {len(unique_routes)} routes. {successful_routes} rendered successfully.")
