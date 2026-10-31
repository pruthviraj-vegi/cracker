"""Management command to audit GET URLs for database query count and response latency.

Usage:
    python manage.py audit_urls
    python manage.py audit_urls --app inventory
    python manage.py audit_urls --threshold 10
    python manage.py audit_urls --top 30 --sort time
"""

import re
import time
from typing import Dict, List, Tuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection, reset_queries
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver


class Command(BaseCommand):
    help = "Audit all registered GET routes to measure database query counts and response latency."

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            type=str,
            default="",
            help="Filter URLs by app name prefix (e.g. 'inventory', 'invoice', 'cart').",
        )
        parser.add_argument(
            "--threshold",
            type=int,
            default=15,
            help="Flag URLs that execute more than this number of queries (default: 15).",
        )
        parser.add_argument(
            "--top",
            type=int,
            default=30,
            help="Number of URLs to display in the ranked summary table (default: 30, 0 for all).",
        )
        parser.add_argument(
            "--sort",
            type=str,
            choices=["queries", "time"],
            default="queries",
            help="Sort by 'queries' (default) or 'time'.",
        )

    def get_sample_ids(self) -> Dict[str, any]:
        """Fetch sample primary keys from the database for parameter substitution."""
        sample_map = {
            "pk": 1,
            "id": 1,
            "user_id": 1,
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

        try:
            from customer.models import Customer
            c = Customer.objects.filter(is_deleted=False).first()
            if c:
                sample_map["customer_id"] = c.id
        except Exception:
            pass

        try:
            from supplier.models import Supplier, SupplierInvoice
            s = Supplier.objects.filter(is_deleted=False).first()
            if s:
                sample_map["supplier_id"] = s.id
            si = SupplierInvoice.objects.filter(is_deleted=False).first()
            if si:
                sample_map["supplier_invoice_id"] = si.id
        except Exception:
            pass

        try:
            from invoice.models import Invoice
            inv = Invoice.objects.first()
            if inv:
                sample_map["invoice_id"] = inv.id
        except Exception:
            pass

        try:
            from cart.models import Cart
            cart = Cart.objects.first()
            if cart:
                sample_map["cart_id"] = cart.id
        except Exception:
            pass

        return sample_map

    def extract_patterns(self, patterns, prefix="") -> List[Tuple[str, str]]:
        """Recursively discover all URL patterns."""
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

    def handle(self, *args, **options):
        filter_app = options.get("app", "").strip().lower()
        threshold = options.get("threshold", 15)
        top = options.get("top", 30)
        sort_by = options.get("sort", "queries")

        old_debug = settings.DEBUG
        settings.DEBUG = True

        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first() or User.objects.first()
        if not user:
            self.stdout.write(self.style.ERROR("No user found in database to authenticate."))
            return

        client = Client(SERVER_NAME="localhost")
        client.force_login(user)

        sample_map = self.get_sample_ids()
        raw_urls = self.extract_patterns(get_resolver().url_patterns)

        # Filter out system and destructive routes
        test_routes = []
        for raw_path, name in raw_urls:
            # Skip Django admin, debug toolbar, static files
            if (
                raw_path.startswith("admin/")
                or raw_path.startswith("__debug__/")
                or raw_path.startswith("static/")
                or raw_path.startswith("media/")
            ):
                continue

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

            # App filter if requested
            if filter_app and not lower_path.startswith(f"{filter_app}/") and not lower_path.startswith(f"inventory_{filter_app}/"):
                continue

            # Resolve parameters using sample map
            resolved = re.sub(
                r"<([^>]+)>",
                lambda m: str(sample_map.get(m.group(1).split(":")[-1], 1)),
                raw_path,
            ).lstrip("^").rstrip("$")

            if not resolved.startswith("/"):
                resolved = "/" + resolved

            test_routes.append((resolved, name))

        # Deduplicate paths
        unique_routes = []
        seen = set()
        for path, name in test_routes:
            if path not in seen:
                seen.add(path)
                unique_routes.append((path, name))

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n=== Auditing {len(unique_routes)} GET URLs (Authenticated as {user.username}) ==="
            )
        )

        results = []
        flagged = []

        for path, name in unique_routes:
            reset_queries()
            try:
                t0 = time.perf_counter()
                resp = client.get(path, follow=False)
                t1 = time.perf_counter()
                dur_ms = (t1 - t0) * 1000
                q_count = len(connection.queries)
                status = resp.status_code
            except Exception as err:
                status = "ERR"
                dur_ms = 0.0
                q_count = 0

            item = {
                "path": path,
                "name": name,
                "status": status,
                "dur_ms": dur_ms,
                "queries": q_count,
            }
            results.append(item)

            if q_count > threshold:
                flagged.append(item)

        settings.DEBUG = old_debug

        # Sort results
        if sort_by == "time":
            results.sort(key=lambda x: x["dur_ms"], reverse=True)
        else:
            results.sort(key=lambda x: (x["queries"], x["dur_ms"]), reverse=True)

        display_results = results[:top] if top > 0 else results

        # Header
        self.stdout.write("\n" + f"{'Path':<50} | {'Status':<6} | {'Time (ms)':<10} | {'Queries':<8} | {'View/Name'}")
        self.stdout.write("-" * 95)

        for r in display_results:
            line = f"{r['path']:<50} | {str(r['status']):<6} | {r['dur_ms']:<10.2f} | {r['queries']:<8} | {r['name']}"
            if r["queries"] > threshold:
                self.stdout.write(self.style.WARNING(line + " [HIGH QUERIES]"))
            elif r["status"] == 500 or r["status"] == "ERR":
                self.stdout.write(self.style.ERROR(line + " [SERVER ERROR]"))
            else:
                self.stdout.write(line)

        # Summary Statistics
        avg_time = sum(r["dur_ms"] for r in results) / len(results) if results else 0
        avg_queries = sum(r["queries"] for r in results) / len(results) if results else 0
        max_q = max(results, key=lambda x: x["queries"]) if results else None
        max_t = max(results, key=lambda x: x["dur_ms"]) if results else None

        self.stdout.write("\n" + "=" * 95)
        self.stdout.write(self.style.SUCCESS(f"Total Routes Audited: {len(results)}"))
        self.stdout.write(f"Average Response Time: {avg_time:.2f} ms")
        self.stdout.write(f"Average Queries / URL: {avg_queries:.1f}")

        if max_q:
            self.stdout.write(
                f"Most Queries: {max_q['queries']} queries on '{max_q['path']}' ({max_q['name']})"
            )
        if max_t:
            self.stdout.write(
                f"Slowest Route: {max_t['dur_ms']:.2f} ms on '{max_t['path']}' ({max_t['name']})"
            )

        if flagged:
            self.stdout.write(
                self.style.WARNING(
                    f"\n[!] {len(flagged)} routes exceeded the threshold of {threshold} queries:"
                )
            )
            for f in flagged:
                self.stdout.write(
                    self.style.WARNING(f"    - {f['path']} ({f['queries']} queries, {f['dur_ms']:.2f}ms)")
                )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\n[OK] All audited routes executed {threshold} queries or fewer!")
            )
