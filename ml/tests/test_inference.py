"""Scoring with the selected models: every predictor, with a trained network and with its
baseline, produces valid rows; the scoring step stores them; the command works."""

import dataclasses
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.models.ml import ModelVersion
from app.models.ml_results import RESULT_TABLES
from data_generation.context import GenerationContext
from data_generation.database import sqlite_url
from inference.common import Context
from inference.score import PREDICTORS, latest_rows, score
from training import keras_setup
from training.data import history_range, read_frame
from training.use_cases import USE_CASES, quick_config

Simulated = tuple[GenerationContext, Engine, dict]
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "score_models.py"


@pytest.fixture(scope="module")
def trained(with_orders: Simulated, tmp_path_factory: pytest.TempPathFactory):
    """A copy of the small dataset with one quickly trained network per use case."""
    _, engine, _ = with_orders
    folder = tmp_path_factory.mktemp("trained")
    database = folder / "trained.db"
    shutil.copy(str(engine.url.database), database)
    artifacts, original = folder / "artifacts", keras_setup.ARTIFACT_DIR
    keras_setup.ARTIFACT_DIR = artifacts
    keras_setup.ML_DIR, ml_dir = folder, keras_setup.ML_DIR  # artifact paths relative to it
    try:
        for info in USE_CASES:
            config = quick_config(info.name)
            first = next(iter(config.models))
            config = dataclasses.replace(config, models={first: config.models[first]})
            info.runner()(database, config=config, report=lambda _: None, write_report=None)
        yield database
    finally:
        keras_setup.ARTIFACT_DIR, keras_setup.ML_DIR = original, ml_dir


def models_of(database: Path, use_case: str) -> dict[str, ModelVersion]:
    """The network and the (best) baseline of a use case's run."""
    with Session(create_engine(sqlite_url(database))) as session:
        rows = session.scalars(select(ModelVersion).where(ModelVersion.use_case == use_case)).all()
    return {
        "network": next(r for r in rows if not r.is_baseline),
        "baseline": next(r for r in rows if r.is_baseline),
    }


def predict(database: Path, use_case: str, kind: str, ml_dir: Path) -> list[dict]:
    engine = create_engine(sqlite_url(database))
    first, last = history_range(engine)
    original = keras_setup.ML_DIR
    keras_setup.ML_DIR = ml_dir
    try:
        return PREDICTORS[use_case](
            engine, Context(models_of(database, use_case)[kind], first, last)
        )
    finally:
        keras_setup.ML_DIR = original
        engine.dispose()


@pytest.mark.parametrize("kind", ["network", "baseline"])
def test_demand_forecasts(trained: Path, kind: str) -> None:
    rows = predict(trained, "demand_forecasting", kind, trained.parent)
    engine = create_engine(sqlite_url(trained))
    products = read_frame(engine, "SELECT COUNT(*) AS n FROM products").n[0]
    _, last = history_range(engine)
    assert len(rows) == products * 30
    assert all(0 <= r["low_units"] <= r["expected_units"] <= r["high_units"] for r in rows)
    days = sorted({r["day"] for r in rows})
    assert (days[0] - last).days == 1 and (days[-1] - last).days == 30  # the coming 30 days


@pytest.mark.parametrize("kind", ["network", "baseline"])
def test_reorder_recommendations(trained: Path, kind: str) -> None:
    rows = predict(trained, "reorder", kind, trained.parent)
    assert rows, "the small dataset always has products at risk"
    for r in rows:
        assert 0 <= r["probability"] <= 1 and r["priority"] in {"medium", "high"}
        assert r["quantity"] >= 0 and isinstance(r["reasons"], list)
    probabilities = [r["probability"] for r in rows]
    assert probabilities == sorted(probabilities, reverse=True)


@pytest.mark.parametrize("kind", ["network", "baseline"])
def test_movement_classes(trained: Path, kind: str) -> None:
    rows = predict(trained, "movement_classification", kind, trained.parent)
    assert len(rows) == 50 and {r["movement_class"] for r in rows} <= {"fast", "medium", "slow"}
    assert all(r["picks_per_day"] >= 0 for r in rows)


@pytest.mark.parametrize("kind", ["network", "baseline"])
def test_slotting_recommendations(trained: Path, kind: str) -> None:
    from feature_engineering.slotting_features import load_layout

    rows = predict(trained, "slotting", kind, trained.parent)
    engine = create_engine(sqlite_url(trained))
    layout = load_layout(engine)
    bin_row = {b: i for i, b in enumerate(layout.bin_ids)}
    product_row = {p: i for i, p in enumerate(layout.product_ids)}
    assert rows
    for r in rows:
        b = bin_row[r["recommended_bin_id"]]
        assert layout.allowed(product_row[r["product_id"]])[b]  # zone rule holds
        assert layout.bin_warehouse[b] == r["warehouse_id"]
        assert r["current_bin_id"] != r["recommended_bin_id"]
        if r["current_seconds_per_day"] is not None:
            assert r["recommended_seconds_per_day"] < r["current_seconds_per_day"]  # faster


@pytest.mark.parametrize("kind", ["network", "baseline"])
def test_delay_predictions(trained: Path, kind: str) -> None:
    rows = predict(trained, "delay_prediction", kind, trained.parent)
    engine = create_engine(sqlite_url(trained))
    on_the_way = read_frame(engine, "SELECT order_id FROM shipments WHERE delivered_at IS NULL")
    assert {r["order_id"] for r in rows} == set(on_the_way.order_id)
    assert all(
        0 <= r["probability"] <= 1 and r["risk_level"] in {"low", "medium", "high"} for r in rows
    )


@pytest.mark.parametrize("kind", ["network", "baseline"])
def test_product_recommendations(trained: Path, kind: str) -> None:
    rows = predict(trained, "recommendation", kind, trained.parent)
    assert len(rows) == 50 * 10
    by_product: dict[int, list] = {}
    for r in rows:
        by_product.setdefault(r["product_id"], []).append(r)
    for product, recs in by_product.items():
        assert [r["rank"] for r in recs] == list(range(1, 11))
        assert product not in {r["recommended_product_id"] for r in recs}
        assert len({r["recommended_product_id"] for r in recs}) == 10


def test_score_stores_every_use_case_and_keeps_history(trained: Path, tmp_path: Path) -> None:
    database = tmp_path / "scored.db"
    shutil.copy(trained, database)
    original = keras_setup.ML_DIR
    keras_setup.ML_DIR = trained.parent
    try:
        first = score(database, report=lambda _: None)
        second = score(database, use_cases=["movement_classification"], report=lambda _: None)
    finally:
        keras_setup.ML_DIR = original
    assert [r.use_case for r in first] == [u.name for u in USE_CASES]
    assert all(r.model_name and r.rows > 0 for r in first)
    engine = create_engine(sqlite_url(database))
    with Session(engine) as session:
        for info in USE_CASES:
            table = RESULT_TABLES[info.name]
            stamps = {row.scored_at for row in session.scalars(select(table))}
            selected = {row.model_version_id for row in session.scalars(select(table))}
            assert len(selected) == 1  # all from the selected model
            assert len(stamps) == (2 if info.name == "movement_classification" else 1)
    assert len(latest_rows(engine, "movement_classification")) == second[0].rows == 50


def test_use_cases_without_a_model_are_skipped(with_orders: Simulated, tmp_path: Path) -> None:
    _, engine, _ = with_orders
    database = tmp_path / "untrained.db"
    shutil.copy(str(engine.url.database), database)
    lines: list[str] = []
    results = score(database, use_cases=["reorder"], report=lines.append)
    assert results[0].model_name is None and "skipped" in lines[0]


def test_saved_models_load_in_a_fresh_process(trained: Path) -> None:
    """A saved model loads without its model code imported first (Context does it)."""
    network = models_of(trained, "demand_forecasting")["network"]
    ml = Path(__file__).resolve().parents[1]
    code = (
        "import sys; from datetime import date; from pathlib import Path\n"
        f"sys.path[:0] = [{str(ml)!r}, {str(ml.parent / 'backend')!r}]\n"
        "from training import keras_setup\n"
        f"keras_setup.ML_DIR = Path({str(trained.parent)!r})\n"
        "from inference.common import Context\n"
        "class M: pass\n"
        "m = M(); m.use_case = 'demand_forecasting'; m.model_name = 'x'\n"
        f"m.artifact_path = {network.artifact_path!r}\n"
        "print(Context(m, date.today(), date.today()).keras_model().name)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    assert network.model_name in out.stdout


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("score_models_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script(script: ModuleType, with_orders: Simulated, tmp_path: Path, capsys) -> None:
    _, engine, _ = with_orders
    database = tmp_path / "plain.db"
    shutil.copy(str(engine.url.database), database)
    assert script.main(["--database", str(database), "--use-case", "slotting"]) == 0
    assert "No selected model for: slotting" in capsys.readouterr().out
    assert script.main(["--database", str(tmp_path / "missing.db")]) == 1
