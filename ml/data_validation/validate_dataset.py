"""Checks a generated dataset and writes a validation report (project document, 11 and 16.7).

Three groups of checks:

- **Integrity**: no orphan records, no negative stock, stock that matches its movement
  history, bins within their weight and volume limits, order lines and statuses that
  agree with each other.
- **Volume**: the row counts the size configuration asks for (section 11.1).
- **Patterns**: the business patterns the ML use cases need (section 11.2): weekly and
  holiday seasonality, growth, fast movers, intermittent demand, baskets, supplier lead
  times, delivery delays, slotting, returns and damages, warehouse space.

Pattern checks need enough history to be meaningful: below `PATTERN_MIN_ORDERS` orders
they are reported as skipped (the small CI dataset only proves integrity and volume).

Run from ml/:  python -m data_validation.validate_dataset --size full
"""

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine

from data_generation.config import SIZE_NAMES, DatasetConfig, get_config
from data_generation.database import DEFAULT_DATABASE, sqlite_url
from data_generation.stock import HEAVY_KG

PATTERN_MIN_ORDERS = 10_000
ORDER_TOLERANCE = 0.10  # generated orders within 10 % of the target
MAX_WAREHOUSE_FILL = 0.90  # share of storage volume in use at the end
BASKET_SAMPLE = 50_000  # most recent orders used for the basket check

# Stored as integers of the smallest unit (app.database.types.ScaledDecimal)
KG = 1_000.0  # weight_kg: grams
CM3 = 1_000.0  # length x width x height in millimetres -> cm³
M = 10.0  # distance_to_packing_m: decimetres

# A bin's zone (joined after a table aliased b for bins): bins > shelves > racks > zones
BIN_ZONE = (
    "JOIN shelves s ON s.id = b.shelf_id JOIN racks r ON r.id = s.rack_id "
    "JOIN zones z ON z.id = r.zone_id"
)
LATE = "date(s.delivered_at) > s.expected_delivery_date"

PASS, FAIL, SKIP = "pass", "fail", "skip"


@dataclass(frozen=True)
class Check:
    group: str
    name: str
    status: str
    value: str
    expected: str

    @property
    def passed(self) -> bool:
        return self.status != FAIL


@dataclass
class ValidationReport:
    database: str
    size: str | None
    checks: list[Check] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [check for check in self.checks if check.status == FAIL]

    def count(self, status: str) -> int:
        return sum(check.status == status for check in self.checks)

    def to_markdown(self) -> str:
        verdict = "PASSED" if self.passed else "FAILED"
        lines = [
            "# Synthetic dataset validation report",
            "",
            f"- Database: `{self.database}`",
            f"- Size configuration: {self.size or 'not given (volume targets not checked)'}",
            f"- Checked at: {self.created_at:%Y-%m-%d %H:%M} UTC",
            f"- Result: **{verdict}**: {self.count(PASS)} passed, {self.count(FAIL)} failed, "
            f"{self.count(SKIP)} skipped",
        ]
        for group in dict.fromkeys(check.group for check in self.checks):
            lines += [
                "",
                f"## {group}",
                "",
                "| Check | Result | Value | Expected |",
                "|---|---|---|---|",
            ]
            for check in self.checks:
                if check.group == group:
                    mark = {PASS: "✅", FAIL: "❌", SKIP: "⏭️"}[check.status]
                    lines.append(
                        f"| {check.name} | {mark} {check.status} | {check.value} "
                        f"| {check.expected} |"
                    )
        return "\n".join(lines) + "\n"


class _Validator:
    def __init__(self, engine: Engine, config: DatasetConfig | None) -> None:
        self.engine = engine
        self.config = config
        self.report = ValidationReport(database=str(engine.url.database), size=None)
        if config is not None:
            self.report.size = config.name
        self.group = ""

    # ----------------------------------------------------------------- helpers
    def rows(self, sql: str) -> list[Sequence[Any]]:
        with self.engine.connect() as connection:
            return [tuple(row) for row in connection.exec_driver_sql(sql)]

    def one(self, sql: str) -> Any:
        return self.rows(sql)[0][0]

    def add(self, name: str, ok: bool, value: Any, expected: str) -> None:
        self.report.checks.append(
            Check(self.group, name, PASS if ok else FAIL, str(value), expected)
        )

    def none(self, name: str, sql: str) -> None:
        """A check that counts problem rows: passes when there are none."""
        found = self.one(sql)
        self.add(name, found == 0, f"{found:,}", "0")

    def skip(self, name: str, reason: str) -> None:
        self.report.checks.append(Check(self.group, name, SKIP, reason, "-"))

    # -------------------------------------------------------------- integrity
    def integrity(self) -> None:
        self.group = "Integrity"
        orphans = self.rows("PRAGMA foreign_key_check")
        tables = sorted({row[0] for row in orphans})
        self.add(
            "No orphan records (foreign keys)",
            not orphans,
            f"{len(orphans):,}" + (f" in {', '.join(tables)}" if tables else ""),
            "0",
        )
        self.none(
            "No negative stock",
            "SELECT COUNT(*) FROM inventory WHERE quantity_on_hand < 0 OR quantity_reserved < 0 "
            "OR quantity_damaged < 0 OR quantity_reserved + quantity_damaged > quantity_on_hand",
        )
        self.none(
            "Movements never take stock below zero",
            "SELECT COUNT(*) FROM inventory_movements "
            "WHERE on_hand_after < 0 OR reserved_after < 0 OR damaged_after < 0",
        )
        self.none(
            "Stock equals the sum of its movements",
            "SELECT COUNT(*) FROM inventory i LEFT JOIN (SELECT product_id, bin_id, "
            "SUM(on_hand_delta) h, SUM(reserved_delta) r, SUM(damaged_delta) d "
            "FROM inventory_movements GROUP BY 1, 2) m "
            "ON m.product_id = i.product_id AND m.bin_id = i.bin_id "
            "WHERE i.quantity_on_hand != COALESCE(m.h, 0) "
            "OR i.quantity_reserved != COALESCE(m.r, 0) "
            "OR i.quantity_damaged != COALESCE(m.d, 0)",
        )
        self.none(
            "Bins within weight and volume limits",
            "SELECT COUNT(*) FROM (SELECT b.id FROM bins b "
            "JOIN inventory i ON i.bin_id = b.id JOIN products p ON p.id = i.product_id "
            "GROUP BY b.id HAVING SUM(i.quantity_on_hand * p.weight_kg) > MAX(b.max_weight_kg) "
            f"OR SUM(i.quantity_on_hand * p.length_cm * p.width_cm * p.height_cm) / {CM3} "
            "> MAX(b.max_volume_cm3))",
        )
        self.none(
            "Active reservations match reserved stock",
            "SELECT COUNT(*) FROM inventory i LEFT JOIN (SELECT product_id, bin_id, "
            "SUM(quantity) q FROM stock_reservations WHERE status = 'active' GROUP BY 1, 2) a "
            "ON a.product_id = i.product_id AND a.bin_id = i.bin_id "
            "WHERE i.quantity_reserved != COALESCE(a.q, 0)",
        )
        self.none(
            "Order lines: shipped <= packed <= picked <= ordered",
            "SELECT COUNT(*) FROM order_items WHERE NOT (quantity_returned <= quantity_shipped "
            "AND quantity_shipped <= quantity_packed AND quantity_packed <= quantity_picked "
            "AND quantity_picked + quantity_reserved <= quantity)",
        )
        self.none(
            "Order status matches its latest history entry",
            "SELECT COUNT(*) FROM orders o JOIN order_status_history h ON h.id = "
            "(SELECT MAX(id) FROM order_status_history WHERE order_id = o.id) "
            "WHERE h.to_status != o.status",
        )
        self.none(
            "Shipped orders have one shipment and the right dates",
            "SELECT COUNT(*) FROM orders o LEFT JOIN shipments s ON s.order_id = o.id "
            "WHERE o.status IN ('shipped', 'delayed', 'delivered', 'returned') AND (s.id IS NULL "
            "OR o.shipped_at IS NULL OR s.shipped_at < o.confirmed_at "
            "OR (o.status IN ('delivered', 'returned') AND (o.delivered_at IS NULL "
            "OR s.delivered_at < s.shipped_at)))",
        )
        self.none(
            "One shipment per order",
            "SELECT COUNT(*) FROM (SELECT order_id FROM shipments GROUP BY 1 HAVING COUNT(*) > 1)",
        )
        self.none(
            "Cancelled orders have a cancel date and ship nothing",
            "SELECT COUNT(*) FROM orders o WHERE o.status = 'cancelled' "
            "AND (o.cancelled_at IS NULL "
            "OR EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.id "
            "AND i.quantity_shipped > 0))",
        )
        self.none(
            "Returns never exceed shipped units",
            "SELECT COUNT(*) FROM (SELECT ri.order_item_id FROM return_items ri "
            "JOIN returns r ON r.id = ri.return_id JOIN order_items oi ON oi.id = ri.order_item_id "
            "WHERE r.status != 'cancelled' GROUP BY ri.order_item_id "
            "HAVING SUM(ri.quantity) > MAX(oi.quantity_shipped))",
        )
        self.none(
            "Purchase orders: received <= ordered",
            "SELECT COUNT(*) FROM purchase_order_items WHERE quantity_received > quantity "
            "OR quantity_received < 0",
        )
        self.none(
            "Picking tasks: picked <= task quantity",
            "SELECT COUNT(*) FROM picking_tasks WHERE quantity_picked > quantity "
            "OR (status = 'completed' AND quantity_picked != quantity)",
        )

    # ----------------------------------------------------------------- volume
    def volume(self) -> None:
        self.group = "Volume"
        counts = {
            table: self.one(f"SELECT COUNT(*) FROM {table}")
            for table in (
                "warehouses",
                "zones",
                "racks",
                "bins",
                "products",
                "suppliers",
                "customers",
                "carriers",
                "orders",
                "order_items",
                "inventory_movements",
                "purchase_orders",
                "shipments",
                "returns",
            )
        }
        config = self.config
        if config is None:
            for table, count in counts.items():
                self.add(table, count > 0, f"{count:,}", "> 0")
            return
        exact = {
            "warehouses": config.warehouses,
            "zones": config.zones,
            "racks": config.racks,
            "bins": config.bins,
            "products": config.products,
            "suppliers": config.suppliers,
            "customers": config.customers,
            "carriers": config.carriers,
        }
        for table, target in exact.items():
            self.add(
                table.capitalize(), counts[table] == target, f"{counts[table]:,}", f"{target:,}"
            )
        low, high = config.orders * (1 - ORDER_TOLERANCE), config.orders * (1 + ORDER_TOLERANCE)
        self.add(
            "Orders",
            low <= counts["orders"] <= high,
            f"{counts['orders']:,}",
            f"{config.orders:,} ± {ORDER_TOLERANCE:.0%}",
        )
        lines = counts["order_items"] / max(counts["orders"], 1)
        self.add("Order lines per order", 2.0 <= lines <= 3.0, f"{lines:.2f}", "2.0 - 3.0")
        first, last = self.rows("SELECT MIN(date(created_at)), MAX(date(created_at)) FROM orders")[
            0
        ]
        span = (
            (datetime.fromisoformat(last) - datetime.fromisoformat(first)).days + 1 if first else 0
        )
        self.add(
            "Days of order history",
            span >= config.days * 0.95,
            f"{span:,} ({first} to {last})",
            f"about {config.days:,}",
        )
        per_order = counts["inventory_movements"] / max(counts["orders"], 1)
        self.add(
            "Inventory movements per order",
            per_order >= 3,
            f"{per_order:.1f}",
            ">= 3 (reserve, pick, receipts)",
        )
        for table in ("purchase_orders", "shipments", "returns"):
            self.add(
                table.replace("_", " ").capitalize(), counts[table] > 0, f"{counts[table]:,}", "> 0"
            )

    # --------------------------------------------------------------- patterns
    def patterns(self) -> None:
        self.group = "Patterns"
        orders = self.one("SELECT COUNT(*) FROM orders")
        checks: list[tuple[str, Callable[[], None]]] = [
            ("Weekday orders above weekends", self._weekly),
            ("Holiday peak in November and December", self._holiday),
            ("Growth: second year above the first", self._trend),
            ("Fast movers: top 20 % of products", self._fast_movers),
            ("Intermittent demand", self._intermittent),
            ("Products bought together (baskets)", self._baskets),
            ("Supplier lead times differ", self._lead_times),
            ("Suppliers less reliable in peak season", self._supplier_peak),
            ("Late deliveries", self._late_share),
            ("Large orders more often late", self._late_large),
            ("Orders that waited for stock more often late", self._late_low_stock),
            ("Peak season deliveries more often late", self._late_peak),
            ("Carriers differ in reliability", self._carriers),
            ("Heavy goods on the lowest shelf", self._slotting_weight),
            ("Fast movers picked nearer to packing", self._picks_near_packing),
            ("Return rate", self._returns),
            ("Some returns damaged", self._damaged_returns),
            ("Noise: short picks and stock adjustments", self._noise),
            ("Warehouse space not overfilled", self._fill),
        ]
        for name, check in checks:
            if orders < PATTERN_MIN_ORDERS:
                self.skip(name, f"needs {PATTERN_MIN_ORDERS:,} orders, has {orders:,}")
            else:
                self._name = name
                check()

    def _add(self, ok: bool, value: str, expected: str) -> None:
        self.add(self._name, ok, value, expected)

    def _daily_orders(self, where: str) -> float:
        return self.one(
            "SELECT CAST(COUNT(*) AS REAL) / COUNT(DISTINCT date(created_at)) FROM orders "
            f"WHERE {where}"
        )

    def _weekly(self) -> None:
        weekdays = self._daily_orders("strftime('%w', created_at) NOT IN ('0', '6')")
        weekends = self._daily_orders("strftime('%w', created_at) IN ('0', '6')")
        ratio = weekdays / weekends
        self._add(ratio >= 1.3, f"{ratio:.2f}x per day", ">= 1.3x")

    def _holiday(self) -> None:
        peak = self._daily_orders("strftime('%m', created_at) IN ('11', '12')")
        rest = self._daily_orders("strftime('%m', created_at) NOT IN ('11', '12')")
        ratio = peak / rest
        self._add(ratio >= 1.15, f"{ratio:.2f}x per day", ">= 1.15x")

    def _trend(self) -> None:
        first = self.one("SELECT MIN(created_at) FROM orders")
        split = f"date('{first}', '+365 day')"
        year1 = self._daily_orders(f"created_at < {split}")
        year2 = self._daily_orders(f"created_at >= {split}")
        ratio = year2 / year1
        self._add(ratio > 1.0, f"{ratio:.2f}x per day", "> 1.0x")

    def _fast_movers(self) -> None:
        units = [
            row[0]
            for row in self.rows(
                "SELECT SUM(quantity) FROM order_items GROUP BY product_id ORDER BY 1 DESC"
            )
        ]
        products = self.one("SELECT COUNT(*) FROM products")
        share = sum(units[: max(1, products // 5)]) / sum(units)
        self._add(share >= 0.5, f"{share:.0%} of units", ">= 50 %")

    def _intermittent(self) -> None:
        days = self.one("SELECT COUNT(DISTINCT date(created_at)) FROM orders")
        products = self.one("SELECT COUNT(*) FROM products")
        rare = self.one(
            "SELECT COUNT(*) FROM (SELECT oi.product_id FROM order_items oi "
            "JOIN orders o ON o.id = oi.order_id GROUP BY 1 "
            f"HAVING COUNT(DISTINCT date(o.created_at)) < {days} * 0.3)"
        )
        rare += products - self.one("SELECT COUNT(DISTINCT product_id) FROM order_items")
        share = rare / products
        self._add(
            0.05 <= share <= 0.6, f"{share:.0%} of products sell on < 30 % of days", "5 - 60 %"
        )

    def _baskets(self) -> None:
        baskets: dict[int, set[int]] = {}
        for order_id, product_id in self.rows(
            "SELECT order_id, product_id FROM order_items WHERE order_id > "
            f"(SELECT MAX(id) - {BASKET_SAMPLE} FROM orders)"
        ):
            baskets.setdefault(order_id, set()).add(product_id)
        singles: Counter[int] = Counter()
        pairs: Counter[tuple[int, int]] = Counter()
        for items in baskets.values():
            singles.update(items)
            pairs.update(combinations(sorted(items), 2))
        total = len(baskets)
        strong = sum(
            1
            for (a, b), together in pairs.items()
            if together >= 20 and together * total / (singles[a] * singles[b]) > 3
        )
        self._add(strong >= 5, f"{strong:,} product pairs with lift > 3", ">= 5")

    def _lead_times(self) -> None:
        leads = [
            row[0]
            for row in self.rows(
                "SELECT AVG(julianday(received_at) - julianday(ordered_at)) FROM purchase_orders "
                "WHERE received_at IS NOT NULL GROUP BY supplier_id HAVING COUNT(*) >= 10"
            )
        ]
        spread = max(leads) / min(leads)
        self._add(
            spread >= 1.5,
            f"{min(leads):.1f} to {max(leads):.1f} days ({spread:.1f}x)",
            ">= 1.5x between suppliers",
        )

    def _supplier_peak(self) -> None:
        late = (
            "AVG(date(received_at) > expected_date) FROM purchase_orders "
            "WHERE received_at IS NOT NULL AND strftime('%m', ordered_at)"
        )
        peak = self.one(f"SELECT {late} IN ('11', '12')")
        rest = self.one(f"SELECT {late} NOT IN ('11', '12')")
        self._add(peak > rest, f"{peak:.0%} late vs {rest:.0%}", "peak > rest")

    def _late(self, where: str = "1") -> float:
        return self.one(
            f"SELECT AVG({LATE}) FROM shipments s JOIN orders o ON o.id = s.order_id "
            f"WHERE s.delivered_at IS NOT NULL AND {where}"
        )

    def _late_share(self) -> None:
        share = self._late()
        self._add(0.03 <= share <= 0.2, f"{share:.1%}", "3 - 20 %")

    def _late_large(self) -> None:
        units = "(SELECT SUM(quantity_shipped) FROM order_items WHERE order_id = o.id)"
        large, small = self._late(f"{units} > 10"), self._late(f"{units} <= 10")
        self._add(large > small * 1.3, f"{large:.1%} vs {small:.1%}", "> 1.3x")

    def _late_low_stock(self) -> None:
        waited = (
            "EXISTS (SELECT 1 FROM order_status_history h WHERE h.order_id = o.id "
            "AND h.to_status IN ('backordered', 'partially_allocated'))"
        )
        low, normal = self._late(waited), self._late(f"NOT {waited}")
        self._add(low > normal * 1.3, f"{low:.1%} vs {normal:.1%}", "> 1.3x")

    def _late_peak(self) -> None:
        peak = self._late("strftime('%m', s.shipped_at) = '12'")
        rest = self._late("strftime('%m', s.shipped_at) NOT IN ('11', '12')")
        self._add(peak > rest * 1.3, f"December {peak:.1%} vs {rest:.1%}", "> 1.3x")

    def _carriers(self) -> None:
        shares = [
            row[0]
            for row in self.rows(
                f"SELECT AVG({LATE}) FROM shipments s WHERE s.delivered_at IS NOT NULL "
                "GROUP BY s.carrier_id HAVING COUNT(*) >= 100"
            )
        ]
        self._add(
            len(shares) >= 2 and max(shares) > min(shares) * 1.3,
            f"{min(shares):.1%} to {max(shares):.1%} late",
            "> 1.3x between carriers",
        )

    def _slotting_weight(self) -> None:
        heavy, light = (
            self.one(
                "SELECT AVG(s.level = 1) FROM (SELECT b.shelf_id FROM inventory i "
                "JOIN products p ON p.id = i.product_id JOIN bins b ON b.id = i.bin_id "
                f"WHERE i.quantity_on_hand > 0 AND p.weight_kg {sign} {int(HEAVY_KG * 1000)}) x "
                "JOIN shelves s ON s.id = x.shelf_id"
            )
            for sign in (">=", "<")
        )
        if heavy is None:
            self.skip(self._name, f"no products of {HEAVY_KG} kg or more in stock")
            return
        self._add(
            heavy > light,
            f"{heavy:.0%} of heavy vs {light:.0%} of light stock records on level 1",
            "heavy > light",
        )

    def _picks_near_packing(self) -> None:
        products = self.one("SELECT COUNT(*) FROM products")
        fast = (
            "t.product_id IN (SELECT product_id FROM order_items GROUP BY 1 "
            f"ORDER BY SUM(quantity) DESC LIMIT {max(1, products // 5)})"
        )
        distance = (
            f"SELECT AVG(r.distance_to_packing_m) / {M} FROM picking_tasks t "
            "JOIN bins b ON b.id = t.bin_id JOIN shelves s ON s.id = b.shelf_id "
            "JOIN racks r ON r.id = s.rack_id JOIN zones z ON z.id = r.zone_id "
            "WHERE z.zone_type = 'picking' AND "
        )
        near, rest = self.one(distance + fast), self.one(distance + f"NOT {fast}")
        self._add(
            near < rest,
            f"{near:.1f} m vs {rest:.1f} m to packing",
            "fast movers nearer",
        )

    def _returns(self) -> None:
        shipped, returned = self.rows(
            "SELECT SUM(quantity_shipped), SUM(quantity_returned) FROM order_items"
        )[0]
        rate = returned / shipped
        self._add(0.01 <= rate <= 0.15, f"{rate:.1%} of shipped units", "1 - 15 %")

    def _damaged_returns(self) -> None:
        share = self.one(
            "SELECT AVG(ri.condition = 'damaged') FROM return_items ri "
            "JOIN returns r ON r.id = ri.return_id WHERE r.status = 'completed'"
        )
        self._add(0.1 <= share <= 0.6, f"{share:.0%} of returned lines", "10 - 60 %")

    def _noise(self) -> None:
        short = self.one("SELECT COUNT(*) FROM picking_tasks WHERE status = 'short'")
        adjustments = self.one("SELECT COUNT(*) FROM stock_adjustments")
        tasks = self.one("SELECT COUNT(*) FROM picking_tasks")
        share = short / tasks
        self._add(
            0 < share < 0.02 and adjustments > 0,
            f"{share:.2%} short picks, {adjustments:,} adjustments",
            "a little (0 - 2 %)",
        )

    def _fill(self) -> None:
        fills = self.rows(
            "SELECT w.code, SUM(COALESCE(x.v, 0)) / SUM(b.max_volume_cm3) "
            f"FROM bins b {BIN_ZONE} JOIN warehouses w ON w.id = z.warehouse_id "
            "LEFT JOIN (SELECT i.bin_id, "
            f"SUM(i.quantity_on_hand * p.length_cm * p.width_cm * p.height_cm) / {CM3} v "
            "FROM inventory i JOIN products p ON p.id = i.product_id GROUP BY 1) x "
            "ON x.bin_id = b.id WHERE z.zone_type != 'returns' GROUP BY 1 ORDER BY 1"
        )
        top = max(fill for _, fill in fills)
        self._add(
            top <= MAX_WAREHOUSE_FILL,
            ", ".join(f"{code} {fill:.0%}" for code, fill in fills),
            f"<= {MAX_WAREHOUSE_FILL:.0%} of storage volume",
        )


def validate_dataset(engine: Engine, config: DatasetConfig | None = None) -> ValidationReport:
    """Run every check; `config` adds the volume targets of a size configuration."""
    validator = _Validator(engine, config)
    validator.integrity()
    validator.volume()
    validator.patterns()
    return validator.report


def default_report_path(database: Path) -> Path:
    return database.with_name(f"{database.stem}_validation.md")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a generated synthetic dataset.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--size", choices=SIZE_NAMES, help="check the volume targets of a size")
    parser.add_argument("--report", type=Path, help="markdown report (default: next to the db)")
    args = parser.parse_args(argv)
    if not args.database.exists():
        print(f"No database at {args.database}", file=sys.stderr)
        return 2
    engine = create_engine(sqlite_url(args.database))
    report = validate_dataset(engine, get_config(args.size) if args.size else None)
    engine.dispose()
    path = args.report or default_report_path(args.database)
    path.write_text(report.to_markdown(), encoding="utf-8")
    for check in report.checks:
        print(f"[{check.status:>4}] {check.group}: {check.name}: {check.value}")
    verdict = "PASSED" if report.passed else "FAILED"
    print(
        f"\n{verdict}: {report.count(PASS)} passed, {report.count(FAIL)} failed, "
        f"{report.count(SKIP)} skipped. Report: {path}"
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
