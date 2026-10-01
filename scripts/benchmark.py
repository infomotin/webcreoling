"""
Performance benchmark harness for the WebCreoling Flask + MySQL stack.

Measures, per hot route: wall-clock latency (median/p95) and the number of
SQL statements executed, plus micro-benchmarks for the heaviest repository
queries. Run before and after an optimisation and diff the two reports:

    python scripts/benchmark.py --json before.json
    python scripts/benchmark.py --json after.json --compare before.json

Counting is done with a SQLAlchemy ``before_cursor_execute`` listener, so the
numbers include queries issued by security middleware, context processors and
template rendering — i.e. exactly what a real request costs.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Query counter
# ---------------------------------------------------------------------------
class QueryCounter:
    """Counts SQL statements executed on the application engine."""

    def __init__(self, engine):
        from sqlalchemy import event

        self.statements: List[str] = []
        self.engine = engine
        event.listen(engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def __enter__(self) -> "QueryCounter":
        self.statements = []
        return self

    def __exit__(self, *exc) -> None:
        pass

    @property
    def count(self) -> int:
        return len(self.statements)


# ---------------------------------------------------------------------------
# Route benchmarks
# ---------------------------------------------------------------------------
def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[idx]


def bench_routes(app, runs: int) -> List[Dict[str, Any]]:
    from src.storage.database import engine

    results: List[Dict[str, Any]] = []
    client = app.test_client()

    # Authenticate once so protected routes are measured too.
    client.post("/auth/login", data={"username": "admin", "password": "admin123"})

    # Pick a representative article id.
    from sqlalchemy import text

    with engine.connect() as conn:
        article_id = conn.execute(
            text("SELECT id FROM articles WHERE scrape_status='completed' ORDER BY id DESC LIMIT 1")
        ).scalar()

    routes: List[Tuple[str, str]] = [
        ("portal_home", "/news/"),
        ("portal_section", "/news/section/politics"),
        ("portal_search", "/news/?q=%E0%A6%B8%E0%A6%82%E0%A6%B8%E0%A6%A6"),
        ("article_detail", f"/news/article/{article_id}" if article_id else "/news/"),
        ("articles_archive", "/articles"),
        ("dashboard", "/"),
        ("newsroom_admin", "/admin/newspaper?tab=articles"),
        ("login_page", "/auth/login"),
    ]

    for name, url in routes:
        # Warm-up (Jinja compile, identity map, caches).
        for _ in range(2):
            client.get(url)

        times: List[float] = []
        for _ in range(runs):
            start = time.perf_counter()
            resp = client.get(url)
            times.append((time.perf_counter() - start) * 1000)
            status = resp.status_code

        with QueryCounter(engine) as qc:
            client.get(url)
        query_count = qc.count

        results.append(
            {
                "name": name,
                "url": url,
                "status": status,
                "queries": query_count,
                "median_ms": round(statistics.median(times), 2),
                "p95_ms": round(_percentile(times, 95), 2),
                "min_ms": round(min(times), 2),
            }
        )
    return results


# ---------------------------------------------------------------------------
# DB micro-benchmarks
# ---------------------------------------------------------------------------
def bench_db(iterations: int) -> List[Dict[str, Any]]:
    from sqlalchemy import text

    from src.storage.database import engine

    def timed(label: str, sql: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        durations: List[float] = []
        rows = 0
        with engine.connect() as conn:
            for _ in range(iterations):
                start = time.perf_counter()
                result = conn.execute(text(sql), params or {})
                rows = len(list(result))
                durations.append((time.perf_counter() - start) * 1000)
        return {
            "name": label,
            "median_ms": round(statistics.median(durations), 3),
            "p95_ms": round(_percentile(durations, 95), 3),
            "rows": rows,
        }

    with engine.connect() as conn:
        sample_id = conn.execute(
            text("SELECT id FROM articles WHERE scrape_status='completed' ORDER BY id DESC LIMIT 1")
        ).scalar() or 1

    cases = [
        (
            "feed_page (public filter + status + limit)",
            "SELECT id, title, published_at FROM articles "
            "WHERE scrape_status = 'completed' "
            "AND LENGTH(TRIM(COALESCE(title,''))) > 0 "
            "AND title NOT LIKE '%SYSTEM ENCRYPTED DATA%' "
            "AND title NOT LIKE '🔒%' "
            "AND COALESCE(content_text,'') NOT LIKE '%🔒 এইসংবাদের%' "
            "ORDER BY published_at DESC LIMIT 12",
        ),
        (
            "category_list (no public filter)",
            "SELECT id, title FROM articles WHERE scrape_status='completed' "
            "AND category='politics' ORDER BY published_at DESC LIMIT 12",
        ),
        (
            "feed_count (COUNT with public filter)",
            "SELECT COUNT(*) FROM articles WHERE scrape_status = 'completed' "
            "AND LENGTH(TRIM(COALESCE(title,''))) > 0 "
            "AND title NOT LIKE '%SYSTEM ENCRYPTED DATA%' "
            "AND title NOT LIKE '🔒%' "
            "AND COALESCE(content_text,'') NOT LIKE '%🔒 এইসংবাদের%'",
        ),
        (
            "breaking_ticker",
            "SELECT id, title FROM articles WHERE is_breaking=1 "
            "AND scrape_status='completed' ORDER BY published_at DESC LIMIT 9",
        ),
        (
            "site_configs bulk fetch",
            "SELECT * FROM site_configs",
        ),
        (
            "article detail by id",
            "SELECT * FROM articles WHERE id = :id",
            {"id": sample_id},
        ),
    ]

    out = []
    for case in cases:
        try:
            out.append(timed(*case))
        except Exception as exc:  # pragma: no cover - diagnostic only
            out.append({"name": case[0], "error": str(exc)})
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_report(route_results: List[Dict[str, Any]], db_results: List[Dict[str, Any]]) -> None:
    print("\n=== Route benchmarks (Flask test client, warm) ===")
    print(f"{'route':<24} {'status':>6} {'queries':>8} {'median ms':>10} {'p95 ms':>9} {'min ms':>9}")
    for r in route_results:
        print(
            f"{r['name']:<24} {r['status']:>6} {r['queries']:>8} "
            f"{r['median_ms']:>10} {r['p95_ms']:>9} {r['min_ms']:>9}"
        )

    print("\n=== DB query micro-benchmarks ===")
    print(f"{'query':<48} {'median ms':>10} {'p95 ms':>9} {'rows':>6}")
    for r in db_results:
        if "error" in r:
            print(f"{r['name']:<48} ERROR: {r['error']}")
        else:
            print(
                f"{r['name']:<48} {r['median_ms']:>10} {r['p95_ms']:>9} {r['rows']:>6}"
            )


def print_comparison(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    print("\n=== Comparison (before -> after) ===")
    print(f"{'route':<24} {'queries':>16} {'median ms':>22}")
    before_routes = {r["name"]: r for r in before.get("routes", [])}
    for r in after.get("routes", []):
        b = before_routes.get(r["name"])
        if not b:
            continue
        q_delta = r["queries"] - b["queries"]
        t_delta = r["median_ms"] - b["median_ms"]
        print(
            f"{r['name']:<24} {b['queries']:>6} -> {r['queries']:<6} ({q_delta:+d}) "
            f"{b['median_ms']:>8} -> {r['median_ms']:<8} ({t_delta:+.2f} ms)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=8, help="timed iterations per route")
    parser.add_argument("--db-iterations", type=int, default=20)
    parser.add_argument("--json", type=str, help="write results to this JSON file")
    parser.add_argument("--compare", type=str, help="compare against a previous JSON file")
    args = parser.parse_args()

    from src.web.app import create_app

    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})

    route_results = bench_routes(app, args.runs)
    db_results = bench_db(args.db_iterations)
    print_report(route_results, db_results)

    payload = {"routes": route_results, "db": db_results}
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")

    if args.compare:
        before = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        print_comparison(before, payload)


if __name__ == "__main__":
    main()
