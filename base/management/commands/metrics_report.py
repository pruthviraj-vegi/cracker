"""
Generate a static HTML performance dashboard from metrics log data.

Reads ``logs/metrics.jsonl`` (and rotated backups), computes aggregated
statistics, and produces a self-contained HTML file that can be opened in any
browser -- no external CSS/JS/font dependencies, works offline.

Design notes
------------
This report is built around three ideas the previous version lacked:

1. **Requests are grouped by view/route, not raw path.**  ``/cart/2127/`` and
   ``/cart/2151/`` are the same endpoint; keying on ``path`` shattered every
   detail-page into a one-hit row and made ranking meaningless.

2. **Endpoints are ranked by total time consumed, not by average.**  A page hit
   once at 500ms matters far less than a page hit 4,000 times at 80ms.  Total
   time is what you can actually claw back by optimising.

3. **The report states findings in words.**  Rules run over the aggregates and
   describe what looks wrong (latency regime shifts, non-DB-bound slowness,
   N+1 suspects, error clusters) instead of leaving you to infer it from six
   tables.

Usage::

    ./venv/bin/python manage.py metrics_report
    ./venv/bin/python manage.py metrics_report --days 7
    ./venv/bin/python manage.py metrics_report --slow-ms 300
    ./venv/bin/python manage.py metrics_report --output /tmp/report.html
"""

import glob
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# Path segments that are clearly identifiers get folded into a placeholder so
# that /cart/2127/ and /cart/2151/ aggregate into a single /cart/{id}/ row.
_NUMERIC_SEG = re.compile(r"^\d+$")
_UUID_SEG = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
_HASH_SEG = re.compile(r"^[0-9a-f]{16,}$", re.I)


def normalise_path(path: str) -> str:
    """Collapse identifier-looking segments: /cart/2127/ -> /cart/{id}/."""
    out = []
    for seg in path.split("/"):
        if _NUMERIC_SEG.match(seg):
            out.append("{id}")
        elif _UUID_SEG.match(seg):
            out.append("{uuid}")
        elif _HASH_SEG.match(seg):
            out.append("{hash}")
        else:
            out.append(seg)
    return "/".join(out)


def clean_view(view: str) -> str:
    """Make class-based-view names readable.

    Django wraps CBVs so ``View.as_view()`` reports as
    ``app.views.View.as_view.<locals>.view``, which is useless in a table.
    The middleware in metrics.py resolves ``view_class`` properly for new
    records; this handles older records already on disk.
    """
    if "<locals>" in view:
        return view.split(".View.as_view")[0] + " (class view)"
    return view


def pct(values, q):
    """Linear-interpolated percentile.  ``q`` is 0..100."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * (q / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(s[int(k)])
    return float(s[lo]) + (float(s[hi]) - float(s[lo])) * (k - lo)


def fmt_span(seconds):
    """Human-readable bucket width."""
    if seconds < 90:
        return f"{seconds:.0f} second" + ("" if round(seconds) == 1 else "s")
    if seconds < 5400:
        return f"{seconds / 60:.0f} minutes"
    return f"{seconds / 3600:.1f} hours"


def fmt_ms(v):
    """Human-readable duration."""
    if v >= 10000:
        return f"{v / 1000:.1f}s"
    if v >= 1000:
        return f"{v / 1000:.2f}s"
    if v >= 100:
        return f"{v:.0f}ms"
    return f"{v:.1f}ms"


def esc(text):
    """Escape HTML special characters."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class Command(BaseCommand):
    """Generate a static HTML performance dashboard."""

    help = "Generate a static HTML performance metrics dashboard from logs/metrics.jsonl"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=0,
            help="Only analyse the last N days (0 = all available data).",
        )
        parser.add_argument(
            "--output", type=str, default="",
            help="Output path for the HTML file (default: logs/metrics_dashboard.html).",
        )
        parser.add_argument(
            "--slow-ms", type=float, default=200.0,
            help="Requests above this many ms are treated as slow (default: 200).",
        )
        parser.add_argument(
            "--top", type=int, default=25,
            help="Rows to show in each endpoint table (default: 25).",
        )

    def handle(self, *args, **options):
        base_dir = str(settings.BASE_DIR)
        log_dir = os.path.join(base_dir, "logs")
        output_path = options["output"] or os.path.join(log_dir, "metrics_dashboard.html")

        records, skipped = load_records(log_dir, options["days"])

        if not records:
            self.stdout.write(self.style.WARNING(
                "No metrics records found in logs/metrics.jsonl. "
                "Check that PerformanceMetricsMiddleware is enabled and the "
                "server has handled requests."
            ))
            return

        report = analyse(records, slow_ms=options["slow_ms"], top=options["top"])
        report["skipped_lines"] = skipped
        html = render_html(report)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        self.stdout.write(self.style.SUCCESS(
            f"Dashboard written to {output_path}  ({len(records):,} requests analysed)"
        ))
        for finding in report["findings"][:3]:
            self.stdout.write(f"  - {finding['title']}")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _rotation_key(filepath):
    """Sort rotated logs oldest-first.

    ``sorted(glob(...))`` puts metrics.jsonl.10 before metrics.jsonl.2, which
    scrambles any time-ordered output.  RotatingFileHandler uses a higher
    suffix for older files, so sort descending on the numeric suffix.
    """
    name = os.path.basename(filepath)
    suffix = name.rsplit(".", 1)[-1]
    return -int(suffix) if suffix.isdigit() else 0


def load_records(log_dir, days=0):
    """Read and parse JSON lines from metrics log files."""
    files = sorted(glob.glob(os.path.join(log_dir, "metrics.jsonl*")), key=_rotation_key)
    if not files:
        return [], 0

    cutoff = datetime.now() - timedelta(days=days) if days > 0 else None
    records, skipped = [], 0

    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = _parse_line(line)
                    if rec is None:
                        skipped += 1
                        continue
                    # Function-profile events share the log; skip them here.
                    if rec.get("t") and rec.get("t") != "req":
                        continue
                    dt = _parse_ts(rec.get("ts"))
                    if dt is None:
                        skipped += 1
                        continue
                    if cutoff and dt.replace(tzinfo=None) < cutoff:
                        continue
                    rec["_dt"] = dt
                    records.append(rec)
        except OSError:
            continue

    records.sort(key=lambda r: r["_dt"])
    return records, skipped


def _parse_line(line):
    """Parse one log line, tolerating a logging-formatter prefix."""
    try:
        if line.startswith("{"):
            return json.loads(line)
        idx = line.find("{")
        if idx >= 0:
            return json.loads(line[idx:])
    except json.JSONDecodeError:
        return None
    return None


def _parse_ts(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    # Normalise to naive local time so aware and naive records can be mixed.
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse(records, slow_ms=200.0, top=25):
    """Turn raw records into everything the template needs."""
    n = len(records)
    durations = [r.get("duration_ms", 0.0) for r in records]
    db_times = [r.get("db_time_ms", 0.0) for r in records]
    queries = [r.get("db_queries", 0) for r in records]
    t_first, t_last = records[0]["_dt"], records[-1]["_dt"]
    span_s = max((t_last - t_first).total_seconds(), 1.0)

    summary = {
        "requests": n,
        "from": t_first,
        "to": t_last,
        "span_s": span_s,
        "rpm": n / (span_s / 60.0),
        "p50": pct(durations, 50),
        "p95": pct(durations, 95),
        "p99": pct(durations, 99),
        "max": max(durations),
        "mean": statistics.fmean(durations),
        "total_ms": sum(durations),
        "db_total_ms": sum(db_times),
        "queries_total": sum(queries),
        "queries_p95": pct(queries, 95),
        "users": len({r.get("user", "anonymous") for r in records}),
        "ips": len({r.get("ip", "") for r in records}),
        "errors": sum(1 for r in records if r.get("status", 200) >= 400),
        "server_errors": sum(1 for r in records if r.get("status", 200) >= 500),
        "slow": sum(1 for d in durations if d > slow_ms),
        "slow_ms": slow_ms,
        "generated_at": datetime.now(),
    }
    summary["error_rate"] = summary["errors"] / n * 100
    summary["db_share"] = (summary["db_total_ms"] / summary["total_ms"] * 100
                           if summary["total_ms"] else 0.0)

    endpoints = _group_endpoints(records, slow_ms)
    endpoints.sort(key=lambda e: e["total_ms"], reverse=True)
    for e in endpoints:
        e["share"] = e["total_ms"] / summary["total_ms"] * 100 if summary["total_ms"] else 0

    return {
        "summary": summary,
        "endpoints": endpoints[:top],
        "all_endpoints": endpoints,
        # Bucket count scales with volume: enough columns to show shape,
        # not so many that most sit empty.
        "timeline": _timeline(records, buckets=max(24, min(180, int(n / 1.5) or 24))),
        "status": _status_breakdown(records),
        "errors": _error_samples(records),
        "slowest": _slowest_samples(records, slow_ms),
        "methods": Counter(r.get("method", "?") for r in records).most_common(),
        "users": _user_breakdown(records, top=10),
        "findings": [],  # filled below
        "top": top,
    }


def _group_endpoints(records, slow_ms):
    """Aggregate requests by resolved view, falling back to a normalised path."""
    groups = defaultdict(lambda: {
        "durations": [], "queries": [], "db_times": [],
        "paths": set(), "statuses": Counter(), "slow": 0, "last": None,
    })

    for r in records:
        # Prefer the route/view identity; raw path is a last resort.
        key = r.get("route") or clean_view(r.get("view", "")) or normalise_path(r.get("path", "?"))
        if key in ("unknown", ""):
            key = normalise_path(r.get("path", "?"))
        g = groups[key]
        d = r.get("duration_ms", 0.0)
        g["durations"].append(d)
        g["queries"].append(r.get("db_queries", 0))
        g["db_times"].append(r.get("db_time_ms", 0.0))
        g["paths"].add(normalise_path(r.get("path", "")))
        g["statuses"][r.get("status", 0)] += 1
        if d > slow_ms:
            g["slow"] += 1
        g["last"] = r["_dt"]

    out = []
    for key, g in groups.items():
        d = g["durations"]
        q = g["queries"]
        out.append({
            "key": key,
            "path": sorted(g["paths"])[0] if g["paths"] else "",
            "paths": len(g["paths"]),
            "count": len(d),
            "total_ms": sum(d),
            "p50": pct(d, 50),
            "p95": pct(d, 95),
            "max": max(d),
            "min": min(d),
            "db_ms": statistics.fmean(g["db_times"]) if g["db_times"] else 0.0,
            "q_med": statistics.median(q) if q else 0,
            "q_max": max(q) if q else 0,
            "q_min": min(q) if q else 0,
            "q_spread": (max(q) - min(q)) if q else 0,
            "slow": g["slow"],
            "errors": sum(c for s, c in g["statuses"].items() if s >= 400),
            "last": g["last"],
        })
    return out


def _timeline(records, buckets=160):
    """Bucket requests over the wall-clock range for the strip chart.

    Buckets (rather than one mark per request) keep the chart readable and the
    file small whether the log holds 60 requests or 6 million.
    """
    t0, t1 = records[0]["_dt"], records[-1]["_dt"]
    span = max((t1 - t0).total_seconds(), 1.0)
    width = span / buckets

    bins = [{"count": 0, "durations": [], "errors": 0, "t": t0 + timedelta(seconds=width * i)}
            for i in range(buckets)]

    for r in records:
        offset = (r["_dt"] - t0).total_seconds()
        i = min(int(offset / width), buckets - 1)
        b = bins[i]
        b["count"] += 1
        b["durations"].append(r.get("duration_ms", 0.0))
        if r.get("status", 200) >= 400:
            b["errors"] += 1

    for b in bins:
        b["p95"] = pct(b["durations"], 95) if b["durations"] else 0.0
        b["max"] = max(b["durations"]) if b["durations"] else 0.0
        b["p50"] = pct(b["durations"], 50) if b["durations"] else 0.0

    return {"bins": bins, "t0": t0, "t1": t1, "bucket_s": width,
            "max_count": max((b["count"] for b in bins), default=1) or 1,
            "max_ms": max((b["max"] for b in bins), default=1.0) or 1.0}


def _status_breakdown(records):
    c = Counter(r.get("status", 0) for r in records)
    total = len(records)
    return [{"code": code, "count": n, "pct": n / total * 100}
            for code, n in sorted(c.items())]


def _error_samples(records, limit=25):
    errs = [r for r in records if r.get("status", 200) >= 400]
    errs.sort(key=lambda r: r["_dt"], reverse=True)
    return errs[:limit]


def _slowest_samples(records, slow_ms, limit=25):
    slow = [r for r in records if r.get("duration_ms", 0) > slow_ms]
    slow.sort(key=lambda r: r.get("duration_ms", 0), reverse=True)
    return slow[:limit]


def _user_breakdown(records, top=10):
    data = defaultdict(lambda: {"count": 0, "durations": [], "paths": set()})
    for r in records:
        u = data[r.get("user", "anonymous")]
        u["count"] += 1
        u["durations"].append(r.get("duration_ms", 0.0))
        u["paths"].add(normalise_path(r.get("path", "")))
    out = [{"user": k, "count": v["count"], "paths": len(v["paths"]),
            "p50": pct(v["durations"], 50), "p95": pct(v["durations"], 95)}
           for k, v in data.items()]
    out.sort(key=lambda x: x["count"], reverse=True)
    return out[:top]


# ---------------------------------------------------------------------------
# Findings: rules that describe, in words, what looks wrong
# ---------------------------------------------------------------------------

def build_findings(report):
    """Run diagnostic rules over the aggregates.

    Each finding is {level, title, body, action}.  ``level`` is one of
    'critical', 'warn', 'info'.
    """
    s = report["summary"]
    eps = report["all_endpoints"]
    slow = report["slowest"]
    out = []

    # -- Fixed-cost latency plateau ---------------------------------------
    # Slow requests that cluster tightly in duration across *different* views
    # are a constant overhead, not an endpoint problem.
    if len(slow) >= 4:
        durs = [r.get("duration_ms", 0.0) for r in slow]
        spread = statistics.pstdev(durs) / statistics.fmean(durs) if statistics.fmean(durs) else 1
        distinct_views = len({clean_view(r.get("view", "")) for r in slow})
        if spread < 0.15 and distinct_views >= 2:
            t_from = min(r["_dt"] for r in slow)
            t_to = max(r["_dt"] for r in slow)
            out.append({
                "level": "critical",
                "title": f"A fixed cost of about {fmt_ms(statistics.fmean(durs))} is being added to requests",
                "body": (
                    f"{len(slow)} slow requests spread across {distinct_views} different views "
                    f"all land between {fmt_ms(min(durs))} and {fmt_ms(max(durs))}. Work that varies "
                    f"(different views, different query counts) producing near-identical timings means "
                    f"the cost is not in the views. It appears from {t_from:%H:%M:%S} to {t_to:%H:%M:%S}."
                ),
                "action": (
                    "Look for a blocking call on a shared path: an external HTTP request "
                    "(payment, SMS, GST lookup) without a short timeout, a DNS retry, a sleep, "
                    "or middleware added around that time. Compare against what changed at "
                    f"{t_from:%H:%M}."
                ),
            })

    # -- Slowness that is not the database --------------------------------
    if slow:
        non_db = [
            (r.get("duration_ms", 0.0) - r.get("db_time_ms", 0.0)) / r["duration_ms"]
            for r in slow if r.get("duration_ms", 0)
        ]
        if non_db and statistics.median(non_db) > 0.8:
            share = statistics.median(non_db) * 100
            out.append({
                "level": "warn",
                "title": f"{share:.0f}% of the time in slow requests is spent outside the database",
                "body": (
                    "SQL execution accounts for very little of the wall time on slow requests, "
                    "so adding indexes or tuning queries will not move these numbers."
                ),
                "action": (
                    "Profile the Python side: template rendering, serialisation of large "
                    "result sets, image or PDF generation, and any synchronous network calls."
                ),
            })

    # -- N+1 suspects ------------------------------------------------------
    n1 = [e for e in eps if e["q_spread"] >= 4 and e["q_max"] >= 8 and e["count"] >= 2]
    n1.sort(key=lambda e: e["q_spread"], reverse=True)
    if n1:
        top = n1[0]
        names = ", ".join(e["key"].split(".")[-1] for e in n1[:3])
        out.append({
            "level": "warn",
            "title": f"{len(n1)} endpoint(s) run a different number of queries on each call",
            "body": (
                f"{top['key']} ranges from {top['q_min']} to {top['q_max']} queries for the same "
                "request. Query count that scales with the number of rows returned is the "
                f"signature of an N+1 loop. Also seen in: {names}."
            ),
            "action": (
                "Add select_related() for forward ForeignKey/OneToOne access and "
                "prefetch_related() for reverse and ManyToMany access on the querysets "
                "behind these views."
            ),
        })

    # -- Time concentration ------------------------------------------------
    if len(eps) >= 3 and s["total_ms"]:
        top3 = sum(e["total_ms"] for e in eps[:3]) / s["total_ms"] * 100
        out.append({
            "level": "info",
            "title": f"Three endpoints account for {top3:.0f}% of all time served",
            "body": "  ".join(
                f"{e['key'].split('.')[-1]} {e['share']:.0f}%" for e in eps[:3]
            ),
            "action": "Optimisation effort anywhere else has a small ceiling. Start here.",
        })

    # -- Errors ------------------------------------------------------------
    if s["server_errors"]:
        codes = Counter(r.get("status") for r in report["errors"] if r.get("status", 0) >= 500)
        out.append({
            "level": "critical",
            "title": f"{s['server_errors']} server error(s) in this window",
            "body": "Status codes seen: " + ", ".join(f"{c} x{n}" for c, n in codes.items())
                    + ". Individual requests are listed in the errors table below.",
            "action": "Cross-reference the timestamps against your Django exception log.",
        })

    # -- Query capture disabled -------------------------------------------
    if s["queries_total"] == 0:
        out.append({
            "level": "warn",
            "title": "No SQL queries were recorded",
            "body": (
                "connection.queries is only populated when DEBUG is True, so query counts "
                "and DB timings silently read as zero in production."
            ),
            "action": (
                "Use the CaptureQueriesContext approach shown in metrics.py so query counts "
                "are collected regardless of the DEBUG setting."
            ),
        })

    # -- Sample representativeness ----------------------------------------
    if s["ips"] == 1 and s["users"] <= 1:
        out.append({
            "level": "info",
            "title": "This sample came from a single client",
            "body": (
                f"All {s['requests']} requests share one IP and one user, over "
                f"{s['span_s'] / 60:.0f} minutes. Concurrency effects, connection-pool "
                "contention and cache-miss behaviour under real load are not represented."
            ),
            "action": "Treat these numbers as a floor, not as production latency.",
        })

    order = {"critical": 0, "warn": 1, "info": 2}
    out.sort(key=lambda f: order[f["level"]])
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

CSS = """
:root{
  --paper:#E7EAEE; --panel:#FCFCFD; --sunk:#F1F3F6;
  --ink:#10151B; --ink2:#58626D; --ink3:#8B95A2;
  --rule:#D2D8DF; --rule2:#E3E8ED;
  --signal:#1B3FB8; --signal-soft:#C9D3F2;
  --warn:#9C5A15; --warn-soft:#F0DFC6;
  --bad:#AC3126; --bad-soft:#F2D2CE;
  --good:#116A53;
}
:root[data-theme="dark"]{
  --paper:#0E1216; --panel:#161B21; --sunk:#1B2127;
  --ink:#E3E9EF; --ink2:#95A1AE; --ink3:#6B7885;
  --rule:#262E37; --rule2:#1F262D;
  --signal:#7C9BFF; --signal-soft:#2A3660;
  --warn:#D89B52; --warn-soft:#3A2E1C;
  --bad:#E87364; --bad-soft:#3D2320;
  --good:#4FB894;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font:400 14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  font-variant-numeric:tabular-nums; -webkit-font-smoothing:antialiased;
}
.shell{max-width:1180px;margin:0 auto;padding:32px 24px 64px}

/* Masthead ------------------------------------------------------------ */
.mast{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;margin-bottom:28px}
.mast h1{margin:0;font-size:19px;font-weight:600;letter-spacing:-.01em}
.mast p{margin:6px 0 0;color:var(--ink2);font-size:13px;max-width:60ch}
.mast b{font-weight:600;color:var(--ink)}
.themer{
  border:1px solid var(--rule);background:var(--panel);color:var(--ink2);
  border-radius:4px;padding:6px 11px;font:inherit;font-size:12px;cursor:pointer;flex:none;
}
.themer:hover{color:var(--ink);border-color:var(--ink3)}
.themer:focus-visible{outline:2px solid var(--signal);outline-offset:2px}

/* Panels -------------------------------------------------------------- */
.panel{background:var(--panel);border:1px solid var(--rule);border-radius:5px;margin-bottom:18px}
.panel > h2{
  margin:0;padding:13px 18px;font-size:13.5px;font-weight:600;
  border-bottom:1px solid var(--rule2);display:flex;justify-content:space-between;
  align-items:center;gap:12px;
}
.panel > h2 .note{font-weight:400;color:var(--ink3);font-size:12px}
.pad{padding:18px}

/* Hero chart ---------------------------------------------------------- */
.chart{padding:18px 18px 8px}
.chart svg{display:block;width:100%;height:auto;overflow:visible}
.gridline{stroke:var(--rule2);stroke-width:1}
.axis{fill:var(--ink3);font-size:10px;font-weight:500}
.bar-p95{fill:var(--signal);opacity:.82}
.bar-p95.err{fill:var(--bad);opacity:.9}
.tick-max{stroke:var(--ink3);stroke-width:1;opacity:.55}
.bar-vol{fill:var(--ink3);opacity:.32}
.legend{display:flex;gap:18px;padding:0 18px 16px;color:var(--ink2);font-size:12px;flex-wrap:wrap}
.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;vertical-align:baseline}

/* Readout strip ------------------------------------------------------- */
.readout{display:grid;grid-template-columns:repeat(auto-fit,minmax(122px,1fr));border-top:1px solid var(--rule2)}
.readout div{padding:14px 18px;border-right:1px solid var(--rule2)}
.readout div:last-child{border-right:0}
.readout dt{margin:0 0 3px;color:var(--ink2);font-size:12px;font-weight:400}
.readout dd{margin:0;font-size:21px;font-weight:600;letter-spacing:-.02em}
.readout dd small{font-size:12px;font-weight:400;color:var(--ink3);letter-spacing:0}
.readout .alert dd{color:var(--bad)}

/* Findings ------------------------------------------------------------ */
.finding{padding:16px 18px;border-bottom:1px solid var(--rule2);display:flex;gap:14px}
.finding:last-child{border-bottom:0}
.finding .mark{width:3px;border-radius:2px;flex:none;background:var(--ink3)}
.finding.critical .mark{background:var(--bad)}
.finding.warn .mark{background:var(--warn)}
.finding.info .mark{background:var(--signal)}
.finding h3{margin:0 0 5px;font-size:13.5px;font-weight:600}
.finding.critical h3{color:var(--bad)}
.finding p{margin:0;color:var(--ink2);font-size:13px;max-width:82ch}
.finding .do{margin-top:7px;color:var(--ink);font-size:13px}
.finding .do::before{content:"Try: ";color:var(--ink3)}

/* Tables -------------------------------------------------------------- */
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{
  text-align:left;padding:9px 14px;font-weight:600;font-size:12px;color:var(--ink2);
  border-bottom:1px solid var(--rule);white-space:nowrap;cursor:pointer;
  position:sticky;top:0;background:var(--panel);
}
th:hover{color:var(--ink)}
th[aria-sort="ascending"]::after{content:" \\2191";color:var(--signal)}
th[aria-sort="descending"]::after{content:" \\2193";color:var(--signal)}
td{padding:8px 14px;border-bottom:1px solid var(--rule2);white-space:nowrap}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--sunk)}
.num{text-align:right}
.name{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
  max-width:360px;overflow:hidden;text-overflow:ellipsis;
}
.dim{color:var(--ink3)}
.hot{color:var(--bad);font-weight:600}
.mild{color:var(--warn)}
.meter{position:relative;min-width:84px;height:6px;border-radius:3px;background:var(--rule2)}
.meter span{position:absolute;inset:0 auto 0 0;border-radius:3px;background:var(--signal)}
.chip{
  display:inline-block;padding:1px 7px;border-radius:3px;font-size:11.5px;font-weight:600;
  background:var(--sunk);color:var(--ink2);
}
.chip.s2{background:var(--signal-soft);color:var(--signal)}
.chip.s3{background:var(--sunk);color:var(--ink2)}
.chip.s4{background:var(--warn-soft);color:var(--warn)}
.chip.s5{background:var(--bad-soft);color:var(--bad)}
:root[data-theme="dark"] .chip.s2,:root[data-theme="dark"] .chip.s4,
:root[data-theme="dark"] .chip.s5{color:var(--ink)}

/* Filter -------------------------------------------------------------- */
.filter{
  width:210px;border:1px solid var(--rule);background:var(--panel);color:var(--ink);
  border-radius:4px;padding:5px 9px;font:inherit;font-size:12px;font-weight:400;
}
.filter:focus-visible{outline:2px solid var(--signal);outline-offset:1px;border-color:var(--signal)}
.empty{padding:18px;color:var(--ink3);font-size:13px}

.cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.cols > .panel{margin-bottom:0}
footer{color:var(--ink3);font-size:12px;padding-top:6px}
footer code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}

@media(max-width:860px){
  .shell{padding:20px 14px 40px}
  .cols{grid-template-columns:1fr}
  .name{max-width:200px}
}
@media print{
  body{background:#fff}
  .themer,.filter{display:none}
  .panel{break-inside:avoid;border-color:#bbb}
}
"""

JS = """
(function(){
  var root=document.documentElement;
  try{var saved=localStorage.getItem('mtheme'); if(saved) root.setAttribute('data-theme',saved);}catch(e){}
  if(!root.getAttribute('data-theme')){
    root.setAttribute('data-theme', matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
  }
  document.getElementById('themer').addEventListener('click',function(){
    var next=root.getAttribute('data-theme')==='dark'?'light':'dark';
    root.setAttribute('data-theme',next);
    this.textContent=next==='dark'?'Light':'Dark';
    try{localStorage.setItem('mtheme',next);}catch(e){}
  });
  document.getElementById('themer').textContent=root.getAttribute('data-theme')==='dark'?'Light':'Dark';

  document.querySelectorAll('table[data-sortable] th').forEach(function(th){
    th.setAttribute('tabindex','0');
    function run(){
      var table=th.closest('table'), body=table.tBodies[0],
          idx=Array.prototype.indexOf.call(th.parentNode.children,th),
          numeric=th.dataset.type==='n',
          asc=th.getAttribute('aria-sort')!=='ascending';
      table.querySelectorAll('th').forEach(function(o){o.removeAttribute('aria-sort')});
      th.setAttribute('aria-sort',asc?'ascending':'descending');
      var rows=Array.prototype.slice.call(body.rows);
      rows.sort(function(a,b){
        var x=a.cells[idx], y=b.cells[idx];
        var va=x?(x.dataset.v!==undefined?x.dataset.v:x.textContent):'';
        var vb=y?(y.dataset.v!==undefined?y.dataset.v:y.textContent):'';
        if(numeric){return ((parseFloat(va)||0)-(parseFloat(vb)||0))*(asc?1:-1);}
        return String(va).localeCompare(String(vb))*(asc?1:-1);
      });
      rows.forEach(function(r){body.appendChild(r)});
    }
    th.addEventListener('click',run);
    th.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();run();}});
  });

  document.querySelectorAll('.filter').forEach(function(box){
    box.addEventListener('input',function(){
      var q=this.value.toLowerCase(),
          table=document.getElementById(this.dataset.target);
      if(!table) return;
      Array.prototype.forEach.call(table.tBodies[0].rows,function(r){
        r.style.display = r.textContent.toLowerCase().indexOf(q)>-1 ? '' : 'none';
      });
    });
  });
})();
"""


def _chart_svg(tl, summary):
    """Latency strip chart: p95 bar plus max tick per time bucket, log scale."""
    W, H = 1000, 190
    L, R, T, B = 46, 6, 10, 26
    plot_w, plot_h = W - L - R, H - T - B
    bins = tl["bins"]
    n = len(bins)
    step = plot_w / n
    bw = max(step - 1.1, 1.0)

    ceiling = max(tl["max_ms"], 10.0) * 1.15
    floor = 1.0

    def y(ms):
        ms = max(ms, floor)
        frac = math.log10(ms / floor) / math.log10(ceiling / floor)
        return T + plot_h - frac * plot_h

    parts = []

    # Gridlines on decade boundaries, plus the slow threshold.
    decade = 10.0
    while decade <= ceiling:
        if True:
            yy = y(decade)
            parts.append(f'<line class="gridline" x1="{L}" y1="{yy:.1f}" x2="{W - R}" y2="{yy:.1f}"/>')
            label = f"{decade:.0f}ms" if decade < 1000 else f"{decade / 1000:.0f}s"
            parts.append(
                f'<text class="axis" x="{L - 8}" y="{yy + 3.5:.1f}" text-anchor="end">'
                f'{label}</text>'
            )
        decade *= 10

    thr = summary["slow_ms"]
    if floor < thr < ceiling:
        yy = y(thr)
        parts.append(
            f'<line x1="{L}" y1="{yy:.1f}" x2="{W - R}" y2="{yy:.1f}" '
            f'stroke="var(--warn)" stroke-width="1" stroke-dasharray="3 3" opacity=".6"/>'
        )
        parts.append(
            f'<text class="axis" x="{W - R}" y="{yy - 5:.1f}" text-anchor="end" '
            f'fill="var(--warn)">slow above {fmt_ms(thr)}</text>'
        )

    for i, b in enumerate(bins):
        if not b["count"]:
            continue
        x = L + i * step
        y95, ymax = y(b["p95"]), y(b["max"])
        cls = "bar-p95 err" if b["errors"] else "bar-p95"
        label = (f'{b["t"]:%H:%M:%S} &#183; {b["count"]} req &#183; '
                 f'p95 {fmt_ms(b["p95"])} &#183; max {fmt_ms(b["max"])}')
        parts.append(
            f'<g><title>{label}</title>'
            f'<rect class="{cls}" x="{x:.2f}" y="{y95:.1f}" width="{bw:.2f}" '
            f'height="{max(T + plot_h - y95, 1):.1f}" rx="1"/>'
            f'<line class="tick-max" x1="{x:.2f}" y1="{ymax:.1f}" '
            f'x2="{x + bw:.2f}" y2="{ymax:.1f}"/></g>'
        )

    parts.append(f'<line class="gridline" x1="{L}" y1="{T + plot_h}" x2="{W - R}" y2="{T + plot_h}"/>')

    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        t = tl["t0"] + timedelta(seconds=tl["bucket_s"] * len(bins) * frac)
        x = L + plot_w * frac
        anchor = "start" if frac == 0 else ("end" if frac == 1 else "middle")
        parts.append(
            f'<text class="axis" x="{x:.0f}" y="{H - 8}" text-anchor="{anchor}">'
            f'{t:%H:%M}</text>'
        )

    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Request latency over time">' \
           + "".join(parts) + "</svg>"


def _volume_svg(tl):
    """Companion request-volume strip, aligned to the latency chart."""
    W, H = 1000, 34
    L, R = 46, 6
    bins = tl["bins"]
    step = (W - L - R) / len(bins)
    bw = max(step - 1.1, 1.0)
    mx = tl["max_count"]
    parts = [f'<text class="axis" x="{L - 8}" y="{H - 10}" text-anchor="end">req</text>']
    for i, b in enumerate(bins):
        if not b["count"]:
            continue
        h = max(b["count"] / mx * (H - 12), 1.2)
        parts.append(
            f'<rect class="bar-vol" x="{L + i * step:.2f}" y="{H - 8 - h:.1f}" '
            f'width="{bw:.2f}" height="{h:.1f}" rx="1"><title>{b["count"]} requests</title></rect>'
        )
    return f'<svg viewBox="0 0 {W} {H}" aria-hidden="true">' + "".join(parts) + "</svg>"


def _status_class(code):
    return f"s{int(code) // 100}" if code else "s5"


def _heat(value, warn, bad):
    if value >= bad:
        return "hot"
    if value >= warn:
        return "mild"
    return ""


def render_html(report):
    s = report["summary"]
    report["findings"] = build_findings(report)
    tl = report["timeline"]

    # --- findings ------------------------------------------------------
    if report["findings"]:
        findings = "".join(
            f'<div class="finding {f["level"]}"><div class="mark"></div><div>'
            f'<h3>{esc(f["title"])}</h3><p>{esc(f["body"])}</p>'
            f'<p class="do">{esc(f["action"])}</p></div></div>'
            for f in report["findings"]
        )
    else:
        findings = '<p class="empty">Nothing stood out in this window.</p>'

    # --- endpoint table ------------------------------------------------
    rows = []
    for e in report["endpoints"]:
        rows.append(
            "<tr>"
            f'<td class="name" title="{esc(e["key"])}">{esc(e["key"])}</td>'
            f'<td class="num" data-v="{e["count"]}">{e["count"]:,}</td>'
            f'<td class="num" data-v="{e["total_ms"]:.0f}">{fmt_ms(e["total_ms"])}</td>'
            f'<td data-v="{e["share"]:.2f}"><div class="meter">'
            f'<span style="width:{min(e["share"], 100):.1f}%"></span></div></td>'
            f'<td class="num {_heat(e["p50"], 150, 400)}" data-v="{e["p50"]:.1f}">{fmt_ms(e["p50"])}</td>'
            f'<td class="num {_heat(e["p95"], 300, 800)}" data-v="{e["p95"]:.1f}">{fmt_ms(e["p95"])}</td>'
            f'<td class="num dim" data-v="{e["max"]:.1f}">{fmt_ms(e["max"])}</td>'
            f'<td class="num" data-v="{e["db_ms"]:.1f}">{fmt_ms(e["db_ms"])}</td>'
            f'<td class="num {_heat(e["q_max"], 12, 25)}" data-v="{e["q_max"]}">'
            f'{e["q_min"]}&#8211;{e["q_max"]}</td>'
            f'<td class="num {"hot" if e["errors"] else "dim"}" data-v="{e["errors"]}">{e["errors"]}</td>'
            "</tr>"
        )
    endpoint_rows = "".join(rows)

    # --- slowest individual requests -----------------------------------
    slow_rows = "".join(
        "<tr>"
        f'<td class="dim">{r["_dt"]:%H:%M:%S}</td>'
        f'<td class="name" title="{esc(r.get("path", ""))}">{esc(r.get("path", ""))}</td>'
        f'<td><span class="chip {_status_class(r.get("status", 0))}">{r.get("status", "?")}</span></td>'
        f'<td class="num hot" data-v="{r.get("duration_ms", 0):.1f}">{fmt_ms(r.get("duration_ms", 0))}</td>'
        f'<td class="num" data-v="{r.get("db_time_ms", 0):.1f}">{fmt_ms(r.get("db_time_ms", 0))}</td>'
        f'<td class="num" data-v="{max(r.get("duration_ms", 0) - r.get("db_time_ms", 0), 0):.1f}">'
        f'{fmt_ms(max(r.get("duration_ms", 0) - r.get("db_time_ms", 0), 0))}</td>'
        f'<td class="num" data-v="{r.get("db_queries", 0)}">{r.get("db_queries", 0)}</td>'
        "</tr>"
        for r in report["slowest"]
    ) or f'<tr><td colspan="7" class="empty">No request exceeded {fmt_ms(s["slow_ms"])}.</td></tr>'

    # --- errors ---------------------------------------------------------
    error_rows = "".join(
        "<tr>"
        f'<td class="dim">{r["_dt"]:%d %b %H:%M:%S}</td>'
        f'<td><span class="chip {_status_class(r.get("status", 0))}">{r.get("status", "?")}</span></td>'
        f'<td class="name" title="{esc(r.get("path", ""))}">{esc(r.get("path", ""))}</td>'
        f'<td class="num">{fmt_ms(r.get("duration_ms", 0))}</td>'
        f'<td class="dim">{esc(r.get("user", "anonymous"))}</td>'
        "</tr>"
        for r in report["errors"]
    ) or '<tr><td colspan="5" class="empty">No 4xx or 5xx responses.</td></tr>'

    # --- status + users -------------------------------------------------
    status_rows = "".join(
        "<tr>"
        f'<td><span class="chip {_status_class(x["code"])}">{x["code"]}</span></td>'
        f'<td class="num" data-v="{x["count"]}">{x["count"]:,}</td>'
        f'<td data-v="{x["pct"]:.2f}"><div class="meter"><span style="width:{x["pct"]:.1f}%"></span></div></td>'
        f'<td class="num dim">{x["pct"]:.1f}%</td>'
        "</tr>"
        for x in report["status"]
    )

    user_rows = "".join(
        "<tr>"
        f'<td class="name">{esc(u["user"])}</td>'
        f'<td class="num" data-v="{u["count"]}">{u["count"]:,}</td>'
        f'<td class="num dim" data-v="{u["paths"]}">{u["paths"]}</td>'
        f'<td class="num" data-v="{u["p95"]:.1f}">{fmt_ms(u["p95"])}</td>'
        "</tr>"
        for u in report["users"]
    )

    span_txt = (f"{s['span_s'] / 3600:.1f} hours" if s["span_s"] >= 3600
                else f"{s['span_s'] / 60:.0f} minutes")
    same_day = s["from"].date() == s["to"].date()
    when = (f"{s['from']:%d %b %Y, %H:%M} to {s['to']:%H:%M}" if same_day
            else f"{s['from']:%d %b %H:%M} to {s['to']:%d %b %H:%M}")
    skipped = report.get("skipped_lines", 0)
    skip_txt = f" {skipped} unreadable line(s) were ignored." if skipped else ""

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Request performance &#8212; {s['from']:%d %b %Y}</title>
<style>{CSS}</style>
</head><body>
<div class="shell">

<div class="mast">
  <div>
    <h1>Request performance</h1>
    <p><b>{s['requests']:,}</b> requests over {span_txt}, {when}.
    Half completed in under {fmt_ms(s['p50'])}; the slowest twentieth took more than
    {fmt_ms(s['p95'])}.{skip_txt}</p>
  </div>
  <button class="themer" id="themer" type="button">Dark</button>
</div>

<div class="panel">
  <h2>Latency over time <span class="note">each bar covers {fmt_span(tl['bucket_s'])} &#8212; filled to p95, tick at slowest</span></h2>
  <div class="chart">{_chart_svg(tl, s)}{_volume_svg(tl)}</div>
  <div class="legend">
    <span><i style="background:var(--signal)"></i>95th percentile latency</span>
    <span><i style="background:var(--bad)"></i>bucket contained an error</span>
    <span><i style="background:var(--ink3)"></i>request volume</span>
  </div>
  <dl class="readout">
    <div><dt>Median</dt><dd>{fmt_ms(s['p50'])}</dd></div>
    <div><dt>95th pct</dt><dd>{fmt_ms(s['p95'])}</dd></div>
    <div><dt>99th pct</dt><dd>{fmt_ms(s['p99'])}</dd></div>
    <div><dt>Slowest</dt><dd>{fmt_ms(s['max'])}</dd></div>
    <div><dt>Time in SQL</dt><dd>{s['db_share']:.0f}<small>%</small></dd></div>
    <div><dt>Queries, p95</dt><dd>{s['queries_p95']:.0f}</dd></div>
    <div class="{'alert' if s['errors'] else ''}"><dt>Errors</dt>
      <dd>{s['errors']}<small> of {s['requests']:,}</small></dd></div>
    <div class="{'alert' if s['slow'] else ''}"><dt>Over {fmt_ms(s['slow_ms'])}</dt>
      <dd>{s['slow']}</dd></div>
  </dl>
</div>

<div class="panel">
  <h2>What stands out</h2>
  {findings}
</div>

<div class="panel">
  <h2>Where the time goes
    <input class="filter" type="search" placeholder="Filter endpoints" data-target="tbl-ep" aria-label="Filter endpoints">
  </h2>
  <div class="scroll"><table id="tbl-ep" data-sortable>
    <thead><tr>
      <th>Endpoint</th><th class="num" data-type="n">Calls</th>
      <th class="num" data-type="n">Total time</th><th data-type="n">Share</th>
      <th class="num" data-type="n">Median</th><th class="num" data-type="n">p95</th>
      <th class="num" data-type="n">Slowest</th><th class="num" data-type="n">Avg SQL</th>
      <th class="num" data-type="n">Queries</th><th class="num" data-type="n">Errors</th>
    </tr></thead>
    <tbody>{endpoint_rows}</tbody>
  </table></div>
</div>

<div class="panel">
  <h2>Slowest requests <span class="note">individual calls, not averages</span></h2>
  <div class="scroll"><table data-sortable>
    <thead><tr>
      <th>Time</th><th>Path</th><th>Status</th>
      <th class="num" data-type="n">Total</th><th class="num" data-type="n">In SQL</th>
      <th class="num" data-type="n">Elsewhere</th><th class="num" data-type="n">Queries</th>
    </tr></thead>
    <tbody>{slow_rows}</tbody>
  </table></div>
</div>

<div class="panel">
  <h2>Failed requests</h2>
  <div class="scroll"><table data-sortable>
    <thead><tr><th>Time</th><th>Status</th><th>Path</th>
      <th class="num" data-type="n">Duration</th><th>User</th></tr></thead>
    <tbody>{error_rows}</tbody>
  </table></div>
</div>

<div class="cols">
  <div class="panel">
    <h2>Response codes</h2>
    <div class="scroll"><table data-sortable>
      <thead><tr><th>Code</th><th class="num" data-type="n">Count</th>
        <th data-type="n">Share</th><th class="num" data-type="n">%</th></tr></thead>
      <tbody>{status_rows}</tbody>
    </table></div>
  </div>
  <div class="panel">
    <h2>Busiest users</h2>
    <div class="scroll"><table data-sortable>
      <thead><tr><th>User</th><th class="num" data-type="n">Requests</th>
        <th class="num" data-type="n">Endpoints</th><th class="num" data-type="n">p95</th></tr></thead>
      <tbody>{user_rows}</tbody>
    </table></div>
  </div>
</div>

<footer>Built {s['generated_at']:%d %b %Y at %H:%M} by <code>manage.py metrics_report</code>.
Percentiles are interpolated. Requests are grouped by resolved view, so detail pages
such as <code>/cart/2127/</code> and <code>/cart/2151/</code> count as one endpoint.</footer>

</div>
<script>{JS}</script>
</body></html>"""
