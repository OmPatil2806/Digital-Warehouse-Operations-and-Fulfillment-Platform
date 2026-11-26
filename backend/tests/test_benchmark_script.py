"""The speed-check script (scripts/benchmark_api.py) runs end to end on a demo database."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "benchmark_api.py"


def _load():
    spec = importlib.util.spec_from_file_location("benchmark_api", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*args: str, database_url: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "APP_ENV": "development", "BCRYPT_ROUNDS": "4"}
    if database_url:
        env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600
    )


@pytest.fixture(scope="module")
def demo_database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("bench") / "demo.db"
    url = f"sqlite:///{path.as_posix()}"
    migrated = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "backend",
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    assert migrated.returncode == 0, migrated.stderr[-2000:]
    seeded = run("scripts/seed_database.py", database_url=url)
    assert seeded.returncode == 0, seeded.stdout[-2000:] + seeded.stderr[-2000:]
    return path


def test_times_every_call_and_writes_a_report(demo_database: Path, tmp_path: Path) -> None:
    report = tmp_path / "speed.md"
    result = run(
        "scripts/benchmark_api.py",
        "--database",
        str(demo_database),
        "--repeat",
        "1",
        "--limit",
        "5000",
        "--report",
        str(report),
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    module = _load()
    assert f"{len(module.CALLS)} calls" in result.stdout
    assert "❌" not in result.stdout  # nothing failed (unscored ML data shows as "no data")
    text = report.read_text(encoding="utf-8")
    assert text.startswith("# API speed on demo.db") and "/dashboards/overview" in text


def test_missing_or_empty_databases_are_explained(tmp_path: Path) -> None:
    missing = run("scripts/benchmark_api.py", "--database", str(tmp_path / "none.db"))
    assert missing.returncode == 1 and "no database" in missing.stderr
    empty = tmp_path / "empty.db"
    empty.touch()
    result = run("scripts/benchmark_api.py", "--database", str(empty))
    assert result.returncode == 1 and "not a migrated warehouse database" in result.stderr


def test_table_marks_slow_calls_errors_and_missing_data() -> None:
    module = _load()
    rows = [
        module.Timing("Orders", "/orders", 200, 20.0, 25.0, 500.0),
        module.Timing("Reports", "/dashboards/x", 200, 700.0, 800.0, 500.0),
        module.Timing("Reports", "/dashboards/y", 200, 700.0, 800.0, 1000.0),
        module.Timing("ML", "/ml/x", 404, 5.0, 5.0, 500.0),
        module.Timing("ML", "/ml/y", 500, 5.0, 5.0, 500.0),
    ]
    lines = module.table(rows).splitlines()[2:]
    assert lines[0].endswith("| ✅ |") and lines[1].endswith("| ⚠️ slow |")
    assert lines[2].endswith("| ✅ |")  # within its own (report) limit
    assert lines[3].endswith("| ➖ no data |") and lines[4].endswith("| ❌ error 500 |")
    assert [r.ok for r in rows] == [True, False, True, True, False]
