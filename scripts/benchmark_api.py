"""Time the API calls behind the main pages on a database (speed check, Phase 10).

Run from the project root, on the full generated dataset:

    python scripts/generate_data.py --size full --demo-users   # once, if not done yet
    python scripts/benchmark_api.py --database database/warehouse_synthetic.db
    python scripts/benchmark_api.py --report docs/performance-results.md

Each call is made `--repeat` times (after one warm-up call) in the same process as the
API, through FastAPI's test client, so the times are the server's own work (database and
Python) without network. The table shows the median and slowest time per call and marks
calls slower than `--limit` milliseconds (report-sized calls: 1 second). The exit
code is 1 when any call is too slow.

It logs in as the demo manager (or `--email` / `--password`), so the dataset needs the
demo logins (generate_data.py --demo-users).
"""

import argparse
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "database" / "warehouse_synthetic.db"
DEFAULT_LIMIT_MS = 500.0  # a page should answer within half a second
REPORT_LIMIT_MS = 1000.0  # reports over several months may take up to a second
# Report-sized calls: months of data, or the ML check of 60,000 forecast product-days.
REPORT_CALLS = {"/ml/accuracy"}

# (page, call) pairs. `{product}`, `{order}`, ... are filled with real ids first.
# `{days30}` / `{days90}`: the last 30 / 90 days *of the data* (a generated dataset may
# end before today, and then "the last 30 days" from today would be partly empty).
CALLS: list[tuple[str, str]] = [
    ("Dashboard", "/dashboards/overview?{days30}"),
    ("Dashboard", "/alerts/summary"),
    ("Dashboard", "/ml/summary"),
    ("Reports", "/dashboards/inventory?limit=5&{days30}"),
    ("Reports", "/dashboards/fulfillment?{days30}"),
    ("Reports", "/dashboards/warehouse?{days30}"),
    ("Reports", "/dashboards/suppliers?{days30}"),
    ("Reports (90 days)", "/dashboards/inventory?limit=5&{days90}"),
    ("Reports (90 days)", "/dashboards/fulfillment?{days90}"),
    ("Reports (90 days)", "/dashboards/warehouse?{days90}"),
    ("Products", "/products?limit=25"),
    ("Products", "/products?q=lamp&limit=25"),
    ("Product page", "/products/{product}"),
    ("Product page", "/inventory/products/{product}"),
    ("Product page", "/inventory/movements?product_id={product}&limit=25"),
    ("Product page", "/ml/demand-forecasts/{product}"),
    ("Product page", "/ml/movement-classification/{product}"),
    ("Product page", "/ml/product-recommendations/{product}"),
    ("Inventory", "/inventory?limit=25"),
    ("Inventory", "/inventory?q=WH01-ZA&limit=25"),
    ("Inventory", "/inventory/movements?limit=25"),
    ("Inventory", "/inventory/approvals"),
    ("Orders", "/orders?limit=25"),
    ("Orders", "/orders?q=SO-2026-0001&limit=25"),
    ("Orders", "/orders?status=backordered&limit=25"),
    ("Order page", "/orders/{order}"),
    ("Order page", "/orders/{order}/shipment"),
    ("Order page", "/returns?order_id={order}&limit=50"),
    ("Order page", "/ml/delay-risk/{order}"),
    ("Fulfillment", "/picking-tasks?status=open&limit=50"),
    ("Fulfillment", "/packing-tasks?status=open&limit=100"),
    ("Shipments", "/shipments?limit=25"),
    ("Shipments", "/shipments?status=delayed&limit=25"),
    ("Purchase orders", "/purchase-orders?limit=25"),
    ("Purchase orders", "/purchase-orders?overdue=true&limit=25"),
    ("Suppliers", "/suppliers?limit=25"),
    ("Warehouse layout", "/warehouses/{warehouse}/layout"),
    ("Alerts", "/alerts?unresolved=true&limit=25"),
    ("ML insights", "/ml/reorder-recommendations?status=pending&limit=25"),
    ("ML insights", "/ml/slotting-recommendations?status=pending&limit=25"),
    ("ML insights", "/ml/delay-risks?limit=25"),
    ("ML insights", "/ml/movement-classifications/summary"),
    ("ML insights", "/ml/models"),
    ("ML insights", "/ml/accuracy"),
]


@dataclass
class Timing:
    page: str
    call: str
    status: int
    median_ms: float
    max_ms: float
    limit_ms: float

    @property
    def no_data(self) -> bool:
        """404: nothing to show yet (e.g. the ML models have not scored this database)."""
        return self.status == 404

    @property
    def ok(self) -> bool:
        return (self.status < 400 or self.no_data) and self.median_ms <= self.limit_ms


def run(
    database: Path, email: str, password: str, repeat: int, limit_ms: float = DEFAULT_LIMIT_MS
) -> list[Timing]:
    os.environ["DATABASE_URL"] = f"sqlite:///{database.resolve().as_posix()}"
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))
    from fastapi.testclient import TestClient

    from app.main import API_V1_PREFIX, app

    client = TestClient(app, raise_server_exceptions=False)
    login = client.post(f"{API_V1_PREFIX}/auth/login", json={"email": email, "password": password})
    if login.status_code >= 500:
        raise SystemExit(
            f"Error: {database} is not a migrated warehouse database "
            "(run alembic upgrade head, or generate one with scripts/generate_data.py)."
        )
    if login.status_code != 200:
        raise SystemExit(f"Login as {email} failed ({login.status_code}): {login.text}")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def get(path: str):
        return client.get(API_V1_PREFIX + path, headers=headers)

    newest = get("/orders?limit=1").json()["items"][0]
    last_day = date.fromisoformat(newest["created_at"][:10])

    def days(n: int) -> str:
        return f"date_from={last_day - timedelta(days=n - 1)}&date_to={last_day}"

    ids = {
        "product": get("/products?limit=1").json()["items"][0]["id"],
        "order": get("/orders?status=shipped&limit=1").json()["items"][0]["id"],
        "warehouse": get("/warehouses").json()[0]["id"],
        "days30": days(30),
        "days90": days(90),
    }
    timings = []
    for page, template in CALLS:
        path = template.format(**ids)
        get(path)  # warm-up: first use of a query and the SQLite page cache
        times, status = [], 0
        for _ in range(repeat):
            started = time.perf_counter()
            response = get(path)
            times.append((time.perf_counter() - started) * 1000)
            status = response.status_code
        report = "{days90}" in template or template in REPORT_CALLS
        limit = max(limit_ms, REPORT_LIMIT_MS) if report else limit_ms
        timings.append(Timing(page, template, status, statistics.median(times), max(times), limit))
    return timings


def table(timings: list[Timing]) -> str:
    lines = [
        "| Page | API call | Median | Slowest | Limit | |",
        "|------|----------|-------:|--------:|------:|---|",
    ]
    for t in timings:
        if t.no_data:
            flag = "➖ no data"
        elif t.status >= 400:
            flag = f"❌ error {t.status}"
        else:
            flag = "✅" if t.ok else "⚠️ slow"
        lines.append(
            f"| {t.page} | `GET {t.call}` | {t.median_ms:,.0f} ms | {t.max_ms:,.0f} ms "
            f"| {t.limit_ms:,.0f} ms | {flag} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Time the main API calls on a database.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--email", default="manager@example.com")
    parser.add_argument("--password", default="Demo-pass-123")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--limit", type=float, default=DEFAULT_LIMIT_MS, help="slow above (ms)")
    parser.add_argument("--report", type=Path, help="also write the table to this file")
    args = parser.parse_args(argv)
    if not args.database.exists():
        print(f"Error: no database at {args.database}", file=sys.stderr)
        return 1

    timings = run(args.database, args.email, args.password, args.repeat, args.limit)
    result = table(timings)
    print(result)
    slow = [t for t in timings if not t.ok]
    medians = [t.median_ms for t in timings]
    summary = (
        f"{len(timings)} calls, median of medians {statistics.median(medians):,.0f} ms, "
        f"slowest {max(medians):,.0f} ms; {len(slow)} over their limit or failing."
    )
    print(f"\n{summary}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        args.report.write_text(
            f"# API speed on {args.database.name}\n\nMeasured {stamp}, {args.repeat} calls "
            f"each after a warm-up.\n\n{result}\n\n{summary}\n",
            encoding="utf-8",
        )
    return 1 if slow else 0


if __name__ == "__main__":
    raise SystemExit(main())
