"""Scoring with the selected models: every predictor, with a trained network and with its
baseline, produces valid rows; the scoring step stores them; the command works."""

import dataclasses
import importlib.util
import shutil
import subprocess
import sys
from datetime import timedelta
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


def test_backtest_scores_checkable_use_cases_as_of_an_earlier_day(
    trained: Path, tmp_path: Path
) -> None:
    database = tmp_path / "backtest.db"
    shutil.copy(trained, database)
    engine = create_engine(sqlite_url(database))
    _, last = history_range(engine)
    as_of = last - timedelta(days=20)
    original = keras_setup.ML_DIR
    keras_setup.ML_DIR = trained.parent
    try:
        current = score(database, use_cases=["demand_forecasting"], report=lambda _: None)
        backtest = score(database, as_of=as_of, report=lambda _: None)
    finally:
        keras_setup.ML_DIR = original
    assert [r.use_case for r in backtest] == ["demand_forecasting", "delay_prediction"]
    with Session(engine) as session:
        table = RESULT_TABLES["demand_forecasting"]
        old = session.scalars(select(table).where(table.as_of == as_of)).all()
    days = sorted({r.day for r in old})
    assert (days[0] - as_of).days == 1 and len(days) == 30  # forecasts the hidden days
    # The application keeps showing the forecasts of the latest day, not the backtest.
    assert {r.as_of for r in latest_rows(engine, "demand_forecasting")} == {last}
    assert current[0].rows == len(latest_rows(engine, "demand_forecasting"))
    # Delays: the parcels dispatched by then and not delivered by then.
    on_the_way = read_frame(
        engine,
        "SELECT order_id FROM shipments WHERE date(shipped_at) <= :d AND "
        "(delivered_at IS NULL OR date(delivered_at) > :d)".replace(":d", f"'{as_of}'"),
    )
    rows = latest_rows(engine, "delay_prediction")
    assert rows and {r.as_of for r in rows} == {as_of}
    assert {r.order_id for r in rows} == set(on_the_way.order_id)


def test_backtest_rejects_other_use_cases_and_bad_days(trained: Path, tmp_path: Path) -> None:
    database = tmp_path / "bad.db"
    shutil.copy(trained, database)
    first, last = history_range(create_engine(sqlite_url(database)))
    with pytest.raises(ValueError, match="can be backtested"):
        score(database, use_cases=["slotting"], as_of=last - timedelta(days=5))
    with pytest.raises(ValueError, match="as_of must be"):
        score(database, as_of=last + timedelta(days=1))
    with pytest.raises(ValueError, match="as_of must be"):
        score(database, as_of=first)


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


def test_script_backtest(script: ModuleType, trained: Path, tmp_path: Path, capsys) -> None:
    database = tmp_path / "script_backtest.db"
    shutil.copy(trained, database)
    original = keras_setup.ML_DIR
    keras_setup.ML_DIR = trained.parent
    try:
        code = script.main(["--database", str(database), "--backtest", "15"])
        bad = script.main(
            ["--database", str(database), "--backtest", "15", "--use-case", "reorder"]
        )
    finally:
        keras_setup.ML_DIR = original
    out = capsys.readouterr()
    assert code == 0 and "Backtest as of" in out.out
    assert bad == 1 and "can be backtested" in out.err
    with pytest.raises(SystemExit):
        script.main(["--database", str(database), "--backtest", "0"])


# ------------------------------------------------------------------------ checks
@pytest.fixture(scope="module")
def scored(trained: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The trained small dataset, scored with every selected model."""
    database = tmp_path_factory.mktemp("scored") / "scored.db"
    shutil.copy(trained, database)
    original = keras_setup.ML_DIR
    keras_setup.ML_DIR = trained.parent
    try:
        score(database, report=lambda _: None)
    finally:
        keras_setup.ML_DIR = original
    return database


def run_checks(database: Path, ml_dir: Path, use_cases: list[str] | None = None):
    from inference.checks import check

    original = keras_setup.ML_DIR
    keras_setup.ML_DIR = ml_dir
    engine = create_engine(sqlite_url(database))
    try:
        return {r.use_case: r for r in check(engine, use_cases)}
    finally:
        keras_setup.ML_DIR = original
        engine.dispose()


def broken_copy(scored: Path, tmp_path: Path, sql: str) -> Path:
    database = tmp_path / "broken.db"
    shutil.copy(scored, database)
    engine = create_engine(sqlite_url(database))
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)
    engine.dispose()
    return database


def test_checks_pass_after_scoring(scored: Path, trained: Path) -> None:
    results = run_checks(scored, trained.parent)
    assert set(results) == {u.name for u in USE_CASES}
    assert all(r.ok for r in results.values()), {u: r.problems for u, r in results.items()}
    assert results["demand_forecasting"].rows == 50 * 30


@pytest.mark.parametrize(
    ("use_case", "sql", "problem"),
    [
        (
            "demand_forecasting",
            "DELETE FROM demand_forecasts WHERE id = (SELECT MAX(id) FROM demand_forecasts)",
            "without exactly the 30 days",
        ),
        (
            "recommendation",
            "UPDATE product_recommendations SET score = 9e999 "
            "WHERE id = (SELECT MIN(id) FROM product_recommendations)",
            "not a finite number",
        ),
        (
            "recommendation",
            "DELETE FROM product_recommendations WHERE rank = 2",
            "ranks with gaps",
        ),
        (
            "movement_classification",
            "DELETE FROM movement_classifications WHERE id = "
            "(SELECT MIN(id) FROM movement_classifications)",
            "classes for 50 products",
        ),
        (
            "slotting",
            "UPDATE slotting_recommendations SET recommended_seconds_per_day = "
            "current_seconds_per_day + 1 WHERE current_seconds_per_day IS NOT NULL",
            "does not save picking time",
        ),
        (
            "delay_prediction",
            "DELETE FROM delay_predictions WHERE id = (SELECT MIN(id) FROM delay_predictions)",
            "parcels",
        ),
    ],
)
def test_checks_find_broken_predictions(
    scored: Path, trained: Path, tmp_path: Path, use_case: str, sql: str, problem: str
) -> None:
    database = broken_copy(scored, tmp_path, sql)
    result = run_checks(database, trained.parent, [use_case])[use_case]
    assert not result.ok and any(problem in p for p in result.problems), result.problems


def test_checks_find_missing_predictions_and_models(scored: Path, trained: Path, tmp_path: Path):
    database = broken_copy(scored, tmp_path, "DELETE FROM demand_forecasts")
    result = run_checks(database, trained.parent, ["demand_forecasting"])["demand_forecasting"]
    assert "no predictions from the selected model" in result.problems[0]
    other = tmp_path / "no_models"
    other.mkdir()
    database = broken_copy(scored, other, "UPDATE model_versions SET status = 'candidate'")
    results = run_checks(database, trained.parent)
    assert all(r.problems == ["no selected model"] for r in results.values())


def test_a_model_file_that_does_not_load_is_reported(trained: Path, tmp_path: Path) -> None:
    from inference.checks import check_model_loads

    network = models_of(trained, "demand_forecasting")["network"]
    engine = create_engine(sqlite_url(trained))
    first, last = history_range(engine)
    engine.dispose()
    copy = tmp_path / network.artifact_path
    copy.parent.mkdir(parents=True)
    copy.write_bytes(b"not a keras file")
    original = keras_setup.ML_DIR
    keras_setup.ML_DIR = tmp_path
    try:
        problems = check_model_loads(network, Context(network, first, last))
    finally:
        keras_setup.ML_DIR = original
    assert problems and problems[0].startswith("model file does not load")
    assert check_model_loads(models_of(trained, "demand_forecasting")["baseline"], None) == []


def test_check_script(trained: Path, scored: Path, tmp_path: Path, capsys) -> None:
    spec = importlib.util.spec_from_file_location(
        "check_models_script", SCRIPT.parent / "check_models.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = keras_setup.ML_DIR
    keras_setup.ML_DIR = trained.parent
    try:
        good = module.main(["--database", str(scored)])
        bad = module.main(
            ["--database", str(broken_copy(scored, tmp_path, "DELETE FROM demand_forecasts"))]
        )
    finally:
        keras_setup.ML_DIR = original
    out = capsys.readouterr().out
    assert good == 0 and "6 of 6 use cases passed" in out
    assert bad == 1 and "5 of 6 use cases passed" in out
    assert module.main(["--database", str(tmp_path / "missing.db")]) == 1
