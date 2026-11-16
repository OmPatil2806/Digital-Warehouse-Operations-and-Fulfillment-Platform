"""The dataset validation: clean datasets pass, each kind of damage is caught."""

import shutil
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine

from data_generation.config import get_config
from data_generation.context import GenerationContext
from data_generation.database import sqlite_url
from data_validation.validate_dataset import (
    FAIL,
    PASS,
    SKIP,
    ValidationReport,
    default_report_path,
    main,
    validate_dataset,
)

Simulated = tuple[GenerationContext, Engine, dict]


def copy_of(engine: Engine, tmp_path: Path, *statements: str) -> Path:
    """A copy of a generated database, damaged by `statements`. The database's own guards
    (foreign keys, CHECK constraints, the movement history being read-only) are switched
    off first: the validation must catch damage however it got in."""
    path = tmp_path / "copy.db"
    shutil.copy(str(engine.url.database), path)
    if statements:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute("DROP TRIGGER inventory_movements_no_update")
        for statement in statements:
            assert connection.execute(statement).rowcount != 0, statement
        connection.commit()
        connection.close()
    return path


def check(path: Path, config=None) -> ValidationReport:
    engine = create_engine(sqlite_url(path))
    try:
        return validate_dataset(engine, config)
    finally:
        engine.dispose()


def failed(report: ValidationReport) -> set[str]:
    return {c.name for c in report.failures}


# ------------------------------------------------------------------ clean data
def test_small_dataset_passes_integrity_and_volume(with_orders: Simulated) -> None:
    ctx, engine, _ = with_orders
    report = validate_dataset(engine, ctx.config)
    assert report.passed, report.failures
    groups = {c.group for c in report.checks}
    assert groups == {"Integrity", "Volume", "Patterns"}
    assert all(c.status == PASS for c in report.checks if c.group != "Patterns")
    assert all(c.status == SKIP for c in report.checks if c.group == "Patterns")  # too few
    assert sum(c.group == "Integrity" for c in report.checks) >= 14


def test_patterns_found_in_a_busy_dataset(busy_pipeline: Simulated) -> None:
    ctx, engine, _ = busy_pipeline
    report = validate_dataset(engine, ctx.config)
    assert report.passed, report.failures
    patterns = [c for c in report.checks if c.group == "Patterns"]
    assert len(patterns) == 19
    skipped = [c.name for c in patterns if c.status == SKIP]
    assert skipped == ["Heavy goods on the lowest shelf"]  # no 8 kg products in a small catalog


def test_without_a_config_only_presence_is_checked(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    report = validate_dataset(engine)
    volume = [c for c in report.checks if c.group == "Volume"]
    assert report.passed and report.size is None
    assert all(c.expected == "> 0" for c in volume)


def test_volume_targets_of_another_size_fail(with_orders: Simulated) -> None:
    ctx, engine, _ = with_orders
    report = validate_dataset(engine, get_config("small", orders=5_000, customers=300))
    assert failed(report) == {"Orders", "Customers"}


# -------------------------------------------------------------- damaged data
DAMAGE = {
    "No negative stock": (
        "UPDATE inventory SET quantity_reserved = quantity_on_hand + 1 WHERE id = "
        "(SELECT MIN(id) FROM inventory WHERE quantity_on_hand > 0)",
    ),
    "No orphan records (foreign keys)": (
        "DELETE FROM customers WHERE id = (SELECT MIN(customer_id) FROM orders)",
    ),
    "Stock equals the sum of its movements": (
        "UPDATE inventory SET quantity_damaged = quantity_damaged + 1 WHERE id = "
        "(SELECT MIN(id) FROM inventory WHERE quantity_on_hand > quantity_reserved "
        "+ quantity_damaged)",
    ),
    "Movements never take stock below zero": (
        "UPDATE inventory_movements SET on_hand_after = -1 WHERE id = 1",
    ),
    "Bins within weight and volume limits": (
        "UPDATE bins SET max_volume_cm3 = 1 WHERE id = "
        "(SELECT MIN(bin_id) FROM inventory WHERE quantity_on_hand > 0)",
    ),
    "Active reservations match reserved stock": (
        "UPDATE stock_reservations SET status = 'released' WHERE id = "
        "(SELECT MIN(id) FROM stock_reservations WHERE status = 'active')",
    ),
    "Stock movements and holds point to existing documents": (
        "DELETE FROM orders WHERE id = (SELECT MAX(reference_id) FROM stock_reservations "
        "WHERE reference_type = 'order')",
    ),
    "Order lines: shipped <= packed <= picked <= ordered": (
        "UPDATE order_items SET quantity_returned = quantity_shipped + 1 WHERE id = "
        "(SELECT MIN(id) FROM order_items WHERE quantity_shipped > 0)",
    ),
    "Order status matches its latest history entry": (
        "UPDATE order_status_history SET to_status = 'confirmed' WHERE id = "
        "(SELECT MAX(id) FROM order_status_history)",
    ),
    "Shipped orders have one shipment and the right dates": (
        "UPDATE orders SET shipped_at = NULL WHERE id = "
        "(SELECT MIN(id) FROM orders WHERE status = 'delivered')",
    ),
    "Cancelled orders have a cancel date and ship nothing": (
        "UPDATE orders SET cancelled_at = NULL WHERE id = "
        "(SELECT MIN(id) FROM orders WHERE status = 'cancelled')",
    ),
    "Returns never exceed shipped units": (
        "UPDATE return_items SET quantity = quantity + 50 WHERE id = "
        "(SELECT MIN(ri.id) FROM return_items ri JOIN returns r ON r.id = ri.return_id "
        "WHERE r.status = 'completed')",
    ),
    "Purchase orders: received <= ordered": (
        "UPDATE purchase_order_items SET quantity_received = quantity + 1 WHERE id = 1",
    ),
    "Picking tasks: picked <= task quantity": (
        "UPDATE picking_tasks SET quantity_picked = quantity - 1 WHERE id = "
        "(SELECT MIN(id) FROM picking_tasks WHERE status = 'completed' AND quantity > 1)",
    ),
}


@pytest.mark.parametrize("name", DAMAGE)
def test_each_kind_of_damage_is_caught(name: str, with_orders: Simulated, tmp_path: Path) -> None:
    ctx, engine, _ = with_orders
    report = check(copy_of(engine, tmp_path, *DAMAGE[name]), ctx.config)
    assert name in failed(report)
    assert not report.passed


def test_every_integrity_check_has_a_damage_test(with_orders: Simulated) -> None:
    ctx, engine, _ = with_orders
    report = validate_dataset(engine, ctx.config)
    integrity = {c.name for c in report.checks if c.group == "Integrity"}
    # a UNIQUE index refuses a second shipment whatever the switches
    assert integrity - set(DAMAGE) == {"One shipment per order"}


PATTERN_DAMAGE = {
    "no delays": (
        "UPDATE shipments SET delivered_at = shipped_at WHERE delivered_at IS NOT NULL",
        {
            "Late deliveries",
            "Large orders more often late",
            "Orders that waited for stock more often late",
            "Peak season deliveries more often late",
        },
    ),
    "no weekly rhythm": (  # Thursday and Friday become the weekend
        "UPDATE orders SET created_at = datetime(created_at, '+2 day')",
        {"Weekday orders above weekends"},
    ),
    "fast movers at the back": (
        "UPDATE racks SET distance_to_packing_m = 10000 - distance_to_packing_m",
        {"Fast movers picked nearer to packing"},
    ),
    "warehouse overfilled": (
        "UPDATE bins SET max_volume_cm3 = max_volume_cm3 / 4",
        {"Warehouse space not overfilled"},
    ),
}


@pytest.mark.parametrize("damage", PATTERN_DAMAGE)
def test_missing_pattern_is_caught(damage: str, busy_pipeline: Simulated, tmp_path: Path) -> None:
    ctx, engine, _ = busy_pipeline
    statement, names = PATTERN_DAMAGE[damage]
    assert names <= failed(check(copy_of(engine, tmp_path, statement), ctx.config))


# ------------------------------------------------------------- report and CLI
def test_markdown_report(with_orders: Simulated, tmp_path: Path) -> None:
    ctx, engine, _ = with_orders
    good = validate_dataset(engine, ctx.config).to_markdown()
    assert good.startswith("# Synthetic dataset validation report")
    assert "**PASSED**" in good and "| Check | Result | Value | Expected |" in good
    assert "## Integrity" in good and "## Volume" in good and "## Patterns" in good
    assert "✅ pass" in good and "⏭️ skip" in good and "❌" not in good
    bad = check(copy_of(engine, tmp_path, *DAMAGE["Movements never take stock below zero"]))
    text = bad.to_markdown()
    assert "**FAILED**" in text and "❌ fail" in text
    assert f"{bad.count(FAIL)} failed" in text


def test_command_line(with_orders: Simulated, tmp_path: Path, capsys) -> None:
    _, engine, _ = with_orders
    path = copy_of(engine, tmp_path)
    assert main(["--database", str(path), "--size", "medium"]) == 1  # wrong targets
    assert main(["--database", str(path), "--size", "small"]) == 0
    report = default_report_path(path)
    assert report == tmp_path / "copy_validation.md" and "**PASSED**" in report.read_text()
    custom = tmp_path / "out.md"
    assert main(["--database", str(path), "--report", str(custom)]) == 0 and custom.exists()
    assert "PASSED" in capsys.readouterr().out
    damaged = copy_of(engine, tmp_path, *DAMAGE["Order status matches its latest history entry"])
    assert main(["--database", str(damaged)]) == 1
    assert main(["--database", str(tmp_path / "missing.db")]) == 2
