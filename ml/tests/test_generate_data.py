"""scripts/generate_data.py: one command to generate, load and validate the dataset."""

import contextlib
import importlib.util
import io
import shutil
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import create_engine

from data_generation.database import sqlite_url

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_data.py"
END = "2026-11-10"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_data_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(script: ModuleType, path: Path, *extra: str) -> int:
    return script.main(["--database", str(path), "--end-date", END, *extra])


def query(path: Path, sql: str) -> list[tuple]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


@pytest.fixture(scope="module")
def generated(script: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    path = tmp_path_factory.mktemp("generated") / "synthetic.db"
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert run(script, path) == 0
    return path, output.getvalue()


def test_one_command_generates_loads_and_validates(generated: tuple[Path, str]) -> None:
    path, output = generated
    for stage in range(1, 6):
        assert f"[{stage}/5]" in output
    assert query(path, "SELECT COUNT(*) FROM orders")[0][0] == pytest.approx(500, rel=0.1)
    first, last = query(path, "SELECT MIN(date(created_at)), MAX(date(created_at)) FROM orders")[0]
    assert first <= "2024-11-20" and "2026-11-01" <= last <= END  # two years up to the end date
    report = path.with_name("synthetic_validation.md")
    assert "**PASSED**" in report.read_text(encoding="utf-8")
    assert "0 failed" in output and "DATABASE_URL=sqlite:///" in output


def test_the_demo_customer_sees_its_own_orders(generated: tuple[Path, str]) -> None:
    path, _ = generated
    ((code, orders),) = query(
        path,
        "SELECT c.code, COUNT(o.id) FROM customers c JOIN users u ON u.id = c.user_id "
        "LEFT JOIN orders o ON o.customer_id = c.id WHERE u.email = 'customer@example.com' "
        "GROUP BY c.id",
    )
    most = query(
        path,
        "SELECT MAX(n) FROM (SELECT COUNT(*) AS n FROM orders o JOIN customers c "
        "ON c.id = o.customer_id WHERE c.is_active = 1 GROUP BY o.customer_id)",
    )
    assert code.startswith("CUST-") and orders == most[0][0] > 0


def test_progress_one_line_per_month(generated: tuple[Path, str]) -> None:
    _, output = generated
    months = [line.split()[0] for line in output.splitlines() if line.startswith("  20")]
    assert len(months) == 25  # November 2024 to November 2026
    assert months[0] == "2024-11" and months[-1] == "2026-11"
    assert "(730/730 days" in output


def test_demo_logins_can_sign_in(generated: tuple[Path, str], script: ModuleType) -> None:
    from app.core.security import verify_password

    path, _ = generated
    users = dict(query(path, "SELECT email, hashed_password FROM users"))
    assert set(users) == {email for email, _, _ in script.DEMO_USERS}
    assert all(verify_password(script.DEMO_PASSWORD, hashed) for hashed in users.values())
    roles = query(
        path,
        "SELECT u.email, r.name FROM users u JOIN user_roles ur ON ur.user_id = u.id "
        "JOIN roles r ON r.id = ur.role_id",
    )
    assert {role for _, role in roles} == {"admin", "manager", "staff", "customer"}


def test_existing_database_needs_replace(
    generated: tuple[Path, str], script: ModuleType, capsys: pytest.CaptureFixture
) -> None:
    path, _ = generated
    before = path.stat().st_mtime_ns
    assert run(script, path) == 1
    assert "--replace" in capsys.readouterr().err
    assert path.stat().st_mtime_ns == before  # untouched


def test_same_seed_same_data_and_replace(
    generated: tuple[Path, str], script: ModuleType, tmp_path: Path
) -> None:
    path, _ = generated
    fingerprint = (
        "SELECT COUNT(*), SUM(subtotal), SUM(customer_id * id), "
        "(SELECT SUM(quantity * product_id) FROM inventory_movements) FROM orders"
    )
    again = tmp_path / "again.db"
    assert run(script, again, "--no-demo-users") == 0
    assert query(again, fingerprint) == query(path, fingerprint)
    assert query(again, "SELECT COUNT(*) FROM users") == [(0,)]
    assert run(script, again, "--replace", "--seed", "7", "--no-demo-users") == 0
    assert query(again, fingerprint) != query(path, fingerprint)


def test_alerts_on_the_last_day(generated: tuple[Path, str]) -> None:
    """The alerts are those the application's own rules give for the final stock."""
    path, _ = generated
    alerts = dict(
        query(path, "SELECT alert_type, COUNT(*) FROM alerts WHERE status = 'open' GROUP BY 1")
    )
    low = query(
        path,
        "SELECT COUNT(*) FROM products p WHERE p.min_stock > 0 AND p.min_stock > "
        "(SELECT COALESCE(SUM(quantity_on_hand - quantity_reserved - quantity_damaged), 0) "
        "FROM inventory i WHERE i.product_id = p.id)",
    )[0][0]
    delayed = query(path, "SELECT COUNT(*) FROM orders WHERE status = 'delayed'")[0][0]
    overdue = query(
        path,
        "SELECT COUNT(*) FROM purchase_orders WHERE status IN ('ordered', 'partially_received') "
        f"AND expected_date < '{END}'",
    )[0][0]
    assert low > 0 and alerts.get("low_stock", 0) == low
    assert alerts.get("delay_risk", 0) == delayed
    assert alerts.get("overdue_supplier", 0) == overdue
    assert "over_capacity" not in alerts  # bins are never overfilled


def test_database_setting(script: ModuleType, tmp_path: Path) -> None:
    inside = script.PROJECT_ROOT / "database" / "warehouse_synthetic.db"
    assert script.database_setting(inside) == "./database/warehouse_synthetic.db"
    assert script.database_setting(tmp_path / "x.db") == (tmp_path / "x.db").resolve().as_posix()


def test_alerts_of_every_kind_on_a_busy_dataset(busy_pipeline, tmp_path: Path) -> None:
    from data_generation.pipeline import raise_alerts

    ctx, engine, _ = busy_pipeline
    path = tmp_path / "busy.db"
    shutil.copy(str(engine.url.database), path)
    stocked_bin = query(path, "SELECT MIN(bin_id) FROM inventory WHERE quantity_on_hand > 0")[0][0]
    original = query(path, f"SELECT max_volume_cm3 FROM bins WHERE id = {stocked_bin}")[0][0]
    copy = create_engine(sqlite_url(path))
    try:
        with copy.begin() as connection:  # one bin overfilled on the last day
            connection.exec_driver_sql(
                f"UPDATE bins SET max_volume_cm3 = 1 WHERE id = {stocked_bin}"
            )
        counts = raise_alerts(copy, ctx.config.end_date)
        again = raise_alerts(copy, ctx.config.end_date)  # evaluating twice adds nothing
        with copy.begin() as connection:  # the bin is fine again: its alert is resolved
            connection.exec_driver_sql(
                f"UPDATE bins SET max_volume_cm3 = {original} WHERE id = {stocked_bin}"
            )
        fixed = raise_alerts(copy, ctx.config.end_date)
    finally:
        copy.dispose()
    assert counts["over_capacity"] == 1 and "over_capacity" not in fixed
    assert fixed["low_stock"] == counts["low_stock"]
    delayed = query(path, "SELECT COUNT(*) FROM orders WHERE status = 'delayed'")[0][0]
    overdue = query(
        path,
        "SELECT COUNT(*) FROM purchase_orders WHERE status IN ('ordered', 'partially_received') "
        f"AND expected_date < '{ctx.config.end_date}'",
    )[0][0]
    assert delayed > 0 and counts["delay_risk"] == delayed
    assert overdue > 0 and counts["overdue_supplier"] == overdue
    assert counts["low_stock"] > 0 and again == counts
    messages = dict(query(path, "SELECT alert_type, message FROM alerts"))
    assert " expected 20" in messages["delay_risk"]  # carrier, tracking and expected date
