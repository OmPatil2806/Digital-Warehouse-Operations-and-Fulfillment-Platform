"""The one-command demo setup (scripts/prepare_demo.py): its steps and safeguards. The
whole run (data, training, scoring) is too slow for the test suite; it was run on the
small and medium datasets when it was written."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prepare_demo.py"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("prepare_demo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_steps_in_order(demo, tmp_path: Path) -> None:
    database = tmp_path / "demo.db"
    steps = demo.steps(database, "small", quick=True, replace=True)
    scripts = [command[0] for _, command in steps]
    assert scripts == [
        "generate_data.py",
        "train_models.py",
        "score_models.py",
        "check_models.py",
        "score_models.py",
    ]
    generate, train, _, _, backtest = (command for _, command in steps)
    assert generate[generate.index("--size") + 1] == "small" and "--replace" in generate
    assert "--quick" in train
    # The committed model reports (full dataset) are never overwritten by a demo run.
    assert "--no-reports" in train
    assert train[train.index("--overview") + 1] == str(tmp_path / "demo_models.md")
    assert backtest[-2:] == ["--backtest", "30"]
    assert all(str(database) in command for _, command in steps)


def test_an_existing_database_is_kept_unless_replaced(demo, tmp_path: Path, capsys) -> None:
    database = tmp_path / "demo.db"
    database.write_bytes(b"")
    assert demo.main(["--database", str(database)]) == 1
    assert "--replace" in capsys.readouterr().err


def test_the_database_setting_for_env(demo, tmp_path: Path) -> None:
    inside = demo.PROJECT_ROOT / "database" / "warehouse_demo.db"
    assert demo.database_setting(inside) == "sqlite:///./database/warehouse_demo.db"
    outside = tmp_path / "demo.db"  # outside the project: an absolute path (any OS)
    assert demo.database_setting(outside) == f"sqlite:///{outside.resolve().as_posix()}"
